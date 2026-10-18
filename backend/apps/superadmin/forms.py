from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.billing.models import ENTITLEMENTS, Plan
from apps.core.uploads import save_public
from apps.industries.models import Industry
from apps.notifications.models import EmailTemplate
from apps.platform_config.registry import SETTINGS
from apps.providers import languages
from apps.rbac.catalog import PERMISSIONS
from apps.rbac.models import Role
from apps.tenancy.models import Company
from apps.website.models import Enquiry

User = get_user_model()


class BootstrapMixin:
    """Rizz / Bootstrap 5 classes on every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            # Django's "---------" blank option reads like a glitch; say what to do instead
            if getattr(field, "empty_label", None) == "---------":
                field.empty_label = "Choose…"
            elif isinstance(field, forms.ChoiceField) and not isinstance(field, forms.ModelChoiceField):
                field.choices = [
                    (v, "Choose…" if v == "" and label == "---------" else label) for v, label in field.choices
                ]
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class CompanyForm(BootstrapMixin, forms.ModelForm):
    owner_email = forms.EmailField(required=False, help_text="Optional: this user becomes the company Owner.")

    class Meta:
        model = Company
        fields = [
            "name",
            "legal_name",
            "industry",
            "business_size",
            "plan",
            "trial_ends_at",
            "email",
            "phone",
            "website",
            "gstin",
            "address",
            "city",
            "state",
            "timezone",
            "default_language",
            "require_2fa",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = Plan.objects.filter(status=Plan.ACTIVE)
        self.fields["trial_ends_at"].widget = forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"}
        )
        if not self.instance._state.adding:
            del self.fields["owner_email"]


class IndustryForm(BootstrapMixin, forms.ModelForm):
    """Super Admin → Industries. Icon and image can be uploaded or given as a URL."""

    icon_upload = forms.ImageField(required=False, label="Upload icon")
    image_upload = forms.ImageField(required=False, label="Upload page image")

    class Meta:
        model = Industry
        fields = [
            "name",
            "key",
            "short_description",
            "description",
            "icon",
            "image",
            "supported_languages",
            "is_active",
            "sort_order",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supported_languages"] = forms.MultipleChoiceField(
            choices=languages.choices, required=False, widget=forms.CheckboxSelectMultiple, label="Supported languages"
        )

    def clean(self):
        data = super().clean()
        for field in ("icon", "image"):
            upload = data.get(f"{field}_upload")
            if upload:
                try:
                    data[field] = save_public(upload, "industries")
                except ValidationError as exc:
                    self.add_error(f"{field}_upload", exc)
        return data


class EnquiryForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Enquiry
        fields = ["status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}


class MemberForm(BootstrapMixin, forms.Form):
    email = forms.EmailField()
    role = forms.ModelChoiceField(queryset=Role.objects.filter(scope="company"))


class UserForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["email", "full_name", "phone", "is_staff", "platform_role"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["platform_role"].queryset = Role.objects.filter(scope="platform")
        self.fields["platform_role"].required = False
        if not self.instance._state.adding:
            self.fields["email"].disabled = True

    def clean(self):
        data = super().clean()
        if data.get("is_staff") and not data.get("platform_role"):
            self.add_error("platform_role", "Staff users need a platform role.")
        return data


class RoleForm(BootstrapMixin, forms.ModelForm):
    permissions = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple, required=False)

    class Meta:
        model = Role
        fields = ["scope", "key", "name", "description", "permissions"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        scope = self.instance.scope or self.data.get("scope") or "platform"
        self.fields["permissions"].choices = [
            (k, f"{label} ({k})") for k, (sc, label) in PERMISSIONS.items() if sc == scope
        ]
        if not self.instance._state.adding:
            self.fields["scope"].disabled = True
            self.fields["key"].disabled = True


class PlanForm(BootstrapMixin, forms.ModelForm):
    price_monthly = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        label="Monthly price (₹)",
        help_text="Empty = custom / on request",
    )
    price_yearly = forms.DecimalField(required=False, min_value=0, decimal_places=2, label="Yearly price (₹)")
    features_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label="Features",
        help_text="One bullet point per line (pricing page)",
    )

    class Meta:
        model = Plan
        fields = [
            "key",
            "name",
            "description",
            "gst_rate",
            "trial_days",
            "is_public",
            "is_custom",
            "status",
            "sort_order",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        plan = self.instance
        if not plan._state.adding:
            self.fields["key"].disabled = True
            self.initial["price_monthly"] = None if plan.price_monthly_paise is None else plan.price_monthly_paise / 100
            self.initial["price_yearly"] = None if plan.price_yearly_paise is None else plan.price_yearly_paise / 100
            self.initial["features_text"] = "\n".join(plan.features)
        for key, label in ENTITLEMENTS:
            ent = plan.entitlements.filter(key=key).first() if not plan._state.adding else None
            self.fields[f"limit__{key}"] = forms.IntegerField(
                required=False, min_value=0, label=label, initial=ent.limit_value if ent else None
            )
            self.fields[f"overage__{key}"] = forms.DecimalField(
                required=False,
                min_value=0,
                decimal_places=2,
                label="Overage price (₹)",
                initial=(ent.overage_price_paise / 100 if ent and ent.overage_price_paise is not None else None),
            )
        for name, field in self.fields.items():
            if name.startswith(("limit__", "overage__")):
                field.widget.attrs["class"] = "form-control form-control-sm"

    def entitlement_rows(self):
        return [(label, self[f"limit__{key}"], self[f"overage__{key}"]) for key, label in ENTITLEMENTS]

    def save(self, commit=True):
        from apps.billing.models import PlanEntitlement

        plan = super().save(commit=False)
        d = self.cleaned_data
        plan.price_monthly_paise = None if d["price_monthly"] is None else int(d["price_monthly"] * 100)
        plan.price_yearly_paise = None if d["price_yearly"] is None else int(d["price_yearly"] * 100)
        plan.features = [line.strip() for line in d["features_text"].splitlines() if line.strip()]
        plan.save()
        for key, _ in ENTITLEMENTS:
            overage = d[f"overage__{key}"]
            PlanEntitlement.objects.update_or_create(
                plan=plan,
                key=key,
                defaults={
                    "limit_value": d[f"limit__{key}"],
                    "overage_price_paise": None if overage is None else int(overage * 100),
                },
            )
        return plan


class EmailTemplateForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = ["name", "subject", "body_html", "is_active"]
        widgets = {"body_html": forms.Textarea(attrs={"rows": 12})}


class ImpersonateForm(BootstrapMixin, forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.none(), label="Sign in as")
    reason = forms.CharField(max_length=255, help_text="Recorded in the audit log")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = User.objects.filter(memberships__company=company, is_staff=False)


# ------------------------------------------------------------------ settings screens built from the registry
def settings_form(group_keys, initial, data=None, files=None):
    """A form for the registry entries of the given groups; values are cleaned again by the settings service."""
    form = forms.Form(data=data, files=files)
    form.registry = []
    for s in SETTINGS:
        if s.group not in group_keys:
            continue
        value = initial.get(s.key)
        help_text = s.help
        if s.type == "boolean":
            field = forms.BooleanField(
                required=False, initial=value, widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
            )
        elif s.type == "number":
            field = forms.IntegerField(initial=value, min_value=s.min, max_value=s.max)
        elif s.type == "choice":
            field = forms.ChoiceField(
                choices=s.choices, initial=value, widget=forms.Select(attrs={"class": "form-select"})
            )
        elif s.type in ("textarea", "rich"):
            field = forms.CharField(required=False, initial=value, widget=forms.Textarea(attrs={"rows": 3}))
            if s.type == "rich":
                help_text = (help_text + " HTML allowed.").strip()
        elif s.type == "list":
            field = forms.CharField(
                required=False, initial="\n".join(value or []), widget=forms.Textarea(attrs={"rows": 3})
            )
            help_text = (help_text + " One per line.").strip()
        elif s.type == "links":
            field = forms.CharField(
                required=False,
                initial="\n".join(f"{i['platform']} | {i['url']}" for i in value or []),
                widget=forms.Textarea(attrs={"rows": 3}),
            )
            help_text = "One per line: Platform | https://link"
        elif s.type == "image":
            field = forms.FileField(required=False)
            help_text = "Upload to replace."
        elif s.type == "time":
            field = forms.CharField(initial=value, widget=forms.TimeInput(attrs={"type": "time"}))
        elif s.type == "translations":
            # one textarea per language: <key>__<lang>
            for i, (code, name) in enumerate(languages.choices()):
                sub = forms.CharField(
                    required=False,
                    initial=(value or {}).get(code, ""),
                    label=f"{s.label} — {name}",
                    help_text=help_text if i == 0 else "",
                    widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
                )
                form.fields[f"{s.key}__{code}"] = sub
            form.registry.append(s)
            continue
        elif s.type == "color":
            field = forms.CharField(
                required=False,
                initial=value,
                widget=forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"}),
            )
        else:
            field = forms.CharField(required=False, initial=value)
        field.label = s.label
        field.help_text = help_text
        field.widget.attrs.setdefault("class", "form-control")
        form.fields[s.key] = field
        form.registry.append(s)
    return form


def settings_values(form):
    """Turn a valid settings form into {key: value} for services.update(); uploads become public URLs."""
    values = {}
    for s in form.registry:
        value = form.cleaned_data.get(s.key)
        if s.type == "image":
            if value:
                values[s.key] = save_public(value, "branding")
            continue
        if s.type == "translations":
            values[s.key] = {code: form.cleaned_data.get(f"{s.key}__{code}", "") for code in languages.codes()}
            continue
        if s.type == "links":
            rows = []
            for line in (value or "").splitlines():
                platform, _, url = line.partition("|")
                rows.append({"platform": platform.strip(), "url": url.strip()})
            value = rows
        values[s.key] = value
    return values
