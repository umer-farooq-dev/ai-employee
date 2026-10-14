from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    path("files/<str:token>/", views.private_file, name="private_file"),
]
