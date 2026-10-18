"""Company panel: knowledge base (KB-01 … KB-11). Logic lives in apps.knowledge.services."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.agents.models import AIEmployee
from apps.knowledge import services as kb
from apps.knowledge.models import FAQ, Source, UnansweredQuestion
from apps.platform_config.services import get as setting
from apps.providers import languages
from apps.rbac.services import has_perm

from .company_views import _errors, company_perm


def _perm(request, key):
    if not has_perm(request.user, key, request.company):
        raise PermissionDenied


def _flags(request):
    return {
        "can_manage": has_perm(request.user, "knowledge.manage", request.company),
        "can_approve": has_perm(request.user, "knowledge.approve", request.company),
    }


FORM_KEYS = ("title", "uri", "body", "category")


def _form_values(post):
    return {k: post.get(k, "") for k in FORM_KEYS}


def _source_data(request):
    post = request.POST
    data = {
        k: post.get(k)
        for k in ("type", "title", "category", "uri", "body", "sync_schedule", "max_pages", "max_depth")
        if k in post
    }
    for key in ("include", "exclude"):
        if key in post:
            data[key] = post.get(key, "")
    if post.get("scope") == "selected":
        data["employees"] = post.getlist("employees")
    elif "scope" in post:
        data["employees"] = []
    return data


@company_perm("knowledge.view")
def index(request):
    """Sources (KB-01 … KB-08) with approval actions."""
    if request.method == "POST":
        source = get_object_or_404(Source, pk=request.POST.get("source"), company=request.company)
        op = request.POST.get("op")
        try:
            if op in ("approve", "unapprove"):
                _perm(request, "knowledge.approve")
                kb.approve(source, op == "approve", request.user, request)
                messages.success(
                    request, f"“{source.title}” {'approved' if op == 'approve' else 'moved back to draft'}."
                )
            elif op == "reprocess":
                _perm(request, "knowledge.manage")
                kb.reprocess(source, request)
                messages.success(request, f"“{source.title}” is being processed again.")
            elif op == "delete":
                _perm(request, "knowledge.manage")
                kb.delete_source(source, request)
                messages.success(request, "Deleted — the AI no longer uses it.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect(request.get_full_path())
    qs = (
        Source.objects.filter(company=request.company)
        .prefetch_related("employees")
        .annotate(n_chunks=Count("chunks", distinct=True), n_faqs=Count("faqs", distinct=True))
    )
    for key in ("type", "approval", "status"):
        if request.GET.get(key):
            qs = qs.filter(**{key: request.GET[key]})
    return render(
        request,
        "panel/company/knowledge/index.html",
        {
            "sources": qs,
            "types": Source.TYPES,
            "p": request.GET,
            "open_unanswered": UnansweredQuestion.objects.filter(company=request.company, status="open").count(),
            "tab": "sources",
            **_flags(request),
        },
    )


@company_perm("knowledge.manage")
def source_new(request):
    kind = request.POST.get("type") or request.GET.get("type") or Source.URL
    if kind not in dict(Source.TYPES):
        kind = Source.URL
    if request.method == "POST":
        try:
            source = kb.create_source(
                request.company, _source_data(request), request.FILES.get("file"), request.user, request
            )
            messages.success(request, f"“{source.title}” added. Approve it when it is ready so the AI can use it.")
            return redirect("panel:kb_source", pk=source.pk)
        except ValidationError as exc:
            _errors(request, exc)
    return render(
        request,
        "panel/company/knowledge/source_form.html",
        {
            "kind": kind,
            "types": Source.TYPES,
            "source": None,
            "employees": AIEmployee.objects.filter(company=request.company).exclude(status=AIEmployee.ARCHIVED),
            "selected": request.POST.getlist("employees") or request.GET.getlist("employee"),
            "crawl_max_pages": setting("knowledge.crawl_max_pages"),
            "crawl_max_depth": setting("knowledge.crawl_max_depth"),
            "sync": Source.SYNC,
            "data": _form_values(request.POST),
            "tab": "sources",
        },
    )


@company_perm("knowledge.view")
def source_detail(request, pk):
    source = get_object_or_404(Source, pk=pk, company=request.company)
    if request.method == "POST":
        op = request.POST.get("op", "save")
        try:
            if op == "save":
                _perm(request, "knowledge.manage")
                kb.update_source(source, _source_data(request), request.user, request)
                messages.success(request, "Saved.")
            elif op in ("faq_add", "faq_save"):
                _perm(request, "knowledge.manage")
                faq = get_object_or_404(FAQ, pk=request.POST.get("faq"), source=source) if op == "faq_save" else None
                kb.save_faq(source, request.POST, faq, request)
                messages.success(request, "FAQ saved — approve it so the AI can use it.")
            elif op in ("faq_approve", "faq_unapprove"):
                _perm(request, "knowledge.approve")
                faq = get_object_or_404(FAQ, pk=request.POST.get("faq"), source=source)
                kb.approve_faq(faq, op == "faq_approve", request)
            elif op == "faq_delete":
                _perm(request, "knowledge.manage")
                kb.delete_faq(get_object_or_404(FAQ, pk=request.POST.get("faq"), source=source), request)
            elif op == "faq_import":
                _perm(request, "knowledge.manage")
                if not request.FILES.get("file"):
                    raise ValidationError("Choose a .csv or .xlsx file.")
                count = kb.import_faqs(source, request.FILES["file"], request)
                messages.success(request, f"{count} FAQs imported as drafts.")
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("panel:kb_source", pk=source.pk)
    return render(
        request,
        "panel/company/knowledge/source_form.html",
        {
            "kind": source.type,
            "source": source,
            "types": Source.TYPES,
            "employees": AIEmployee.objects.filter(company=request.company).exclude(status=AIEmployee.ARCHIVED),
            "selected": [str(e.pk) for e in source.employees.all()],
            "documents": source.documents.annotate(n=Count("chunks"))[:200],
            "faqs": source.faqs.all() if source.type == Source.FAQ else [],
            "languages": languages.choices(),
            "crawl_max_pages": setting("knowledge.crawl_max_pages"),
            "crawl_max_depth": setting("knowledge.crawl_max_depth"),
            "sync": Source.SYNC,
            "data": _form_values({}),
            "tab": "sources",
            **_flags(request),
        },
    )


@company_perm("knowledge.view")
def test(request):
    """KB-09: ask a question, see the answer and the exact sources."""
    result, question, employee_id = None, "", ""
    if request.method == "POST":
        question, employee_id = request.POST.get("question", ""), request.POST.get("employee", "")
        employee = AIEmployee.objects.filter(company=request.company, pk=employee_id).first() if employee_id else None
        try:
            result = kb.test_query(request.company, question, employee, request.user)
        except ValidationError as exc:
            _errors(request, exc)
    return render(
        request,
        "panel/company/knowledge/test.html",
        {
            "result": result,
            "question": question,
            "employee_id": employee_id,
            "employees": AIEmployee.objects.filter(company=request.company).exclude(status=AIEmployee.ARCHIVED),
            "tab": "test",
        },
    )


@company_perm("knowledge.view")
def unanswered(request):
    """KB-10: grouped and counted questions the AI could not answer."""
    if request.method == "POST":
        _perm(request, "knowledge.manage")
        item = get_object_or_404(UnansweredQuestion, pk=request.POST.get("item"), company=request.company)
        kb.resolve_unanswered(item, request)
        messages.success(request, "Marked as resolved.")
        return redirect("panel:kb_unanswered")
    status = request.GET.get("status") or UnansweredQuestion.OPEN
    faq_sources = Source.objects.filter(company=request.company, type=Source.FAQ)
    return render(
        request,
        "panel/company/knowledge/unanswered.html",
        {
            "items": UnansweredQuestion.objects.filter(company=request.company, status=status).select_related(
                "employee"
            )[:200],
            "status": status,
            "faq_source": faq_sources.filter(~Q(category="template")).first() or faq_sources.first(),
            "tab": "unanswered",
            **_flags(request),
        },
    )
