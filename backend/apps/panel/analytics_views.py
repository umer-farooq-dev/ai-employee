"""Company panel: dashboard figures and the analytics page (DASH-01 … DASH-05, EMP-13). Logic: apps.analytics."""

from django.core.exceptions import ValidationError
from django.shortcuts import render

from apps.agents.models import AIEmployee
from apps.analytics import services as analytics
from apps.platform_config.services import get as setting

from .company_views import _errors, company_perm


def filters(request):
    """(period, employee, choices) from ?range=&from=&to=&employee= — a bad custom range falls back to the default."""
    company = request.company
    try:
        p = analytics.period(company, request.GET.get("range", ""), request.GET.get("from"), request.GET.get("to"))
    except ValidationError as exc:
        _errors(request, exc)
        p = analytics.period(company)
    staff = list(AIEmployee.objects.filter(company=company).exclude(status=AIEmployee.ARCHIVED).order_by("name"))
    employee = next((e for e in staff if str(e.pk) == request.GET.get("employee")), None)
    return (
        p,
        employee,
        {
            "period": p,
            "employee": employee,
            "staff": staff,
            "ranges": analytics.RANGES,
            "series_names": dict(analytics.SERIES),
            "refresh_seconds": setting("analytics.refresh_seconds"),
        },
    )


@company_perm("analytics.view")
def analytics_page(request):
    p, employee, ctx = filters(request)
    data = analytics.report(request.company, p, employee, parts=("kpis", "employees", "campaigns"))
    if employee:
        data["employees"] = [row for row in data["employees"] if row["id"] == str(employee.pk)]
    return render(request, "panel/company/analytics.html", {**ctx, "data": data, "funnel": analytics.FUNNEL})
