"""Dynamic field engine (CRM-04, CAT-01): validate values against FieldDefinitions and build form fields.

Values are stored in a JSON column (lead.custom, catalog item.attributes) keyed by the field key.
Currency is stored in paise, dates as ISO strings, multi-select as a list, yes/no as a boolean.
"""

import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.core.india import normalise_phone
from apps.core.money import format_inr, parse_inr


def options(defn):
    """Select options as [(value, label)] from ["A", "B"] or [{"value", "label"}]."""
    out = []
    for o in defn.options or []:
        if isinstance(o, dict):
            out.append((str(o.get("value", o.get("label", ""))), str(o.get("label", o.get("value", "")))))
        else:
            out.append((str(o), str(o)))
    return out


def clean_value(defn, raw):
    """One value → its stored form. Raises ValidationError with the field label."""
    t, label, rules = defn.type, defn.label, defn.validation or {}
    empty = raw in (None, "", [], {})
    if empty:
        if defn.required:
            raise ValidationError(f"{label} is required.")
        return [] if t == "multi_select" else None
    try:
        if t in ("text", "textarea", "location", "file"):
            value = str(raw).strip()
            if rules.get("max_length") and len(value) > int(rules["max_length"]):
                raise ValidationError(f"{label}: at most {rules['max_length']} characters.")
            return value
        if t == "number":
            value = float(str(raw).replace(",", ""))
            value = int(value) if value.is_integer() else value
        elif t == "currency":
            value = parse_inr(raw)
        elif t == "date":
            value = (
                raw.isoformat() if isinstance(raw, datetime.date) else datetime.date.fromisoformat(str(raw)).isoformat()
            )
        elif t == "datetime":
            value = (
                raw if isinstance(raw, datetime.datetime) else datetime.datetime.fromisoformat(str(raw))
            ).isoformat()
        elif t == "yes_no":
            value = raw if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "yes", "y", "on")
        elif t == "phone":
            from apps.accounts.models import phone_validator

            value = normalise_phone(str(raw))
            phone_validator(value)
        elif t == "email":
            value = str(raw).strip().lower()
            validate_email(value)
        elif t in ("single_select", "multi_select"):
            allowed = {v for v, _ in options(defn)}
            labels = {lab.lower(): v for v, lab in options(defn)}
            items = raw if isinstance(raw, (list, tuple)) else ([raw] if t == "single_select" else str(raw).split(","))
            items = [labels.get(str(i).strip().lower(), str(i).strip()) for i in items if str(i).strip()]
            bad = [i for i in items if i not in allowed]
            if bad:
                raise ValidationError(f"{label}: {', '.join(bad)} is not one of the options.")
            return items[0] if t == "single_select" else items
        else:
            return raw
    except ValidationError as exc:
        raise ValidationError([m if m.startswith(label) else f"{label}: {m}" for m in exc.messages]) from None
    except (TypeError, ValueError):
        raise ValidationError(f"{label}: enter a valid {defn.get_type_display().lower()}.") from None
    if t in ("number", "currency"):
        if rules.get("min") is not None and value < float(rules["min"]) * (100 if t == "currency" else 1):
            raise ValidationError(f"{label}: must be at least {rules['min']}.")
        if rules.get("max") is not None and value > float(rules["max"]) * (100 if t == "currency" else 1):
            raise ValidationError(f"{label}: must be at most {rules['max']}.")
    return value


def clean_values(definitions, data: dict, partial=False) -> dict:
    """All values for an entity. Unknown keys are dropped; with partial=True missing keys are left alone."""
    out, errors = {}, []
    for defn in definitions:
        if partial and defn.key not in data:
            continue
        try:
            out[defn.key] = clean_value(defn, data.get(defn.key))
        except ValidationError as exc:
            errors.extend(exc.messages)
    if errors:
        raise ValidationError(errors)
    return out


def display(defn, value):
    """Human-readable value for lists and detail pages."""
    if value in (None, "", []):
        return ""
    if defn.type == "currency":
        return format_inr(value)
    if defn.type == "yes_no":
        return "Yes" if value else "No"
    if defn.type in ("single_select", "multi_select"):
        labels = dict(options(defn))
        values = value if isinstance(value, list) else [value]
        return ", ".join(labels.get(v, v) for v in values)
    return str(value)


def form_field(defn, initial=None):
    """Django form field for a definition (panel forms). Values are validated again by clean_value."""
    common = {"label": defn.label, "required": defn.required, "help_text": defn.help_text, "initial": initial}
    t = defn.type
    if t in ("single_select",):
        return forms.ChoiceField(choices=[("", "—")] + options(defn), **common)
    if t == "multi_select":
        return forms.MultipleChoiceField(choices=options(defn), widget=forms.SelectMultiple, **common)
    if t == "yes_no":
        return forms.BooleanField(**{**common, "required": False})
    if t == "date":
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), **common)
    if t == "datetime":
        return forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}), **common)
    if t == "textarea":
        return forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), **common)
    if t == "currency":
        common["initial"] = (initial / 100) if isinstance(initial, int) else initial
        return forms.CharField(**{**common, "help_text": common["help_text"] or "e.g. 70,00,000 or 70 lakh"})
    if t == "email":
        return forms.EmailField(**common)
    if t == "number":
        return forms.CharField(widget=forms.NumberInput(attrs={"step": "any"}), **common)
    if t == "phone":
        return forms.CharField(widget=forms.TextInput(attrs={"type": "tel"}), **common)
    return forms.CharField(**common)


def add_form_fields(form, definitions, values, prefix="f_"):
    """Append dynamic fields to a Django form; read them back with read_form_values()."""
    for defn in definitions:
        form.fields[prefix + defn.key] = form_field(defn, (values or {}).get(defn.key))


def read_form_values(form, definitions, prefix="f_"):
    return {d.key: form.cleaned_data.get(prefix + d.key) for d in definitions}
