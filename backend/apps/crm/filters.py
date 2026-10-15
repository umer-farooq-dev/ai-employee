"""CRM-09 lead list filters, shared by the panel list, the pipeline, exports and the API.

Query parameters: q, status, score, source, assignee (user id | "me" | "none"), ai_employee, created_from/created_to,
follow_up (today | overdue | upcoming), tag, deleted=1, sort, and cf_<field key> for filterable custom fields
(cf_<key>_min / cf_<key>_max for numbers and currency).
"""

import datetime

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.money import parse_inr
from apps.industries import services as templates

from . import services as crm

SORTS = {
    "newest": "-created_at",
    "oldest": "created_at",
    "name": "name",
    "score": "-score_value",
    "follow_up": "follow_up_at",
    "updated": "-updated_at",
}


def _date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def apply(request, params, include_deleted=False):
    """→ (queryset, custom filter definitions). Never widens visibility: starts from crm.visible()."""
    company = request.company
    deleted = params.get("deleted") == "1"
    qs = crm.visible(request, include_deleted=deleted or include_deleted)
    if deleted:
        qs = qs.filter(deleted_at__isnull=False)
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(crm.search_q(q))
    if params.get("status"):
        qs = qs.filter(status__key=params["status"])
    if params.get("score"):
        qs = qs.filter(score_label=params["score"])
    if params.get("source"):
        qs = qs.filter(source__key=params["source"])
    assignee = params.get("assignee")
    if assignee == "me":
        qs = qs.filter(assigned_user=request.user)
    elif assignee == "none":
        qs = qs.filter(assigned_user__isnull=True)
    elif assignee:
        qs = qs.filter(assigned_user_id=assignee)
    if params.get("ai_employee"):
        qs = qs.filter(assigned_ai_employee_id=params["ai_employee"])
    if _date(params.get("created_from")):
        qs = qs.filter(created_at__date__gte=_date(params["created_from"]))
    if _date(params.get("created_to")):
        qs = qs.filter(created_at__date__lte=_date(params["created_to"]))
    today = timezone.localdate()
    follow = params.get("follow_up")
    if follow == "today":
        qs = qs.filter(follow_up_at__date=today)
    elif follow == "overdue":
        qs = qs.filter(follow_up_at__lt=timezone.now())
    elif follow == "upcoming":
        qs = qs.filter(follow_up_at__gte=timezone.now())
    if params.get("tag"):
        qs = qs.filter(tags__contains=[params["tag"]])
    defs = [d for d in templates.fields_for(company, "lead") if d.filterable]
    for d in defs:
        key = f"cf_{d.key}"
        if d.type in ("number", "currency"):
            convert = parse_inr if d.type == "currency" else float
            for suffix, lookup in (("_min", "gte"), ("_max", "lte")):
                raw = params.get(key + suffix)
                if raw:
                    try:
                        qs = qs.filter(**{f"custom__{d.key}__{lookup}": convert(raw)})
                    except (TypeError, ValueError, ValidationError):
                        pass  # bad input = no filter
            continue
        value = params.get(key)
        if not value:
            continue
        if d.type == "multi_select":
            qs = qs.filter(**{f"custom__{d.key}__contains": [value]})
        elif d.type == "yes_no":
            qs = qs.filter(**{f"custom__{d.key}": value in ("1", "true", "yes")})
        elif d.type == "single_select":
            qs = qs.filter(**{f"custom__{d.key}": value})
        else:
            qs = qs.filter(**{f"custom__{d.key}__icontains": value})
    return qs.order_by(SORTS.get(params.get("sort"), "-created_at"), "-number"), defs
