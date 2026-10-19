from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.audit.services import record
from apps.superadmin.forms import BootstrapMixin
from apps.tenancy import services as tenancy


@login_required
def after_login(request):
    """Single post-login landing: platform staff go to Super Admin, everyone else to the company panel.

    Staff who signed in on the website host are signed out there and sent to the admin host, so the website and
    company panel never carry a staff session (see AdminHostMiddleware)."""
    admin_host = settings.ADMIN_HOST
    if request.user.is_staff and admin_host and request.get_host() != admin_host:
        logout(request)
        return redirect(f"{request.scheme}://{admin_host}{reverse('account_login')}?next=/superadmin/")
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
        if "phone" in self.changed_data:
            user.phone_verified_at = None  # a new number must be verified again (AUTH-02)
        user.notification_prefs = {
            **user.notification_prefs,
            "email_security_alerts": self.cleaned_data["email_security_alerts"],
        }
        user.save()
        return user


@login_required
def profile(request):
    """AUTH-08: own profile; password, email, 2FA and sessions use the secure allauth flows linked from here.
    Company people also choose their alert channels and push devices here (CP-03, MOB-03)."""
    from apps.notifications import alerts, push
    from apps.providers.adapters import ProviderError

    company = getattr(request, "company", None)
    op = request.POST.get("op") if request.method == "POST" else None
    if op and company:
        if op == "alerts":
            alerts.save_prefs(
                request.user,
                {k: [c for c in alerts.OPTIONAL if request.POST.get(f"{k}__{c}") == "on"] for k in alerts.KINDS},
            )
            record(request, "profile.alerts", "user", request.user.id)
            messages.success(request, "Alert settings saved.")
        elif op == "remove_device":
            push.unregister(request.user, device_id=request.POST.get("device"))
            messages.success(request, "Device removed: it no longer receives push alerts.")
        elif op == "test_push":
            try:
                n = push.send(
                    request.user,
                    {"title": "Test alert", "body": "Push alerts work on this device.", "url": "/app/", "kind": "test"},
                )
                messages.success(request, f"Test alert sent to {n} device(s).")
            except ProviderError as exc:
                messages.error(request, f"No push alert sent: {exc}")
        return redirect(reverse("panel:profile") + "#alerts")
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        record(request, "profile.update", "user", request.user.id)
        messages.success(request, "Profile saved.")
        return redirect("panel:profile")
    layout = "panel/admin/layout.html" if request.user.is_staff else "panel/company/layout.html"
    context = {"form": form, "layout": layout}
    if company and not request.user.is_staff:
        context.update(
            alert_channels=[(c, label) for c, label in alerts.CHANNELS if c in alerts.OPTIONAL],
            alert_rows=[
                (kind, label, [(c, prefs[kind][c]) for c in alerts.OPTIONAL])
                for prefs in [alerts.prefs(request.user)]
                for kind, label in alerts.KINDS.items()
            ],
            devices=request.user.devices.all(),
            push_key=push.public_key(),
        )
    return render(request, "panel/profile.html", context)


@require_POST
def stop_impersonation(request):
    staff = tenancy.stop_impersonation(request)
    if staff:
        messages.success(request, "Support login ended.")
        return redirect("superadmin:dashboard")
    return redirect("panel:home")
