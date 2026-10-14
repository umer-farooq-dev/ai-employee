from django.urls import path

from . import company_views, views

app_name = "panel"

urlpatterns = [
    path("dashboard/", views.after_login, name="home"),
    path("profile/", views.profile, name="profile"),
    path("support/stop/", views.stop_impersonation, name="stop_impersonation"),
    path("invite/<str:token>/", company_views.accept_invitation, name="accept_invitation"),
    # Company panel (/app/)
    path("app/", company_views.dashboard, name="company_home"),
    path("app/pending/", company_views.pending, name="pending"),
    path("app/settings/", company_views.company_settings, name="company_settings"),
    path("app/team/", company_views.team_page, name="team"),
    path("app/soon/<slug:key>/", company_views.coming_soon, name="coming_soon"),
]
