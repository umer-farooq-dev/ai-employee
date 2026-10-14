from django.urls import path

from . import views

app_name = "superadmin"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("companies/", views.company_list, name="company_list"),
    path("companies/new/", views.company_form, name="company_create"),
    path("companies/<uuid:pk>/", views.company_detail, name="company_detail"),
    path("companies/<uuid:pk>/edit/", views.company_form, name="company_edit"),
    path("companies/<uuid:pk>/members/", views.company_add_member, name="company_add_member"),
    path("companies/<uuid:pk>/status/", views.company_status, name="company_status"),
    path("companies/<uuid:pk>/export/", views.company_export, name="company_export"),
    path("companies/<uuid:pk>/delete/", views.company_delete, name="company_delete"),
    path("companies/<uuid:pk>/impersonate/", views.company_impersonate, name="company_impersonate"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_form, name="user_create"),
    path("users/<uuid:pk>/", views.user_detail, name="user_detail"),
    path("users/<uuid:pk>/edit/", views.user_form, name="user_edit"),
    path("users/<uuid:pk>/security/<slug:op>/", views.user_security, name="user_security"),
    path("roles/", views.role_list, name="role_list"),
    path("roles/new/", views.role_form, name="role_create"),
    path("roles/<uuid:pk>/", views.role_form, name="role_edit"),
    path("roles/<uuid:pk>/delete/", views.role_delete, name="role_delete"),
    path("plans/", views.plan_list, name="plan_list"),
    path("plans/new/", views.plan_form, name="plan_create"),
    path("plans/<uuid:pk>/", views.plan_form, name="plan_edit"),
    path("settings/general/", views.general_settings, name="general_settings"),
    path("settings/system/", views.system_settings, name="system_settings"),
    path("website/", views.cms_pages, name="cms_pages"),
    path("website/pages/<uuid:pk>/", views.cms_page, name="cms_page"),
    path("website/sections/<uuid:pk>/", views.cms_section, name="cms_section"),
    path("email-templates/", views.email_template_list, name="email_template_list"),
    path("email-templates/<uuid:pk>/", views.email_template_form, name="email_template_edit"),
    path("logs/", views.logs, name="logs"),
    path("logs/<slug:kind>/", views.logs, name="logs_kind"),
    path("security/sessions/", views.sessions, name="sessions"),
]
