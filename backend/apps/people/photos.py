"""Student photo upload: validation and normalisation (ADR 0018).

Why re-encode instead of storing the upload as is:
- the TYPE is checked from the content (Pillow decodes it), never from the
  file name or the Content-Type header sent by the client;
- EXIF metadata (GPS position of the phone that took the picture, camera
  serial…) is dropped: only pixels are kept;
- the stored file is small and uniform (JPEG, at most 800 px), which is all
  the student card and the admin screen need;
- the stored name is random (`students/photos/<uuid>.jpg`): no client path,
  no pupil name in a file name.
"""

import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 3 * 1024 * 1024  # what a phone or a scanner produces; larger is refused
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MIN_SIDE = 120  # below, the face is unreadable on a card
MAX_SIDE = 6000  # decompression-bomb guard (Pillow has its own global limit too)
STORED_SIDE = 800


def normalise_photo(upload):
    """Uploaded file -> ContentFile (JPEG). Raises ValidationError with a
    stable code: photo_too_large, photo_invalid, photo_format, photo_too_small."""
    if upload is None:
        raise ValidationError("Choose a photo.", code="photo_required")
    if upload.size > MAX_BYTES:
        raise ValidationError("The photo is larger than 3 MB.", code="photo_too_large")
    raw = upload.read()
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            image_format = probe.format
            probe.verify()  # structure check without decoding everything
        image = Image.open(io.BytesIO(raw))
        width, height = image.size
        if image_format not in ALLOWED_FORMATS:
            raise ValidationError("Use a JPEG, PNG or WebP photo.", code="photo_format")
        if max(width, height) > MAX_SIDE:
            raise ValidationError("The photo is too large in pixels.", code="photo_too_large")
        if min(width, height) < MIN_SIDE:
            raise ValidationError(f"The photo must be at least {MIN_SIDE} px wide and high.", code="photo_too_small")
        image = ImageOps.exif_transpose(image)  # keep the orientation the phone recorded
        image = image.convert("RGB")
        image.thumbnail((STORED_SIDE, STORED_SIDE))
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("This file is not a readable image.", code="photo_invalid") from None
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88, optimize=True)  # no exif= argument: metadata dropped
    return ContentFile(out.getvalue(), name=f"{uuid.uuid4().hex}.jpg")
