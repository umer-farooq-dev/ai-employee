"""Company panel: Billing & Usage (USE-02 … USE-04, SUB-03 … SUB-06, CP-06 billing details). Logic: apps.billing."""

import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.billing import access, gst, razorpay, usage
from apps.billing import services as billing
from apps.billing.models import FEATURES, CreditAdjustment, Invoice, Payment, Plan, Subscription
from apps.platform_config.services import get as setting
from apps.rbac.services import has_perm
from apps.tenancy.models import Company

from .company_views import _errors, company_perm


def _can_manage(request):
    return has_perm(request.user, "billing.manage", request.company)


def _details(company, data, request):
    """Billing details printed on GST invoices."""
    company = Company.objects.get(pk=company.pk)
    company.legal_name = str(data.get("legal_name", "")).strip()[:200]
    company.gstin = gst.clean_gstin(data.get("gstin"))
    company.address = str(data.get("address", "")).strip()[:1000]
    company.city = str(data.get("city", "")).strip()[:100]
    state = str(data.get("state", "")).strip()
    if state and state not in gst.NAMES:
        raise ValidationError("Choose your state.")
    if company.gstin and state and company.gstin[:2] != state:
        raise ValidationError("The GSTIN belongs to another state than the one chosen.")
    company.state = gst.NAMES.get(state, "")
    company.save(update_fields=["legal_name", "gstin", "address", "city", "state", "updated_at"])
    from apps.audit.services import record

    record(request, "company.billing_details", "company", company.id, company=company)


@company_perm("billing.view")
def billing_page(request):
    company = request.company
    if request.method == "POST":
        if not _can_manage(request):
            raise PermissionDenied
        op = request.POST.get("op")
        try:
            if op == "details":
                _details(company, request.POST, request)
                messages.success(request, "Billing details saved.")
            elif op == "cancel":
                when = billing.cancel(company, request.user, request.POST.get("reason", ""), request)
                messages.success(request, f"Your subscription will end on {when} and not renew.")
            elif op == "keep_plan":
                sub = billing.subscription(company)
                billing.change_plan(company, company.plan, sub.interval, request.user, request)
                messages.success(request, "The scheduled plan change was removed.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("panel:billing")
    sub = billing.subscription(company)
    invoices = Invoice.objects.filter(company=company).exclude(status=Invoice.VOID)[:24]
    payments = Payment.objects.filter(company=company).exclude(status=Payment.CREATED)[:24]
    rows = usage.overview(company)
    credits = next(r for r in rows if r["key"] == "ai_credits")
    return render(
        request,
        "panel/company/billing/index.html",
        {
            "company": company,
            "sub": sub,
            "price": billing.price(company, company.plan, sub.interval) if company.plan_id else None,
            "rows": rows,
            "monthly_rows": [r for r in rows if r["monthly"]],
            "other_rows": [r for r in rows if not r["monthly"]],
            "overage_total": sum(r["overage_paise"] for r in rows),
            "meters": usage.meters(company),
            "credits": credits,
            "extra_credits": CreditAdjustment.objects.filter(company=company)[:12],
            "invoices": invoices,
            "due": [i for i in invoices if i.status == Invoice.DUE],
            "payments": payments,
            "features": [(label, access.enabled(company, key)) for key, label in FEATURES],
            "states": gst.STATES,
            "state_code": gst.state_code(company.gstin, company.state),
            "can_manage": _can_manage(request),
            "online": bool(razorpay.provider()),
            "checkout_js": razorpay.CHECKOUT_JS,
            "month": usage.month_start(company),
            "includes_gst": setting("billing.prices_include_gst"),
        },
    )


@company_perm("billing.view")
def plans_page(request):
    company = request.company
    sub = billing.subscription(company)
    cards = []
    for plan in billing.purchasable(company):
        rows = {e.key: e for e in plan.entitlements.all()}
        prices = {}
        for interval in ("monthly", "yearly"):
            amount = billing.price(company, plan, interval)
            if amount is not None:
                prices[interval] = {"list": amount, "quote": billing.plan_quote(company, plan, interval)}
        cards.append(
            {
                "plan": plan,
                "current": plan.pk == company.plan_id,
                "prices": prices,
                "limits": [(label, rows.get(key)) for key, label in usage.ENTITLEMENTS if rows.get(key)],
                "upgrade": {i: billing.proration(company, plan, i) for i in ("monthly", "yearly")},
            }
        )
    return render(
        request,
        "panel/company/billing/plans.html",
        {
            "company": company,
            "sub": sub,
            "cards": cards,
            "has_yearly": any("yearly" in c["prices"] for c in cards),
            "interval": request.GET.get("interval") or sub.interval or "monthly",
            "can_manage": _can_manage(request),
            "online": bool(razorpay.provider()),
            "checkout_js": razorpay.CHECKOUT_JS,
            "includes_gst": setting("billing.prices_include_gst"),
            "gst_rate": setting("billing.gst_rate"),
            "running": sub.status == Subscription.ACTIVE
            and bool(sub.current_period_end)
            and not sub.cancel_at_period_end,
        },
    )


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


@require_POST
@company_perm("billing.manage")
def checkout(request):
    """→ Razorpay checkout options for: choose / change a plan, resume, pay an invoice."""
    company, data = request.company, _json_body(request)
    try:
        what = data.get("what")
        if what == "invoice":
            inv = get_object_or_404(Invoice, pk=data.get("invoice"), company=company)
            out = billing.pay_invoice(company, inv, request.user)
        elif what == "resume":
            out = billing.resume(company, request.user, request)
        else:
            plan = get_object_or_404(Plan, pk=data.get("plan"))
            out = billing.change_plan(company, plan, data.get("interval", "monthly"), request.user, request)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    if "scheduled" in out:
        if out["scheduled"]:
            messages.success(request, f"Your plan changes on {out['scheduled']}, at the next renewal.")
        else:
            messages.success(request, "You stay on your current plan.")
    elif out.get("resumed"):
        messages.success(request, "Your subscription continues.")
    return JsonResponse(out)


@require_POST
@company_perm("billing.manage")
def confirm(request):
    try:
        billing.confirm(request.company, _json_body(request), request.user, request)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    messages.success(request, "Payment received — thank you. Your invoice is in Billing and on its way by e-mail.")
    return JsonResponse({"ok": True})


@company_perm("billing.view")
def invoice_pdf(request, pk):
    inv = get_object_or_404(Invoice, pk=pk, company=request.company)
    response = HttpResponse(billing.invoice_pdf(inv), content_type="application/pdf")
    disposition = "attachment" if request.GET.get("download") else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{inv.number.replace("/", "-")}.pdf"'
    return response
