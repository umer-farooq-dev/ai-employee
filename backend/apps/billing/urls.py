from django.urls import path

from . import views

app_name = "billing"
urlpatterns = [path("webhooks/razorpay/", views.razorpay_webhook, name="razorpay_webhook")]
