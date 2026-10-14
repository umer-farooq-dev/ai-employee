from django.contrib.auth.decorators import login_required
from django.urls import path
from django.views.generic import TemplateView

app_name = "panel"

# Phase 0: Rizz layout shell. Phase 1 splits this into Super Admin and company panel views.
urlpatterns = [
    path("", login_required(TemplateView.as_view(template_name="panel/pages/pages-starter.html")), name="home"),
]
