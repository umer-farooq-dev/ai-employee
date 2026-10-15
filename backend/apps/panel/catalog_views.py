"""Company panel: catalogue (CAT-01, CAT-02, CAT-04 … CAT-08). Logic lives in apps.catalog.services."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.catalog import services as catalog
from apps.catalog.models import CatalogCollection, CatalogImport, CatalogItem, CatalogMedia
from apps.industries import fields as field_engine
from apps.rbac.services import has_perm
from apps.superadmin.forms import BootstrapMixin

from .company_views import _errors, company_perm


class ItemForm(BootstrapMixin, forms.Form):
    status = forms.ChoiceField(choices=CatalogItem.STATUSES)

    def __init__(self, *args, defs=(), values=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.defs = defs
        field_engine.add_form_fields(self, defs, values or {})
        for name, field in self.fields.items():
            if name.startswith("f_"):
                w = field.widget
                w.attrs.setdefault(
                    "class",
                    (
                        "form-select"
                        if isinstance(w, forms.Select)
                        else ("form-check-input" if isinstance(w, forms.CheckboxInput) else "form-control")
                    ),
                )

    def values(self):
        return field_engine.read_form_values(self, self.defs)


def _type(request, key):
    try:
        return catalog.get_type(request.company, key)
    except ValidationError:
        raise Http404 from None


def _can_manage(request):
    return has_perm(request.user, "catalog.manage", request.company)


@company_perm("catalog.view")
def home(request):
    types = catalog.types(request.company)
    if types:
        return redirect("panel:catalog_list", type_key=types[0].key)
    return render(request, "panel/company/catalog/empty.html")


@company_perm("catalog.view")
def item_list(request, type_key):
    company, ctype = request.company, _type(request, type_key)
    defs = catalog.fields(company, ctype)
    if request.method == "POST":
        if not _can_manage(request):
            raise PermissionDenied
        try:
            items = CatalogItem.objects.filter(catalog_type=ctype, pk__in=request.POST.getlist("ids"))
            if not items.exists():
                raise ValidationError("Select at least one item.")
            count = catalog.bulk_edit(
                company, items, request.POST.get("field"), request.POST.get("value"), request=request
            )
            messages.success(request, f"{count} item(s) updated.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect(request.get_full_path())
    qs = catalog.filter_items(company, ctype, request.GET)
    page = Paginator(qs, 24).get_page(request.GET.get("page"))
    list_defs = [d for d in defs if d.show_in_list]
    rows = [
        (item, [(d.label, field_engine.display(d, item.attributes.get(d.key))) for d in list_defs]) for item in page
    ]
    return render(
        request,
        "panel/company/catalog/list.html",
        {
            "ctype": ctype,
            "types": catalog.types(company),
            "page": page,
            "rows": rows,
            "list_defs": list_defs,
            "filter_defs": [d for d in defs if d.filterable],
            "edit_defs": defs,
            "p": request.GET,
            "can_manage": _can_manage(request),
            "params": request.GET.urlencode(),
        },
    )


@company_perm("catalog.manage")
def item_form(request, type_key, pk=None):
    company, ctype = request.company, _type(request, type_key)
    item = get_object_or_404(CatalogItem, pk=pk, catalog_type=ctype) if pk else None
    defs = catalog.fields(company, ctype)
    if request.method == "POST" and request.POST.get("op") in ("media", "remove_media", "delete") and item:
        try:
            if request.POST["op"] == "media":
                for upload in request.FILES.getlist("files"):
                    catalog.add_media(item, upload, request.POST.get("kind", "photo"), request=request)
                messages.success(request, "Files added.")
            elif request.POST["op"] == "remove_media":
                catalog.remove_media(
                    get_object_or_404(CatalogMedia, pk=request.POST.get("media"), item=item), request=request
                )
            else:
                catalog.delete_item(item, request=request)
                messages.success(request, "Item deleted.")
                return redirect("panel:catalog_list", type_key=type_key)
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("panel:catalog_edit", type_key=type_key, pk=item.pk)
    form = ItemForm(
        request.POST or None,
        defs=defs,
        values=item.attributes if item else None,
        initial={"status": item.status if item else CatalogItem.ACTIVE},
    )
    if request.method == "POST" and form.is_valid():
        try:
            if item:
                catalog.update_item(item, form.values(), form.cleaned_data["status"], request=request)
            else:
                item = catalog.create_item(company, ctype, form.values(), form.cleaned_data["status"], request=request)
            messages.success(request, f"{ctype.item_label or 'Item'} saved.")
            return redirect("panel:catalog_edit", type_key=type_key, pk=item.pk)
        except ValidationError as exc:
            for m in exc.messages:
                form.add_error(None, m)
    return render(
        request,
        "panel/company/catalog/item_form.html",
        {
            "ctype": ctype,
            "item": item,
            "form": form,
            "media": item.media.all() if item else [],
        },
    )


@company_perm("catalog.view")
def collections(request, type_key):
    ctype = _type(request, type_key)
    return render(
        request,
        "panel/company/catalog/collections.html",
        {
            "ctype": ctype,
            "types": catalog.types(request.company),
            "collections": CatalogCollection.objects.filter(catalog_type=ctype),
            "can_manage": _can_manage(request),
        },
    )


@company_perm("catalog.manage")
def collection_form(request, type_key, pk=None):
    company, ctype = request.company, _type(request, type_key)
    collection = get_object_or_404(CatalogCollection, pk=pk, catalog_type=ctype) if pk else None
    if request.method == "POST":
        try:
            if request.POST.get("op") == "delete" and collection:
                collection.delete()
                messages.success(request, "Collection deleted.")
                return redirect("panel:catalog_collections", type_key=type_key)
            collection = catalog.save_collection(company, ctype, request.POST, collection, request=request)
            if collection.mode == CatalogCollection.MANUAL:
                catalog.set_collection_items(collection, request.POST.getlist("items"), request=request)
            messages.success(request, "Collection saved.")
            return redirect("panel:catalog_collection_edit", type_key=type_key, pk=collection.pk)
        except ValidationError as exc:
            _errors(request, exc)
    selected = set(collection.entries.values_list("item_id", flat=True)) if collection else set()
    return render(
        request,
        "panel/company/catalog/collection_form.html",
        {
            "ctype": ctype,
            "collection": collection,
            "selected": selected,
            "items": CatalogItem.objects.filter(catalog_type=ctype).order_by("title"),
            "members": list(catalog.collection_items(collection)) if collection else [],
        },
    )


@company_perm("catalog.manage")
def item_import(request, type_key, pk=None):
    company, ctype = request.company, _type(request, type_key)
    imp = get_object_or_404(CatalogImport, pk=pk, catalog_type=ctype) if pk else None
    if request.method == "POST":
        try:
            if not imp:
                if not request.FILES.get("file"):
                    raise ValidationError("Choose a CSV or Excel file.")
                imp = catalog.start_import(company, ctype, request.FILES["file"], request=request)
            elif imp.status == "pending":
                mapping = {h: request.POST.get(f"map_{i}", "") for i, h in enumerate(imp.headers)}
                catalog.run_import(imp, mapping, request=request)
            return redirect("panel:catalog_import_step", type_key=type_key, pk=imp.pk)
        except ValidationError as exc:
            _errors(request, exc)
            return redirect(request.path)
    return render(
        request,
        "panel/company/catalog/import.html",
        {
            "ctype": ctype,
            "imp": imp,
            "defs": catalog.fields(company, ctype),
            "columns": list(enumerate(imp.headers)) if imp else [],
            "back": reverse("panel:catalog_list", args=[type_key]),
        },
    )
