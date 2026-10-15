from django.urls import path

from . import company_views, crm_views, views

app_name = "panel"

urlpatterns = [
    path("dashboard/", views.after_login, name="home"),
    path("profile/", views.profile, name="profile"),
    path("support/stop/", views.stop_impersonation, name="stop_impersonation"),
    path("invite/<str:token>/", company_views.accept_invitation, name="accept_invitation"),
    # Company panel (/app/)
    path("app/", company_views.dashboard, name="company_home"),
    path("app/pending/", company_views.pending, name="pending"),
    path("app/template-update/", company_views.accept_template_update, name="accept_template_update"),
    path("app/settings/", company_views.company_settings, name="company_settings"),
    path("app/team/", company_views.team_page, name="team"),
    path("app/soon/<slug:key>/", company_views.coming_soon, name="coming_soon"),
    # CRM (Phase 3)
    path("app/leads/", crm_views.lead_list, name="lead_list"),
    path("app/leads/board/", crm_views.lead_board, name="lead_board"),
    path("app/leads/new/", crm_views.lead_form, name="lead_create"),
    path("app/leads/export/", crm_views.lead_export, name="lead_export"),
    path("app/leads/import/", crm_views.lead_import, name="lead_import"),
    path("app/leads/import/<uuid:pk>/", crm_views.lead_import, name="lead_import_map"),
    path("app/leads/duplicates/", crm_views.duplicates, name="lead_duplicates"),
    path("app/leads/<uuid:pk>/", crm_views.lead_detail, name="lead_detail"),
    path("app/leads/<uuid:pk>/edit/", crm_views.lead_form, name="lead_edit"),
    path("app/leads/<uuid:pk>/status/", crm_views.lead_status, name="lead_status"),
    path("app/tasks/", crm_views.tasks, name="tasks"),
    path("app/search/", crm_views.search, name="search"),
    path("app/settings/crm/", crm_views.crm_settings, name="crm_settings"),
    path("app/settings/crm/fields/new/", crm_views.company_field, name="crm_field_create"),
    path("app/settings/crm/fields/<uuid:pk>/", crm_views.company_field, name="crm_field_edit"),
    path("app/settings/crm/scoring/new/", crm_views.company_scoring_rule, name="crm_scoring_rule_create"),
    path("app/settings/crm/scoring/<uuid:pk>/", crm_views.company_scoring_rule, name="crm_scoring_rule_edit"),
    path("app/settings/crm/assignment/new/", crm_views.assignment_rule, name="crm_assignment_create"),
    path("app/settings/crm/assignment/<uuid:pk>/", crm_views.assignment_rule, name="crm_assignment_edit"),
]
