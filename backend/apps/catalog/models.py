"""Business catalogues (M11: CAT-01, CAT-02, CAT-04 … CAT-08): properties, travel packages, courses …

Catalogue types and their fields come from the industry template (same field engine as the CRM); companies manage
their own items. Company-owned tables (TenantModel + RLS).
"""

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.tenancy.models import TenantModel


class CatalogItem(TenantModel):
    ACTIVE, INACTIVE = "active", "inactive"
    STATUSES = [(ACTIVE, "Active"), (INACTIVE, "Inactive")]

    catalog_type = models.ForeignKey("industries.CatalogType", on_delete=models.PROTECT, related_name="items")
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE, db_index=True)
    price_paise = models.BigIntegerField(null=True, blank=True, help_text="From the type's price field")
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["company", "catalog_type", "status"]),
            GinIndex(fields=["attributes"], name="catalog_attributes_gin"),
        ]

    def __str__(self):
        return self.title


class CatalogMedia(TenantModel):
    """CAT-07 photos and brochures, stored privately per company and served through signed links."""

    KINDS = [("photo", "Photo"), ("brochure", "Brochure"), ("video", "Video")]

    item = models.ForeignKey(CatalogItem, on_delete=models.CASCADE, related_name="media")
    kind = models.CharField(max_length=10, choices=KINDS, default="photo")
    file_key = models.CharField(max_length=500)
    file_name = models.CharField(max_length=255)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "created_at"]


class CatalogCollection(TenantModel):
    """CAT-04: a named set of items, picked by hand or defined by a filter (used by campaigns and WhatsApp later)."""

    MANUAL, FILTER = "manual", "filter"

    catalog_type = models.ForeignKey("industries.CatalogType", on_delete=models.PROTECT, related_name="collections")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    mode = models.CharField(max_length=10, choices=[(MANUAL, "Picked by hand"), (FILTER, "By filter")], default=MANUAL)
    filter = models.CharField(max_length=2000, blank=True, help_text="Query string of the item list filters")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CollectionItem(TenantModel):
    collection = models.ForeignKey(CatalogCollection, on_delete=models.CASCADE, related_name="entries")
    item = models.ForeignKey(CatalogItem, on_delete=models.CASCADE, related_name="+")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "created_at"]
        constraints = [models.UniqueConstraint(fields=["collection", "item"], name="uniq_collection_item")]


class CatalogImport(TenantModel):
    catalog_type = models.ForeignKey("industries.CatalogType", on_delete=models.PROTECT, related_name="+")
    file_name = models.CharField(max_length=255)
    file_key = models.CharField(max_length=500)
    headers = models.JSONField(default=list)
    mapping = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, default="pending")
    total = models.PositiveIntegerField(default=0)
    created = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]
