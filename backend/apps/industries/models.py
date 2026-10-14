from django.db import models

from apps.core.models import BaseModel


class Industry(BaseModel):
    """An industry the platform serves (Super Admin → Industries). Phase 2 uses it for the website and registration;
    Phase 3 adds the industry templates (CRM fields, catalogue, roles) to it."""

    key = models.SlugField(max_length=50, unique=True, help_text="Also the website URL: /industries/<key>/")
    name = models.CharField(max_length=100)
    short_description = models.CharField(max_length=255, blank=True, help_text="Card text on the website")
    description = models.TextField(blank=True, help_text="Industry page body (HTML allowed)")
    icon = models.CharField(max_length=500, blank=True, help_text="Image URL")
    image = models.CharField(max_length=500, blank=True, help_text="Image URL for the industry page")
    is_active = models.BooleanField(
        default=False, help_text="Active industries show on the website and in registration"
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "industries"

    def __str__(self):
        return self.name
