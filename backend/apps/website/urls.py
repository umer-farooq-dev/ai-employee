from django.urls import path

from . import views

app_name = "website"

# Included last in config/urls.py: <slug> pages are a catch-all for the CMS pages.
urlpatterns = [
    path("", views.page, name="home"),
    path("robots.txt", views.robots, name="robots"),
    path("sitemap.xml", views.sitemap, name="sitemap"),
    path("enquiry/", views.enquiry, name="enquiry"),
    path("industries/<slug:key>/", views.industry, name="industry"),
    path("<slug:slug>/", views.page, name="page"),
]
