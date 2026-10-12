"""Self-service profile: what a member may change about THEMSELF.

Only personal contact details are self-service. Everything that drives a
check or a right stays with the administration: names (identity), e-mail and
username (login), role, school, membership status, parent-child links,
employee number, salary, guardian number...

    every role       User.phone, personal photo (password and sessions:
                     existing auth/password/change/ and auth/sessions/)
    PARENT           ParentProfile.occupation, address, emergency_phone, preferred_language
    employee         EmployeeProfile.address (teachers, staff, admins who have one)
    GUARDIAN         nothing more (GuardianProfile holds only administrative data)

A field outside this list is REFUSED (never silently ignored): a client
cannot slip `role`, `school`, `email`... into the request. Every change is
audited with the names of the fields, not their values (personal data).
"""

import re

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_audit
from apps.people.models import ParentProfile
from apps.people.models.parents import Language
from apps.people.models.staff import EmployeeProfile

USER_FIELDS = ("phone",)
PARENT_FIELDS = ("occupation", "address", "emergency_phone", "preferred_language")
EMPLOYEE_FIELDS = ("address",)
PHONE_FIELDS = {"phone", "emergency_phone"}
MAX_LENGTH = {"phone": 40, "emergency_phone": 40, "occupation": 150, "address": 500}
_PHONE = re.compile(r"^\+?[0-9 ().-]+$")


def _parent(membership):
    return ParentProfile.objects.filter(membership=membership).first()


def _employee(membership):
    return EmployeeProfile.objects.filter(membership=membership).first()


def editable_fields(membership):
    """Field names this member may change, in display order."""
    fields = list(USER_FIELDS)
    if _parent(membership) is not None:
        fields += [f for f in PARENT_FIELDS if f not in fields]
    if _employee(membership) is not None:
        fields += [f for f in EMPLOYEE_FIELDS if f not in fields]
    return fields


def profile_data(membership):
    user = membership.user
    parent = _parent(membership)
    employee = _employee(membership)
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone or "",
        "has_photo": bool(user.profile_photo),
        "school_name": membership.school.name,
        "school_code": membership.school.code,
        "roles": sorted(membership.role_codes()),
        "parent": (
            {
                "occupation": parent.occupation or "",
                "address": parent.address or "",
                "emergency_phone": parent.emergency_phone or "",
                "preferred_language": parent.preferred_language,
            }
            if parent
            else None
        ),
        "employee": {"address": employee.address or ""} if employee else None,
        "editable": editable_fields(membership),
        "languages": dict(Language.choices) if parent else {},
    }


def _clean(field, value):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError({field: ["Texte attendu."]})
    value = value.strip()
    if len(value) > MAX_LENGTH.get(field, 500):
        raise ValidationError({field: [f"{MAX_LENGTH.get(field, 500)} caractères au maximum."]})
    if field in PHONE_FIELDS and value:
        digits = re.sub(r"\D", "", value)
        if not _PHONE.match(value) or not 6 <= len(digits) <= 15:
            raise ValidationError({field: ["Numéro de téléphone invalide."]})
    if field == "preferred_language":
        if value not in Language.values:
            raise ValidationError({field: ["Langue inconnue."]})
        return value
    return value or None


@transaction.atomic
def update_profile(membership, changes, *, ctx=None):
    """Applies `changes` (a dict) or refuses the whole request."""
    allowed = set(editable_fields(membership))
    forbidden = sorted(set(changes) - allowed)
    if forbidden:
        raise ValidationError({name: ["Ce champ ne peut pas être modifié depuis votre profil."] for name in forbidden})
    cleaned = {field: _clean(field, value) for field, value in changes.items()}
    user = type(membership.user).objects.select_for_update().get(pk=membership.user_id)
    membership.user = user  # profile_data() then reads the fresh row
    parent = _parent(membership)
    employee = _employee(membership)
    changed = []
    for field, value in cleaned.items():
        if field in USER_FIELDS:
            target = user
        elif field in PARENT_FIELDS and parent is not None:
            target = parent
        else:
            target = employee
        if getattr(target, field) != value:
            setattr(target, field, value)
            changed.append((target, field))
    for target in {id(t): t for t, _ in changed}.values():
        target.save(update_fields=[f for t, f in changed if t is target] + ["updated_at"])
    if changed:
        record_audit(
            "PROFILE_UPDATED",
            actor=membership,
            entity=user,
            school=membership.school,
            new={"fields": sorted(f for _, f in changed)},  # names only: no personal data in the trail
            ctx=ctx,
        )
    return profile_data(membership)


@transaction.atomic
def set_photo(membership, upload, *, ctx=None):
    """Same checks as a pupil photo (people/photos.py: real decoding, 3 MB,
    EXIF dropped, JPEG <= 800 px, random name), stored apart from pupils'
    photos and the school logo (users/photos/), served only to its owner."""
    from apps.people.photos import normalise_photo

    content = normalise_photo(upload)
    user = type(membership.user).objects.select_for_update().get(pk=membership.user_id)
    membership.user = user  # profile_data() then reads the fresh row
    old = user.profile_photo.name if user.profile_photo else None
    user.profile_photo.save(content.name, content, save=False)
    user.save(update_fields=["profile_photo", "updated_at"])
    record_audit(
        "PROFILE_PHOTO_SET",
        actor=membership,
        entity=user,
        school=membership.school,
        old={"photo": old},
        new={"photo": user.profile_photo.name},
        ctx=ctx,
    )
    return user


@transaction.atomic
def remove_photo(membership, *, ctx=None):
    user = type(membership.user).objects.select_for_update().get(pk=membership.user_id)
    membership.user = user  # profile_data() then reads the fresh row
    if user.profile_photo:
        old = user.profile_photo.name
        user.profile_photo = None
        user.save(update_fields=["profile_photo", "updated_at"])
        record_audit(
            "PROFILE_PHOTO_REMOVED",
            actor=membership,
            entity=user,
            school=membership.school,
            old={"photo": old},
            new={"photo": None},
            ctx=ctx,
        )
    return user
