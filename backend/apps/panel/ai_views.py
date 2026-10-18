"""Company panel: AI Employees (EMP-01 … EMP-12), test console (EMP-10) and conversations (KB-11, TOOL-14).

Views only read the request and call apps.agents.services / runtime; the test console page talks to the REST API.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.agents import runtime
from apps.agents import services as employees
from apps.agents import tools as toolkit
from apps.agents.models import AIEmployee, Conversation, UsageEvent
from apps.core.uploads import save_public
from apps.crm.services import members
from apps.industries import services as templates
from apps.knowledge.models import Source
from apps.providers import languages
from apps.rbac.services import has_perm
from apps.roles_tools.models import CHANNELS
from apps.scheduling.models import Resource

from .company_views import _errors, company_perm

STEPS = employees.WIZARD_STEPS
STEP_KEYS = [k for k, _ in STEPS]
DAYS = [
    ("mon", "Monday"),
    ("tue", "Tuesday"),
    ("wed", "Wednesday"),
    ("thu", "Thursday"),
    ("fri", "Friday"),
    ("sat", "Saturday"),
    ("sun", "Sunday"),
]


def _can_manage(request):
    return has_perm(request.user, "ai_employees.manage", request.company)


def _need_manage(request):
    if not _can_manage(request):
        raise PermissionDenied


def _employee(request, pk):
    return get_object_or_404(
        AIEmployee.objects.select_related("industry", "role", "template_version"), pk=pk, company=request.company
    )


def _lang_names(codes):
    names = languages.names()
    return [(c, names.get(c, c)) for c in codes]


# ------------------------------------------------------------------ list (EMP-01)
@company_perm("ai_employees.view")
def employee_list(request):
    if request.method == "POST":
        _need_manage(request)
        employee = _employee(request, request.POST.get("employee"))
        try:
            if request.POST.get("op") == "activate":
                employees.activate(employee, request.user, request)
                messages.success(request, f"{employee.name} is active.")
            elif request.POST.get("op") == "pause":
                employees.pause(employee, request.POST.get("reason", ""), user=request.user, request=request)
                messages.success(request, f"{employee.name} is paused.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect(request.get_full_path())
    qs = AIEmployee.objects.filter(company=request.company).select_related("industry", "role")
    status = request.GET.get("status") or ""
    qs = qs.filter(status=status) if status else qs.exclude(status=AIEmployee.ARCHIVED)
    if request.GET.get("q"):
        qs = qs.filter(Q(name__icontains=request.GET["q"]) | Q(role__name__icontains=request.GET["q"]))
    rows = list(qs)
    stats = employees.stats(rows)
    names = languages.names()
    return render(
        request,
        "panel/company/ai/list.html",
        {
            "rows": [(e, stats[e.pk], [names.get(c, c) for c in e.languages]) for e in rows],
            "statuses": AIEmployee.STATUSES,
            "status": status,
            "q": request.GET.get("q", ""),
            "can_manage": _can_manage(request),
            "any": AIEmployee.objects.filter(company=request.company).exists(),
        },
    )


# ------------------------------------------------------------------ wizard steps 1-2 (EMP-02, EMP-03)
@company_perm("ai_employees.manage")
def employee_new(request):
    company = request.company
    industries = list(employees.industries())
    key = (
        request.POST.get("industry")
        or request.GET.get("industry")
        or (company.industry.key if company.industry else "")
    )
    industry = next((i for i in industries if i.key == key), None) or (industries[0] if industries else None)
    roles = employees.roles_for(company, industry) if industry else []
    channel_names = dict(CHANNELS)
    for role in roles:
        role.channel_labels = [channel_names.get(c, c) for c in role.allowed_channels]
    if request.method == "POST":
        try:
            employee = employees.create_employee(
                company,
                {
                    "industry": industry.key if industry else "",
                    "role": request.POST.get("role"),
                    "name": request.POST.get("name"),
                    "wizard_step": 3,
                },
                request.user,
                request,
            )
            messages.success(request, f"{employee.name} created as a draft. Continue the setup.")
            return redirect("panel:ai_step", pk=employee.pk, step="identity")
        except ValidationError as exc:
            _errors(request, exc)
    return render(
        request,
        "panel/company/ai/new.html",
        {
            "industries": industries,
            "industry": industry,
            "roles": roles,
            "steps": STEPS,
            "current": "industry",
            "selected_role": request.POST.get("role", ""),
        },
    )


# ------------------------------------------------------------------ wizard steps 3-10 (EMP-04 … EMP-11), editable later
def _texts(post, prefix, codes):
    return {c: post.get(f"{prefix}_{c}", "").strip() for c in codes}


def _step_data(request, employee, step):
    """POST → data for services.update_employee."""
    post, codes = request.POST, employee.languages or [employee.primary_language]
    if step == "identity":
        data = {
            "name": post.get("name"),
            "persona": {"description": post.get("description"), "tone": post.get("tone"), "gender": post.get("gender")},
            "greetings": _texts(post, "greeting", codes),
        }
        if request.FILES.get("avatar"):
            data["avatar"] = save_public(request.FILES["avatar"], "avatars")
        return data
    if step == "voice":
        return {"voices": {**{c: post.get(f"voice_{c}", "") for c in codes}, "speed": post.get("speed") or 1}}
    if step == "languages":
        return {"primary_language": post.get("primary_language"), "languages": post.getlist("languages")}
    if step == "tools":
        return {
            "tools": {t.key: t.key in post.getlist("tools") for t in toolkit.available(employee)},
            "calendar_resources": post.getlist("calendar_resources"),
        }
    if step == "rules":
        hours = {}
        for day, _ in DAYS:
            if post.get(f"day_{day}_closed"):
                hours[day] = {"closed": True}
            elif post.get(f"day_{day}_open") and post.get(f"day_{day}_close"):
                hours[day] = {"open": post.get(f"day_{day}_open"), "close": post.get(f"day_{day}_close")}
        questions = []
        for field, text in zip(post.getlist("q_field"), post.getlist("q_text"), strict=False):
            if text.strip():
                questions.append({"field": field, "question": {employee.primary_language: text.strip()}})
        return {
            "rules": {
                "working_hours": hours,
                "after_hours_message": post.get("after_hours_message"),
                "max_call_minutes": post.get("max_call_minutes") or 15,
                "transfer_user_ids": post.getlist("transfer_user_ids"),
                "escalation_triggers": post.get("escalation_triggers", ""),
                "restricted_topics": post.get("restricted_topics", ""),
                "fallback": _texts(post, "fallback", codes),
                "fallback_action": post.get("fallback_action") or "callback",
                "disclosure": _texts(post, "disclosure", codes),
                "recording": bool(post.get("recording")),
                "consent": _texts(post, "consent", codes),
                "handoff_keywords": post.get("handoff_keywords", ""),
                "handoff_on_knowledge_gap": bool(post.get("handoff_on_knowledge_gap")),
                "handoff_on_hot_lead": bool(post.get("handoff_on_hot_lead")),
                "follow_up": {
                    "enabled": bool(post.get("follow_up_enabled")),
                    "after_hours": post.get("follow_up_hours"),
                },
            },
            "qualification": questions,
        }
    return {}


def _voice_rows(employee):
    """EMP-05: per language — voices of the providers that speak it (Super Admin routes), the default, the choice."""
    from apps.providers.models import Voice
    from apps.providers.services import speech_chain

    rows = []
    for code, name in _lang_names(employee.languages or [employee.primary_language]):
        chain = speech_chain(code, "tts")
        providers = [r.provider_id for r in chain]
        voices = Voice.objects.filter(language__code=code, is_active=True, provider_id__in=providers).select_related(
            "provider"
        )
        default = chain[0].voice if chain and chain[0].voice else None
        rows.append(
            {
                "code": code,
                "name": name,
                "voices": voices,
                "selected": (employee.voices or {}).get(code) or (str(default.pk) if default else ""),
                "default": default,
            }
        )
    return rows


def _number_post(request, employee):
    """EMP-08: connect the chosen company number to this employee (and only that one)."""
    from apps.voice import services as voice

    numbers = voice.numbers_for(request.company)
    chosen = request.POST.get("phone_number") or ""
    for number in numbers:
        if str(number.pk) == chosen and number.employee_id != employee.pk:
            voice.connect_number(request.company, number, employee, request.user, request)
        elif str(number.pk) != chosen and number.employee_id == employee.pk:
            voice.connect_number(request.company, number, None, request.user, request)


def _knowledge_post(request, employee):
    """EMP-07 / KB-08: per source — all employees, only selected (incl. this one), or not this employee."""
    for source in Source.objects.filter(company=request.company):
        choice = request.POST.get(f"scope_{source.pk}")
        others = [e for e in source.employees.all() if e.pk != employee.pk]
        if choice == "all":
            source.employees.clear()
        elif choice == "include":
            source.employees.add(employee)
        elif choice == "exclude":
            if not others and not source.employees.exists():
                raise ValidationError(f"“{source.title}” is shared with all employees; choose who may use it instead.")
            source.employees.remove(employee)


@company_perm("ai_employees.view")
def employee_step(request, pk, step):
    if step not in STEP_KEYS or step in ("industry", "role"):
        raise Http404
    employee = _employee(request, pk)
    if request.method == "POST":
        _need_manage(request)
        try:
            if step == "activate":
                employees.activate(employee, request.user, request)
                messages.success(request, f"{employee.name} is active.")
                return redirect("panel:ai_detail", pk=employee.pk)
            if step == "test":
                employees.mark_tested(employee, request.user, request)
                messages.success(request, "Test passed for this version.")
            if step == "knowledge":
                _knowledge_post(request, employee)
            if step == "tools" and has_perm(request.user, "phone_numbers.manage", request.company):
                _number_post(request, employee)
            next_index = STEP_KEYS.index(step) + 1
            data = {**_step_data(request, employee, step), "wizard_step": next_index + 1}
            employees.update_employee(employee, data, request.user, request)
            if request.POST.get("then") == "stay":
                messages.success(request, "Saved.")
                return redirect("panel:ai_step", pk=employee.pk, step=step)
            return redirect("panel:ai_step", pk=employee.pk, step=STEP_KEYS[min(next_index, len(STEP_KEYS) - 1)])
        except ValidationError as exc:
            _errors(request, exc)
    context = {
        "employee": employee,
        "steps": STEPS,
        "current": step,
        "can_manage": _can_manage(request),
        "languages": _lang_names(employee.languages or [employee.primary_language]),
        "rules": employee.rules or {},
    }
    if step == "identity":
        context["greetings"] = employee.greetings or (
            employee.template_version.greetings if employee.template_version else {}
        )
    elif step == "voice":
        context["voice_rows"] = _voice_rows(employee)
    elif step == "languages":
        context["supported"] = _lang_names(employee.industry.supported_languages or languages.codes())
    elif step == "knowledge":
        sources = Source.objects.filter(company=request.company).prefetch_related("employees")
        context["sources"] = [
            (s, "all" if not s.employees.all() else ("include" if employee in s.employees.all() else "exclude"))
            for s in sources
        ]
    elif step == "tools":
        tools = toolkit.available(employee)
        from apps.voice.services import numbers_for

        context.update(
            numbers=numbers_for(request.company).filter(status="active"),
            can_numbers=has_perm(request.user, "phone_numbers.manage", request.company),
        )
        context.update(
            tools=[(t, employee.tools.get(t.key, True)) for t in tools],
            resources=Resource.objects.filter(company=request.company, is_active=True),
            statuses=templates.statuses(request.company),
        )
    elif step == "rules":
        version = employee.template_version
        flow = employee.qualification or (version.qualification_flow if version else [])
        lang = employee.primary_language
        context.update(
            days=[(k, label, (context["rules"].get("working_hours") or {}).get(k) or {}) for k, label in DAYS],
            team=members(request.company),
            lead_fields=[d for d in templates.fields_for(request.company, "lead") if d.is_active],
            questions=[
                {
                    "field": q.get("field", ""),
                    "text": (
                        q["question"].get(lang) or next(iter(q["question"].values()), "")
                        if isinstance(q.get("question"), dict)
                        else q.get("question", "")
                    ),
                }
                for q in flow
            ],
            fallback_default=runtime.fallback_text(employee, lang),
            disclosure_default=runtime.disclosure(employee, lang),
        )
    elif step == "test":
        context["field_labels"] = {d.key: d.label for d in templates.fields_for(request.company, "lead")}
    elif step == "activate":
        context["checks"] = employees.readiness(employee)
    return render(request, f"panel/company/ai/step_{step}.html", context)


# ------------------------------------------------------------------ detail, versions, usage (EMP-12)
@company_perm("ai_employees.view")
def employee_detail(request, pk):
    employee = _employee(request, pk)
    if request.method == "POST":
        _need_manage(request)
        op = request.POST.get("op")
        try:
            if op == "activate":
                employees.activate(employee, request.user, request)
            elif op == "pause":
                employees.pause(employee, request.POST.get("reason", ""), user=request.user, request=request)
            elif op == "archive":
                employees.archive(employee, request.user, request)
                messages.success(request, f"{employee.name} archived.")
                return redirect("panel:ai_list")
            elif op == "restore":
                employees.restore_version(employee, int(request.POST["version"]), request.user, request)
                messages.success(request, f"Version {request.POST['version']} restored as a new version.")
        except (ValidationError, ValueError, KeyError) as exc:
            _errors(request, exc)
        return redirect("panel:ai_detail", pk=employee.pk)
    month_start = timezone.localdate().replace(day=1)
    usage = (
        UsageEvent.objects.filter(employee=employee, occurred_at__date__gte=month_start)
        .values("meter")
        .annotate(total=Sum("quantity"))
    )
    return render(
        request,
        "panel/company/ai/detail.html",
        {
            "employee": employee,
            "stats": employees.stats([employee])[employee.pk],
            "usage": {u["meter"]: u["total"] for u in usage},
            "versions": employee.versions.all()[:30],
            "conversations": Conversation.objects.filter(employee=employee).select_related("lead")[:10],
            "steps": STEPS,
            "can_manage": _can_manage(request),
            "languages": [n for _, n in _lang_names(employee.languages)],
            "knowledge": Source.objects.filter(company=request.company)
            .filter(Q(employees__isnull=True) | Q(employees=employee))
            .distinct()[:20],
        },
    )


# ------------------------------------------------------------------ conversations (transcripts, tool log)
@company_perm("conversations.view")
def conversation_list(request):
    qs = Conversation.objects.filter(company=request.company).select_related("employee", "lead")
    for key, field in (("employee", "employee_id"), ("channel", "channel"), ("status", "status")):
        if request.GET.get(key):
            qs = qs.filter(**{field: request.GET[key]})
    if request.GET.get("test") in ("0", "1"):
        qs = qs.filter(is_test=request.GET["test"] == "1")
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "panel/company/ai/conversations.html",
        {
            "page": page,
            "employees": AIEmployee.objects.filter(company=request.company),
            "channels": Conversation.CHANNELS,
            "p": request.GET,
        },
    )


@company_perm("conversations.view")
def conversation_detail(request, pk):
    conv = get_object_or_404(
        Conversation.objects.select_related("employee", "lead").prefetch_related("messages", "tool_invocations"),
        pk=pk,
        company=request.company,
    )
    return render(request, "panel/company/ai/conversation.html", {"conv": conv})
