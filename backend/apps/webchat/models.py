"""M16 Website Chat Widget (CHAT-01 … CHAT-07): one widget per AI Employee.

The public key in the website snippet is the only thing a visitor's browser sends; the company and the AI Employee are
resolved from it on the server (TEN-01). Empty appearance fields fall back to the AI Employee, the language phrases
(Super Admin → Languages & Voices) and General Settings, so nothing in the widget is fixed in code.
"""

import secrets

from django.db import models

from apps.tenancy.models import TenantModel


def new_key():
    return "wk_" + secrets.token_urlsafe(18)


class ChatWidget(TenantModel):
    POSITIONS = [("right", "Bottom right"), ("left", "Bottom left")]
    ACTIONS = [
        ("enquiry", "Send an enquiry"),
        ("callback", "Request a callback"),
        ("book", "Book an appointment"),
        ("human", "Talk to a person"),
    ]

    employee = models.OneToOneField("agents.AIEmployee", on_delete=models.CASCADE, related_name="widget")
    key = models.CharField(max_length=40, unique=True, default=new_key, help_text="Public key in the website snippet")
    is_enabled = models.BooleanField(default=True)
    title = models.CharField(max_length=80, blank=True, help_text="Empty = the AI Employee's name")
    subtitle = models.CharField(max_length=120, blank=True, help_text="Empty = the company name")
    launcher_text = models.JSONField(default=dict, blank=True, help_text="{language: text}; empty = language phrase")
    greetings = models.JSONField(default=dict, blank=True, help_text="{language: text}; empty = AI Employee greeting")
    avatar = models.CharField(max_length=500, blank=True, help_text="Image URL; empty = the AI Employee's avatar")
    color = models.CharField(max_length=7, blank=True, help_text="Empty = platform primary colour")
    position = models.CharField(max_length=5, choices=POSITIONS, default="right")
    language = models.CharField(max_length=10, blank=True, help_text="Opening language; empty = employee primary")
    allowed_domains = models.JSONField(default=list, blank=True, help_text="Websites that may show the widget")
    actions = models.JSONField(default=dict, blank=True, help_text="{action: true/false}; missing = on")

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Widget of {self.employee_id}"

    def action_on(self, key):
        return bool((self.actions or {}).get(key, True))
