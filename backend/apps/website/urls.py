from django.urls import path
from django.views.generic import TemplateView

app_name = "website"

# Phase 0: static HR layout (index5). Phase 2 renders every section from the Super Admin CMS.
urlpatterns = [
    path("", TemplateView.as_view(template_name="website/pages/index5.html"), name="home"),
]
