"""SUB-03 … SUB-06, USE-02 … USE-04, NOTI-01: the subscription lifecycle (trial → paid → renewals → overdue → hold),
Razorpay checkout and webhooks, prorated upgrades, scheduled downgrades, cancellation, GST invoices with PDF, manual
(enterprise) invoicing, AI credit adjustments. Prices, GST, grace days and texts are data (Super Admin)."""

import calendar
import json
import logging
from datetime import UTC, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.audit.services import record
from apps.platform_config.services import get as setting
from apps.providers.adapters import ProviderError
from apps.tenancy.context import company_context, platform_context
from apps.tenancy.models import Company

from . import gst, razorpay
from .models import CreditAdjustment, Invoice, InvoiceSequence, Payment, Plan, Subscription

logger = logging.getLogger(__name__)
S = Subscription


# ------------------------------------------------------------------ money
def fmt(paise, decimals=True):
    """Paise → "₹1,23,456.00" in the platform number format."""
    rupees = Decimal(paise or 0) / 100
    sign, rupees = ("-" if rupees < 0 else ""), abs(rupees)
    whole, frac = f"{rupees:.2f}".split(".")
    if setting("locale.number_format") == "indian" and len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])
    else:
        whole = f"{int(whole):,}"
    return f"{sign}₹{whole}" + (f".{frac}" if decimals else "")


def period_text(plan, interval, start, end):
    return f"{plan.name} plan, {interval} ({timezone.localtime(start):%d %b %Y} to {timezone.localtime(end):%d %b %Y})"


def add_period(start, interval, n=1):
    months = n * (12 if interval == "yearly" else 1)
    m = start.month - 1 + months
    year, month = start.year + m // 12, m % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


# ------------------------------------------------------------------ subscription and prices
def subscription(company):
    """The company's billing row, created on first use from the company status."""
    sub = Subscription.objects.filter(company=company).first()
    if sub:
        return sub
    if company.status == Company.TRIAL:
        status, gateway = S.TRIALING, S.RAZORPAY
    elif company.billing_hold:
        status, gateway = S.PENDING, S.RAZORPAY
    else:  # active before billing existed / created by Super Admin: billed by invoice until it subscribes online
        status, gateway = S.ACTIVE, S.MANUAL
    return Subscription.objects.create(company=company, status=status, gateway=gateway)


def gst_rate(plan=None):
    return Decimal(str(plan.gst_rate if plan and plan.gst_rate is not None else setting("billing.gst_rate")))


def price(company, plan, interval):
    """List price (paise, as entered: with or without GST per setting) or None when not sold online."""
    sub = Subscription.objects.filter(company=company).first()
    if sub and sub.custom_price_paise is not None and plan.pk == company.plan_id:
        return sub.custom_price_paise
    return plan.price_yearly_paise if interval == "yearly" else plan.price_monthly_paise


def taxable(gross_or_net, plan=None):
    """The taxable value of a list price."""
    if setting("billing.prices_include_gst"):
        return gst.taxable_from_inclusive(gross_or_net, gst_rate(plan))
    return gross_or_net


def quote(company, amount_taxable, plan=None):
    """GST on a taxable amount for this company → {taxable, cgst, sgst, igst, total, intra_state, rate}."""
    rate = gst_rate(plan)
    tax = gst.split(amount_taxable, rate, setting("billing.seller_state"), gst.state_code(company.gstin, company.state))
    return {**tax, "taxable": amount_taxable, "rate": str(rate)}


def plan_quote(company, plan, interval):
    amount = price(company, plan, interval)
    if amount is None:
        raise ValidationError(f"The {plan.name} plan is not sold online. Please contact us.")
    return quote(company, taxable(amount, plan), plan)


def purchasable(company):
    """Plans the company can choose: public active plans, plus its own (custom) plan."""
    return [
        p
        for p in Plan.objects.filter(status=Plan.ACTIVE).order_by("sort_order", "name")
        if p.is_public or p.pk == company.plan_id
    ]


# ------------------------------------------------------------------ invoices (SUB-06)
def seller():
    code = setting("billing.seller_state")
    return {
        "name": setting("contact.legal_name") or setting("general.platform_name"),
        "gstin": setting("contact.gstin"),
        "pan": setting("contact.pan"),
        "address": setting("contact.address"),
        "state": gst.NAMES.get(code, ""),
        "state_code": code,
        "email": setting("contact.support_email"),
        "phone": setting("contact.support_phone"),
    }


def buyer(company):
    code = gst.state_code(company.gstin, company.state)
    return {
        "name": company.legal_name or company.name,
        "gstin": company.gstin,
        "address": "\n".join(x for x in (company.address, company.city) if x),
        "state": gst.NAMES.get(code, company.state),
        "state_code": code,
        "email": company.email,
        "phone": company.phone,
    }


def next_number(when):
    """PREFIX/26-27/00001 — consecutive within the Indian financial year (April–March)."""
    local = timezone.localtime(when)
    fy = local.year if local.month >= 4 else local.year - 1
    key = f"{setting('billing.invoice_prefix')}/{fy % 100:02d}-{(fy + 1) % 100:02d}"
    with transaction.atomic():
        seq, _ = InvoiceSequence.objects.select_for_update().get_or_create(key=key)
        seq.last += 1
        seq.save(update_fields=["last", "updated_at"])
    return f"{key}/{seq.last:05d}"


