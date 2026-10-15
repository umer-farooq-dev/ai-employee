"""Super Admin forms: industry templates (SA-05), CRM configuration (SA-07), roles (ROLE-01), holidays (CAL-09)."""

import json

from django import forms
from django.core.exceptions import ValidationError

from apps.billing.models import Plan
from apps.industries.editor import EVENTS
from apps.industries.models import (
    AppointmentType,
    CatalogType,
    FieldDefinition,
    Holiday,
    Industry,
    LeadSource,
    LeadStatus,
    ScoringRule,
)
from apps.roles_tools.models import CHANNELS, EmployeeRole

from .forms import BootstrapMixin


def _json_field(label, help_text=""):
    return forms.CharField(label=label, required=False, help_text=help_text, widget=forms.Textarea(attrs={"rows": 3}))


def _parse_json(value, label):
    if not (value or "").strip():
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise ValidationError(f"{label}: enter valid JSON.") from None


class FieldDefinitionForm(BootstrapMixin, forms.ModelForm):
    """CRM-04 / CAT-01 field. Options one per line; validation as min / max / max length."""

    options_text = forms.CharField(
        label="Options",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Select fields: one option per line",
    )
    min_value = forms.FloatField(label="Minimum", required=False)
    max_value = forms.FloatField(label="Maximum", required=False)
    max_length = forms.IntegerField(label="Maximum length", required=False, min_value=1)

    class Meta:
        model = FieldDefinition
        fields = [
            "entity",
            "key",
            "label",
            "type",
            "required",
            "ai_extractable",
            "extraction_hint",
            "filterable",
            "show_in_list",
            "help_text",
            "sort_order",
            "is_active",
        ]

    def __init__(self, *args, entities=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entity"] = forms.ChoiceField(choices=entities, label="Belongs to")
        self.fields["entity"].widget.attrs["class"] = "form-select"
        self.fields["options_text"].initial = "\n".join(
            o if isinstance(o, str) else o.get("label", "") for o in self.instance.options or []
        )
        v = self.instance.validation or {}
        self.fields["min_value"].initial, self.fields["max_value"].initial = v.get("min"), v.get("max")
        self.fields["max_length"].initial = v.get("max_length")

    def clean(self):
        data = super().clean()
        options = [o.strip() for o in (data.get("options_text") or "").splitlines() if o.strip()]
        if data.get("type") in ("single_select", "multi_select") and not options:
            self.add_error("options_text", "Select fields need at least one option.")
        self.instance.options = options
        self.instance.validation = {
            k: v
            for k, v in (
                ("min", data.get("min_value")),
                ("max", data.get("max_value")),
                ("max_length", data.get("max_length")),
            )
            if v is not None
        }
        return data


class CatalogTypeForm(BootstrapMixin, forms.ModelForm):
    title_field = forms.CharField(required=False, help_text="Field key used as the item title, e.g. project_name")
    price_field = forms.CharField(required=False, help_text="Currency field key used as the item price")
    match_rules_json = _json_field("Matching rules (JSON)", "Used by AI matching in Phase 4")

    class Meta:
        model = CatalogType
        fields = ["key", "name", "item_label", "sort_order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        d = self.instance.display or {}
        self.fields["title_field"].initial, self.fields["price_field"].initial = d.get("title_field"), d.get(
            "price_field"
        )
        self.fields["match_rules_json"].initial = json.dumps(self.instance.match_rules or {}, indent=1)

    def clean(self):
        data = super().clean()
        self.instance.display = {"title_field": data.get("title_field", ""), "price_field": data.get("price_field", "")}
        try:
            self.instance.match_rules = _parse_json(data.get("match_rules_json"), "Matching rules")
        except ValidationError as exc:
            self.add_error("match_rules_json", exc)
        return data


class AppointmentTypeForm(BootstrapMixin, forms.ModelForm):
    reminders = forms.CharField(required=False, help_text="Minutes before, comma separated, e.g. 1440, 120")

    class Meta:
        model = AppointmentType
        fields = ["key", "name", "duration_min", "buffer_min", "location_mode", "sort_order", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reminders"].initial = ", ".join(str(m) for m in self.instance.reminder_offsets or [])

    def clean_reminders(self):
        try:
            values = [int(x) for x in (self.cleaned_data["reminders"] or "").replace(" ", "").split(",") if x]
        except ValueError:
            raise ValidationError("Use whole minutes, e.g. 1440, 120.") from None
        self.instance.reminder_offsets = sorted(set(values), reverse=True)
        return values


class LeadStatusForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = LeadStatus
        fields = ["key", "label", "color", "category", "sort_order"]
        widgets = {"color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color"})}


class ScoringRuleForm(BootstrapMixin, forms.ModelForm):
    """SCORE-02 rule builder: a field condition, an event, or a status."""

    OPS = [
        ("present", "has a value"),
        ("eq", "equals"),
        ("neq", "does not equal"),
        ("gt", "greater than"),
        ("gte", "at least"),
        ("lt", "less than"),
        ("lte", "at most"),
        ("contains", "contains"),
    ]
    kind = forms.ChoiceField(choices=[("field", "Field"), ("event", "Event"), ("status", "Status")], label="When")
    field = forms.CharField(required=False, help_text="CRM field key, e.g. budget")
    op = forms.ChoiceField(choices=OPS, required=False, label="Condition")
    value = forms.CharField(required=False)
    event = forms.ChoiceField(choices=[("", "—")] + EVENTS, required=False)
    status = forms.CharField(required=False, help_text="Status key, e.g. not_interested")

    class Meta:
        model = ScoringRule
        fields = ["key", "name", "points", "force_label", "priority", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        c = self.instance.condition or {}
        kind = "event" if "event" in c else "status" if "status" in c else "field"
        for name, value in (
            ("kind", kind),
            ("field", c.get("field")),
            ("op", c.get("op")),
            ("value", c.get("value")),
            ("event", c.get("event")),
            ("status", c.get("status")),
        ):
            self.fields[name].initial = value
        for name in ("kind", "op", "event"):
            self.fields[name].widget.attrs["class"] = "form-select"

    def clean(self):
        data = super().clean()
        kind = data.get("kind")
        if kind == "event":
            if not data.get("event"):
                self.add_error("event", "Choose an event.")
            self.instance.condition = {"event": data.get("event")}
        elif kind == "status":
            if not data.get("status"):
                self.add_error("status", "Enter a status key.")
            self.instance.condition = {"status": data.get("status")}
        else:
            if not data.get("field"):
                self.add_error("field", "Enter a field key.")
            self.instance.condition = {
                "field": data.get("field"),
                "op": data.get("op") or "present",
                **({"value": data["value"]} if data.get("value") else {}),
            }
        return data


class IndustryCloneForm(BootstrapMixin, forms.Form):
    name = forms.CharField(max_length=100)
    key = forms.SlugField(max_length=50, help_text="Website URL: /industries/<key>/")

    def clean_key(self):
        if Industry.objects.filter(key=self.cleaned_data["key"]).exists():
            raise ValidationError("This key is taken.")
        return self.cleaned_data["key"]


class LeadSourceForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = LeadSource
        fields = ["key", "label", "is_active", "sort_order"]


class HolidayForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["date", "name", "region"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class EmployeeRoleForm(BootstrapMixin, forms.ModelForm):
    """ROLE-01."""

    allowed_channels = forms.MultipleChoiceField(choices=CHANNELS, widget=forms.CheckboxSelectMultiple, required=False)
    tools_text = forms.CharField(
        required=False, label="Allowed tools", help_text="Tool keys, comma separated (Phase 4)"
    )
    plan_keys = forms.MultipleChoiceField(
        required=False, widget=forms.CheckboxSelectMultiple, help_text="None ticked = available on every plan"
    )
    default_rules_json = _json_field("Default rules (JSON)")

    class Meta:
        model = EmployeeRole
        fields = ["key", "name", "description", "icon", "instructions", "industries", "is_active", "sort_order"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "instructions": forms.Textarea(attrs={"rows": 4}),
            "industries": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan_keys"].choices = [(p.key, p.name) for p in Plan.objects.all()]
        self.fields["allowed_channels"].initial = self.instance.allowed_channels
        self.fields["plan_keys"].initial = self.instance.plan_keys
        self.fields["tools_text"].initial = ", ".join(self.instance.allowed_tools or [])
        self.fields["default_rules_json"].initial = json.dumps(self.instance.default_rules or {}, indent=1)

    def clean(self):
        data = super().clean()
        self.instance.allowed_channels = data.get("allowed_channels") or []
        self.instance.plan_keys = data.get("plan_keys") or []
        self.instance.allowed_tools = [t.strip() for t in (data.get("tools_text") or "").split(",") if t.strip()]
        try:
            self.instance.default_rules = _parse_json(data.get("default_rules_json"), "Default rules")
        except ValidationError as exc:
            self.add_error("default_rules_json", exc)
        return data
