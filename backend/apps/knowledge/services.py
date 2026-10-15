"""Knowledge base services (KB-01 … KB-11, TEN-04, SEC-11). Panels and the REST API call these functions.

Processing runs right after a change (a background thread on the server, inline in tests) and again from the
`process_knowledge` command (cron) for anything left queued, scheduled re-syncs and re-embedding.
"""

import hashlib
import logging
import os
import re
import threading
from datetime import timedelta
from functools import reduce
from operator import or_

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.db.models import F, Q, Sum
from django.db.models.expressions import RawSQL
from django.utils import timezone
from django.utils.html import strip_tags

from apps.audit.services import record
from apps.billing import limits
from apps.core.india import detect_language
from apps.core.storage import company_path, private_storage
from apps.core.uploads import scan, validate_upload
from apps.platform_config.services import get as setting
from apps.tenancy.context import company_context, platform_context

from . import ingest
from .models import FAQ, Chunk, Document, Source, UnansweredQuestion

log = logging.getLogger(__name__)
FILE_TYPES = {Source.PDF: {"pdf"}, Source.DOCX: {"docx"}, Source.SHEET: {"csv", "xlsx"}}
EMBED_BATCH = 64


# ------------------------------------------------------------------ create / edit (KB-01 … KB-05, KB-08)
def _check_limits(company, adding_bytes=0, new_source=True):
    if new_source:
        limits.check(company, "kb_sources", Source.objects.filter(company=company).count(), label="knowledge sources")
    cap_mb = limits.limit(company, "kb_storage_mb")
    if cap_mb is not None and adding_bytes:
        used = Source.objects.filter(company=company).aggregate(s=Sum("file_size"))["s"] or 0
        if used + adding_bytes > cap_mb * 1024 * 1024:
            raise ValidationError(f"Your plan allows {cap_mb} MB of knowledge files. Delete files or upgrade.")


def _employees(company, ids):
    from apps.agents.models import AIEmployee

    ids = [str(i) for i in ids or [] if i]
    found = list(AIEmployee.objects.filter(company=company, pk__in=ids))
    if len(found) != len(set(ids)):
        raise ValidationError("Unknown AI Employee in the scope.")
    return found


def _crawl_options(data):
    def lines(value):
        if isinstance(value, str):
            value = value.splitlines()
        return [v.strip() for v in value or [] if v.strip()]

    out = {"include": lines(data.get("include")), "exclude": lines(data.get("exclude"))}
    for key, setting_key in (("max_pages", "knowledge.crawl_max_pages"), ("max_depth", "knowledge.crawl_max_depth")):
        cap = setting(setting_key)
        try:
            out[key] = max(0 if key == "max_depth" else 1, min(int(data.get(key) or cap), cap))
        except (TypeError, ValueError):
            raise ValidationError(f"{key.replace('_', ' ').capitalize()} must be a number.") from None
    for pattern in out["include"] + out["exclude"]:
        try:
            re.compile(pattern)
        except re.error:
            raise ValidationError(f"Invalid page pattern: {pattern}") from None
    return out


