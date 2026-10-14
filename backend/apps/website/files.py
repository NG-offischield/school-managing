"""Files of the ISBREE contents (ADR 0032), decided by their CONTENT:

- images (PNG, JPEG, WebP): decoded by Pillow (dimensions checked before the
  pixels: decompression-bomb guard), orientation applied, then RE-ENCODED
  (JPEG, or PNG when transparent): EXIF / GPS / author metadata are dropped —
  important for photographs taken at school — and the largest side is reduced
  to WEBSITE_IMAGE_MAX_SIDE;
- documents: PDF only, readable, not encrypted, without active content
  (scripts, launch actions, embedded files);
- applications: Android APK SIGNED FOR RELEASE only. An APK is a zip with an
  AndroidManifest.xml and classes.dex; its signature is the v1 certificate in
  META-INF and/or the "APK Sig Block 42" (v2/v3). Unsigned APKs and APKs
  signed with the Android DEBUG certificate ("CN=Android Debug", what Gradle
  uses for debug builds) are refused: a debug build is never distributed.
  This is a guard, not a full signature verification — the release key
  itself is managed outside the application (see docs/isbree-web.md).

Everything is stored in the private storage under a random name; only views
that check publication and audience stream it.
"""

import hashlib
import io
import uuid
import zipfile
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from apps.communication.attachments import _clean_name, private_storage

_ACTIVE_PDF_MARKERS = (b"/JavaScript", b"/JS ", b"/JS(", b"/Launch", b"/EmbeddedFile", b"/RichMedia")
_IMAGE_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
_DEBUG_CERTIFICATE = b"Android Debug"
_SIGNING_BLOCK_MAGIC = b"APK Sig Block 42"


@dataclass
class CheckedFile:
    content: bytes
    mime_type: str
    extension: str
    name: str
    width: int = 0
    height: int = 0


def _refuse(message, code):
    raise ValidationError(message, code=code)


def _read(upload, limit, too_large_code):
    size = getattr(upload, "size", None) or 0
    if size <= 0:
        _refuse("Empty file.", "file_empty")
    if size > limit:
        _refuse("File too large.", too_large_code)
    upload.seek(0)
    data = upload.read(limit + 1)
    upload.seek(0)
    if len(data) > limit:  # never trust the declared size alone
        _refuse("File too large.", too_large_code)
    return data


def check_image(upload):
    data = _read(upload, settings.WEBSITE_IMAGE_MAX_BYTES, "image_too_large")
    is_webp = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if not (data.startswith(_IMAGE_SIGNATURES) or is_webp):
        _refuse("Only PNG, JPEG and WebP images are accepted.", "image_format_not_supported")
    limit = settings.WEBSITE_IMAGE_MAX_SIDE
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.size[0] > 12000 or probe.size[1] > 12000:
                _refuse("Image too large.", "image_too_large")
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)  # keep the visual orientation, drop EXIF
            image.load()
            image.thumbnail((limit, limit))
            out = io.BytesIO()
            transparent = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
            if transparent:
                image.save(out, format="PNG", optimize=True)
                mime, extension = "image/png", "png"
            else:
                image.convert("RGB").save(out, format="JPEG", quality=86, optimize=True, progressive=True)
                mime, extension = "image/jpeg", "jpg"
            width, height = image.size
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        _refuse("Unreadable image.", "image_corrupted")
    return CheckedFile(
        out.getvalue(), mime, extension, _clean_name(getattr(upload, "name", "") or "image"), width, height
    )


def check_document(upload):
    data = _read(upload, settings.WEBSITE_DOCUMENT_MAX_BYTES, "document_too_large")
    if not data.startswith(b"%PDF-"):
        _refuse("Only PDF documents are accepted.", "document_format_not_supported")
    if any(marker in data for marker in _ACTIVE_PDF_MARKERS):
        _refuse("PDF with active content (scripts, embedded files) is refused.", "document_active_content")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            _refuse("Encrypted PDF.", "document_encrypted")
        pages = len(reader.pages)
        if pages:
            reader.pages[0].mediabox  # noqa: B018 - parses the first page for real
    except ValidationError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, OSError):
        _refuse("Unreadable PDF.", "document_corrupted")
    if not 1 <= pages <= settings.WEBSITE_DOCUMENT_MAX_PAGES:
        _refuse("Too many pages.", "document_pages")
    return CheckedFile(data, "application/pdf", "pdf", _clean_name(getattr(upload, "name", "") or "document.pdf"))


def _signing_block(data):
    """Bytes of the APK Signing Block (v2/v3), or b"" when absent: it sits
    right before the zip central directory and ends with its magic."""
    position = data.rfind(_SIGNING_BLOCK_MAGIC)
    if position < 0:
        return b""
    end = position + len(_SIGNING_BLOCK_MAGIC)
    size = int.from_bytes(data[position - 8 : position], "little")
    start = max(0, end - size - 8)
    return data[start:end]


def check_apk(upload):
    data = _read(upload, settings.MOBILE_APP_MAX_BYTES, "apk_too_large")
    if not data.startswith(b"PK\x03\x04"):
        _refuse("This file is not an Android application (APK).", "apk_invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "AndroidManifest.xml" not in names or not any(n.startswith("classes") for n in names):
                _refuse("This file is not an Android application (APK).", "apk_invalid")
            certificates = [
                archive.read(n)
                for n in names
                if n.startswith("META-INF/") and n.rsplit(".", 1)[-1].upper() in ("RSA", "DSA", "EC")
            ]
    except ValidationError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError, KeyError):
        _refuse("This file is not an Android application (APK).", "apk_invalid")
    block = _signing_block(data)
    if not certificates and not block:
        _refuse("Unsigned APK: only a signed release build can be distributed.", "apk_unsigned")
    if any(_DEBUG_CERTIFICATE in c for c in certificates) or _DEBUG_CERTIFICATE in block:
        _refuse("Debug build: only a signed release build can be distributed.", "apk_debug_build")
    return CheckedFile(
        data, "application/vnd.android.package-archive", "apk", _clean_name(getattr(upload, "name", "") or "app.apk")
    )


def store(checked, school, folder):
    """Write to the private storage; returns (path, sha256, size)."""
    path = f"website/{school.pk.hex}/{folder}/{uuid.uuid4().hex}.{checked.extension}"
    saved = private_storage().save(path, ContentFile(checked.content))
    return saved, hashlib.sha256(checked.content).hexdigest(), len(checked.content)


def open_file(path):
    return private_storage().open(path, "rb")
