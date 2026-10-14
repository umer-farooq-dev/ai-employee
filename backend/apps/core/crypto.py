"""Field-level encryption (SEC-07) for credentials, tokens and 2FA secrets.

The master key is an infrastructure secret (FIELD_ENCRYPTION_KEY in the server environment),
never stored in the database.
"""

import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import models


def _fernet():
    # Any string works as the configured key; it is stretched to the 32-byte key Fernet needs.
    digest = hashlib.sha256(settings.FIELD_ENCRYPTION_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


class EncryptedTextField(models.TextField):
    """Stores ciphertext in the database, gives plaintext to Python code."""

    def from_db_value(self, value, expression, connection):
        return value if value in (None, "") else decrypt(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return value if value in (None, "") else encrypt(value)
