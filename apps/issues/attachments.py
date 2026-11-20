"""Issue attachments: what may be uploaded, and how it is stored.

The type is decided from the file's first bytes, never from its name or the browser's Content-Type, and
the name's extension must agree with it, so an HTML page renamed to .png is refused. Only formats a
browser cannot execute are accepted (no HTML, SVG or scripts), files are stored under a random name
outside any public URL, and they are only ever sent back through the API, as downloads.
"""

import os
import re
import unicodedata
import uuid

from django.conf import settings
from rest_framework import serializers

MAX_ATTACHMENTS_PER_ISSUE = 20
TEXT_EXTENSIONS = {"txt", "md", "csv", "log", "json"}
KINDS = {
    "png": ("image/png", {"png"}),
    "jpeg": ("image/jpeg", {"jpg", "jpeg"}),
    "gif": ("image/gif", {"gif"}),
    "webp": ("image/webp", {"webp"}),
    "pdf": ("application/pdf", {"pdf"}),
    "text": ("text/plain; charset=utf-8", TEXT_EXTENSIONS),
}


def attachment_upload_path(instance, filename):
    return f"attachments/{uuid.uuid4().hex}"


def sniff(head):
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if b"\x00" not in head:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as error:
            # A multi-byte character cut off at the end of the sample is still text.
            if error.start < len(head) - 4:
                return None
        return "text"
    return None


def clean_name(name):
    name = os.path.basename(name.replace("\\", "/"))
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    if len(name) > 120:
        stem, dot, extension = name.rpartition(".")
        name = (stem[: 119 - len(extension)] + dot + extension) if dot else name[:120]
    return name or "file"


def check_upload(upload):
    """(clean file name, content type) for an acceptable upload; a validation error otherwise."""
    if upload.size > settings.ATTACHMENT_MAX_BYTES:
        raise serializers.ValidationError(f"Files can be at most {settings.ATTACHMENT_MAX_BYTES // (1024 * 1024)} MB.")
    if upload.size == 0:
        raise serializers.ValidationError("The file is empty.")
    name = clean_name(upload.name or "")
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    upload.seek(0)
    kind = sniff(upload.read(8192))
    upload.seek(0)
    if kind is None or extension not in KINDS[kind][1]:
        raise serializers.ValidationError("Only images (PNG, JPEG, GIF, WebP), PDF and plain text files can be attached.")
    return name, KINDS[kind][0]
