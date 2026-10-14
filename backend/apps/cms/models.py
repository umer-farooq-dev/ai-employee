from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class SectionType(BaseModel):
    key = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    schema = models.JSONField(default=list, help_text="List of field definitions")
    is_dynamic = models.BooleanField(default=False, help_text="Part of the content is read live from other data")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Page(BaseModel):
    key = models.SlugField(max_length=50, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True, help_text="URL path; empty = home page")
    title = models.CharField(max_length=200)
    seo = models.JSONField(default=dict, blank=True, help_text="meta_title, meta_description, og_image")
    is_system = models.BooleanField(default=False, help_text="Seeded page: cannot be deleted")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title


class Section(BaseModel):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="sections")
    section_type = models.ForeignKey(SectionType, on_delete=models.PROTECT)
    sort_order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    anchor_id = models.SlugField(max_length=50, blank=True, help_text="For menu links like #pricing")
    content = models.JSONField(default=dict, blank=True, help_text="Published content")
    draft_content = models.JSONField(null=True, blank=True, help_text="Unpublished changes")
    version = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["page", "sort_order"]

    def __str__(self):
        return f"{self.page.key}:{self.section_type.key}"

    @property
    def has_draft(self):
        return self.draft_content is not None and self.draft_content != self.content


class SectionVersion(models.Model):
    """Every publish is kept so content can be compared and restored."""

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    content = models.JSONField()
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["section", "version"], name="uniq_section_version")]

    def __str__(self):
        return f"{self.section} v{self.version}"
