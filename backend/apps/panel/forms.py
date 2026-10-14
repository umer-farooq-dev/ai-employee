from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.core.india import STATE_CHOICES, normalise_phone, validate_gstin
from apps.core.uploads import save_public
from apps.platform_config.registry import LANGUAGES, TIMEZONES
from apps.rbac.models import Role
from apps.superadmin.forms import BootstrapMixin
from apps.tenancy.models import Company, Membership
from apps.tenancy.team import company_roles


class CompanyProfileForm(BootstrapMixin, forms.ModelForm):
    """AUTH-09: company profile, edited by the company itself."""

    logo_upload = forms.ImageField(required=False, label="Logo")

    class Meta:
        model = Company
        fields = [
            "name",
            "legal_name",
            "email",
            "phone",
            "website",
            "gstin",
            "address",
            "city",
            "state",
            "timezone",
            "default_language",
        ]
        labels = {"name": "Display name", "gstin": "GSTIN (printed on invoices)"}
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["state"] = forms.ChoiceField(choices=[("", "Select state")] + STATE_CHOICES, required=False)
        self.fields["timezone"] = forms.ChoiceField(
            choices=[("", "Platform default")] + list(TIMEZONES), required=False
        )
        self.fields["default_language"] = forms.ChoiceField(
            choices=[("", "Platform default")] + list(LANGUAGES), required=False
        )
        for name in ("state", "timezone", "default_language"):
            self.fields[name].widget.attrs["class"] = "form-select"

    def clean_gstin(self):
        value = self.cleaned_data["gstin"].upper().strip()
        validate_gstin(value)
        return value

    def clean_phone(self):
        from apps.accounts.models import phone_validator

        value = self.cleaned_data["phone"]
        if value:
            value = normalise_phone(value)
            phone_validator(value)
        return value

    def clean(self):
        data = super().clean()
        upload = data.get("logo_upload")
        if upload:
            try:
                data["logo"] = save_public(upload, "company-logos")
            except ValidationError as exc:
                self.add_error("logo_upload", exc)
        return data


class InviteForm(BootstrapMixin, forms.Form):
    email = forms.EmailField()
    role = forms.ModelChoiceField(queryset=Role.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = company_roles()


class TransferOwnershipForm(BootstrapMixin, forms.Form):
    new_owner = forms.ModelChoiceField(queryset=Membership.all_companies.none(), label="New owner")
    my_new_role = forms.ModelChoiceField(queryset=Role.objects.none(), label="Your role afterwards")

    def __init__(self, *args, company=None, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_owner"].queryset = (
            Membership.objects.filter(company=company, status=Membership.ACTIVE)
            .exclude(user=current_user)
            .select_related("user")
        )
        self.fields["new_owner"].label_from_instance = lambda m: f"{m.user.full_name or m.user.email} ({m.user.email})"
        self.fields["my_new_role"].queryset = company_roles()


class AcceptInvitationForm(BootstrapMixin, forms.Form):
    full_name = forms.CharField(max_length=150, label="Your full name")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Password (again)")

    def clean(self):
        data = super().clean()
        if data.get("password1") and data.get("password1") != data.get("password2"):
            self.add_error("password2", "The passwords do not match.")
        elif data.get("password1"):
            try:
                validate_password(data["password1"])
            except ValidationError as exc:
                self.add_error("password1", exc)
        return data


class OTPForm(BootstrapMixin, forms.Form):
    code = forms.CharField(max_length=8, label="Verification code")
