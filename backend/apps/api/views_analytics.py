"""REST API for the company dashboard and analytics (DASH-01 … DASH-05, EMP-13): /api/v1/analytics/

analytics/   GET ?range=today|7d|30d|custom&from=YYYY-MM-DD&to=YYYY-MM-DD&employee=<id>
                 &parts=kpis,series,employees,campaigns (default kpis,series)
             → {period, kpis, series: {labels, series: {leads, calls, …}}, employees: [...], campaigns: [...]}
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AIEmployee
from apps.analytics import services as analytics

from .base import TenantContextMixin, perm

PARTS = ("kpis", "series", "employees", "campaigns")


class AnalyticsView(TenantContextMixin, APIView):
    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("analytics.view")()]

    @extend_schema(
        parameters=[OpenApiParameter(n, str, required=False) for n in ("range", "from", "to", "employee", "parts")],
        responses=dict,
    )
    def get(self, request):
        q = request.query_params
        try:
            p = analytics.period(request.company, q.get("range", ""), q.get("from"), q.get("to"))
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from None
        employee = None
        if q.get("employee"):
            employee = AIEmployee.objects.filter(company=request.company, pk=q["employee"]).first()
            if not employee:
                raise ValidationError({"employee": "Unknown AI Employee."})
        parts = [x for x in q.get("parts", "kpis,series").split(",") if x in PARTS] or ["kpis"]
        return Response(analytics.report(request.company, p, employee, parts))
