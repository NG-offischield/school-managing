"""Validation and private storage of imported school plan files.

Accepted (first scope): PDF, PNG, JPEG — decided by the file's CONTENT,
never by its name or the client's Content-Type:
- PDF: "%PDF-" signature, then opened with pypdf: readable, not encrypted,
  1..SCHOOL_PLAN_MAX_PDF_PAGES pages, and without active content
  (JavaScript, launch actions, embedded files) — a plan only needs drawings;
- PNG / JPEG: decoded by Pillow (dimensions checked BEFORE decoding the
  pixels: decompression-bomb guard), then RE-ENCODED: EXIF / text chunks
  (GPS position, software, author...) are dropped, pixels kept at full
  resolution (no 800 px reduction as for photos: a plan needs its details).

Refused with a stable code: SVG (may embed scripts), DWG / DXF (no CAD engine
here — export the plan to PDF or PNG from the architecture software), any
other content, a name whose extension contradicts the content, oversized
files, malformed files.

Stored in the `private` storage (no public route) under a random name; only
the views of plans_api.py stream them, after a permission check.
"""

import hashlib
import io
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from apps.communication.attachments import _clean_name, private_storage

PDF, PNG, JPEG = "application/pdf", "image/png", "image/jpeg"
_SIGNATURES = [(b"%PDF-", PDF, "pdf"), (b"\x89PNG\r\n\x1a\n", PNG, "png"), (b"\xff\xd8\xff", JPEG, "jpg")]
_EXTENSIONS = {PDF: {"pdf"}, PNG: {"png"}, JPEG: {"jpg", "jpeg"}}
_REFUSED_EXTENSIONS = {"svg", "svgz", "dwg", "dxf", "dwf"}
_ACTIVE_PDF_MARKERS = (b"/JavaScript", b"/JS ", b"/JS(", b"/Launch", b"/EmbeddedFile", b"/RichMedia")


@dataclass
class CheckedPlanFile:
    content: bytes  # what is stored (re-encoded for images, original for PDF)
    mime_type: str
    extension: str
    original_name: str
    width: int | None = None
    height: int | None = None
    page_count: int | None = None


def _refuse(message, code, **params):
    raise ValidationError(message, code=code, params=params or None)


def _extension(name):
    name = _clean_name(name)
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def check(upload):
    """Validate an uploaded plan file; returns a CheckedPlanFile (nothing stored)."""
    name = _clean_name(getattr(upload, "name", "") or "plan")
    extension = _extension(name)
    if extension in _REFUSED_EXTENSIONS:
        _refuse(
            "SVG, DWG and DXF are not accepted: export the plan to PDF or PNG from the drawing software.",
            "plan_format_not_supported",
            extension=extension,
        )
    size = getattr(upload, "size", None) or 0
    if size <= 0:
        _refuse("Empty file.", "plan_file_empty")
    if size > settings.SCHOOL_PLAN_MAX_BYTES:
        _refuse("File too large.", "plan_file_too_large", max_bytes=settings.SCHOOL_PLAN_MAX_BYTES)
    upload.seek(0)
    data = upload.read(settings.SCHOOL_PLAN_MAX_BYTES + 1)
    upload.seek(0)
    if len(data) > settings.SCHOOL_PLAN_MAX_BYTES:  # never trust the declared size alone
        _refuse("File too large.", "plan_file_too_large", max_bytes=settings.SCHOOL_PLAN_MAX_BYTES)
    detected = next(((mime, ext) for magic, mime, ext in _SIGNATURES if data.startswith(magic)), None)
    if detected is None:
        _refuse("Only PDF, PNG and JPEG plans are accepted.", "plan_format_not_supported", extension=extension)
    mime, stored_ext = detected
    if extension and extension not in _EXTENSIONS[mime]:
        _refuse("The file name does not match its content.", "plan_extension_mismatch", extension=extension)
    if mime == PDF:
        return _check_pdf(data, name)
    return _check_image(data, name, mime, stored_ext)


def _check_pdf(data, name):
    if any(marker in data for marker in _ACTIVE_PDF_MARKERS):
        _refuse("PDF with active content (scripts, embedded files) is refused.", "plan_pdf_active_content")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            _refuse("Encrypted PDF: export it without password.", "plan_pdf_encrypted")
        pages = len(reader.pages)
        if pages:
            reader.pages[0].mediabox  # noqa: B018 - parses the first page for real
    except ValidationError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, OSError):
        _refuse("Unreadable PDF.", "plan_file_corrupted")
    if not 1 <= pages <= settings.SCHOOL_PLAN_MAX_PDF_PAGES:
        _refuse("Too many pages for a plan.", "plan_pdf_pages", max_pages=settings.SCHOOL_PLAN_MAX_PDF_PAGES)
    return CheckedPlanFile(data, PDF, "pdf", name, page_count=pages)


def _check_image(data, name, mime, extension):
    limit = settings.SCHOOL_PLAN_MAX_IMAGE_SIDE
    try:
        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size  # header only: no pixel decoded yet
            if width > limit or height > limit:
                _refuse("Image too large.", "plan_image_too_large", max_side=limit)
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)  # keep the visual orientation, drop EXIF
            image.load()
            width, height = image.size
            out = io.BytesIO()
            if mime == PNG:
                image.save(out, format="PNG", optimize=True)  # no text / EXIF chunks copied
            else:
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.save(out, format="JPEG", quality=92, optimize=True)  # no EXIF
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        _refuse("Unreadable image.", "plan_file_corrupted")
    return CheckedPlanFile(out.getvalue(), mime, extension, name, width=width, height=height)


def store(checked, school):
    """Write the checked file to the private storage; returns (path, sha256, size)."""
    stored_name = f"{uuid.uuid4().hex}.{checked.extension}"
    path = f"plans/{school.pk.hex}/{stored_name}"
    saved = private_storage().save(path, ContentFile(checked.content))
    return saved, stored_name, hashlib.sha256(checked.content).hexdigest(), len(checked.content)


def open_file(version):
    return private_storage().open(version.storage_path, "rb")


def delete_file(path):
    private_storage().delete(path)
