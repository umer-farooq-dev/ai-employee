"""Company panel: website chat widget settings (CHAT-01 / CHAT-02 / CHAT-05) and the shared inbox (WA-06, CHAT-06).

Views read the request and call apps.webchat.services / apps.agents.inbox; the inbox page talks to the REST API for
live updates, replies and actions.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.agents.models import AIEmployee, Conversation
from apps.api.views_webchat import VIEWS, inbox_queryset
from apps.core.uploads import save_public
from apps.crm.services import members
from apps.industries import services as templates
from apps.platform_config.services import get as setting
from apps.rbac.services import has_perm
from apps.webchat import services as chat
from apps.webchat.models import ChatWidget

from .ai_views import _lang_names
from .company_views import _errors, company_perm


def _employee(request, pk):
    return get_object_or_404(AIEmployee, pk=pk, company=request.company)


def _widget_post(request, widget):
    post, codes = request.POST, widget.employee.languages or [widget.employee.primary_language]
    data = {
        "is_enabled": bool(post.get("is_enabled")),
        "title": post.get("title", ""),
        "subtitle": post.get("subtitle", ""),
        "color": post.get("color", "") if post.get("own_color") else "",
        "position": post.get("position", "right"),
        "language": post.get("language", ""),
        "launcher_text": {c: post.get(f"launcher_{c}", "") for c in codes},
        "greetings": {c: post.get(f"greeting_{c}", "") for c in codes},
        "allowed_domains": post.get("allowed_domains", ""),
        "actions": {k: bool(post.get(f"action_{k}")) for k, _ in ChatWidget.ACTIONS},
    }
    if request.FILES.get("avatar"):
        data["avatar"] = save_public(request.FILES["avatar"], "avatars")
    elif post.get("remove_avatar"):
        data["avatar"] = ""
    return data


@company_perm("ai_employees.view")
def widget_settings(request, pk):
    employee = _employee(request, pk)
    widget = chat.widget_for(employee)
    can_manage = has_perm(request.user, "ai_employees.manage", request.company)
    if request.method == "POST":
        if not can_manage:
            raise Http404
        try:
            if request.POST.get("op") == "regenerate":
                chat.save_widget(widget, {"regenerate_key": True}, request.user, request)
                messages.success(request, "New key created: replace the code on your website.")
            else:
                chat.save_widget(widget, _widget_post(request, widget), request.user, request)
                messages.success(request, "Website chat saved.")
            return redirect("panel:widget", pk=employee.pk)
        except ValidationError as exc:
            _errors(request, exc)
    from apps.agents import runtime
    from apps.providers import languages

    codes = _lang_names(employee.languages or [employee.primary_language])
    return render(
        request,
        "panel/company/chat/widget.html",
        {
            "employee": employee,
            "widget": widget,
            "can_manage": can_manage,
            "snippet": chat.snippet(widget),
            "languages": [
                {
                    "code": c,
                    "name": n,
                    "launcher": (widget.launcher_text or {}).get(c, ""),
                    "launcher_default": languages.text(c, "chat_launcher"),
                    "greeting": (widget.greetings or {}).get(c, ""),
                    "greeting_default": runtime.greeting(employee, c),
                }
                for c, n in codes
            ],
            "actions": [(k, label, widget.action_on(k)) for k, label in ChatWidget.ACTIONS],
            "platform_color": setting("general.color_primary"),
            "require_domains": setting("chat.require_allowed_domains"),
        },
    )


@company_perm("ai_employees.view")
def widget_preview(request, pk):
    """A plain page with the real snippet, so the company sees the widget as visitors will."""
    employee = _employee(request, pk)
    return render(
        request,
        "panel/company/chat/preview.html",
        {"employee": employee, "widget": chat.widget_for(employee), "script": chat.script_url()},
    )


# ------------------------------------------------------------------ shared inbox
VIEW_LABELS = [
    ("open", "Open"),
    ("waiting", "Waiting for a person"),
    ("mine", "Mine"),
    ("ai", "AI answering"),
    ("ended", "Ended"),
]


def _list(request):
    view = request.GET.get("view") if request.GET.get("view") in VIEWS else "open"
    q = request.GET.get("q", "").strip()
    rows = list(inbox_queryset(request, view, request.GET.get("channel", ""), q)[:50])
    # ponytail: three counts per page view; cache them if the inbox gets heavy
    counts = {k: inbox_queryset(request, k).count() for k in ("open", "waiting", "mine")}
    views = [(k, label, counts.get(k)) for k, label in VIEW_LABELS]
    return {"rows": rows, "view": view, "q": q, "views": views}


@company_perm("conversations.view")
def inbox_list(request):
    return render(request, "panel/company/chat/inbox.html", {**_list(request), "conv": None})


@company_perm("conversations.view")
def inbox_detail(request, pk):
    conv = get_object_or_404(
        Conversation.objects.select_related("employee", "lead__status", "assigned_user"),
        pk=pk,
        company=request.company,
        channel__in=Conversation.CHAT_CHANNELS,
        is_test=False,
    )
    defs = {d.key: d.label for d in templates.fields_for(request.company, "lead")}
    return render(
        request,
        "panel/company/chat/inbox.html",
        {
            **_list(request),
            "conv": conv,
            "can_answer": has_perm(request.user, "handoffs.receive", request.company),
            "team": [u for u in members(request.company) if has_perm(u, "handoffs.receive", request.company)],
            "field_labels": defs,
            "handoff": conv.handoffs.order_by("-created_at").first(),
            "poll_seconds": setting("chat.poll_seconds"),
            "timezone": request.company.timezone or setting("locale.timezone"),
            "wa_templates": _wa_templates(request, conv),
        },
    )


def _wa_templates(request, conv):
    """WhatsApp outside the 24-hour window: the approved templates the team can send instead."""
    if conv.channel != "whatsapp":
        return []
    from apps.whatsapp.models import Template

    return list(
        Template.objects.filter(company=request.company, status=Template.APPROVED).exclude(
            header_type__in=["image", "document"]
        )
    )
