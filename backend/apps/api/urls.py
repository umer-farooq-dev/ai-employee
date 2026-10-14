"""/api/v1/ (signed-in users and staff) and /public/v1/ (website, widget, future app). API-04: stable v1 paths."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

admin = DefaultRouter(trailing_slash=True)
admin.register("companies", views.CompanyViewSet, basename="admin-companies")
admin.register("users", views.UserViewSet, basename="admin-users")
admin.register("roles", views.RoleViewSet, basename="admin-roles")
admin.register("plans", views.PlanViewSet, basename="admin-plans")
admin.register("cms/pages", views.PageViewSet, basename="admin-cms-pages")
admin.register("cms/sections", views.SectionViewSet, basename="admin-cms-sections")
admin.register("email-templates", views.EmailTemplateViewSet, basename="admin-email-templates")
admin.register("logs/audit", views.AuditLogViewSet, basename="admin-audit-logs")
admin.register("logs/api", views.ApiLogViewSet, basename="admin-api-logs")
admin.register("logs/errors", views.ErrorLogViewSet, basename="admin-error-logs")

api_v1 = [
    path("me/", views.MeView.as_view(), name="me"),
    path("company/", views.OwnCompanyView.as_view(), name="own-company"),
    path("admin/settings/<str:screen>/", views.SettingsView.as_view(), name="admin-settings"),
    path("admin/uploads/", views.UploadView.as_view(), name="admin-uploads"),
    path("admin/sessions/", views.SessionsView.as_view(), name="admin-sessions"),
    path("admin/", include(admin.urls)),
]

public_v1 = [
    path("branding/", views.PublicBrandingView.as_view(), name="public-branding"),
    path("cms/<slug:key>/", views.PublicPageView.as_view(), name="public-cms-page"),
    path("plans/", views.PublicPlansView.as_view(), name="public-plans"),
]