def issue_invoice(
    company,
    description,
    amount_taxable,
    kind="subscription",
    plan=None,
    interval="",
    period=(None, None),
    paid=False,
    payment_ref="",
    notes="",
    now=None,
):
    now = now or timezone.now()
    q = quote(company, amount_taxable, plan)
    b = buyer(company)
    return Invoice.objects.create(
        company=company,
        number=next_number(now),
        kind=kind,
        status=Invoice.PAID if paid else Invoice.DUE,
        issued_at=now,
        due_at=None if paid else now + timedelta(days=setting("billing.invoice_due_days")),
        paid_at=now if paid else None,
        period_start=period[0],
        period_end=period[1],
        plan=plan,
        interval=interval,
        seller=seller(),
        buyer=b,
        place_of_supply=f"{b['state']} ({b['state_code']})" if b["state_code"] else "",
        intra_state=q["intra_state"],
        lines=[
            {
                "description": description,
                "sac": setting("billing.sac_code"),
                "quantity": 1,
                "unit_paise": amount_taxable,
                "amount_paise": amount_taxable,
            }
        ],
        subtotal_paise=amount_taxable,
        gst_rate=Decimal(q["rate"]),
        cgst_paise=q["cgst"],
        sgst_paise=q["sgst"],
        igst_paise=q["igst"],
        total_paise=q["total"],
        notes=notes,
        payment_ref=payment_ref,
    )


def taxable_in(company, total_paise, plan=None):
    """The taxable value inside an amount that was charged with GST (gateway renewals)."""
    rate = gst_rate(plan)
    base = gst.taxable_from_inclusive(total_paise, rate)
    for guess in (base, base - 1, base + 1, base - 2, base + 2):
        if quote(company, guess, plan)["total"] == total_paise:
            return guess
    return base


