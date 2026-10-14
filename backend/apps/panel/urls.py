from django.contrib.auth.decorators import login_required
from django.urls import path
from django.views.generic import TemplateView

from . import views

app_name = "panel"

company_home = login_required(TemplateView.as_view(template_name="panel/company/dashboard.html"))

urlpatterns = [
    path("dashboard/", views.after_login, name="home"),
    path("app/", company_home, name="company_home"),
    path("profile/", views.profile, name="profile"),
    path("support/stop/", views.stop_impersonation, name="stop_impersonation"),
]
