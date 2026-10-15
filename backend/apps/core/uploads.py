"""Validated uploads. Size and allowed types come from Super Admin → Security (SEC-11 basics in Phase 1)."""

import uuid
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage

from apps.platform_config import services as config

IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "svg", "ico", "gif"}


def validate_upload(upload, images_only=False):
    ext = PurePosixPath(upload.name).suffix.lower().lstrip(".")
    allowed = set(config.get("security.upload_allowed_types"))
    if images_only:
        allowed &= IMAGE_TYPES
    if ext not in allowed:
        raise ValidationError(f"File type .{ext} is not allowed. Allowed: {', '.join(sorted(allowed))}.")
    max_mb = config.get("security.upload_max_mb")
    if upload.size > max_mb * 1024 * 1024:
        raise ValidationError(f"File is larger than {max_mb} MB.")
    return ext


def save_public(upload, folder, images_only=True) -> str:
    """Store a public file (logos, website images) and return its URL. Original names never reach the path."""
    ext = validate_upload(upload, images_only=images_only)
    path = default_storage.save(f"{folder}/{uuid.uuid4().hex}.{ext}", upload)
    return default_storage.url(path)


def scan(data: bytes):
    """SEC-11 malware scan through ClamAV (clamd INSTREAM). CLAMAV_ADDRESS (host:port) is infrastructure (.env);
    when it is empty the scan is skipped — the launch checklist (Phase 8) requires it on staging / production."""
    import socket
    import struct

    from django.conf import settings

    address = getattr(settings, "CLAMAV_ADDRESS", "")
    if not address:
        return "not_scanned"
    host, _, port = address.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=30) as sock:
            sock.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), 64 * 1024):
                part = data[i : i + 64 * 1024]
                sock.sendall(struct.pack("!L", len(part)) + part)
            sock.sendall(struct.pack("!L", 0))
            reply = sock.recv(4096).decode(errors="replace").strip("\0 \n")
    except OSError as exc:
        raise ValidationError(f"The virus scanner is not reachable ({exc}). Try again later.") from None
    if not reply.endswith("OK"):
        raise ValidationError("This file failed the virus scan and was rejected.")
    return "clean"