def _words(n):
    """Rupees in words, Indian system (lakh / crore)."""
    ones = (
        "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen Sixteen "
        "Seventeen Eighteen Nineteen"
    ).split()
    tens = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()

    def two(x):
        return ones[x] if x < 20 else tens[x // 10] + ("" if x % 10 == 0 else " " + ones[x % 10])

    def three(x):
        return (ones[x // 100] + " Hundred" + (" " + two(x % 100) if x % 100 else "")) if x >= 100 else two(x)

    if n == 0:
        return "Zero"
    parts = []
    for div, name in ((10**7, "Crore"), (10**5, "Lakh"), (1000, "Thousand")):
        if n >= div:
            parts.append(f"{_words(n // div) if div == 10**7 else two(n // div)} {name}")
            n %= div
    if n:
        parts.append(three(n))
    return " ".join(parts)


def invoice_pdf(inv):
    from .pdf import A4, Document, wrap

    d, W, M = Document(), A4[0], 40
    s, b = inv.seller, inv.buyer
    brand = setting("general.color_primary")
    d.box(0, 0, W, 6, brand)
    d.text(M, 30, s.get("name", ""), 16, bold=True)
    y = 52
    for line in wrap(s.get("address", ""), 9, 260):
        d.text(M, y, line, 9, colour="#4b5563")
        y += 12
    for label, key in (("GSTIN", "gstin"), ("PAN", "pan"), ("Email", "email")):
        if s.get(key):
            d.text(M, y, f"{label}: {s[key]}", 9, colour="#4b5563")
            y += 12
    d.text(W - M, 30, "TAX INVOICE", 16, bold=True, colour=brand, align="right")
    rows = [
        ("Invoice no.", inv.number),
        ("Date", timezone.localtime(inv.issued_at).strftime("%d %b %Y")),
        (
            "Status",
            "PAID" if inv.status == Invoice.PAID else ("CANCELLED" if inv.status == Invoice.VOID else "DUE"),
        ),
    ]
    if inv.due_at and inv.status == Invoice.DUE:
        rows.append(("Due by", timezone.localtime(inv.due_at).strftime("%d %b %Y")))
    if inv.place_of_supply:
        rows.append(("Place of supply", inv.place_of_supply))
    ry = 54
    for label, value in rows:
        d.text(W - M - 150, ry, label, 9, colour="#6b7280")
        d.text(W - M, ry, value, 9, bold=True, align="right")
        ry += 13
    y = max(y, ry) + 14
    d.box(M, y, W - 2 * M, 1, "#e5e7eb")
    y += 14
    d.text(M, y, "BILL TO", 8, bold=True, colour="#6b7280")
    y += 14
    d.text(M, y, b.get("name", ""), 11, bold=True)
    y += 15
    for line in wrap(b.get("address", ""), 9, 300):
        d.text(M, y, line, 9, colour="#4b5563")
        y += 12
    if b.get("state"):
        d.text(M, y, f"State: {b['state']}" + (f" ({b['state_code']})" if b.get("state_code") else ""), 9)
        y += 12
    d.text(M, y, f"GSTIN: {b.get('gstin') or 'Unregistered'}", 9)
    y += 24
    # line items
    cols = [M + 8, M + 30, W - M - 210, W - M - 150, W - M - 80, W - M - 8]
    d.box(M, y, W - 2 * M, 22, "#f3f4f6")
    for x, label, align in zip(
        cols, ("#", "Description", "SAC", "Qty", "Rate", "Amount"), ("left",) * 3 + ("right",) * 3, strict=True
    ):
        d.text(x if align == "left" else x, y + 7, label, 8, bold=True, colour="#374151", align=align)
    y += 30
    for i, line in enumerate(inv.lines, 1):
        text = wrap(line["description"], 9, cols[2] - cols[1] - 10)
        d.text(cols[0], y, str(i), 9)
        for j, t in enumerate(text):
            d.text(cols[1], y + j * 12, t, 9)
        d.text(cols[2], y, line.get("sac") or "-", 9)
        d.text(cols[3], y, str(line.get("quantity", 1)), 9, align="right")
        d.text(cols[4], y, fmt(line["unit_paise"]), 9, align="right")
        d.text(cols[5], y, fmt(line["amount_paise"]), 9, align="right")
        y += 12 * len(text) + 10
        d.line(M, y - 4, W - M, y - 4)
    # totals
    y += 8
    rate = Decimal(inv.gst_rate)
    totals = [("Taxable value", inv.subtotal_paise)]
    if inv.intra_state:
        totals += [(f"CGST @ {rate / 2:g}%", inv.cgst_paise), (f"SGST @ {rate / 2:g}%", inv.sgst_paise)]
    else:
        totals.append((f"IGST @ {rate:g}%", inv.igst_paise))
    for label, value in totals:
        d.text(W - M - 150, y, label, 9, colour="#4b5563")
        d.text(cols[5], y, fmt(value), 9, align="right")
        y += 15
    d.box(W - M - 160, y - 2, 160, 24, "#f3f4f6")
    d.text(W - M - 150, y + 5, "Total", 11, bold=True)
    d.text(cols[5], y + 5, fmt(inv.total_paise), 11, bold=True, align="right")
    y += 36
    rupees, paise = divmod(inv.total_paise, 100)
    words = f"Rupees {_words(rupees)}" + (f" and {_words(paise)} Paise" if paise else "") + " Only"
    for line in wrap(f"Amount in words: {words}", 9, W - 2 * M):
        d.text(M, y, line, 9, colour="#374151")
        y += 12
    if inv.payment_ref:
        d.text(M, y + 4, f"Payment reference: {inv.payment_ref}", 9, colour="#4b5563")
        y += 16
    if inv.notes:
        for line in wrap(inv.notes, 9, W - 2 * M):
            d.text(M, y + 4, line, 9, colour="#4b5563")
            y += 12
    fy = A4[1] - 70
    for line in wrap(setting("billing.invoice_footer"), 8, W - 2 * M):
        d.text(M, fy, line, 8, colour="#6b7280")
        fy += 11
    d.text(M, A4[1] - 30, "This is a computer-generated invoice and needs no signature.", 8, colour="#9ca3af")
    return d.render()


# ------------------------------------------------------------------ messages
def billing_url():
    from django.conf import settings

    return settings.PUBLIC_BASE_URL.rstrip("/") + reverse("panel:billing")


def _recipients(company):
    from apps.tenancy.services import owners

    return list(dict.fromkeys([*owners(company), *([company.email] if company.email else [])]))


def _email(company, key, context, invoice=None):
    from apps.notifications import services as mail

    ctx = {"company_name": company.name, "url": billing_url(), **context}
    files = [(f"{invoice.number.replace('/', '-')}.pdf", invoice_pdf(invoice))] if invoice else ()
    for to in _recipients(company):
        try:
            mail.send(key, to, ctx, attachments=files)
        except Exception:  # noqa: BLE001 — mail failures must not undo a payment
            logger.exception("billing mail %s to %s failed", key, to)


def _alert(company, title, body=""):
    from apps.notifications import alerts

    alerts.notify(company, alerts.people_with(company, "billing.view"), "usage", title, body, reverse("panel:billing"))


def _invoice_mail(company, inv, description):
    _email(
        company,
        "billing/invoice" if inv.status == Invoice.PAID else "billing/invoice_due",
        {
            "invoice_number": inv.number,
            "amount": fmt(inv.total_paise),
            "description": description,
            "due_date": timezone.localtime(inv.due_at).strftime("%d %b %Y") if inv.due_at else "",
        },
        inv,
    )


# ------------------------------------------------------------------ hold (unpaid → only Billing opens)
def hold(company, reason, request=None):
    if company.billing_hold:
        return
    company.billing_hold = timezone.now()
    company.save(update_fields=["billing_hold", "updated_at"])
    record(request, "billing.hold", "company", company.id, company=company, changes={"reason": reason})
    _email(company, "billing/on_hold", {"reason": reason})
    _alert(company, "AI Employees paused: subscription unpaid", reason)


def release(company):
    if company.billing_hold:
        company.billing_hold = None
        company.save(update_fields=["billing_hold", "updated_at"])


# ------------------------------------------------------------------ activation after a payment
def _paid(
    company,
    payment,
    payment_id,
    plan,
    interval,
    start=None,
    end=None,
    gateway_sub="",
    kind="subscription",
    method="",
    user=None,
):
    """A captured payment → paid invoice, active subscription, plan applied, hold lifted, receipt e-mailed."""
    if payment_id and Payment.objects.filter(gateway_payment_id=payment_id, status=Payment.CAPTURED).exists():
        return None  # already processed (checkout handler and webhook both report the same payment)
    now = timezone.now()
    sub = subscription(company)
    amount = payment.amount_paise
    if kind == "subscription":
        start = start or now
        end = end or add_period(start, interval)
        desc = period_text(plan, interval, start, end)
    else:
        desc = f"Upgrade to the {plan.name} plan for the rest of the current period"
    inv = issue_invoice(
        company,
        desc,
        taxable_in(company, amount, plan),
        kind=kind,
        plan=plan,
        interval=interval,
        period=(start, end) if kind == "subscription" else (None, None),
        paid=True,
        payment_ref=payment_id,
        now=now,
    )
    payment.status, payment.invoice, payment.gateway_payment_id = Payment.CAPTURED, inv, payment_id
    payment.method = method or payment.method
    payment.save()
    if kind == "subscription":
        sub.status, sub.interval = S.ACTIVE, interval
        sub.current_period_start, sub.current_period_end = start, end
        if gateway_sub:
            sub.gateway, sub.gateway_subscription_id = S.RAZORPAY, gateway_sub
            sub.cancel_at_period_end, sub.cancel_reason, sub.cancelled_at = False, "", None
        if sub.pending_plan_id == plan.pk:
            sub.pending_plan, sub.pending_interval = None, ""
    else:
        sub.pending_plan, sub.pending_interval = None, ""
    sub.failed_payments, sub.grace_until, sub.last_payment_at = 0, None, now
    sub.save()
    company.plan = plan
    if company.status == Company.TRIAL:
        company.status, company.trial_ends_at = Company.ACTIVE, None
    company.billing_hold = None
    company.save(update_fields=["plan", "status", "trial_ends_at", "billing_hold", "updated_at"])
    record(
        None,
        "billing.paid",
        "invoice",
        inv.id,
        company=company,
        user=user,
        changes={"amount": amount, "plan": plan.key, "kind": kind},
    )
    _invoice_mail(company, inv, desc)
    return inv


# ------------------------------------------------------------------ checkout (SUB-03)
def _gateway():
    p = razorpay.provider()
    if not p:
        raise ValidationError("Online payment is not set up yet. Please contact support.")
    return p


def _checkout(company, user, amount, description, **ids):
    return {
        "key": razorpay.key_id(_gateway()),
        "name": setting("general.platform_name"),
        "description": description,
        "amount": amount,
        "currency": "INR",
        "prefill": {"name": user.full_name or "", "email": user.email, "contact": user.phone or company.phone},
        "notes": {"company": str(company.pk)},
        "theme": {"color": setting("general.color_company_panel")},
        **ids,
    }


def _check_plan(company, plan, interval):
    if plan.status != Plan.ACTIVE or not (plan.is_public or plan.pk == company.plan_id):
        raise ValidationError("This plan is not available.")
    if interval not in ("monthly", "yearly"):
        raise ValidationError("Choose monthly or yearly.")


def subscribe(company, plan, interval, user, request=None, start_at=None):
    """New subscription with auto-renewal: Razorpay subscription → checkout opens on the page."""
    _check_plan(company, plan, interval)
    sub = subscription(company)
    if sub.status == S.ACTIVE and sub.gateway_subscription_id and not sub.cancel_at_period_end:
        raise ValidationError("You already have an active subscription. Change the plan instead.")
    q = plan_quote(company, plan, interval)
    p = _gateway()
    try:
        rp_plan = razorpay.ensure_plan(p, plan, interval, q["total"])
        rsub = razorpay.create_subscription(
            p, rp_plan, interval, {"company": str(company.pk), "plan": plan.key, "interval": interval}, start_at
        )
    except ProviderError as exc:
        raise ValidationError(f"Payment could not be started: {exc}") from None
    Payment.objects.create(
        company=company,
        amount_paise=q["total"],
        purpose="subscription",
        gateway_order_id=rsub["id"],
        data={"plan": plan.key, "interval": interval, "subscription_id": rsub["id"], "quote": q},
    )
    record(request, "billing.checkout", "plan", plan.id, company=company, changes={"interval": interval})
    return _checkout(company, user, q["total"], f"{plan.name} plan · {interval}", subscription_id=rsub["id"])


def _order(company, user, amount, purpose, data, description):
    p = _gateway()
    try:
        order = razorpay.create_order(
            p, amount, f"{purpose}-{timezone.now():%y%m%d%H%M%S}", {"company": str(company.pk)}
        )
    except ProviderError as exc:
        raise ValidationError(f"Payment could not be started: {exc}") from None
    Payment.objects.create(
        company=company, amount_paise=amount, purpose=purpose, gateway_order_id=order["id"], data=data
    )
    return _checkout(company, user, amount, description, order_id=order["id"])


def confirm(company, data, user=None, request=None):
    """Checkout handler data: razorpay_payment_id, razorpay_signature and the order or subscription id."""
    p = _gateway()
    pay_id = str(data.get("razorpay_payment_id", ""))
    order_id, sub_id = str(data.get("razorpay_order_id", "")), str(data.get("razorpay_subscription_id", ""))
    payment = Payment.objects.filter(company=company, gateway_order_id=order_id or sub_id).first()
    if not payment or not pay_id:
        raise ValidationError("Unknown payment.")
    try:
        razorpay.verify_payment(p, pay_id, str(data.get("razorpay_signature", "")), order_id, sub_id)
    except ProviderError as exc:
        payment.status, payment.error = Payment.FAILED, str(exc)[:300]
        payment.save(update_fields=["status", "error", "updated_at"])
        raise ValidationError(str(exc)) from None
    return _apply(company, payment, pay_id, user=user, gateway_sub=sub_id)


def _apply(company, payment, pay_id, user=None, gateway_sub="", start=None, end=None, method=""):
    info = payment.data or {}
    if payment.purpose == "invoice":
        inv = Invoice.objects.filter(company=company, pk=info.get("invoice")).first()
        return mark_paid(inv, pay_id, user, method="razorpay", payment=payment) if inv else None
    plan = Plan.objects.get(key=info["plan"])
    kind = "upgrade" if payment.purpose == "upgrade" else "subscription"
    inv = _paid(
        company,
        payment,
        pay_id,
        plan,
        info.get("interval", "monthly"),
        start=start,
        end=end,
        gateway_sub=gateway_sub or info.get("subscription_id", ""),
        kind=kind,
        method=method,
        user=user,
    )
    if inv and kind == "upgrade":
        _schedule_gateway_price(company, plan, info.get("interval", "monthly"))
    return inv


def _schedule_gateway_price(company, plan, interval):
    """From the next renewal Razorpay charges the new plan's price."""
    sub = subscription(company)
    p = razorpay.provider()
    if not (p and sub.gateway_subscription_id):
        return
    try:
        razorpay.update_subscription(
            p,
            sub.gateway_subscription_id,
            razorpay.ensure_plan(p, plan, interval, plan_quote(company, plan, interval)["total"]),
        )
    except (ProviderError, ValidationError) as exc:
        logger.warning("Razorpay plan change for %s failed: %s", company.pk, exc)


# ------------------------------------------------------------------ change plan / cancel
def proration(company, plan, interval, now=None):
    """Taxable difference for the rest of the current period when moving to a dearer plan (0 = not an upgrade)."""
    sub = subscription(company)
    now = now or timezone.now()
    if not (sub.status == S.ACTIVE and sub.current_period_start and sub.current_period_end and company.plan_id):
        return 0
    if interval != sub.interval or sub.current_period_end <= now:
        return 0
    old, new = price(company, company.plan, sub.interval), price(company, plan, interval)
    if old is None or new is None or new <= old:
        return 0
    left = (sub.current_period_end - now) / (sub.current_period_end - sub.current_period_start)
    return gst.paise(Decimal(taxable(new, plan) - taxable(old, company.plan)) * Decimal(str(left)))


def change_plan(company, plan, interval, user, request=None):
    """Upgrade now (prorated payment) or change at the next renewal. → checkout dict or {"scheduled": date}."""
    _check_plan(company, plan, interval)
    sub = subscription(company)
    if sub.manual and sub.status == S.ACTIVE and sub.current_period_end:
        raise ValidationError("Your plan is billed by invoice. Please contact support to change it.")
    if sub.status != S.ACTIVE or not sub.current_period_end or sub.cancel_at_period_end:
        return subscribe(company, plan, interval, user, request)
    if plan.pk == company.plan_id and interval == sub.interval:
        if sub.pending_plan_id:
            sub.pending_plan, sub.pending_interval = None, ""
            sub.save(update_fields=["pending_plan", "pending_interval", "updated_at"])
            _schedule_gateway_price(company, plan, interval)
            return {"scheduled": None}
        raise ValidationError("You are already on this plan.")
    plan_quote(company, plan, interval)  # must be priced
    diff = proration(company, plan, interval) if setting("billing.proration") else 0
    if diff > 0:
        q = quote(company, diff, plan)
        return _order(
            company,
            user,
            q["total"],
            "upgrade",
            {"plan": plan.key, "interval": interval, "quote": q},
            f"Upgrade to {plan.name} (rest of this period)",
        )
    sub.pending_plan, sub.pending_interval = plan, interval
    sub.save(update_fields=["pending_plan", "pending_interval", "updated_at"])
    _schedule_gateway_price(company, plan, interval)
    when = timezone.localtime(sub.current_period_end).strftime("%d %b %Y")
    record(request, "billing.plan_scheduled", "plan", plan.id, company=company, changes={"interval": interval})
    _email(company, "billing/plan_changed", {"summary": f"Your plan changes to {plan.name} ({interval}) on {when}"})
    return {"scheduled": when}


def cancel(company, user, reason="", request=None):
    """Stops renewal; the plan works until the end of the paid period (SUB-03)."""
    sub = subscription(company)
    if sub.status != S.ACTIVE or not sub.current_period_end:
        raise ValidationError("There is no running subscription to cancel.")
    if sub.cancel_at_period_end:
        raise ValidationError("The subscription is already set to end.")
    p = razorpay.provider()
    if sub.gateway_subscription_id and p:
        try:
            razorpay.cancel_subscription(p, sub.gateway_subscription_id, at_cycle_end=True)
        except ProviderError as exc:
            raise ValidationError(f"Could not cancel at the payment provider: {exc}") from None
    sub.cancel_at_period_end, sub.cancel_reason, sub.cancelled_at = True, reason[:300], timezone.now()
    sub.pending_plan, sub.pending_interval = None, ""
    sub.save()
    when = timezone.localtime(sub.current_period_end).strftime("%d %b %Y")
    record(request, "billing.cancel", "company", company.id, company=company, changes={"reason": reason})
    _email(company, "billing/plan_changed", {"summary": f"Your subscription ends on {when} and will not renew"})
    return when


def resume(company, user, request=None):
    """Undo a cancellation before the period ends: a new auto-renewal starting when the paid period ends."""
    sub = subscription(company)
    if not sub.cancel_at_period_end or sub.status != S.ACTIVE:
        raise ValidationError("Nothing to resume.")
    if sub.gateway == S.RAZORPAY and sub.gateway_subscription_id:
        out = subscribe(company, company.plan, sub.interval, user, request, start_at=sub.current_period_end)
        return out
    sub.cancel_at_period_end, sub.cancel_reason, sub.cancelled_at = False, "", None
    sub.save()
    return {"resumed": True}


# ------------------------------------------------------------------ invoices paid outside the gateway (SUB-04)
def mark_paid(inv, reference, user=None, method="manual", payment=None, request=None):
    if inv.status == Invoice.PAID:
        return inv
    if inv.status == Invoice.VOID:
        raise ValidationError("A cancelled invoice cannot be paid.")
    company = inv.company
    now = timezone.now()
    payment = payment or Payment(company=company, amount_paise=inv.total_paise, purpose="invoice", gateway=method)
    payment.status, payment.invoice, payment.method = Payment.CAPTURED, inv, method
    payment.gateway_payment_id = payment.gateway_payment_id or reference[:60]
    payment.recorded_by = user if user and user.is_authenticated else None
    payment.save()
    inv.status, inv.paid_at, inv.payment_ref = Invoice.PAID, now, reference[:120]
    inv.save(update_fields=["status", "paid_at", "payment_ref", "updated_at"])
    sub = subscription(company)
    if inv.period_end:
        sub.status, sub.current_period_start, sub.current_period_end = S.ACTIVE, inv.period_start, inv.period_end
        sub.interval = inv.interval or sub.interval
        if inv.plan_id:
            company.plan_id = inv.plan_id
            if sub.pending_plan_id == inv.plan_id:
                sub.pending_plan, sub.pending_interval = None, ""
    if sub.status == S.PAST_DUE and not Invoice.objects.filter(company=company, status=Invoice.DUE).exists():
        sub.status = S.ACTIVE
    sub.failed_payments, sub.grace_until, sub.last_payment_at = 0, None, now
    sub.save()
    if company.status == Company.TRIAL and inv.period_end:
        company.status, company.trial_ends_at = Company.ACTIVE, None
    company.billing_hold = None
    company.save(update_fields=["plan", "status", "trial_ends_at", "billing_hold", "updated_at"])
    record(request, "billing.invoice_paid", "invoice", inv.id, company=company, user=user, changes={"ref": reference})
    _invoice_mail(company, inv, inv.lines[0]["description"] if inv.lines else inv.number)
    return inv


def pay_invoice(company, inv, user):
    """Pay a due invoice online (one-time Razorpay order)."""
    if inv.status != Invoice.DUE:
        raise ValidationError("This invoice is not due.")
    return _order(company, user, inv.total_paise, "invoice", {"invoice": str(inv.pk)}, f"Invoice {inv.number}")


def void_invoice(inv, reason, user=None, request=None):
    if inv.status != Invoice.DUE:
        raise ValidationError("Only a due invoice can be cancelled.")
    inv.status, inv.notes = Invoice.VOID, f"{inv.notes}\nCancelled: {reason}".strip()
    inv.save(update_fields=["status", "notes", "updated_at"])
    record(
        request, "billing.invoice_void", "invoice", inv.id, company=inv.company, user=user, changes={"reason": reason}
    )


def manual_invoice(
    company, description, amount_taxable, user=None, request=None, plan=None, interval="", period=None, notify=True
):
    """Super Admin bills a company directly (enterprise / custom work)."""
    if amount_taxable <= 0:
        raise ValidationError("Enter an amount above zero.")
    inv = issue_invoice(
        company,
        description,
        amount_taxable,
        kind="subscription" if period else "manual",
        plan=plan,
        interval=interval,
        period=period or (None, None),
    )
    record(request, "billing.invoice_issue", "invoice", inv.id, company=company, user=user)
    if notify:
        _invoice_mail(company, inv, description)
    return inv


# ------------------------------------------------------------------ credits (USE-04) and enterprise terms (SUB-04)
def adjust_credits(company, credits, reason, user=None, request=None):
    from .usage import month_start

    if not credits or not reason.strip():
        raise ValidationError("Enter the credits (+ or −) and a reason.")
    row = CreditAdjustment.objects.create(
        company=company,
        credits=credits,
        reason=reason.strip()[:300],
        month=month_start(company).date(),
        created_by=user,
    )
    record(request, "billing.credits", "company", company.id, company=company, changes={"credits": credits})
    return row


def save_terms(company, data, user=None, request=None):
    """Super Admin: billing method, custom price, company limits and feature overrides."""
    from .models import ENTITLEMENTS, FEATURES, PlanEntitlement

    sub = subscription(company)
    gateway = data.get("gateway", sub.gateway)
    if gateway not in (S.RAZORPAY, S.MANUAL):
        raise ValidationError("Unknown billing method.")
    sub.gateway = gateway
    raw = str(data.get("custom_price", "")).strip()
    try:
        sub.custom_price_paise = round(Decimal(raw) * 100) if raw else None
    except ArithmeticError:
        raise ValidationError("Custom price: enter an amount in rupees.") from None
    if sub.custom_price_paise is not None and sub.custom_price_paise < 0:
        raise ValidationError("Custom price cannot be negative.")
    limits_out = {}
    for key, label in ENTITLEMENTS:
        mode = data.get(f"limit_{key}_mode", "plan")
        if mode == "plan":
            continue
        value = str(data.get(f"limit_{key}", "")).strip()
        try:
            limit = int(value) if value else None
            overage = round(Decimal(str(data.get(f"overage_{key}") or 0)) * 100) or None
        except (ValueError, ArithmeticError):
            raise ValidationError(f"{label}: enter whole numbers.") from None
        if limit is not None and limit < 0:
            raise ValidationError(f"{label}: cannot be negative.")
        enforcement = data.get(f"enforcement_{key}", PlanEntitlement.HARD)
        if enforcement not in (PlanEntitlement.HARD, PlanEntitlement.SOFT):
            enforcement = PlanEntitlement.HARD
        limits_out[key] = {"limit": limit, "enforcement": enforcement, "overage": overage}
    sub.custom_limits = limits_out
    flags = {}
    for key, _label in FEATURES:
        v = data.get(f"feature_{key}", "plan")
        if v in ("on", "off"):
            flags[key] = v == "on"
    sub.feature_overrides = flags
    sub.save()
    record(
        request,
        "billing.terms",
        "company",
        company.id,
        company=company,
        user=user,
        changes={"gateway": gateway, "custom_price": sub.custom_price_paise, "limits": limits_out, "features": flags},
    )
    return sub


# ------------------------------------------------------------------ Razorpay webhooks (SEC-13)
def _sub_by_gateway(gateway_id):
    with platform_context():
        return Subscription.all_companies.select_related("company").filter(gateway_subscription_id=gateway_id).first()


def _payment_failed(company, sub, amount, reason):
    now = timezone.now()
    sub.status = S.PAST_DUE
    sub.failed_payments += 1
    sub.grace_until = sub.grace_until or now + timedelta(days=setting("billing.grace_days"))
    sub.save()
    Payment.objects.create(company=company, amount_paise=amount or 0, status=Payment.FAILED, error=reason[:300])
    _email(
        company,
        "billing/payment_failed",
        {
            "plan_name": company.plan.name if company.plan_id else "",
            "amount": fmt(amount),
            "reason": reason,
            "grace_until": timezone.localtime(sub.grace_until).strftime("%d %b %Y"),
        },
    )
    _alert(company, "Payment failed", f"Pay by {timezone.localtime(sub.grace_until):%d %b} to keep the AI working.")


def webhook(body, signature):
    """Razorpay events → subscription state. Returns a short result for the log."""
    p = razorpay.provider()
    if not p:
        raise ProviderError("Payments are not set up.")
    razorpay.verify_webhook(p, body, signature)
    event = json.loads(body)
    kind, payload = event.get("event", ""), event.get("payload", {})
    rsub = (payload.get("subscription") or {}).get("entity") or {}
    pay = (payload.get("payment") or {}).get("entity") or {}
    order = (payload.get("order") or {}).get("entity") or {}
    if kind.startswith("subscription."):
        sub = _sub_by_gateway(rsub.get("id", ""))
        if not sub:  # first charge before the checkout handler: find the started payment
            with platform_context():
                started = Payment.all_companies.filter(gateway_order_id=rsub.get("id", "")).first()
            if not started:
                return "unknown subscription"
            company = started.company
        else:
            company = sub.company
        with company_context(company.id):
            sub = subscription(company)
            return _subscription_event(company, sub, kind, rsub, pay)
    if kind in ("order.paid", "payment.failed"):
        oid = order.get("id") or pay.get("order_id") or ""
        with platform_context():
            payment = Payment.all_companies.select_related("company").filter(gateway_order_id=oid).first()
        if not payment or payment.status == Payment.CAPTURED:
            return "ignored"
        with company_context(payment.company_id):
            if kind == "payment.failed":
                payment.status, payment.error = Payment.FAILED, str(pay.get("error_description", ""))[:300]
                payment.save(update_fields=["status", "error", "updated_at"])
                return "payment failed"
            _apply(payment.company, payment, pay.get("id", ""), method=pay.get("method", ""))
            return "order paid"
    return "ignored"


def _ts(value):
    from datetime import datetime

    return datetime.fromtimestamp(int(value), tz=UTC) if value else None


def _subscription_event(company, sub, kind, rsub, pay):
    if kind == "subscription.charged":
        notes = rsub.get("notes") or {}
        renewal = sub.gateway_subscription_id == rsub.get("id") and sub.current_period_end
        if renewal:  # the next period: a scheduled change applies now, else the plan the company is on
            plan = sub.pending_plan or company.plan
            interval = sub.pending_interval or sub.interval
        else:
            plan = Plan.objects.filter(key=notes.get("plan", "")).first() or company.plan
            interval = notes.get("interval") or sub.interval
        payment = Payment.objects.filter(
            company=company, gateway_order_id=rsub.get("id", ""), status=Payment.CREATED
        ).first() or Payment(company=company, amount_paise=int(pay.get("amount") or 0), purpose="subscription")
        payment.amount_paise = int(pay.get("amount") or payment.amount_paise)
        payment.data = {**(payment.data or {}), "plan": plan.key, "interval": interval}
        _paid(
            company,
            payment,
            pay.get("id", ""),
            plan,
            interval,
            start=_ts(rsub.get("current_start")),
            end=_ts(rsub.get("current_end")),
            gateway_sub=rsub.get("id", ""),
            method=pay.get("method", ""),
        )
        return "charged"
    if kind in ("subscription.pending", "subscription.halted"):
        _payment_failed(company, sub, int(pay.get("amount") or 0), str(pay.get("error_description") or "declined"))
        return "past due"
    if kind in ("subscription.cancelled", "subscription.completed"):
        if sub.gateway_subscription_id == rsub.get("id") and sub.status != S.CANCELLED:
            end = sub.current_period_end
            if not end or end <= timezone.now():
                sub.status = S.CANCELLED
                sub.save(update_fields=["status", "updated_at"])
                hold(company, "The subscription has ended.")
            else:
                sub.cancel_at_period_end = True
                sub.save(update_fields=["cancel_at_period_end", "updated_at"])
        return "cancelled"
    if kind == "subscription.authenticated" and sub.gateway_subscription_id != rsub.get("id"):
        # a new mandate (resumed after a cancellation, or the first checkout): renewals continue on it
        if sub.cancel_at_period_end and sub.status == S.ACTIVE:
            sub.gateway_subscription_id, sub.cancel_at_period_end, sub.cancel_reason = rsub.get("id", ""), False, ""
            sub.cancelled_at = None
            sub.save()
        return "authenticated"
    return "ignored"


# ------------------------------------------------------------------ daily run (cron: run_billing)
def run(now=None):
    """Trial reminders and ends, overdue → hold after the grace days, cancelled periods ending, manual renewals."""
    now = now or timezone.now()
    done = 0
    with platform_context():
        companies = list(Company.objects.filter(status__in=(Company.TRIAL, Company.ACTIVE), deleted_at__isnull=True))
    for company in companies:
        with company_context(company.id):
            try:
                done += _run_one(company, now)
            except Exception:  # noqa: BLE001 — one company must not stop the run
                logger.exception("billing run failed for %s", company.pk)
    return done


def _run_one(company, now):
    sub = subscription(company)
    changed = 0
    if company.status == Company.TRIAL and company.trial_ends_at and sub.status in (S.TRIALING, S.PENDING):
        days = setting("billing.trial_reminder_days")
        if days and not sub.reminded_at and company.trial_ends_at - timedelta(days=days) <= now < company.trial_ends_at:
            end = timezone.localtime(company.trial_ends_at)
            _email(company, "billing/trial_ending", {"trial_end": f"{end:%d %b %Y}"})
            sub.reminded_at = now
            sub.save(update_fields=["reminded_at", "updated_at"])
            changed += 1
        if now >= company.trial_ends_at and not company.billing_hold:
            sub.status = S.PENDING
            sub.save(update_fields=["status", "updated_at"])
            hold(company, "The free trial has ended. Choose a plan to continue.")
            changed += 1
    if sub.status == S.ACTIVE and sub.cancel_at_period_end and sub.current_period_end and sub.current_period_end <= now:
        sub.status = S.CANCELLED
        sub.save(update_fields=["status", "updated_at"])
        hold(company, "The subscription has ended.")
        changed += 1
    if sub.manual and sub.status in (S.ACTIVE, S.PAST_DUE) and sub.current_period_end and sub.current_period_end <= now:
        changed += _manual_renewal(company, sub, now)
    if sub.status == S.ACTIVE and not sub.manual and sub.gateway_subscription_id and sub.current_period_end:
        if sub.current_period_end + timedelta(days=2) <= now:  # no renewal webhook arrived
            _payment_failed(company, sub, 0, "the renewal payment did not arrive")
            changed += 1
    if sub.status == S.PAST_DUE and sub.grace_until and sub.grace_until <= now and not company.billing_hold:
        hold(company, "The subscription payment is overdue.")
        changed += 1
    return changed


def _manual_renewal(company, sub, now):
    """Billed by invoice: the next period's invoice at the period end; unpaid after its due date → overdue."""
    start = sub.current_period_end
    inv = Invoice.objects.filter(company=company, period_start=start).exclude(status=Invoice.VOID).first()
    if not inv:
        plan = sub.pending_plan or company.plan
        interval = sub.pending_interval or sub.interval
        amount = price(company, plan, interval) if plan else None
        if not amount:
            return 0
        end = add_period(start, interval)
        manual_invoice(
            company,
            period_text(plan, interval, start, end),
            taxable(amount, plan),
            plan=plan,
            interval=interval,
            period=(start, end),
        )
        return 1
    if inv.status == Invoice.DUE and inv.due_at and inv.due_at <= now and sub.status != S.PAST_DUE:
        sub.status = S.PAST_DUE
        sub.grace_until = inv.due_at + timedelta(days=setting("billing.grace_days"))
        sub.save(update_fields=["status", "grace_until", "updated_at"])
        _alert(company, f"Invoice {inv.number} is overdue", f"Pay {fmt(inv.total_paise)} in Billing.")
        return 1
    return 0
