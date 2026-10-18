from django.urls import path

from . import views

app_name = "voice"
HOOK = "webhooks/telephony/<slug:provider_key>/<str:token>"
urlpatterns = [
    path(f"{HOOK}/answer/", views.answer, name="answer"),
    path(f"{HOOK}/status/", views.status, name="status"),
    path(f"{HOOK}/transfer/", views.transfer, name="transfer"),
    path(f"{HOOK}/whisper/", views.whisper, name="whisper"),
    path(f"{HOOK}/transfer-result/", views.transfer_result, name="transfer_result"),
    path("calls/recording/<str:token>/", views.recording, name="recording"),
]
