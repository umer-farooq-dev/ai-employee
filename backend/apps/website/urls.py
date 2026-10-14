from django.urls import path
from django.views.generic import TemplateView

app_name = "website"

# Phase 0: eSoft HR layout (index5 sections in pages/home.html). Phase 2 renders every section from the Super Admin CMS.
urlpatterns = [
    path("", TemplateView.as_view(template_name="website/pages/home.html"), name="home"),
]
