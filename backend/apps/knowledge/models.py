"""Knowledge base (M08: KB-01 … KB-11, TEN-04). Company-owned tables (TenantModel + RLS).

Sources (website, document, approved text, spreadsheet, FAQ list) → documents → chunks. Chunks carry a pgvector
embedding (when an embedding model is set in AI Settings) and a full-text vector; search is hybrid and always
filtered by company, approval and employee scope.
"""

from django.conf import settings
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models

from apps.tenancy.models import TenantModel


class VectorField(models.Field):
    """pgvector column without a fixed size (the size depends on the embedding model chosen in Super Admin).
    ponytail: exact search per company; add an HNSW index per model dimension when companies hold very large KBs."""

    def db_type(self, connection):
        return "vector"

    def get_prep_value(self, value):
        return None if value is None else "[" + ",".join(f"{float(x):.7g}" for x in value) + "]"

    def from_db_value(self, value, expression, connection):
        return None if value is None else [float(x) for x in value.strip("[]").split(",") if x]


class Source(TenantModel):
    URL, PDF, DOCX, TEXT, SHEET, FAQ = "url", "pdf", "docx", "text", "sheet", "faq"
    TYPES = [
        (URL, "Website"),
        (PDF, "PDF"),
        (DOCX, "Word document"),
        (TEXT, "Approved text"),
        (SHEET, "Excel / CSV"),
        (FAQ, "FAQs"),
    ]
    QUEUED, PROCESSING, READY, FAILED = "queued", "processing", "ready", "failed"
    STATUSES = [(QUEUED, "Queued"), (PROCESSING, "Processing"), (READY, "Ready"), (FAILED, "Failed")]
    DRAFT, APPROVED = "draft", "approved"
    APPROVALS = [(DRAFT, "Draft"), (APPROVED, "Approved")]
    SYNC = [("", "Never"), ("daily", "Daily"), ("weekly", "Weekly")]

    type = models.CharField(max_length=10, choices=TYPES)
    title = models.CharField(max_length=200)
    uri = models.URLField(max_length=1000, blank=True, help_text="Website start page")
    file_key = models.CharField(max_length=500, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    body = models.TextField(blank=True, help_text="Approved text (KB-04), HTML allowed")
    category = models.CharField(max_length=60, blank=True, help_text="e.g. Services, Policies, Prices")
    language = models.CharField(max_length=10, blank=True)
    crawl = models.JSONField(
        default=dict, blank=True, help_text='KB-01: {"max_pages", "max_depth", "include", "exclude"}'
    )
    status = models.CharField(max_length=12, choices=STATUSES, default=QUEUED, db_index=True)
    error = models.CharField(max_length=500, blank=True)
    approval = models.CharField(max_length=10, choices=APPROVALS, default=DRAFT, db_index=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # KB-08: empty = company-wide, else only these AI Employees
    employees = models.ManyToManyField("agents.AIEmployee", blank=True, related_name="knowledge_sources")
    sync_schedule = models.CharField(max_length=10, choices=SYNC, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Document(TenantModel):
    """One page / file / sheet of a source."""

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=300, blank=True)
    url = models.URLField(max_length=1000, blank=True)
    language = models.CharField(max_length=10, blank=True)
    content_hash = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]


class FAQ(TenantModel):
    """KB-03: question & answer per language, approved one by one."""

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="faqs")
    question = models.TextField()
    answer = models.TextField()
    language = models.CharField(max_length=10, default="en")
    approval = models.CharField(max_length=10, choices=Source.APPROVALS, default=Source.DRAFT)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "created_at"]


class Chunk(TenantModel):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="chunks")
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.CASCADE, related_name="chunks")
    faq = models.ForeignKey(FAQ, null=True, blank=True, on_delete=models.CASCADE, related_name="chunks")
    index = models.PositiveIntegerField(default=0)
    text = models.TextField()
    language = models.CharField(max_length=10, blank=True)
    tokens = models.PositiveIntegerField(default=0)
    embedding = VectorField(null=True, blank=True)
    embedding_model = models.CharField(max_length=260, blank=True, help_text="provider/model that made the vector")
    tsv = models.GeneratedField(
        expression=SearchVector("text", config="simple"), output_field=SearchVectorField(), db_persist=True
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["source", "index"]
        indexes = [models.Index(fields=["company", "source"])]


class UnansweredQuestion(TenantModel):
    """KB-10: what the AI could not answer, grouped by normalised text and counted."""

    OPEN, RESOLVED = "open", "resolved"

    employee = models.ForeignKey(
        "agents.AIEmployee", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    normalized_question = models.CharField(max_length=300)
    example_text = models.TextField()
    count = models.PositiveIntegerField(default=1)
    last_seen_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=10, default=OPEN, db_index=True)
    conversation = models.ForeignKey(
        "agents.Conversation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-count", "-last_seen_at"]
        constraints = [
            models.UniqueConstraint(fields=["company", "normalized_question"], name="uniq_unanswered_question")
        ]
