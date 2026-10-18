from django.urls import path

from . import ai_views, calendar_views, calls_views, catalog_views, company_views, crm_views, knowledge_views, views

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
    # Calendar (Phase 3)
    path("app/calendar/", calendar_views.index, name="calendar"),
    path("app/calendar/events/", calendar_views.events, name="calendar_events"),
    path("app/calendar/book/", calendar_views.book, name="calendar_book"),
    path("app/calendar/appointments/<uuid:pk>/", calendar_views.appointment, name="appointment"),
    path("app/calendar/resources/", calendar_views.resources, name="calendar_resources"),
    path("app/calendar/resources/new/", calendar_views.resource_form, name="calendar_resource_create"),
    path("app/calendar/resources/<uuid:pk>/", calendar_views.resource_form, name="calendar_resource_edit"),
    # Catalogue (Phase 3)
    path("app/catalogue/", catalog_views.home, name="catalog_home"),
    path("app/catalogue/<slug:type_key>/", catalog_views.item_list, name="catalog_list"),
    path("app/catalogue/<slug:type_key>/new/", catalog_views.item_form, name="catalog_create"),
    path("app/catalogue/<slug:type_key>/import/", catalog_views.item_import, name="catalog_import"),
    path("app/catalogue/<slug:type_key>/import/<uuid:pk>/", catalog_views.item_import, name="catalog_import_step"),
    path("app/catalogue/<slug:type_key>/collections/", catalog_views.collections, name="catalog_collections"),
    path("app/catalogue/<slug:type_key>/matching/", catalog_views.matching, name="catalog_matching"),
    path(
        "app/catalogue/<slug:type_key>/collections/new/",
        catalog_views.collection_form,
        name="catalog_collection_create",
    ),
    path(
        "app/catalogue/<slug:type_key>/collections/<uuid:pk>/",
        catalog_views.collection_form,
        name="catalog_collection_edit",
    ),
    path("app/catalogue/<slug:type_key>/<uuid:pk>/", catalog_views.item_form, name="catalog_edit"),
    # AI Employees, knowledge, conversations (Phase 4)
    path("app/ai-employees/", ai_views.employee_list, name="ai_list"),
    path("app/ai-employees/new/", ai_views.employee_new, name="ai_new"),
    path("app/ai-employees/<uuid:pk>/", ai_views.employee_detail, name="ai_detail"),
    path("app/ai-employees/<uuid:pk>/setup/<slug:step>/", ai_views.employee_step, name="ai_step"),
    path("app/conversations/", ai_views.conversation_list, name="conversations"),
    path("app/conversations/<uuid:pk>/", ai_views.conversation_detail, name="conversation"),
    path("app/knowledge/", knowledge_views.index, name="kb"),
    path("app/knowledge/new/", knowledge_views.source_new, name="kb_new"),
    path("app/knowledge/test/", knowledge_views.test, name="kb_test"),
    path("app/knowledge/unanswered/", knowledge_views.unanswered, name="kb_unanswered"),
    path("app/knowledge/<uuid:pk>/", knowledge_views.source_detail, name="kb_source"),
    # Calls (Phase 5)
    path("app/calls/", calls_views.call_list, name="calls"),
    path("app/calls/<uuid:pk>/", calls_views.call_detail, name="call_detail"),
    path("app/leads/<uuid:lead_pk>/call/", calls_views.call_now, name="call_now"),
    path("app/settings/calling/", calls_views.calling_settings, name="calling_settings"),
    path("app/search/", crm_views.search, name="search"),
    path("app/settings/crm/", crm_views.crm_settings, name="crm_settings"),
    path("app/settings/crm/fields/new/", crm_views.company_field, name="crm_field_create"),
    path("app/settings/crm/fields/<uuid:pk>/", crm_views.company_field, name="crm_field_edit"),
    path("app/settings/crm/scoring/new/", crm_views.company_scoring_rule, name="crm_scoring_rule_create"),
    path("app/settings/crm/scoring/<uuid:pk>/", crm_views.company_scoring_rule, name="crm_scoring_rule_edit"),
    path("app/settings/crm/assignment/new/", crm_views.assignment_rule, name="crm_assignment_create"),
    path("app/settings/crm/assignment/<uuid:pk>/", crm_views.assignment_rule, name="crm_assignment_edit"),
]
