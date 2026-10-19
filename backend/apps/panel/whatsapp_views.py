"""Company panel: WhatsApp (M15) — numbers and the AI Employee answering each, message templates with Meta's approval
status, the template library, usage this month, and sending a template from a lead.
Views read the request and call apps.whatsapp.services.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.agents.models import AIEmployee
from apps.catalog.models import CatalogItem
from apps.crm.models import Lead
from apps.providers import languages
from apps.rbac.services import has_perm
from apps.scheduling.models import Appointment
from apps.whatsapp import services as wa
from apps.whatsapp.models import CATEGORIES, HEADERS, PURPOSES, VARIABLES, DefaultTemplate, Template, WaMessage

from .company_views import _errors, company_perm


def _number(request, pk):
    number = next((n for n in wa.numbers_for(request.company) if str(n.pk) == str(pk)), None)
    if number is None:
        raise Http404
    return number


@company_perm("whatsapp.manage")
def settings_page(request):
    company = request.company
    if request.method == "POST":
        op = request.POST.get("op")
        try:
            if op == "connect":
                number = _number(request, request.POST.get("number"))
                emp = request.POST.get("employee")
                employee = get_object_or_404(AIEmployee, pk=emp, company=company) if emp else None
                wa.connect_number(company, number, employee, request.user, request)
                messages.success(request, f"{number.e164} saved.")
            elif op == "sync":
                n = wa.sync_templates(company)
                messages.success(request, f"Approval status updated from Meta ({n} changed).")
            elif op == "library":
                default = get_object_or_404(DefaultTemplate, pk=request.POST.get("default"), is_active=True)
                number = _number(request, request.POST.get("number"))
                t = wa.copy_default(company, default, number, request.POST.get("language", ""), request.user, request)
                messages.success(request, "Template copied: check it and submit it to Meta.")
                return redirect("panel:whatsapp_template", pk=t.pk)
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("panel:whatsapp_settings")
    month = timezone.localdate().replace(day=1)
    usage = WaMessage.objects.filter(company=company, created_at__date__gte=month).aggregate(
        received=Count("id", filter=Q(direction="in")),
        sent=Count("id", filter=Q(direction="out")),
        delivered=Count("id", filter=Q(direction="out", status__in=["delivered", "read"])),
        read=Count("id", filter=Q(direction="out", status="read")),
        failed=Count("id", filter=Q(direction="out", status="failed")),
        billable=Count("id", filter=Q(billable=True)),
    )
    numbers = wa.numbers_for(company)
    return render(
        request,
        "panel/company/whatsapp/settings.html",
        {
            "numbers": numbers,
            "employees": AIEmployee.objects.filter(company=company).exclude(status=AIEmployee.ARCHIVED),
            "templates": Template.objects.filter(company=company).select_related("number"),
            "library": wa.library(),
            "languages": languages.choices(),
            "usage": usage,
            "webhook_ready": all(n.provider.webhook_secret for n in numbers),
        },
    )


def _template_post(request):
    post = request.POST
    buttons = [{"type": "QUICK_REPLY", "text": t.strip()[:25]} for t in post.getlist("button") if t.strip()][:3]
    return {
        "number": post.get("number"),
        "name": post.get("name", ""),
        "language": post.get("language", ""),
        "meta_language": post.get("meta_language", ""),
        "category": post.get("category", ""),
        "purpose": post.get("purpose", ""),
        "header_type": post.get("header_type", "none"),
        "header_text": post.get("header_text", ""),
        "body": post.get("body", ""),
        "footer": post.get("footer", ""),
        "buttons": buttons,
        "variables": [v for v in post.getlist("variable") if v],
    }


def _values(template):
    if template is None:
        return {"category": "UTILITY", "purpose": "general", "header_type": "none", "buttons": [], "variables": []}
    return {f: getattr(template, f) for f in wa.TEMPLATE_FIELDS} | {"number": str(template.number_id)}


@company_perm("whatsapp.manage")
def template_form(request, pk=None):
    template = get_object_or_404(Template, pk=pk, company=request.company) if pk else None
    if request.method == "POST":
        op = request.POST.get("op", "save")
        try:
            if op == "delete" and template:
                wa.delete_template(template, request.user, request)
                messages.success(request, "Template deleted.")
                return redirect("panel:whatsapp_settings")
            if op == "submit" and template:
                upload = request.FILES.get("sample")
                wa.submit_template(
                    template, (upload.read(), upload.content_type) if upload else None, request.user, request
                )
                messages.success(request, "Sent to Meta for review. Approval usually takes minutes to a day.")
                return redirect("panel:whatsapp_template", pk=template.pk)
            template = wa.save_template(request.company, template, _template_post(request), request.user, request)
            messages.success(request, "Template saved as a draft.")
            return redirect("panel:whatsapp_template", pk=template.pk)
        except ValidationError as exc:
            _errors(request, exc)
    return render(
        request,
        "panel/company/whatsapp/template.html",
        {
            "template": template,
            "f": _template_post(request) if request.method == "POST" else _values(template),
            "numbers": wa.numbers_for(request.company),
            "languages": languages.choices(),
            "categories": CATEGORIES,
            "purposes": PURPOSES,
            "headers": HEADERS,
            "variables": VARIABLES,
            "editable": template is None or template.status in (Template.DRAFT, Template.REJECTED),
        },
    )


@company_perm("whatsapp.send")
def send_to_lead(request, lead_pk):
    """WA-04 from the lead page: an approved template (with an item or appointment when it needs one)."""
    if request.method != "POST":
        raise Http404
    lead = get_object_or_404(Lead, pk=lead_pk, company=request.company, deleted_at__isnull=True)
    template = get_object_or_404(Template, pk=request.POST.get("template"), company=request.company)
    ctx = {"text": request.POST.get("text", "")[:500]}
    if request.POST.get("item"):
        ctx["item"] = get_object_or_404(CatalogItem, pk=request.POST["item"], company=request.company)
    if request.POST.get("appointment"):
        ctx["appointment"] = get_object_or_404(Appointment, pk=request.POST["appointment"], company=request.company)
    try:
        wa.send_template(template, lead, ctx, request.user, None, request)
        messages.success(request, f"WhatsApp “{template.name}” sent to {lead.phone}.")
    except ValidationError as exc:
        _errors(request, exc)
    return redirect("panel:lead_detail", pk=lead.pk)


def lead_card(request, lead):
    """Context for the WhatsApp card on the lead page."""
    if not has_perm(request.user, "whatsapp.send", request.company):
        return {}
    return {
        "wa": {
            "consent": wa.consent_state(lead),
            "templates": Template.objects.filter(company=request.company, status=Template.APPROVED),
            "items": CatalogItem.objects.filter(company=request.company, status=CatalogItem.ACTIVE)[:200],
            "appointments": lead.appointments.filter(status__in=Appointment.ACTIVE).select_related("appointment_type"),
            "messages": WaMessage.objects.filter(company=request.company, lead=lead).select_related("template")[:5],
            "has_numbers": bool(wa.numbers_for(request.company)),
        }
    }
