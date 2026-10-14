"""Private, per-company file storage (TEN-03). Files are served only through short-lived signed URLs."""

import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.core import signing
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from django.utils.functional import LazyObject

SIGNING_SALT = "private-file"


class _PrivateStorage(LazyObject):
    def _setup(self):
        self._wrapped = FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


private_storage = _PrivateStorage()


def company_path(company_id, folder, filename):
    """tenants/<company_id>/<folder>/<random>.<ext> — the original name never becomes part of the path."""
    ext = PurePosixPath(filename).suffix.lower()
    return f"tenants/{company_id}/{folder}/{uuid.uuid4().hex}{ext}"


def signed_url(path, max_age=None):
    token = signing.dumps({"p": path}, salt=SIGNING_SALT)
    return reverse("core:private_file", args=[token])


def path_from_token(token, max_age):
    return signing.loads(token, salt=SIGNING_SALT, max_age=max_age)["p"]
