"""Render and send emails from the database templates, wrapped in the General Settings email header / footer."""

from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template
from django.utils.html import strip_tags

from apps.platform_config import services as config

from .models import EmailTemplate


def branding_context():
    return {
        "platform_name": config.get("general.platform_name"),
        "tagline": config.get("general.tagline"),
        "support_email": config.get("contact.support_email"),
    }


def team_recipients():
    """Platform team inbox for registrations and enquiries (General Settings), falling back to the support email."""
    return config.get("contact.team_notify_emails") or [e for e in [config.get("contact.support_email")] if e]


def from_email():
    return f"{config.get('email.sender_name')} <{config.get('email.sender_address')}>"


def render(key, context):
    """Returns (subject, html, text) or None when no active template exists for the key."""
    tpl = EmailTemplate.objects.filter(key=key, is_active=True).first()
    if not tpl:
        return None
    ctx = Context({**branding_context(), **context})
    subject = " ".join(Template(tpl.subject).render(ctx).split())
    body = Template(tpl.body_html).render(ctx)
    html = f"{config.get('email.header_html')}{body}{config.get('email.footer_html')}"
    return subject, html, strip_tags(html)


def send(key, to, context, attachments=()) -> bool:
    """attachments: [(file name, bytes)]."""
    rendered = render(key, context)
    if not rendered:
        return False
    subject, html, text = rendered
    msg = EmailMultiAlternatives(subject, text, from_email(), [to])
    msg.attach_alternative(html, "text/html")
    for name, content in attachments:
        msg.attach(name, content)
    msg.send()
    return True