def create_source(company, data, upload=None, user=None, request=None):
    kind = data.get("type")
    if kind not in dict(Source.TYPES):
        raise ValidationError("Choose a knowledge type.")
    source = Source(
        company=company,
        type=kind,
        title=str(data.get("title") or "").strip()[:200],
        category=str(data.get("category") or "").strip()[:60],
        sync_schedule=data.get("sync_schedule") or "",
        created_by=user if user and user.is_authenticated else None,
    )
    if source.sync_schedule not in dict(Source.SYNC):
        raise ValidationError("Unknown re-sync schedule.")
    size = 0
    if kind == Source.URL:
        source.uri = str(data.get("uri") or "").strip()
        if not source.uri.startswith(("http://", "https://")):
            raise ValidationError("Enter the website address, e.g. https://example.com")
        source.crawl = _crawl_options(data)
        source.title = source.title or source.uri
    elif kind in FILE_TYPES:
        if not upload:
            raise ValidationError("Choose a file to upload.")
        ext = validate_upload(upload)
        if ext not in FILE_TYPES[kind]:
            raise ValidationError(f"Upload a {' or '.join('.' + e for e in sorted(FILE_TYPES[kind]))} file.")
        size = upload.size
        _check_limits(company, size)
        data_bytes = upload.read()
        scan(data_bytes)
        upload.seek(0)
        source.file_key = private_storage.save(company_path(company.id, "knowledge", upload.name), upload)
        source.file_name, source.file_size = os.path.basename(upload.name)[:255], size
        source.title = source.title or source.file_name
    elif kind == Source.TEXT:
        source.body = str(data.get("body") or "").strip()
        if not source.body or not source.title:
            raise ValidationError("Give the text a title and content.")
    elif kind == Source.FAQ:
        source.title = source.title or "Frequently asked questions"
        source.approval = Source.APPROVED  # FAQs are approved one by one (KB-03)
    if not size:
        _check_limits(company)
    if not source.title:
        raise ValidationError("Give the source a title.")
    source.save()
    if "employees" in data:
        source.employees.set(_employees(company, data["employees"]))
    record(request, "knowledge.create", "kb_source", source.id, company=company, changes={"type": kind})
    enqueue(source)
    source.refresh_from_db()
    return source


def update_source(source, data, user=None, request=None):
    """Title, category, scope, schedule; changing the content of an approved source sends it back to draft (KB-06)."""
    content_changed = False
    for field in ("title", "category"):
        if field in data:
            setattr(source, field, str(data[field] or "").strip()[: Source._meta.get_field(field).max_length])
    if "sync_schedule" in data:
        if data["sync_schedule"] not in dict(Source.SYNC):
            raise ValidationError("Unknown re-sync schedule.")
        source.sync_schedule = data["sync_schedule"]
    if source.type == Source.TEXT and "body" in data and str(data["body"]).strip() != source.body:
        source.body, content_changed = str(data["body"]).strip(), True
    if source.type == Source.URL and any(k in data for k in ("uri", "include", "exclude", "max_pages", "max_depth")):
        source.uri = str(data.get("uri") or source.uri).strip()
        source.crawl = _crawl_options({**source.crawl, **data})
        content_changed = True
    if not source.title:
        raise ValidationError("Give the source a title.")
    if content_changed and source.type != Source.FAQ:
        source.approval, source.approved_by, source.approved_at = Source.DRAFT, None, None
        source.status = Source.QUEUED
    source.save()
    if "employees" in data:
        source.employees.set(_employees(source.company, data["employees"]))
    record(request, "knowledge.update", "kb_source", source.id, company=source.company)
    if content_changed:
        enqueue(source)
        source.refresh_from_db()
    return source


def approve(source, approved=True, user=None, request=None):
    """KB-06: only approved knowledge reaches the AI."""
    if approved and source.status != Source.READY:
        raise ValidationError("Approve the source after processing has finished.")
    source.approval = Source.APPROVED if approved else Source.DRAFT
    source.approved_by = user if approved and user and user.is_authenticated else None
    source.approved_at = timezone.now() if approved else None
    source.save(update_fields=["approval", "approved_by", "approved_at", "updated_at"])
    record(
        request,
        "knowledge.approve" if approved else "knowledge.unapprove",
        "kb_source",
        source.id,
        company=source.company,
    )
    return source


def reprocess(source, request=None):
    source.status, source.error = Source.QUEUED, ""
    source.save(update_fields=["status", "error", "updated_at"])
    record(request, "knowledge.reprocess", "kb_source", source.id, company=source.company)
    enqueue(source)
    source.refresh_from_db()
    return source


def delete_source(source, request=None):
    """KB-07: removed from the AI immediately (chunks are deleted with the source)."""
    if source.file_key:
        private_storage.delete(source.file_key)
    record(request, "knowledge.delete", "kb_source", source.id, company=source.company)
    source.delete()


