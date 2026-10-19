from django.urls import path

from . import views

app_name = "whatsapp"
urlpatterns = [
    path("webhooks/whatsapp/<slug:provider_key>/", views.webhook, name="webhook"),
]
