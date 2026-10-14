"""Company registration (AUTH-01). allauth adds email + password; this form adds the business details.

The same form serves the website page and the headless API (/api/v1/auth/app/v1/auth/signup) for the app.
"""

from django import forms
from django.core.exceptions import ValidationError

from apps.core.india import STATE_CHOICES, normalise_phone, validate_gstin
from apps.industries.models import Industry
from apps.platform_config import services as config

from .models import phone_validator


class CompanySignupForm(forms.Form):
    business_name = forms.CharField(max_length=200, label="Business name")
    full_name = forms.CharField(max_length=150, label="Your full name")
    phone = forms.CharField(max_length=20, label="Mobile number", help_text="+91 is added if you leave it out")
    industry = forms.ModelChoiceField(
        queryset=Industry.objects.none(), to_field_name="key", empty_label="Select your industry"
    )
    city = forms.CharField(max_length=100)
    state = forms.ChoiceField(choices=[("", "Select state")] + STATE_CHOICES)
    business_size = forms.ChoiceField(required=False, label="Business size (employees)")
    website = forms.URLField(required=False)
    gstin = forms.CharField(max_length=15, required=False, label="GSTIN", validators=[validate_gstin])
    accept_terms = forms.BooleanField(label="I accept the Terms of Service and Privacy Policy")
    plan = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["industry"].queryset = Industry.objects.filter(is_active=True)
        sizes = config.get("registration.business_sizes")
        self.fields["business_size"].choices = [("", "Select")] + [(s, s) for s in sizes]

    def clean_phone(self):
        phone = normalise_phone(self.cleaned_data["phone"])
        try:
            phone_validator(phone)
        except ValidationError:
            raise ValidationError("Enter a valid mobile number, e.g. 98765 43210.") from None
        return phone

    def signup(self, request, user):
        from apps.tenancy.services import register_company

        user.full_name = self.cleaned_data["full_name"]
        user.phone = self.cleaned_data["phone"]
        user.save(update_fields=["full_name", "phone"])
        register_company(user, self.cleaned_data, request=request)
