from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect
from django.urls import path
from django.views.generic import TemplateView

app_name = "panel"

staff_required = user_passes_test(lambda u: u.is_active and u.is_staff)


@login_required
def after_login(request):
    """Single post-login landing: platform staff go to Super Admin, everyone else to the company panel."""
    return redirect("panel:admin_home" if request.user.is_staff else "panel:company_home")


# Phase 0 shells on the Rizz template. Phase 1 adds the Super Admin screens, Phase 2 the company panel.
admin_home = staff_required(TemplateView.as_view(template_name="panel/admin/dashboard.html"))
company_home = login_required(TemplateView.as_view(template_name="panel/company/dashboard.html"))

urlpatterns = [
    path("dashboard/", after_login, name="home"),
    path("superadmin/", admin_home, name="admin_home"),
    path("app/", company_home, name="company_home"),
]
