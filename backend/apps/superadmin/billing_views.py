"""Super Admin: billing across companies (SA-13), one company's billing terms, feature overrides, credits and invoices
(SUB-04, SA-20, USE-04) and the usage / cost / margin report (SA-14, USE-06). Logic: apps.billing."""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.billing import access, gst, reports, usage
from apps.billing import services as billing
from apps.billing.models import (
    ENTITLEMENTS,
    FEATURES,
    INTERVALS,
    CreditAdjustment,
    Invoice,
    Payment,
    Plan,
    PlanEntitlement,
    Subscription,
)
from apps.rbac.services import has_perm
from apps.tenancy.context import company_context
from apps.tenancy.models import Company

from .views import _errors, page_of, staff_perm


def _rupees_to_paise(value, label):
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{label}: enter an amount in rupees.") from None
    return int(amount * 100)


@staff_perm("subscriptions.view")
def billing_home(request):
    tab = request.GET.get("tab", "subscriptions")
    q, status = request.GET.get("q", "").strip(), request.GET.get("status", "")
    ctx = {"tab": tab, "q": q, "status": status, "can_manage": has_perm(request.user, "subscriptions.manage")}
    if tab == "invoices":
        qs = Invoice.all_companies.select_related("company").order_by("-issued_at")
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(number__icontains=q) | qs.filter(company__name__icontains=q)
        ctx.update(page=page_of(request, qs), statuses=Invoice.STATUSES)
    elif tab == "payments":
        qs = Payment.all_companies.select_related("company", "invoice").exclude(status=Payment.CREATED)
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(company__name__icontains=q)
        ctx.update(page=page_of(request, qs.order_by("-created_at")), statuses=Payment.STATUSES[1:])
    else:
        tab = ctx["tab"] = "subscriptions"
        missing = Company.objects.filter(deleted_at__isnull=True, subscription__isnull=True).exclude(
            status__in=(Company.PENDING, Company.REJECTED)
        )
        for company in missing:  # billing rows are created on first use; list every billed company
            with company_context(company.id):
                billing.subscription(company)
        qs = Subscription.all_companies.select_related("company", "company__plan", "pending_plan").filter(
            company__deleted_at__isnull=True
        )
        if status == "on_hold":
            qs = qs.filter(company__billing_hold__isnull=False)
        elif status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(company__name__icontains=q)
        ctx.update(
            page=page_of(request, qs.order_by("company__name")),
            statuses=[*Subscription.STATUSES, ("on_hold", "On hold (unpaid)")],
        )
    ctx["summary"] = {
        "mrr": reports.mrr(),
        "past_due": Subscription.all_companies.filter(status=Subscription.PAST_DUE).count(),
        "on_hold": Company.objects.filter(billing_hold__isnull=False, deleted_at__isnull=True).count(),
        "due": Invoice.all_companies.filter(status=Invoice.DUE).count(),
        "failed": Payment.all_companies.filter(status=Payment.FAILED).count(),
    }
    return render(request, "panel/admin/billing/index.html", ctx)


@require_POST
@staff_perm("subscriptions.manage")
def invoice_action(request, pk):
    inv = get_object_or_404(Invoice.all_companies.select_related("company"), pk=pk)
    op = request.POST.get("op")
    with company_context(inv.company_id):
        try:
            if op == "paid":
                ref = request.POST.get("reference", "").strip()
                if not ref:
                    raise ValidationError("Enter the payment reference (UTR, cheque no. …).")
                billing.mark_paid(inv, ref, request.user, method=request.POST.get("method") or "bank", request=request)
                messages.success(request, f"{inv.number} marked as paid.")
            elif op == "void":
                billing.void_invoice(inv, request.POST.get("reason", "").strip() or "Cancelled", request.user, request)
                messages.success(request, f"{inv.number} cancelled.")
        except ValidationError as exc:
            _errors(request, exc)
    return redirect(request.POST.get("next") or "superadmin:billing")


