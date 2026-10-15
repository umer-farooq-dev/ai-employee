"""Catalogue logic (CAT-01, CAT-02, CAT-04 … CAT-08). Panel views, the API and (Phase 4) AI tools call these."""

import os

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.http import QueryDict

from apps.audit.services import record
from apps.core.money import parse_inr
from apps.core.storage import company_path, private_storage
from apps.core.tabular import read_table
from apps.core.uploads import validate_upload
from apps.industries import fields as field_engine
from apps.industries import services as templates
from apps.platform_config import services as config

from .models import CatalogCollection, CatalogImport, CatalogItem, CatalogMedia, CollectionItem


# ------------------------------------------------------------------ types & fields
def types(company):
    return templates.catalog_types(company)


def get_type(company, key):
    for t in types(company):
        if t.key == key:
            return t
    raise ValidationError(f"Unknown catalogue: {key}.")


def fields(company, ctype):
    return templates.fields_for(company, ctype.entity)


# ------------------------------------------------------------------ items (CAT-01, CAT-02, CAT-05, CAT-06)
def _apply(item, ctype, defs, values, partial=False):
    cleaned = field_engine.clean_values(defs, values or {}, partial=partial)
    item.attributes = {**(item.attributes if partial else {}), **cleaned}
    display = ctype.display or {}
    title_key, price_key = display.get("title_field"), display.get("price_field")
    title = item.attributes.get(title_key) if title_key else None
    if not title and defs:
        title = item.attributes.get(defs[0].key)
    item.title = str(title or "Untitled").strip()[:255]
    item.price_paise = item.attributes.get(price_key) if price_key else None


def create_item(company, ctype, values, status=CatalogItem.ACTIVE, request=None):
    item = CatalogItem(company=company, catalog_type=ctype, status=status)
    _apply(item, ctype, fields(company, ctype), values)
    item.save()
    record(request, "catalog.item_create", "catalog_item", item.id, company=company)
    return item


def update_item(item, values, status=None, request=None):
    _apply(item, item.catalog_type, fields(item.company, item.catalog_type), values, partial=True)
    if status in dict(CatalogItem.STATUSES):
        item.status = status
    item.save()
    record(request, "catalog.item_update", "catalog_item", item.id, company=item.company)
    return item


def delete_item(item, request=None):
    for media in item.media.all():
        private_storage.delete(media.file_key)
    record(request, "catalog.item_delete", "catalog_item", item.id, company=item.company)
    item.delete()


@transaction.atomic
def bulk_edit(company, items, field_key, value, request=None):
    """CAT-07 bulk edit: set status or one field on many items."""
    items = list(items)
    if field_key == "status":
        if value not in dict(CatalogItem.STATUSES):
            raise ValidationError("Unknown status.")
        for item in items:
            item.status = value
            item.save(update_fields=["status", "updated_at"])
    elif field_key == "delete":
        for item in items:
            delete_item(item, request=request)
    else:
        for item in items:
            defs = [d for d in fields(company, item.catalog_type) if d.key == field_key]
            if not defs:
                raise ValidationError("Unknown field.")
            _apply(item, item.catalog_type, fields(company, item.catalog_type), {field_key: value}, partial=True)
            item.save()
    record(
        request,
        "catalog.bulk_edit",
        "catalog_item",
        f"{len(items)} items",
        company=company,
        changes={"field": field_key},
    )
    return len(items)


# ------------------------------------------------------------------ media (CAT-07)
def add_media(item, upload, kind="photo", request=None):
    validate_upload(upload, images_only=kind == "photo")
    key = private_storage.save(company_path(item.company_id, f"catalog/{item.pk}", upload.name), upload)
    media = CatalogMedia.objects.create(
        company_id=item.company_id,
        item=item,
        kind=kind,
        file_key=key,
        file_name=os.path.basename(upload.name)[:255],
        sort_order=item.media.count(),
    )
    record(request, "catalog.media_add", "catalog_item", item.id, company=item.company)
    return media


def remove_media(media, request=None):
    private_storage.delete(media.file_key)
    record(request, "catalog.media_remove", "catalog_item", media.item_id, company=media.item.company)
    media.delete()


