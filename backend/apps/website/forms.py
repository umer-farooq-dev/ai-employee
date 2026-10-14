from django import forms

from apps.accounts.models import phone_validator
from apps.core.india import normalise_phone
from apps.industries.models import Industry

from .models import Enquiry


class EnquiryForm(forms.ModelForm):
    # Honeypot: real visitors never see or fill this field.
    company_website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1"}))

    class Meta:
        model = Enquiry
        fields = ["name", "business_name", "phone", "email", "industry", "message"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["industry"].queryset = Industry.objects.filter(is_active=True)
        self.fields["industry"].to_field_name = "key"
        self.fields["industry"].required = True
        self.fields["industry"].empty_label = "Industry*"

    def clean_phone(self):
        phone = normalise_phone(self.cleaned_data["phone"])
        try:
            phone_validator(phone)
        except forms.ValidationError:
            raise forms.ValidationError("Enter a valid mobile number, e.g. 98765 43210.") from None
        return phone

    @property
    def is_spam(self):
        return bool(self.cleaned_data.get("company_website"))