@staff_perm("subscriptions.view")
def invoice_pdf(request, pk):
    inv = get_object_or_404(Invoice.all_companies, pk=pk)
    response = HttpResponse(billing.invoice_pdf(inv), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{inv.number.replace("/", "-")}.pdf"'
    return response


@staff_perm("subscriptions.view")
def company_billing(request, pk):
    company = get_object_or_404(Company, pk=pk)
    can_manage = has_perm(request.user, "subscriptions.manage")
    with company_context(company.id):
        if request.method == "POST":
            if not can_manage:
                return redirect("superadmin:company_billing", pk=pk)
            op = request.POST.get("op")
            try:
                if op == "terms":
                    billing.save_terms(company, request.POST, request.user, request)
                    messages.success(request, "Billing terms saved.")
                elif op == "credits":
                    billing.adjust_credits(
                        company,
                        int(request.POST.get("credits") or 0),
                        request.POST.get("reason", ""),
                        request.user,
                        request,
                    )
                    messages.success(request, "Credits adjusted.")
                elif op == "invoice":
                    plan = Plan.objects.filter(pk=request.POST.get("plan") or None).first()
                    interval = request.POST.get("interval") or "monthly"
                    period, description = None, request.POST.get("description", "").strip()
                    if plan and request.POST.get("period_start"):
                        start = timezone.make_aware(datetime.fromisoformat(request.POST["period_start"]))
                        period = (start, billing.add_period(start, interval))
                        description = description or billing.period_text(plan, interval, *period)
                    if request.POST.get("amount", "").strip() or not period:
                        amount = _rupees_to_paise(request.POST.get("amount", ""), "Amount")
                    else:  # plan period without an amount: the plan's (or the company's custom) price
                        list_price = billing.price(company, plan, interval)
                        if not list_price:
                            raise ValidationError(f"{plan.name} has no {interval} price; enter the amount.")
                        amount = billing.taxable(list_price, plan)
                    inv = billing.manual_invoice(
                        company,
                        description or "Services",
                        amount,
                        request.user,
                        request,
                        plan=plan if period else None,
                        interval=request.POST.get("interval", "") if period else "",
                        period=period,
                    )
                    messages.success(request, f"Invoice {inv.number} issued and e-mailed.")
                elif op == "release":
                    billing.release(company)
                    messages.success(request, "Billing hold lifted.")
                elif op == "hold":
                    billing.hold(
                        company, request.POST.get("reason", "").strip() or "Paused by the platform team.", request
                    )
                    messages.success(request, "Company put on billing hold.")
            except ValidationError as exc:
                _errors(request, exc)
            except ValueError:
                messages.error(request, "Enter whole numbers and valid dates.")
            return redirect("superadmin:company_billing", pk=pk)
        sub = billing.subscription(company)
        plan_rows = (
            {e.key: e for e in PlanEntitlement.objects.filter(plan_id=company.plan_id)} if company.plan_id else {}
        )
        limits_rows = []
        for key, label in ENTITLEMENTS:
            custom = (sub.custom_limits or {}).get(key)
            limits_rows.append({"key": key, "label": label, "plan": plan_rows.get(key), "custom": custom})
        plan_flags = company.plan.flags if company.plan_id else {}
        ctx = {
            "company": company,
            "sub": sub,
            "rows": usage.overview(company),
            "limits_rows": limits_rows,
            "features": [
                (
                    key,
                    label,
                    (sub.feature_overrides or {}).get(key),
                    plan_flags.get(key, True),
                    access.enabled(company, key),
                )
                for key, label in FEATURES
            ],
            "invoices": Invoice.objects.filter(company=company)[:30],
            "payments": Payment.objects.filter(company=company).exclude(status=Payment.CREATED)[:30],
            "credits": CreditAdjustment.objects.filter(company=company).select_related("created_by")[:20],
            "plans": Plan.objects.filter(status=Plan.ACTIVE),
            "intervals": INTERVALS,
            "price": billing.price(company, company.plan, sub.interval) if company.plan_id else None,
            "state": gst.NAMES.get(gst.state_code(company.gstin, company.state), company.state),
            "can_manage": can_manage,
            "today": timezone.localdate(),
        }
        return render(request, "panel/admin/billing/company.html", ctx)


@staff_perm("usage_reports.view")
def usage_report(request):
    data = reports.usage_report(request.GET.get("month"))
    start = data["start"]
    months = []
    cursor = timezone.localdate().replace(day=1)
    for _ in range(12):
        months.append((cursor.strftime("%Y-%m"), cursor.strftime("%b %Y")))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    return render(request, "panel/admin/billing/usage.html", {"data": data, "months": months, "start": start})