# ------------------------------------------------------------------ list filters
def filter_items(company, ctype, params):
    """q, status, sort and f_<key> / f_<key>_min / f_<key>_max for filterable fields."""
    qs = CatalogItem.objects.filter(catalog_type=ctype).prefetch_related("media")
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(attributes__icontains=q))
    if params.get("status"):
        qs = qs.filter(status=params["status"])
    for d in [d for d in fields(company, ctype) if d.filterable]:
        key = f"f_{d.key}"
        if d.type in ("number", "currency"):
            convert = parse_inr if d.type == "currency" else float
            for suffix, lookup in (("_min", "gte"), ("_max", "lte")):
                raw = params.get(key + suffix)
                if raw:
                    try:
                        qs = qs.filter(**{f"attributes__{d.key}__{lookup}": convert(raw)})
                    except (TypeError, ValueError, ValidationError):
                        pass
        elif params.get(key):
            value = params[key]
            if d.type == "multi_select":
                qs = qs.filter(**{f"attributes__{d.key}__contains": [value]})
            elif d.type == "single_select":
                qs = qs.filter(**{f"attributes__{d.key}": value})
            elif d.type == "yes_no":
                qs = qs.filter(**{f"attributes__{d.key}": value in ("1", "true", "yes")})
            else:
                qs = qs.filter(**{f"attributes__{d.key}__icontains": value})
    sort = {"price": "price_paise", "-price": "-price_paise", "newest": "-created_at"}.get(params.get("sort"), "title")
    return qs.order_by(sort)


# ------------------------------------------------------------------ collections (CAT-04)
def save_collection(company, ctype, data, collection=None, request=None):
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("Give the collection a name.")
    collection = collection or CatalogCollection(company=company, catalog_type=ctype)
    collection.name, collection.description = name[:120], str(data.get("description") or "")[:255]
    collection.mode = data.get("mode") if data.get("mode") in ("manual", "filter") else "manual"
    collection.filter = str(data.get("filter") or "")[:2000]
    collection.save()
    record(request, "catalog.collection_save", "catalog_collection", collection.id, company=company)
    return collection


def set_collection_items(collection, item_ids, request=None):
    items = list(CatalogItem.objects.filter(catalog_type=collection.catalog_type, pk__in=item_ids))
    with transaction.atomic():
        CollectionItem.objects.filter(collection=collection).delete()
        CollectionItem.objects.bulk_create(
            [
                CollectionItem(company_id=collection.company_id, collection=collection, item=item, sort_order=i)
                for i, item in enumerate(items)
            ]
        )
    record(
        request,
        "catalog.collection_items",
        "catalog_collection",
        collection.id,
        company=collection.company,
        changes={"items": len(items)},
    )


def collection_items(collection):
    if collection.mode == CatalogCollection.FILTER:
        return filter_items(collection.company, collection.catalog_type, QueryDict(collection.filter))
    return CatalogItem.objects.filter(pk__in=collection.entries.values("item_id")).order_by("title")


# ------------------------------------------------------------------ import (CAT-07)
def start_import(company, ctype, upload, request=None):
    max_mb = config.get("crm.import_max_mb")
    if upload.size > max_mb * 1024 * 1024:
        raise ValidationError(f"The file is larger than {max_mb} MB.")
    data = upload.read()
    rows = read_table(upload.name, data)
    if not rows:
        raise ValidationError("The file is empty.")
    limit = config.get("crm.import_max_rows")
    if len(rows) - 1 > limit:
        raise ValidationError(f"The file has {len(rows) - 1} rows; the limit is {limit}.")
    key = private_storage.save(company_path(company.id, "imports", upload.name), ContentFile(data))
    headers = [str(h).strip() for h in rows[0]]
    labels = {d.label.lower(): d.key for d in fields(company, ctype)} | {d.key: d.key for d in fields(company, ctype)}
    mapping = {h: labels.get(h.lower(), "") for h in headers}
    return CatalogImport.objects.create(
        company=company,
        catalog_type=ctype,
        file_name=upload.name[:255],
        file_key=key,
        headers=headers,
        mapping=mapping,
        total=len(rows) - 1,
    )


@transaction.atomic
def run_import(imp, mapping, request=None):
    company, ctype = imp.company, imp.catalog_type
    defs = fields(company, ctype)
    keys = {d.key for d in defs}
    mapping = {h: k for h, k in (mapping or {}).items() if h in imp.headers and k in keys}
    if not mapping:
        raise ValidationError("Map at least one column.")
    with private_storage.open(imp.file_key, "rb") as fh:
        rows = read_table(imp.file_name, fh.read())[1:]
    index = {h: i for i, h in enumerate(imp.headers)}
    to_create, errors = [], []
    for number, row in enumerate(rows, start=2):
        values = {k: (row[index[h]] if index[h] < len(row) else "") for h, k in mapping.items()}
        item = CatalogItem(company=company, catalog_type=ctype)
        try:
            _apply(item, ctype, defs, values)
        except ValidationError as exc:
            errors.append({"row": number, "reason": "; ".join(exc.messages)})
            continue
        to_create.append(item)
    CatalogItem.objects.bulk_create(to_create, batch_size=1000)
    imp.mapping, imp.status, imp.created, imp.failed, imp.errors = mapping, "done", len(to_create), len(errors), errors
    imp.save()
    record(
        request,
        "catalog.import",
        "catalog_import",
        imp.id,
        company=company,
        changes={"created": imp.created, "failed": imp.failed},
    )
    return imp
