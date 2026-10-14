"""ISBREE contents (ADR 0032): who may edit, what each audience may read.

Editing: ADMIN / SUPER_ADMIN or CONTENT_MANAGER of the school, through these
functions only (API of the desktop); every change is audited.

Reading: the server decides. Public visitors get PUBLISHED rows whose
audience includes PUBLIC; a portal member gets PUBLISHED rows for the ONE role
context they chose among the roles they really hold (a role they do not hold
is refused, never "added"). Role resources are further narrowed by their
scope (level, class, year, staff function) and visibility window.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from apps.audit.models import AuditLayer
from apps.audit.services import record_audit, snapshot
from common.permissions import ADMIN_ROLES, membership_has_role

from . import files
from .models import (
    AUDIENCES,
    PORTAL_ROLES,
    PUBLIC,
    ContentImage,
    FaqEntry,
    MobileAppRelease,
    NewsArticle,
    Page,
    PublicationStatus,
    ReleaseStatus,
    RoleResource,
    SiteLocation,
    SiteProfile,
)

EDITOR_ROLES = frozenset({*ADMIN_ROLES, "CONTENT_MANAGER"})


def require_editor(actor, school):
    if actor is None or actor.school_id != school.pk or not membership_has_role(actor, EDITOR_ROLES):
        raise PermissionDenied("This action requires an administrator or content manager of the school.")


def _audit(action, actor, entity, old=None, new=None):
    record_audit(action, actor=actor, entity=entity, old=old, new=new, layer=AuditLayer.ADMINISTRATIVE)


def clean_audiences(values, *, allow_public=True):
    allowed = AUDIENCES if allow_public else PORTAL_ROLES
    audiences = sorted({str(v).upper() for v in (values or [])})
    if not audiences:
        raise ValidationError("Choose at least one audience.", code="audience_required")
    unknown = [a for a in audiences if a not in allowed]
    if unknown:
        raise ValidationError("Unknown audience.", code="audience_invalid")
    return audiences


def unique_slug(model, school, text, exclude=None):
    base = slugify(text)[:70] or "page"
    slug, n = base, 2
    while model.objects.filter(school=school, slug=slug).exclude(pk=exclude).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


# =============================================================================
# Generic editing of the editorial models
# =============================================================================

EDITABLE = {
    "pages": (Page, ["kind", "slug", "title", "summary", "body", "audiences"]),
    "faq": (FaqEntry, ["category", "question", "answer", "audiences"]),
    "news": (NewsArticle, ["slug", "title", "summary", "body", "category", "event_date", "cover", "audiences"]),
    "locations": (SiteLocation, ["name", "description", "address_text", "is_main"]),
    "resources": (
        RoleResource,
        [
            "kind",
            "title",
            "body",
            "audiences",
            "level",
            "school_class",
            "academic_year",
            "staff_function",
            "visible_from",
            "visible_until",
        ],
    ),
    "images": (
        ContentImage,
        ["alt_text", "caption", "credit", "category", "in_gallery", "is_illustration", "audiences"],
    ),
}
COMMON = ["status", "to_validate", "is_demo", "order"]
AUDIT_FIELDS = {
    model: [f for f in fields if f not in ("body", "answer")] + COMMON for model, fields in EDITABLE.values()
}


def _check_scope(school, values):
    for name in ("level", "school_class", "academic_year", "staff_function", "cover"):
        value = values.get(name)
        if value is not None and value.school_id != school.pk:
            raise PermissionDenied("This reference belongs to another school.")


@transaction.atomic
def save_content(kind, school, *, actor, values, instance=None):
    """Create (instance=None) or update a content row of `kind` with the
    already-validated `values` (serializers of admin_api.py)."""
    require_editor(actor, school)
    model, fields = EDITABLE[kind]
    if instance is not None and instance.school_id != school.pk:
        raise PermissionDenied("This content belongs to another school.")
    _check_scope(school, values)
    if "audiences" in values:
        values["audiences"] = clean_audiences(values["audiences"], allow_public=model is not RoleResource)
    if model in (Page, NewsArticle) and not values.get("slug") and (instance is None or "title" in values):
        values["slug"] = unique_slug(model, school, values.get("title") or instance.title, instance and instance.pk)
    old = snapshot(instance, AUDIT_FIELDS[model]) if instance else None
    row = instance or model(school=school)
    for name in [*fields, *COMMON]:
        if name in values:
            setattr(row, name, values[name])
    if model is NewsArticle and row.status == PublicationStatus.PUBLISHED and row.published_at is None:
        row.published_at = timezone.now()
    row.full_clean(exclude=["school"] if instance is None else None)
    row.save()
    _audit(
        f"WEBSITE_{model.__name__.upper()}_{'UPDATED' if instance else 'CREATED'}",
        actor,
        row,
        old,
        snapshot(row, AUDIT_FIELDS[model]),
    )
    return row


@transaction.atomic
def add_image(school, *, actor, upload, values):
    require_editor(actor, school)
    checked = files.check_image(upload)
    path, digest, size = files.store(checked, school, "images")
    values = dict(values)
    values["audiences"] = clean_audiences(values.get("audiences") or [PUBLIC])
    image = ContentImage(
        school=school,
        storage_path=path,
        mime_type=checked.mime_type,
        size=size,
        sha256=digest,
        width=checked.width,
        height=checked.height,
        **{k: v for k, v in values.items() if k in EDITABLE["images"][1] + COMMON},
    )
    image.full_clean(exclude=["school"])
    image.save()
    _audit("WEBSITE_CONTENTIMAGE_CREATED", actor, image, None, snapshot(image, AUDIT_FIELDS[ContentImage]))
    return image


@transaction.atomic
def attach_document(resource, *, actor, upload):
    require_editor(actor, resource.school)
    checked = files.check_document(upload)
    path, _digest, size = files.store(checked, resource.school, "documents")
    old = {"document_name": resource.document_name}
    resource.document_path, resource.document_name, resource.document_size = path, checked.name[:200], size
    resource.save(update_fields=["document_path", "document_name", "document_size", "updated_at"])
    _audit("WEBSITE_RESOURCE_DOCUMENT_ATTACHED", actor, resource, old, {"document_name": resource.document_name})
    return resource


@transaction.atomic
def save_profile(school, *, actor, values):
    require_editor(actor, school)
    profile, _ = SiteProfile.objects.get_or_create(school=school)
    fields = [
        "tagline",
        "presentation",
        "values",
        "pedagogy",
        "location_details",
        "office_hours",
        "address_confirmed",
        "to_validate",
    ]
    old = snapshot(profile, fields)
    for name in fields:
        if name in values:
            setattr(profile, name, values[name])
    profile.save()
    _audit("WEBSITE_PROFILE_UPDATED", actor, profile, old, snapshot(profile, fields))
    return profile


# =============================================================================
# Mobile application releases
# =============================================================================

RELEASE_FIELDS = ["app", "version_name", "version_code", "status", "published_at"]


@transaction.atomic
def add_release(school, *, actor, upload, app, version_name, version_code, release_notes="", min_android=None):
    require_editor(actor, school)
    checked = files.check_apk(upload)  # signed release builds only
    if MobileAppRelease.objects.filter(school=school, app=app, version_code=version_code).exists():
        raise ValidationError("This version code already exists for this application.", code="release_version_exists")
    path, digest, size = files.store(checked, school, "apps")
    release = MobileAppRelease(
        school=school,
        app=app,
        version_name=version_name,
        version_code=version_code,
        release_notes=release_notes or "",
        storage_path=path,
        file_name=checked.name[:200],
        size=size,
        sha256=digest,
    )
    if min_android:
        release.min_android = min_android
    release.full_clean(exclude=["school"])
    release.save()
    _audit("WEBSITE_APP_RELEASE_ADDED", actor, release, None, snapshot(release, RELEASE_FIELDS))
    return release


@transaction.atomic
def set_release_status(release, status, *, actor):
    require_editor(actor, release.school)
    if status not in ReleaseStatus.values:
        raise ValidationError("Unknown status.", code="invalid_status")
    old = snapshot(release, RELEASE_FIELDS)
    release.status = status
    if status == ReleaseStatus.PUBLISHED and release.published_at is None:
        release.published_at = timezone.now()
    release.save(update_fields=["status", "published_at", "updated_at"])
    _audit("WEBSITE_APP_RELEASE_STATUS", actor, release, old, snapshot(release, RELEASE_FIELDS))
    return release


# =============================================================================
# Reading — the server filters, the client never receives more
# =============================================================================


def published(queryset, audience, today=None):
    rows = queryset.filter(status=PublicationStatus.PUBLISHED, audiences__contains=[audience])
    if queryset.model is RoleResource:
        today = today or timezone.localdate()
        rows = rows.filter(Q(visible_from__isnull=True) | Q(visible_from__lte=today)).filter(
            Q(visible_until__isnull=True) | Q(visible_until__gte=today)
        )
    return rows


def role_context(membership, requested):
    """The role context the member asked for, among the roles they HOLD."""
    role = (requested or "").upper()
    held = [r for r in PORTAL_ROLES if membership_has_role(membership, {r})]
    if not held:
        raise PermissionDenied("This account has no portal role.")
    if not role:
        return held[0], held
    if role not in held:
        raise PermissionDenied("This role is not granted to this account.")
    return role, held


def scoped_resources(school, role, *, levels=(), classes=(), years=(), functions=()):
    """Resources of `role` whose scope fits: an unset scope field means "all";
    a set one must be among the given ids (a parent's child's class, a
    teacher's classes, a staff member's functions)."""
    rows = published(RoleResource.objects.filter(school=school), role)
    for field, allowed in (
        ("level", levels),
        ("school_class", classes),
        ("academic_year", years),
        ("staff_function", functions),
    ):
        rows = rows.filter(Q(**{f"{field}__isnull": True}) | Q(**{f"{field}_id__in": list(allowed)}))
    return rows.select_related("level", "school_class", "academic_year", "staff_function")
