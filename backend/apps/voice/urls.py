from django.urls import path

from . import views

app_name = "voice"
urlpatterns = [
    path("webhooks/telephony/<slug:provider_key>/<str:token>/answer/", views.answer, name="answer"),
    path("webhooks/telephony/<slug:provider_key>/<str:token>/status/", views.status, name="status"),
]
