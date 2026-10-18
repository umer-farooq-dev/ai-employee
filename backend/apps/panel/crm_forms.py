"""Company panel CRM forms. Choices (statuses, sources, team, fields) always come from the company's template / data."""

from django import forms

from apps.crm import services as crm
from apps.crm.models import AssignmentRule, Task
from apps.industries import fields as field_engine
from apps.industries import services as templates
from apps.industries.models import FieldDefinition, LeadSource
from apps.providers import languages
from apps.superadmin.forms import BootstrapMixin
from apps.superadmin.template_forms import FieldDefinitionForm, ScoringRuleForm


def _members(company):
    return [(str(u.pk), u.full_name or u.email) for u in crm.members(company)]


class LeadForm(BootstrapMixin, forms.Form):
    """CRM-01 common fields + the template's / company's custom fields (CRM-04)."""

    name = forms.CharField(max_length=150, required=False)
    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"type": "tel", "data-phone": "", "autocomplete": "off"}),
    )
    email = forms.EmailField(required=False)
    status = forms.ChoiceField()
    source = forms.ChoiceField(required=False)
    assigned_user = forms.ChoiceField(required=False, label="Assigned to")
    preferred_language = forms.ChoiceField(required=False, choices=lambda: [("", "—")] + languages.choices())
    tags = forms.CharField(required=False, help_text="Comma separated")
    follow_up_at = forms.DateTimeField(
        required=False, label="Follow-up", widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    next_action = forms.CharField(required=False, max_length=255)
    dnd = forms.BooleanField(required=False, label="Do not call (DND)")

    def __init__(self, *args, company=None, lead=None, can_assign=True, **kwargs):
        initial = kwargs.pop("initial", {}) or {}
        if lead:
            initial = {
                "name": lead.name,
                "phone": lead.phone,
                "email": lead.email,
                "status": lead.status.key,
                "source": lead.source.key if lead.source_id else "",
                "preferred_language": lead.preferred_language,
                "assigned_user": str(lead.assigned_user_id or ""),
                "tags": ", ".join(lead.tags),
                "follow_up_at": lead.follow_up_at,
                "next_action": lead.next_action,
                "dnd": lead.dnd,
                **initial,
            }
        super().__init__(*args, initial=initial, **kwargs)
        self.defs = templates.fields_for(company, "lead")
        self.fields["status"].choices = [(s.key, s.label) for s in templates.statuses(company)]
        self.fields["status"].initial = initial.get("status") or crm.default_status(company).key
        self.fields["source"].choices = [("", "—")] + [
            (s.key, s.label) for s in LeadSource.objects.filter(is_active=True)
        ]
        self.fields["assigned_user"].choices = [("", "Unassigned / by rules")] + _members(company)
        if not can_assign:
            self.fields["assigned_user"].disabled = True
        field_engine.add_form_fields(self, self.defs, lead.custom if lead else {})
        for name in self.fields:
            if name.startswith("f_"):
                w = self.fields[name].widget
                w.attrs.setdefault(
                    "class",
                    (
                        "form-select"
                        if isinstance(w, forms.Select)
                        else ("form-check-input" if isinstance(w, forms.CheckboxInput) else "form-control")
                    ),
                )

    def lead_data(self):
        d = self.cleaned_data
        data = {
            k: d.get(k)
            for k in (
                "name",
                "phone",
                "email",
                "status",
                "source",
                "preferred_language",
                "tags",
                "follow_up_at",
                "next_action",
                "dnd",
            )
        }
        if not self.fields["assigned_user"].disabled:
            data["assigned_user"] = d.get("assigned_user") or None
        data["custom"] = field_engine.read_form_values(self, self.defs)
        return data


class TaskForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "type", "due_at", "assigned_user", "notes"]
        widgets = {
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_user"] = forms.ChoiceField(
            choices=[("", "Me")] + _members(company), required=False, label="Assign to"
        )
        self.fields["assigned_user"].widget.attrs["class"] = "form-select"


class FollowUpForm(BootstrapMixin, forms.Form):
    when = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}), label="Follow up on")
    next_action = forms.CharField(required=False, max_length=255)


class AssignmentRuleForm(BootstrapMixin, forms.ModelForm):
    """CRM-15: optional condition on a lead field + one person or round robin."""

    field = forms.ChoiceField(required=False, label="When lead field")
    op = forms.ChoiceField(
        choices=[("", "always"), ("eq", "equals"), ("contains", "contains"), ("present", "has a value")],
        required=False,
        label="Condition",
    )
    value = forms.CharField(required=False)
    targets = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple, label="Assign to")

    class Meta:
        model = AssignmentRule
        fields = ["name", "strategy", "priority", "is_active"]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["field"].choices = [("", "—"), ("source", "Source")] + [
            (d.key, d.label) for d in templates.fields_for(company, "lead")
        ]
        self.fields["targets"].choices = _members(company)
        c = self.instance.condition or {}
        self.fields["field"].initial, self.fields["op"].initial = c.get("field"), c.get("op")
        self.fields["value"].initial = c.get("value")
        self.fields["targets"].initial = self.instance.targets
        for name in ("field", "op"):
            self.fields[name].widget.attrs["class"] = "form-select"

    def clean(self):
        data = super().clean()
        op, field = data.get("op"), data.get("field")
        self.instance.condition = (
            {"field": field, "op": op, **({"value": data["value"]} if data.get("value") else {})}
            if op and field
            else {}
        )
        self.instance.targets = list(data.get("targets") or [])
        return data


class CompanyFieldForm(FieldDefinitionForm):
    """CRM-04: a company's own lead field (plan-gated)."""

    class Meta(FieldDefinitionForm.Meta):
        model = FieldDefinition
        fields = [
            "key",
            "label",
            "type",
            "required",
            "filterable",
            "show_in_list",
            "help_text",
            "sort_order",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, entities=[("lead", "Lead")], **kwargs)
        del self.fields["entity"]


class CompanyScoringRuleForm(ScoringRuleForm):
    """SCORE-02: a company adjusts a template rule (same key) or adds its own."""
