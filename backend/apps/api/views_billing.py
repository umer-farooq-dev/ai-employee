"""REST API for the company's subscription and billing (USE-02 … USE-04, SUB-03 … SUB-06): /api/v1/billing/…

billing/                    GET {subscription, plan, usage: [...], meters, features, credits}       (billing.view)
billing/plans/              GET plans the company can choose, with prices and GST quotes            (billing.view)
billing/checkout/           POST {plan, interval} | {what: "resume"} | {what: "invoice", invoice}   (billing.manage)
                            → Razorpay checkout options, or {"scheduled": date} for a change at renewal
billing/confirm/            POST the checkout handler's razorpay_* fields                           (billing.manage)
billing/cancel/             POST {reason}                                                           (billing.manage)
billing/details/            GET / PATCH {legal_name, gstin, address, city, state (GST code)}        (billing.manage)
billing/invoices/           GET · billing/invoices/<id>/pdf/ GET (PDF)                              (billing.view)
billing/payments/           GET                                                                     (billing.view)
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing import access, gst, usage
from apps.billing import services as billing
from apps.billing.models import FEATURES, Invoice, Payment, Plan

from .base import TenantContextMixin, perm


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


class _Billing(TenantContextMixin, APIView):
    manage = False

    def get_permissions(self):
        write = self.manage or self.request.method not in permissions.SAFE_METHODS
        return [permissions.IsAuthenticated(), perm("billing.manage" if write else "billing.view")()]


def _sub(sub):
    return {
        "status": sub.status,
        "interval": sub.interval,
        "current_period_start": sub.current_period_start,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "pending_plan": sub.pending_plan.key if sub.pending_plan_id else None,
        "pending_interval": sub.pending_interval,
        "grace_until": sub.grace_until,
        "billing": "invoice" if sub.manual else "automatic",
        "last_payment_at": sub.last_payment_at,
    }


class SummaryView(_Billing):
    @extend_schema(responses=dict)
    def get(self, request):
        company = request.company
        sub = billing.subscription(company)
        return Response(
            {
                "subscription": _sub(sub),
                "plan": {"key": company.plan.key, "name": company.plan.name} if company.plan_id else None,
                "price_paise": billing.price(company, company.plan, sub.interval) if company.plan_id else None,
                "trial_ends_at": company.trial_ends_at,
                "on_hold": bool(company.billing_hold),
                "usage": usage.overview(company),
                "meters": [{"label": k, "value": v} for k, v in usage.meters(company)],
                "features": {k: access.enabled(company, k) for k, _ in FEATURES},
                "credits_left": access.credits_left(company),
            }
        )


class PlansView(_Billing):
    @extend_schema(responses=dict)
    def get(self, request):
        company = request.company
        out = []
        for plan in billing.purchasable(company):
            prices = {}
            for interval in ("monthly", "yearly"):
                amount = billing.price(company, plan, interval)
                if amount is not None:
                    prices[interval] = {"price_paise": amount, **billing.plan_quote(company, plan, interval)}
            out.append(
                {
                    "id": str(plan.pk),
                    "key": plan.key,
                    "name": plan.name,
                    "description": plan.description,
                    "features": plan.features,
                    "current": plan.pk == company.plan_id,
                    "prices": prices,
                    "limits": {e.key: e.limit_value for e in plan.entitlements.all()},
                }
            )
        return Response(out)


class CheckoutView(_Billing):
    manage = True

    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        company, data = request.company, request.data
        if data.get("what") == "invoice":
            inv = Invoice.objects.filter(company=company, pk=data.get("invoice")).first()
            if not inv:
                raise ValidationError({"invoice": "Unknown invoice."})
            return Response(_errors(billing.pay_invoice, company, inv, request.user))
        if data.get("what") == "resume":
            return Response(_errors(billing.resume, company, request.user, request._request))
        ref = str(data.get("plan", ""))
        plan = Plan.objects.filter(key=ref).first()
        if not plan:
            try:
                plan = Plan.objects.filter(pk=uuid.UUID(ref)).first()
            except ValueError:
                plan = None
        if not plan:
            raise ValidationError({"plan": "Unknown plan."})
        out = _errors(
            billing.change_plan, company, plan, data.get("interval", "monthly"), request.user, request._request
        )
        return Response(out)


class ConfirmView(_Billing):
    manage = True

    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        inv = _errors(billing.confirm, request.company, request.data, request.user, request._request)
        return Response({"ok": True, "invoice": inv.number if inv else None})


class CancelView(_Billing):
    manage = True

    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        when = _errors(
            billing.cancel, request.company, request.user, str(request.data.get("reason", "")), request._request
        )
        return Response({"ends_on": when})


class DetailsView(_Billing):
    @extend_schema(responses=dict)
    def get(self, request):
        c = request.company
        return Response(
            {
                "legal_name": c.legal_name,
                "gstin": c.gstin,
                "address": c.address,
                "city": c.city,
                "state": gst.state_code(c.gstin, c.state),
                "states": dict(gst.STATES),
            }
        )

    @extend_schema(request=dict, responses=dict)
    def patch(self, request):
        from apps.panel.billing_views import _details

        current = self.get(request).data
        _errors(_details, request.company, {**current, **request.data}, request._request)
        request.company.refresh_from_db()
        return self.get(request)


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            "kind",
            "status",
            "issued_at",
            "due_at",
            "paid_at",
            "period_start",
            "period_end",
            "place_of_supply",
            "intra_state",
            "lines",
            "subtotal_paise",
            "gst_rate",
            "cgst_paise",
            "sgst_paise",
            "igst_paise",
            "total_paise",
            "payment_ref",
        ]
        read_only_fields = fields


class InvoiceViewSet(TenantContextMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = InvoiceSerializer

    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("billing.view")()]

    def get_queryset(self):
        return Invoice.objects.filter(company=self.request.company).exclude(status=Invoice.VOID)

    @extend_schema(responses=bytes)
    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        inv = self.get_object()
        response = HttpResponse(billing.invoice_pdf(inv), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{inv.number.replace("/", "-")}.pdf"'
        return response


class PaymentSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.number", default="", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "amount_paise",
            "status",
            "purpose",
            "method",
            "error",
            "invoice",
            "invoice_number",
            "created_at",
        ]
        read_only_fields = fields


class PaymentViewSet(TenantContextMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = PaymentSerializer

    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("billing.view")()]

    def get_queryset(self):
        return Payment.objects.filter(company=self.request.company).exclude(status=Payment.CREATED)
