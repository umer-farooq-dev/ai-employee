from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.audit.services import record
from apps.superadmin.forms import BootstrapMixin
from apps.tenancy import services as tenancy


@login_required
def after_login(request):
    """Single post-login landing: platform staff go to Super Admin, everyone else to the company panel."""
    return redirect("superadmin:dashboard" if request.user.is_staff else "panel:company_home")


class ProfileForm(BootstrapMixin, forms.ModelForm):
    email_security_alerts = forms.BooleanField(required=False, label="Email me security alerts")

    class Meta:
        from django.contrib.auth import get_user_model

        model = get_user_model()
        fields = ["full_name", "phone", "avatar", "timezone", "availability"]
        help_texts = {"timezone": "Empty = platform default, e.g. Asia/Kolkata"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email_security_alerts"].initial = self.instance.notification_prefs.get(
            "email_security_alerts", True
        )
        self.fields["email_security_alerts"].widget.attrs["class"] = "form-check-input"

    def clean_timezone(self):
        from zoneinfo import available_timezones

        value = self.cleaned_data["timezone"].strip()
        if value and value not in available_timezones():
            raise forms.ValidationError("Unknown timezone.")
        return value

    def save(self, commit=True):
        user = super().save(commit=False)
        user.notification_prefs = {
            **user.notification_prefs,
            "email_security_alerts": self.cleaned_data["email_security_alerts"],
        }
        user.save()
        return user


@login_required
def profile(request):
    """AUTH-08: own profile; password, email, 2FA and sessions use the secure allauth flows linked from here."""
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        record(request, "profile.update", "user", request.user.id)
        messages.success(request, "Profile saved.")
        return redirect("panel:profile")
    layout = "panel/admin/layout.html" if request.user.is_staff else "panel/company/layout.html"
    return render(request, "panel/profile.html", {"form": form, "layout": layout})


@require_POST
def stop_impersonation(request):
    staff = tenancy.stop_impersonation(request)
    if staff:
        messages.success(request, "Support login ended.")
        return redirect("superadmin:dashboard")
    return redirect("panel:home")