# ------------------------------------------------------------------ FAQs (KB-03)
def save_faq(source, data, faq=None, request=None):
    if source.type != Source.FAQ:
        raise ValidationError("FAQs belong to an FAQ list.")
    question, answer = str(data.get("question") or "").strip(), str(data.get("answer") or "").strip()
    if not question or not answer:
        raise ValidationError("Enter the question and the answer.")
    faq = faq or FAQ(company=source.company, source=source, sort_order=source.faqs.count())
    changed = (faq.question, faq.answer) != (question, answer)
    faq.question, faq.answer = question, answer
    faq.language = data.get("language") or detect_language(question + answer)
    if "sort_order" in data:
        faq.sort_order = int(data["sort_order"] or 0)
    if changed and faq.pk:
        faq.approval = Source.DRAFT  # edited answers are approved again
    if data.get("approved") is not None:
        faq.approval = Source.APPROVED if data["approved"] else Source.DRAFT
    faq.save()
    index_faq(faq)
    record(request, "knowledge.faq_save", "faq", faq.id, company=source.company)
    return faq


def approve_faq(faq, approved=True, request=None):
    faq.approval = Source.APPROVED if approved else Source.DRAFT
    faq.save(update_fields=["approval", "updated_at"])
    record(request, "knowledge.faq_approve", "faq", faq.id, company=faq.company)
    return faq


def delete_faq(faq, request=None):
    record(request, "knowledge.faq_delete", "faq", faq.id, company=faq.company)
    faq.delete()


def import_faqs(source, upload, request=None):
    """Bulk import: columns question, answer, language (optional). → number imported."""
    from apps.core.tabular import read_table

    validate_upload(upload)
    rows = read_table(upload.name, upload.read())
    if not rows:
        raise ValidationError("The file is empty.")
    header = [h.strip().lower() for h in rows[0]]
    if "question" not in header or "answer" not in header:
        raise ValidationError("The first row must have the columns: question, answer (and optional language).")
    qi, ai, li = (
        header.index("question"),
        header.index("answer"),
        header.index("language") if "language" in header else None,
    )
    count = 0
    for row in rows[1:]:
        cells = row + [""] * (len(header) - len(row))
        if cells[qi].strip() and cells[ai].strip():
            save_faq(
                source, {"question": cells[qi], "answer": cells[ai], "language": cells[li] if li is not None else ""}
            )
            count += 1
    record(request, "knowledge.faq_import", "kb_source", source.id, company=source.company, changes={"rows": count})
    return count


def add_template_faqs(company, version, user=None):
    """Industry template FAQs copied as a draft FAQ list; the company approves them (no unapproved facts reach AI)."""
    faqs = version.default_faqs if version else []
    if not faqs or Source.objects.filter(company=company, type=Source.FAQ, category="template").exists():
        return None
    source = Source.objects.create(
        company=company,
        type=Source.FAQ,
        title=f"{version.industry.name} — common questions",
        category="template",
        approval=Source.APPROVED,
        status=Source.READY,
        created_by=user,
    )
    for i, item in enumerate(faqs):
        for lang, pair in _faq_languages(item):
            faq = FAQ.objects.create(
                company=company, source=source, question=pair[0], answer=pair[1], language=lang, sort_order=i
            )
            index_faq(faq)
    return source


def _faq_languages(item):
    """Template FAQ shapes: {"question": {lang: q}, "answer": {lang: a}} or {"question": q, "answer": a}."""
    q, a = item.get("question"), item.get("answer")
    if isinstance(q, dict):
        return [(lang, (q[lang], (a or {}).get(lang, ""))) for lang in q if (a or {}).get(lang)]
    return [(item.get("language") or detect_language(f"{q} {a}"), (q, a))] if q and a else []


# ------------------------------------------------------------------ processing (KB-07)
def enqueue(source):
    if source.type == Source.FAQ:
        return
    if getattr(settings, "KNOWLEDGE_INLINE", False):
        process(source.pk)
        return
    company_id, pk = source.company_id, source.pk

    def run():
        try:
            with company_context(company_id):
                process(pk)
        finally:
            close_old_connections()

    transaction.on_commit(lambda: threading.Thread(target=run, daemon=True).start())


