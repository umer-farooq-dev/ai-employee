"""Company registration (AUTH-01). allauth adds email + password; this form adds the business details.

The same form serves the website page and the headless API (/api/v1/auth/app/v1/auth/signup) for the app.
"""

from django import forms
from django.core.exceptions import ValidationError

from apps.billing.currency import countries
from apps.core.india import STATES, normalise_phone, validate_gstin
from apps.industries.models import Industry
from apps.platform_config import services as config

from .models import phone_validator


class CompanySignupForm(forms.Form):
    business_name = forms.CharField(max_length=200, label="Business name")
    full_name = forms.CharField(max_length=150, label="Your full name")
    phone = forms.CharField(
        max_length=20,
        label="Mobile number",
        widget=forms.TextInput(attrs={"type": "tel", "data-phone": "", "autocomplete": "tel"}),
    )
    industry = forms.ModelChoiceField(
        queryset=Industry.objects.none(), to_field_name="key", empty_label="Select your industry"
    )
    country = forms.ChoiceField(choices=(), required=False, help_text="Empty = where the visitor is")
    city = forms.CharField(max_length=100)
    state = forms.CharField(
        max_length=100,
        required=False,
        label="State / region",
        widget=forms.TextInput(attrs={"list": "signup-states", "autocomplete": "address-level1"}),
    )
    business_size = forms.ChoiceField(required=False, label="Business size")
    website = forms.URLField(required=False)
    gstin = forms.CharField(max_length=15, required=False, label="GSTIN", validators=[validate_gstin])
    accept_terms = forms.BooleanField(label="I accept the Terms of Service and Privacy Policy")
    plan = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["industry"].queryset = Industry.objects.filter(is_active=True)
        self.fields["country"].choices = [("", "Select country"), *countries()]
        self.fields["country"].initial = _visitor_country()
        sizes = config.get("registration.business_sizes")
        self.fields["business_size"].choices = [("", "Select")] + [(s, s) for s in sizes]
        placeholders = {
            "business_name": "e.g. Sunrise Realty",
            "full_name": "Full name",
            "city": "City",
            "website": "https://",
            "gstin": "Optional",
        }
        for name, text in placeholders.items():
            self.fields[name].widget.attrs.setdefault("placeholder", text)

    @property
    def seller_country(self):
        return _seller_country()

    @property
    def states_json(self):
        import json

        return json.dumps(STATES)  # fixed reference names, no markup

    def clean(self):
        data = super().clean()
        data["country"] = data.get("country") or _visitor_country() or _seller_country()
        if data["country"] == _seller_country():
            if data.get("state") and data["state"] not in STATES:
                self.add_error("state", "Choose your state from the list.")
            elif not data.get("state"):
                self.add_error("state", "This field is required.")
        else:
            data["gstin"] = ""  # GST registration exists only in the seller's country
        return data

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


def _visitor_country():
    from apps.billing.region import visitor_country
    from apps.core.request import current_request

    request = current_request()
    return visitor_country(request) if request else ""


def _seller_country():
    from apps.billing.services import seller_country

    return seller_country()
