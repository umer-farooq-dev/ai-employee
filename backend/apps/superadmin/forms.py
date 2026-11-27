from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.billing.models import ENTITLEMENTS, FEATURES, Plan
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


def _rupees(minor, code=""):
    """Minor units → a form value in the currency (default: the base currency)."""
    from apps.billing import currency

    return None if minor is None else currency.to_major(minor, code or currency.base())


def _minor(value, code=""):
    from apps.billing import currency

    return None if value is None else currency.to_minor(value, code or currency.base())


PREVIEW_CURRENCIES = ("USD", "EUR", "GBP", "AED", "SAR", "PKR", "CAD", "AUD")
EXTRA_PRICE_ROWS = 3


class PlanForm(BootstrapMixin, forms.ModelForm):
    price_monthly = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=3,
        label="Monthly price",
        help_text="Empty = custom / on request",
    )
    price_yearly = forms.DecimalField(required=False, min_value=0, decimal_places=3, label="Yearly price")
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
        labels = {"gst_rate": "GST rate (%)", "is_public": "Public", "is_custom": "Enterprise / custom plan"}
        help_texts = {"is_custom": 'Shown as "Custom" pricing; each company\'s terms are set on its Billing page'}

    def __init__(self, *args, **kwargs):
        from apps.billing import currency

        super().__init__(*args, **kwargs)
        plan = self.instance
        base = currency.base()
        self.fields["price_monthly"].label = f"Monthly price ({base})"
        self.fields["price_yearly"].label = f"Yearly price ({base})"
        self.fields["price_monthly"].help_text = (
            "Empty = custom / on request. Other currencies: their own price below, else converted at today's rate."
        )
        self._price_rows(plan, base)
        if not plan._state.adding:
            self.fields["key"].disabled = True
            self.initial["price_monthly"] = _rupees(plan.price_monthly_paise)
            self.initial["price_yearly"] = _rupees(plan.price_yearly_paise)
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
                label=f"Overage price ({base})",
                initial=_rupees(ent.overage_price_paise) if ent else None,
            )
            self.fields[f"enforce__{key}"] = forms.ChoiceField(
                required=False,
                choices=[("hard", "Stop"), ("soft", "Overage")],
                label="When reached",
                initial=ent.enforcement if ent else "hard",
            )
        for key, label in FEATURES:  # SA-20: missing on the plan = on
            self.fields[f"feature__{key}"] = forms.BooleanField(
                required=False, label=label, initial=(plan.flags or {}).get(key, True)
            )
        for name, field in self.fields.items():
            if name.startswith(("limit__", "overage__")):
                field.widget.attrs["class"] = "form-control form-control-sm"
            if name.startswith("enforce__"):
                field.widget.attrs["class"] = "form-select form-select-sm"
            if name.startswith("feature__"):
                field.widget.attrs["class"] = "form-check-input"

    def _price_rows(self, plan, base):
        from apps.billing import currency

        codes = sorted(c for c in currency.offered() if c != base)
        choices = [("", "— currency —"), *((c, f"{c} — {currency.name(c)}") for c in codes)]
        rows = list(plan.prices.all()) if not plan._state.adding else []
        self.price_count = len(rows) + EXTRA_PRICE_ROWS
        for i in range(self.price_count):
            row = rows[i] if i < len(rows) else None
            code = row.currency if row else ""
            self.fields[f"cp{i}_currency"] = forms.ChoiceField(
                required=False, choices=choices, initial=code, label="Currency"
            )
            self.fields[f"cp{i}_monthly"] = forms.DecimalField(
                required=False, min_value=0, label="Monthly", initial=_rupees(row.monthly_paise, code) if row else None
            )
            self.fields[f"cp{i}_yearly"] = forms.DecimalField(
                required=False, min_value=0, label="Yearly", initial=_rupees(row.yearly_paise, code) if row else None
            )

    def price_rows(self):
        return [
            (self[f"cp{i}_currency"], self[f"cp{i}_monthly"], self[f"cp{i}_yearly"]) for i in range(self.price_count)
        ]

    def auto_prices(self):
        """What visitors pay in a few currencies without their own price (today's rate, rounded)."""
        from apps.billing import currency

        plan = self.instance
        if plan._state.adding or plan.price_monthly_paise is None:
            return []
        rows, own = currency.offered(), {p.currency for p in plan.prices.all()}
        out = []
        for code in PREVIEW_CURRENCIES:
            amount = currency.convert(plan.price_monthly_paise, code, rows)
            if code != currency.base() and code not in own and amount is not None:
                out.append(currency.fmt(amount, code, decimals=False))
        return out

    def clean(self):
        data = super().clean()
        seen = set()
        for i in range(self.price_count):
            code = data.get(f"cp{i}_currency")
            if code and code in seen:
                self.add_error(f"cp{i}_currency", f"{code} is listed twice.")
            seen.add(code)
        return data

    def entitlement_rows(self):
        return [
            (label, self[f"limit__{key}"], self[f"enforce__{key}"], self[f"overage__{key}"])
            for key, label in ENTITLEMENTS
        ]

    def feature_fields(self):
        return [self[f"feature__{key}"] for key, _ in FEATURES]

    def plan_fields(self):
        return [f for f in self if not f.name.startswith(("limit__", "overage__", "enforce__", "feature__", "cp"))]

    def save(self, commit=True):
        from apps.billing.models import PlanEntitlement, PlanPrice

        plan = super().save(commit=False)
        d = self.cleaned_data
        plan.price_monthly_paise = _minor(d["price_monthly"])
        plan.price_yearly_paise = _minor(d["price_yearly"])
        plan.features = [line.strip() for line in d["features_text"].splitlines() if line.strip()]
        plan.flags = {key: bool(d[f"feature__{key}"]) for key, _ in FEATURES}
        plan.save()
        for key, _ in ENTITLEMENTS:
            overage = d[f"overage__{key}"]
            PlanEntitlement.objects.update_or_create(
                plan=plan,
                key=key,
                defaults={
                    "limit_value": d[f"limit__{key}"],
                    "enforcement": d[f"enforce__{key}"] or PlanEntitlement.HARD,
                    "overage_price_paise": _minor(overage),
                },
            )
        keep = {}
        for i in range(self.price_count):
            code, monthly, yearly = d[f"cp{i}_currency"], d[f"cp{i}_monthly"], d[f"cp{i}_yearly"]
            if code and (monthly is not None or yearly is not None):
                keep[code] = {"monthly_paise": _minor(monthly, code), "yearly_paise": _minor(yearly, code)}
        plan.prices.exclude(currency__in=keep).delete()
        for code, values in keep.items():
            PlanPrice.objects.update_or_create(plan=plan, currency=code, defaults=values)
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
