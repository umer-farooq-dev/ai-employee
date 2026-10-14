"""Current-company context (TEN-01 / TEN-02).

The company is resolved from a trusted source only (signed-in membership now; dialled number, WhatsApp number and
widget key in later phases) — never from user input or AI output. The same value is pushed to PostgreSQL for
row-level security.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connection

_company_id: ContextVar = ContextVar("company_id", default=None)
_bypass: ContextVar = ContextVar("tenant_bypass", default=False)


class TenantContextMissing(Exception):
    """Raised when tenant data is queried without a company context (fail closed)."""


def current_company_id():
    return _company_id.get()


def bypass_active():
    return _bypass.get()


def _push_to_db(company_id, bypass):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.company_id', %s, false), set_config('app.bypass_rls', %s, false)",
            [str(company_id or ""), "on" if bypass else ""],
        )


def activate(company_id=None, bypass=False):
    """Set the context for this request / task. Returns tokens for deactivate()."""
    tokens = (_company_id.set(company_id), _bypass.set(bypass))
    if connection.vendor == "postgresql":
        _push_to_db(company_id, bypass)
    return tokens


def deactivate(tokens):
    _company_id.reset(tokens[0])
    _bypass.reset(tokens[1])
    if connection.vendor == "postgresql":
        _push_to_db(_company_id.get(), _bypass.get())


@contextmanager
def company_context(company_id):
    tokens = activate(company_id)
    try:
        yield
    finally:
        deactivate(tokens)


@contextmanager
def platform_context():
    """Explicit cross-company access for platform staff and system jobs. Use only in Super Admin / platform code."""
    tokens = activate(None, bypass=True)
    try:
        yield
    finally:
        deactivate(tokens)
