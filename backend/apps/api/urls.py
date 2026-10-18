"""/api/v1/ (signed-in users and staff) and /public/v1/ (website, widget, future app). API-04: stable v1 paths."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from . import views_agents as agentapi
from . import views_ai as aiapi
from . import views_calendar as calapi
from . import views_catalog as catapi
from . import views_company as company
from . import views_crm as crmapi
from . import views_knowledge as kbapi
from . import views_templates as tpl
from . import views_voice as voiceapi

admin = DefaultRouter(trailing_slash=True)
admin.register("companies", views.CompanyViewSet, basename="admin-companies")
admin.register("users", views.UserViewSet, basename="admin-users")
admin.register("roles", views.RoleViewSet, basename="admin-roles")
admin.register("plans", views.PlanViewSet, basename="admin-plans")
admin.register("industries", views.IndustryViewSet, basename="admin-industries")
admin.register("enquiries", views.EnquiryViewSet, basename="admin-enquiries")
admin.register("templates", tpl.TemplateVersionViewSet, basename="admin-templates")
admin.register("template-fields", tpl.TemplateFieldViewSet, basename="admin-template-fields")
admin.register("template-catalog-types", tpl.TemplateCatalogTypeViewSet, basename="admin-template-catalog-types")
admin.register("template-appointment-types", tpl.TemplateAppointmentTypeViewSet, basename="admin-template-appt-types")
admin.register("template-statuses", tpl.TemplateStatusViewSet, basename="admin-template-statuses")
admin.register("template-scoring-rules", tpl.TemplateScoringViewSet, basename="admin-template-scoring")
admin.register("lead-statuses", tpl.DefaultStatusViewSet, basename="admin-lead-statuses")
admin.register("lead-sources", tpl.LeadSourceViewSet, basename="admin-lead-sources")
admin.register("holidays", tpl.HolidayViewSet, basename="admin-holidays")
admin.register("employee-roles", tpl.EmployeeRoleViewSet, basename="admin-employee-roles")
admin.register("ai-providers", aiapi.ProviderViewSet, basename="admin-ai-providers")
admin.register("languages", aiapi.LanguageViewSet, basename="admin-languages")
admin.register("voices", aiapi.VoiceViewSet, basename="admin-voices")
admin.register("phone-numbers", voiceapi.AdminPhoneNumberViewSet, basename="admin-phone-numbers")
admin.register("tools", agentapi.ToolViewSet, basename="admin-tools")
admin.register("ai-employees", agentapi.AdminEmployeeViewSet, basename="admin-ai-employees")
admin.register("cms/pages", views.PageViewSet, basename="admin-cms-pages")
admin.register("cms/sections", views.SectionViewSet, basename="admin-cms-sections")
admin.register("email-templates", views.EmailTemplateViewSet, basename="admin-email-templates")
admin.register("logs/audit", views.AuditLogViewSet, basename="admin-audit-logs")
admin.register("logs/api", views.ApiLogViewSet, basename="admin-api-logs")
admin.register("logs/errors", views.ErrorLogViewSet, basename="admin-error-logs")

team = DefaultRouter(trailing_slash=True)
team.register("members", company.TeamMemberViewSet, basename="team-members")
team.register("invitations", company.InvitationViewSet, basename="team-invitations")

crm_router = DefaultRouter(trailing_slash=True)
crm_router.register("leads", crmapi.LeadViewSet, basename="crm-leads")
crm_router.register("tasks", crmapi.TaskViewSet, basename="crm-tasks")
crm_router.register("fields", crmapi.CompanyFieldViewSet, basename="crm-fields")
crm_router.register("scoring-rules", crmapi.CompanyScoringRuleViewSet, basename="crm-scoring-rules")
crm_router.register("assignment-rules", crmapi.AssignmentRuleViewSet, basename="crm-assignment-rules")

catalog_router = DefaultRouter(trailing_slash=True)
catalog_router.register("items", catapi.CatalogItemViewSet, basename="catalog-items")
catalog_router.register("collections", catapi.CollectionViewSet, basename="catalog-collections")

calendar_router = DefaultRouter(trailing_slash=True)
calendar_router.register("resources", calapi.ResourceViewSet, basename="calendar-resources")
calendar_router.register("appointments", calapi.AppointmentViewSet, basename="calendar-appointments")

agents_router = DefaultRouter(trailing_slash=True)
agents_router.register("ai-employees", agentapi.AIEmployeeViewSet, basename="ai-employees")
agents_router.register("conversations", agentapi.ConversationViewSet, basename="conversations")
agents_router.register("phone-numbers", voiceapi.PhoneNumberViewSet, basename="phone-numbers")
agents_router.register("calls", voiceapi.CallViewSet, basename="calls")

kb_router = DefaultRouter(trailing_slash=True)
kb_router.register("sources", kbapi.SourceViewSet, basename="kb-sources")
kb_router.register("faqs", kbapi.FAQViewSet, basename="kb-faqs")
kb_router.register("unanswered", kbapi.UnansweredViewSet, basename="kb-unanswered")

public = DefaultRouter(trailing_slash=True)
public.register("industries", company.PublicIndustryViewSet, basename="public-industries")

api_v1 = [
    path("me/", views.MeView.as_view(), name="me"),
    path("me/phone-otp/", company.PhoneOTPView.as_view(), name="me-phone-otp"),
    path("company/", company.OwnCompanyView.as_view(), name="own-company"),
    path("company/hours/", company.CompanyHoursView.as_view(), name="company-hours"),
    path("company/onboarding/", company.OnboardingView.as_view(), name="company-onboarding"),
    path("company/template/", tpl.CompanyTemplateView.as_view(), name="company-template"),
    path("company/team/transfer-ownership/", company.TransferOwnershipView.as_view(), name="team-transfer"),
    path("company/team/", include(team.urls)),
    path("crm/config/", crmapi.CrmConfigView.as_view(), name="crm-config"),
    path("crm/imports/", crmapi.LeadImportView.as_view(), name="crm-import"),
    path("crm/imports/<uuid:pk>/", crmapi.LeadImportView.as_view(), name="crm-import-run"),
    path("crm/", include(crm_router.urls)),
    path("catalog/types/", catapi.CatalogTypesView.as_view(), name="catalog-types"),
    path("catalog/imports/", catapi.CatalogImportView.as_view(), name="catalog-import"),
    path("catalog/imports/<uuid:pk>/", catapi.CatalogImportView.as_view(), name="catalog-import-run"),
    path("catalog/", include(catalog_router.urls)),
    path("calendar/config/", calapi.CalendarConfigView.as_view(), name="calendar-config"),
    path("calendar/", include(calendar_router.urls)),
    path("kb/test-query/", kbapi.TestQueryView.as_view(), name="kb-test-query"),
    path("kb/", include(kb_router.urls)),
    path("calling-policy/", voiceapi.CallingPolicyView.as_view(), name="calling-policy"),
    path("", include(agents_router.urls)),
    path("admin/conversations/<uuid:pk>/", agentapi.AdminConversationView.as_view(), name="admin-conversation"),
    path(
        "admin/companies/<uuid:pk>/ai-employee/",
        agentapi.AdminCompanyEmployeeView.as_view(),
        name="admin-company-employee",
    ),
    path("admin/settings/<str:screen>/", views.SettingsView.as_view(), name="admin-settings"),
    path("admin/ai-routes/", aiapi.RoutesView.as_view(), name="admin-ai-routes"),
    path("admin/ai-routes/<slug:task>/", aiapi.RoutesView.as_view(), name="admin-ai-route"),
    path("admin/uploads/", views.UploadView.as_view(), name="admin-uploads"),
    path("admin/sessions/", views.SessionsView.as_view(), name="admin-sessions"),
    path("admin/", include(admin.urls)),
]

public_v1 = [
    path("branding/", views.PublicBrandingView.as_view(), name="public-branding"),
    path("cms/<slug:key>/", views.PublicPageView.as_view(), name="public-cms-page"),
    path("plans/", views.PublicPlansView.as_view(), name="public-plans"),
    path("enquiries/", company.PublicEnquiryView.as_view(), name="public-enquiries"),
    path("registration-options/", company.RegistrationOptionsView.as_view(), name="public-registration-options"),
    path("invitations/<str:token>/", company.InvitationPublicView.as_view(), name="public-invitation"),
    path("", include(public.urls)),
]