def _extract(source):
    if source.type == Source.URL:
        c = source.crawl or {}
        return ingest.crawl(
            source.uri,
            c.get("max_pages") or setting("knowledge.crawl_max_pages"),
            c.get("max_depth", setting("knowledge.crawl_max_depth")),
            c.get("include") or (),
            c.get("exclude") or (),
            setting("knowledge.user_agent"),
        )
    if source.type == Source.TEXT:
        text, _title, _links = ingest.html_to_text(source.body) if "<" in source.body else (source.body, "", [])
        return [{"title": source.title, "text": text, "metadata": {}}]
    with private_storage.open(source.file_key, "rb") as fh:
        data = fh.read()
    if source.type == Source.PDF:
        return ingest.pdf_text(data)
    if source.type == Source.DOCX:
        return ingest.docx_text(data)
    if source.type == Source.SHEET:
        return ingest.sheet_rows(source.file_name, data)
    return []


def process(source_id):
    source = Source.objects.filter(pk=source_id).first()
    if not source or source.type == Source.FAQ:
        return source
    source.status, source.error = Source.PROCESSING, ""
    source.save(update_fields=["status", "error", "updated_at"])
    try:
        docs = _extract(source)
        if not docs:
            raise ValidationError("No text was found in this source.")
        size, overlap = setting("knowledge.chunk_chars"), setting("knowledge.chunk_overlap")
        keep = set()
        with transaction.atomic():
            for item in docs:
                digest = hashlib.sha256(f"{item.get('url', '')}\n{item['text']}".encode()).hexdigest()
                existing = source.documents.filter(content_hash=digest).first()
                if existing:  # unchanged page on re-sync: keep its chunks and vectors
                    keep.add(existing.pk)
                    continue
                doc = Document.objects.create(
                    company=source.company,
                    source=source,
                    title=(item.get("title") or "")[:300],
                    url=item.get("url", "")[:1000],
                    language=detect_language(item["text"]),
                    content_hash=digest,
                    metadata=item.get("metadata") or {},
                )
                keep.add(doc.pk)
                pieces = [item["text"]] if source.type == Source.SHEET else ingest.chunk(item["text"], size, overlap)
                Chunk.objects.bulk_create(
                    [
                        Chunk(
                            company=source.company,
                            source=source,
                            document=doc,
                            index=i,
                            text=piece,
                            language=detect_language(piece),
                            tokens=max(1, len(piece) // 4),
                            metadata={"title": doc.title, "url": doc.url, **(item.get("metadata") or {})},
                        )
                        for i, piece in enumerate(pieces)
                    ]
                )
            source.documents.exclude(pk__in=keep).delete()
        embed_pending(source.company_id, source=source)
        source.status, source.processed_at = Source.READY, timezone.now()
        if source.type == Source.URL:
            source.last_synced_at = source.processed_at
    except ValidationError as exc:
        source.status, source.error = Source.FAILED, "; ".join(exc.messages)[:500]
    except Exception as exc:  # noqa: BLE001 — any parser / network failure becomes a visible "Failed" reason
        log.exception("knowledge processing failed")
        source.status, source.error = Source.FAILED, f"Processing failed: {type(exc).__name__}"[:500]
    source.save(update_fields=["status", "error", "processed_at", "last_synced_at", "updated_at"])
    return source


def index_faq(faq):
    Chunk.objects.filter(faq=faq).delete()
    Chunk.objects.create(
        company=faq.company,
        source=faq.source,
        faq=faq,
        text=f"Q: {faq.question}\nA: {faq.answer}",
        language=faq.language,
        tokens=max(1, (len(faq.question) + len(faq.answer)) // 4),
        metadata={"title": faq.question[:200]},
    )
    embed_pending(faq.company_id)


def embedding_model():
    """'provider/model' of the first usable embedding route, or '' (keyword search only)."""
    from apps.providers.services import _chain

    chain = _chain("embedding")
    return f"{chain[0].provider.key}/{chain[0].model}" if chain else ""


def embed_pending(company_id, source=None):
    """Embed chunks without a vector from the current model (new chunks, or after the model changed)."""
    from apps.agents import usage
    from apps.providers.services import NoProviderAvailable, embed

    current = embedding_model()
    if not current:
        return 0
    qs = Chunk.objects.filter(company_id=company_id).exclude(embedding_model=current)
    if source:
        qs = qs.filter(source=source)
    done = 0
    chunks = list(qs.only("id", "text")[:5000])
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i : i + EMBED_BATCH]
        try:
            result = embed([c.text for c in batch])
        except NoProviderAvailable as exc:
            log.warning("embedding skipped: %s", exc)
            return done
        model = f"{result['provider']}/{result['route_model']}"
        for c, vector in zip(batch, result["vectors"], strict=False):
            c.embedding, c.embedding_model = vector, model
        Chunk.objects.bulk_update(batch, ["embedding", "embedding_model"])
        usage.record(company_id, result, "embedding")
        done += len(batch)
    return done


# ------------------------------------------------------------------ retrieval (TEN-04, KB-06, KB-08)
def usable_chunks(company, employee=None):
    """Approved knowledge of this company, company-wide or scoped to this AI Employee."""
    qs = Chunk.objects.filter(company=company).filter(
        Q(faq__isnull=True, source__approval=Source.APPROVED, source__status=Source.READY)
        | Q(faq__approval=Source.APPROVED)
    )
    scope = Q(source__employees__isnull=True)
    if employee is not None:
        scope |= Q(source__employees=employee)
    return qs.filter(scope).distinct()


def _terms(query):
    words = re.findall(r"\w+", (query or "").lower())
    return list(dict.fromkeys(w for w in words if len(w) > 1))[:20]


def search(company, query, employee=None, top_k=None):
    """Hybrid search: full-text rank + vector similarity, merged by reciprocal rank. → [Chunk] with .score."""
    top_k = top_k or setting("ai.kb_top_k")
    base = usable_chunks(company, employee)
    ranked = {}
    terms = _terms(query)
    if terms:
        q = reduce(or_, [SearchQuery(t, config="simple") for t in terms])
        hits = list(
            base.annotate(rank=SearchRank(F("tsv"), q))
            .filter(rank__gt=0)
            .order_by("-rank")
            .values_list("id", flat=True)[: top_k * 4]
        )
        for pos, cid in enumerate(hits):
            ranked[cid] = ranked.get(cid, 0) + 1 / (60 + pos)
    current = embedding_model()
    if current and base.filter(embedding_model=current).exists():
        from apps.agents import usage
        from apps.providers.services import NoProviderAvailable, embed

        try:
            result = embed([query])
            usage.record(company.id, result, "embedding")
            vector = "[" + ",".join(f"{x:.7g}" for x in result["vectors"][0]) + "]"
            hits = list(
                base.filter(embedding_model=current)
                .annotate(distance=RawSQL("embedding <=> %s::vector", [vector]))
                .order_by("distance")
                .values_list("id", flat=True)[: top_k * 4]
            )
            for pos, cid in enumerate(hits):
                ranked[cid] = ranked.get(cid, 0) + 1 / (60 + pos)
        except NoProviderAvailable:
            pass
    best = sorted(ranked, key=ranked.get, reverse=True)[:top_k]
    chunks = {c.pk: c for c in Chunk.objects.filter(pk__in=best).select_related("source", "faq", "document")}
    out = []
    for cid in best:
        chunk = chunks[cid]
        chunk.score = ranked[cid]
        out.append(chunk)
    return out


def citation(chunk):
    """What a transcript shows for a used chunk (KB-11)."""
    return {
        "chunk": str(chunk.pk),
        "source": str(chunk.source_id),
        "source_title": chunk.source.title,
        "type": chunk.source.type,
        "title": chunk.metadata.get("title", ""),
        "url": chunk.metadata.get("url", ""),
        "faq": str(chunk.faq_id) if chunk.faq_id else "",
    }


def test_query(company, question, employee=None, user=None):
    """KB-09: answer a question from approved knowledge only and show the exact sources used."""
    from apps.agents import usage
    from apps.providers.services import NoProviderAvailable, chat

    question = (question or "").strip()
    if not question:
        raise ValidationError("Type a question.")
    chunks = search(company, question, employee)
    if not chunks:
        return {"answer": "", "found": False, "sources": []}
    context = "\n\n".join(f"[K{i}] {c.text}" for i, c in enumerate(chunks, 1))
    messages = [
        {
            "role": "system",
            "content": "Answer the question using only the knowledge below. Add the [K#] marker of every piece you "
            "use. If the knowledge does not contain the answer, reply exactly: NOT_FOUND\n\n"
            f"<knowledge>\n{context}\n</knowledge>",
        },
        {"role": "user", "content": question},
    ]
    try:
        result = chat("chat_dialog", messages)
    except NoProviderAvailable as exc:
        raise ValidationError(f"No AI provider is available: {exc}") from None
    usage.record(company.id, result, "chat_dialog")
    answer, used = split_citations(result["text"], chunks)
    found = "NOT_FOUND" not in answer
    return {
        "answer": answer if found else "",
        "found": found,
        "sources": [citation(c) for c in used] if found else [],
        "retrieved": [citation(c) for c in chunks],
    }


MARKER = re.compile(r"\s*\[K(\d+)\]")


def split_citations(text, chunks):
    """Strip [K#] markers from the answer and return (clean text, cited chunks)."""
    used = []
    for n in MARKER.findall(text or ""):
        i = int(n) - 1
        if 0 <= i < len(chunks) and chunks[i] not in used:
            used.append(chunks[i])
    return MARKER.sub("", text or "").strip(), used


# ------------------------------------------------------------------ unanswered questions (KB-10)
def normalize_question(text):
    return " ".join(re.findall(r"\w+", (text or "").lower()))[:300]


def log_unanswered(company, question, employee=None, conversation=None):
    key = normalize_question(question)
    if not key:
        return None
    item, created = UnansweredQuestion.objects.get_or_create(
        company=company,
        normalized_question=key,
        defaults={"example_text": question[:2000], "employee": employee, "conversation": conversation},
    )
    if not created:
        item.count, item.status = item.count + 1, UnansweredQuestion.OPEN
        item.conversation = conversation or item.conversation
        item.save(update_fields=["count", "status", "conversation", "last_seen_at"])
    return item


def resolve_unanswered(item, request=None):
    item.status = UnansweredQuestion.RESOLVED
    item.save(update_fields=["status", "last_seen_at"])
    record(request, "knowledge.unanswered_resolve", "unanswered", item.id, company=item.company)
    return item


# ------------------------------------------------------------------ scheduler (process_knowledge command)
def run_scheduled(now=None):
    """Queued / stuck sources, due re-syncs (KB-01) and chunks missing vectors of the current embedding model."""
    now = now or timezone.now()
    stuck = now - timedelta(minutes=30)
    with platform_context():
        due = list(
            Source.all_companies.filter(
                Q(status=Source.QUEUED)
                | Q(status=Source.PROCESSING, updated_at__lt=stuck)
                | Q(type=Source.URL, sync_schedule="daily", last_synced_at__lt=now - timedelta(days=1))
                | Q(type=Source.URL, sync_schedule="weekly", last_synced_at__lt=now - timedelta(days=7))
            ).values_list("pk", "company_id")
        )
        companies = set(Chunk.all_companies.values_list("company_id", flat=True).distinct())
    for pk, company_id in due:
        with company_context(company_id):
            process(pk)
    embedded = 0
    for company_id in companies:
        with company_context(company_id):
            embedded += embed_pending(company_id)
    return len(due), embedded


def strip_html(text):
    return strip_tags(text or "")
