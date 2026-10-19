"""Super Admin: WhatsApp number pool (WA-02) with the webhook details to paste at Meta, and the default template
library companies copy from (WA-03). Views call apps.whatsapp.services."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.services import record
from apps.providers import languages
from apps.providers.models import Provider
from apps.tenancy.context import platform_context
from apps.tenancy.models import Company
from apps.whatsapp import services as wa
from apps.whatsapp.models import CATEGORIES, HEADERS, PURPOSES, VARIABLES, DefaultTemplate, WhatsAppNumber

from .views import staff_perm


def _errors(request, exc):
    for m in exc.messages:
        messages.error(request, m)


@staff_perm("number_pool.manage")
def numbers(request):
    with platform_context():
        editing = get_object_or_404(WhatsAppNumber, pk=request.GET["edit"]) if request.GET.get("edit") else None
        if request.method == "POST":
            post = request.POST
            data = {
                "provider": post.get("provider", ""),
                "e164": post.get("e164", ""),
                "display_name": post.get("display_name", ""),
                "phone_number_id": post.get("phone_number_id", ""),
                "waba_id": post.get("waba_id", ""),
                "company": post.get("company", ""),
                "is_test": bool(post.get("is_test")),
                "status": "active" if post.get("active") else "inactive",
            }
            try:
                wa.save_number(editing, data, request.user, request)
                messages.success(request, "WhatsApp number saved.")
                return redirect("superadmin:whatsapp_numbers")
            except ValidationError as exc:
                _errors(request, exc)
        rows = list(WhatsAppNumber.objects.select_related("provider", "company", "employee"))
    providers = Provider.objects.filter(capabilities__contains=["whatsapp"])
    return render(
        request,
        "panel/admin/whatsapp/numbers.html",
        {
            "rows": rows,
            "editing": editing,
            "providers": providers,
            "companies": Company.objects.filter(status__in=[Company.ACTIVE, Company.TRIAL]).order_by("name"),
            "hooks": [
                {
                    "provider": p,
                    "url": wa.webhook_url(p),
                    "token": wa.webhook_token(p),
                    "ready": bool(p.api_key and p.webhook_secret),
                }
                for p in providers
            ],
        },
    )


@staff_perm("whatsapp_templates.manage")
def library(request):
    return render(request, "panel/admin/whatsapp/library.html", {"rows": DefaultTemplate.objects.all()})


@staff_perm("whatsapp_templates.manage")
def library_form(request, pk=None):
    row = get_object_or_404(DefaultTemplate, pk=pk) if pk else None
    codes = languages.choices()
    if request.method == "POST":
        post = request.POST
        if post.get("op") == "delete" and row:
            record(request, "whatsapp_library.delete", "whatsapp_template", row.name)
            row.delete()
            messages.success(request, "Template removed from the library.")
            return redirect("superadmin:whatsapp_library")
        texts = {}
        for code, _ in codes:
            body = post.get(f"body_{code}", "").strip()
            if body:
                texts[code] = {
                    "header": post.get(f"header_{code}", "").strip(),
                    "body": body,
                    "footer": post.get(f"footer_{code}", "").strip(),
                }
        variables = [v for v in post.getlist("variable") if v]
        target = row or DefaultTemplate()
        try:
            wa.check_default(post.get("name", "").strip(), texts, variables)
            target.name, target.title = post.get("name", "").strip(), post.get("title", "").strip()
            target.purpose, target.category = post.get("purpose", "general"), post.get("category", "UTILITY")
            target.header_type, target.texts, target.variables = post.get("header_type", "none"), texts, variables
            target.is_active = bool(post.get("is_active"))
            target.sort_order = int(post.get("sort_order") or 0)
            target.full_clean()
            target.save()
            record(request, "whatsapp_library.save", "whatsapp_template", target.name)
            messages.success(request, "Library template saved.")
            return redirect("superadmin:whatsapp_library")
        except (ValidationError, ValueError) as exc:
            _errors(request, exc if isinstance(exc, ValidationError) else ValidationError("Order must be a number."))
    return render(
        request,
        "panel/admin/whatsapp/library_form.html",
        {
            "row": row,
            "languages": [(c, n, ((row.texts if row else {}) or {}).get(c, {})) for c, n in codes],
            "purposes": PURPOSES,
            "categories": CATEGORIES,
            "headers": HEADERS,
            "variables": VARIABLES,
            "chosen": (row.variables if row else []) + [""] * 6,
        },
    )
