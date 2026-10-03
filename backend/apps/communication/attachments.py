"""Private attachments (spec §9: "never public by URL alone", ADR 0015).

- type decided by the file's CONTENT (magic bytes, image decoded by Pillow),
  never by the client's name or Content-Type: a renamed executable is refused;
- size limited by the school (SchoolConfiguration.default_attachment_limit_mb)
  under a global ceiling (settings.ATTACHMENT_MAX_BYTES);
- stored through Django's storage abstraction (`private` storage, no public
  route) under a random name; the original name is only metadata;
- served only by views that check the permission first (api.py).
"""

import hashlib
import re
import unicodedata
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.utils import timezone
from PIL import Image

MAX_FILES_PER_ITEM = 5
_SIGNATURES = [
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
]


def private_storage():
    return storages["private"]


def _limit(school):
    school_limit = school.configuration.default_attachment_limit_mb * 1024 * 1024
    return min(school_limit, settings.ATTACHMENT_MAX_BYTES)


def _clean_name(name):
    name = unicodedata.normalize("NFC", str(name or "fichier")).replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip() or "fichier"
    return name[:255]


def inspect(upload, school):
    """Validate one uploaded file; returns (mime_type, extension)."""
    size = upload.size or 0
    if size <= 0:
        raise ValidationError("Empty file.", code="attachment_empty")
    if size > _limit(school):
        raise ValidationError("File too large.", code="attachment_too_large", params={"max_bytes": _limit(school)})
    upload.seek(0)
    head = upload.read(16)
    upload.seek(0)
    detected = next(((mime, ext) for magic, mime, ext in _SIGNATURES if head.startswith(magic)), None)
    if detected is None:
        raise ValidationError("Only PDF, PNG and JPEG files are accepted.", code="attachment_type_not_allowed")
    mime, ext = detected
    if mime.startswith("image/"):
        try:
            with Image.open(upload) as image:
                image.verify()  # decodes the structure: a fake image is refused
        except Exception:
            raise ValidationError("Corrupted image.", code="attachment_corrupted") from None
        finally:
            upload.seek(0)
    return mime, ext


def validate_all(uploads, school):
    uploads = list(uploads or [])
    if len(uploads) > MAX_FILES_PER_ITEM:
        raise ValidationError(f"At most {MAX_FILES_PER_ITEM} files.", code="too_many_attachments")
    return [(upload, *inspect(upload, school)) for upload in uploads]


def store(model, inspected, *, school, uploaded_by, **owner):
    """Write validated files to the private storage and record them.
    `owner` = message=... or complaint=..."""
    created = []
    storage = private_storage()
    for upload, mime, ext in inspected:
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        path = f"communication/{school.pk.hex}/{timezone.now():%Y/%m}/{stored_name}"
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
        saved_path = storage.save(path, upload)
        try:
            created.append(
                model.objects.create(
                    school=school,
                    original_name=_clean_name(upload.name),
                    stored_name=stored_name,
                    mime_type=mime,
                    size_bytes=upload.size,
                    storage_path=saved_path,
                    sha256=digest.hexdigest(),
                    uploaded_by=uploaded_by,
                    **owner,
                )
            )
        except Exception:
            storage.delete(saved_path)  # no orphan file when the row is refused
            raise
    return created


def open_file(attachment):
    return private_storage().open(attachment.storage_path, "rb")


def serialize(attachment, kind):
    return {
        "id": str(attachment.pk),
        "name": attachment.original_name,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
        "download_url": f"/api/v1/attachments/{kind}/{attachment.pk}/download/",
    }
