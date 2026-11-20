"""Avatar uploads: accept only real, reasonably small JPEG/PNG/WebP images and store a clean copy.

An uploaded file is untrusted input that ends up served from our storage, so it is never stored as
sent: the image is decoded and re-encoded, which drops EXIF metadata (GPS position, camera serial) and
anything hidden in the file that is not pixel data, and it is saved under a random name so the
uploader's file name (and any trick in it) never reaches the filesystem or a URL.
"""

import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import serializers

MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000  # e.g. 4000 x 4000
ALLOWED_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def avatar_upload_path(instance, filename):
    """Random file name, keeping only the (already validated) extension."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "img"
    if extension not in set(ALLOWED_FORMATS.values()):
        extension = "img"
    return f"avatars/{uuid.uuid4().hex}.{extension}"


def clean_avatar(upload):
    """Validate an uploaded avatar and return a re-encoded copy (a ContentFile with a random name)."""
    if upload.size > MAX_AVATAR_BYTES:
        raise serializers.ValidationError(f"The image must be at most {MAX_AVATAR_BYTES // (1024 * 1024)} MB.")
    try:
        upload.seek(0)
        image = Image.open(upload)
        image_format = image.format
        if image_format not in ALLOWED_FORMATS:
            raise serializers.ValidationError("Only JPEG, PNG or WebP images are allowed.")
        # Size is known from the header, before any pixel data is decoded: refuse decompression bombs early.
        if image.width * image.height > MAX_AVATAR_PIXELS:
            raise serializers.ValidationError("The image dimensions are too large.")
        image = ImageOps.exif_transpose(image)  # honour the camera orientation before metadata is dropped
        if image_format == "JPEG" and image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buffer = BytesIO()
        save_options = {"quality": 90, "optimize": True} if image_format == "JPEG" else {}
        image.save(buffer, format=image_format, **save_options)
    except serializers.ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise serializers.ValidationError("Upload a valid image file.") from None
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.{ALLOWED_FORMATS[image_format]}")
