"""Self-service profile (apps/accounts/profile.py): each role edits ONLY its
personal contact details; identity, login, role, school and rights stay with
the administration. Personal photo checked like a pupil photo and served to
its owner only. Password change and sessions reuse the existing endpoints."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import MembershipStatus
from apps.audit.models import AuditLog

from .communication_world import make_communication_world
from .conftest import DB, DEVICE
from .factories import DEFAULT_PASSWORD, SchoolFactory, member_with_role

pytestmark = DB

PROFILE = "/api/v1/auth/me/profile/"
PHOTO = "/api/v1/auth/me/photo/"


@pytest.fixture
def w(school):
    return make_communication_world(school)


def as_(member):
    client = APIClient()
    client.force_authenticate(member.user)
    return client


def jpeg(size=(400, 300), exif=False):
    image = Image.new("RGB", size, (200, 120, 90))
    out = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010F] = "Phone maker"
        image.save(out, format="JPEG", exif=data.tobytes())
    else:
        image.save(out, format="JPEG")
    return SimpleUploadedFile("moi.jpg", out.getvalue(), content_type="image/jpeg")


def login(user, name):
    client = APIClient()
    r = client.post(
        "/api/v1/auth/login/",
        {"identifier": user.username, "password": DEFAULT_PASSWORD, "device": {**DEVICE, "identifier": name}},
        format="json",
    )
    assert r.status_code == 200, r.json()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['data']['access_token']}")
    return client


# --- read ----------------------------------------------------------------------------------


def test_each_role_gets_its_own_editable_fields(w):
    cases = {
        "parent": (w.parent, ["phone", "occupation", "address", "emergency_phone", "preferred_language"]),
        "teacher": (w.tm.employee.membership, ["phone", "address"]),
        "staff": (w.staff_member, ["phone", "address"]),
        "guardian": (w.guardian, ["phone"]),
        "admin": (w.admin, ["phone"]),
    }
    for label, (member, fields) in cases.items():
        r = as_(member).get(PROFILE)
        assert r.status_code == 200, label
        data = r.json()["data"]
        assert data["editable"] == fields, label
        assert data["school_name"] == w.school.name and data["email"] == member.user.email, label
    parent = as_(w.parent).get(PROFILE).json()["data"]
    assert parent["roles"] == ["PARENT"] and parent["parent"]["preferred_language"] == "fr"
    assert parent["employee"] is None and parent["has_photo"] is False


# --- update --------------------------------------------------------------------------------


def test_parent_updates_allowed_fields_audited_without_values(w):
    r = as_(w.parent).patch(
        PROFILE,
        {
            "phone": "+237 6 99 00 11 22",
            "occupation": "Infirmière",
            "address": "Bastos, Yaoundé",
            "emergency_phone": "699001133",
        },
        format="json",
    )
    assert r.status_code == 200, r.json()
    data = r.json()["data"]
    assert data["phone"] == "+237 6 99 00 11 22" and data["parent"]["occupation"] == "Infirmière"
    w.parent.user.refresh_from_db()
    w.parent.parent_profile.refresh_from_db()
    assert w.parent.user.phone == "+237 6 99 00 11 22" and w.parent.parent_profile.address == "Bastos, Yaoundé"
    log = AuditLog.objects.get(action="PROFILE_UPDATED", actor=w.parent)
    assert log.new_data == {"fields": ["address", "emergency_phone", "occupation", "phone"]}
    assert "Bastos" not in str(log.new_data) and log.school_id == w.school.id


def test_employee_address_and_clearing_a_field(w):
    teacher = w.tm.employee.membership
    assert as_(teacher).patch(PROFILE, {"address": "Akwa, Douala"}, format="json").status_code == 200
    w.tm.employee.refresh_from_db()
    assert w.tm.employee.address == "Akwa, Douala"
    assert as_(teacher).patch(PROFILE, {"address": "  "}, format="json").json()["data"]["employee"]["address"] == ""
    w.tm.employee.refresh_from_db()
    assert w.tm.employee.address is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "ADMIN"),
        ("roles", ["ADMIN"]),
        ("school", "x"),
        ("school_code", "OTHER"),
        ("email", "pirate@x.test"),
        ("username", "pirate"),
        ("first_name", "Autre"),
        ("last_name", "Nom"),
        ("is_staff", True),
        ("status", "ACTIVE"),
        ("financial_responsible", True),
        ("can_pay", True),
    ],
)
def test_forbidden_fields_refuse_the_whole_request(w, field, value):
    before = (w.parent.user.email, w.parent.user.first_name, w.parent.user.phone, w.parent.role_codes())
    r = as_(w.parent).patch(PROFILE, {"phone": "699001122", field: value}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert field in r.json()["error"]["details"]
    w.parent.user.refresh_from_db()
    w.parent.refresh_from_db()
    after = (w.parent.user.email, w.parent.user.first_name, w.parent.user.phone, w.parent.role_codes())
    assert after == before  # nothing applied, not even the allowed phone
    assert not AuditLog.objects.filter(action="PROFILE_UPDATED").exists()


def test_role_specific_fields_are_refused_to_other_roles(w):
    assert as_(w.guardian).patch(PROFILE, {"address": "x"}, format="json").status_code == 400
    assert as_(w.staff_member).patch(PROFILE, {"occupation": "x"}, format="json").status_code == 400
    assert (
        as_(w.tm.employee.membership).patch(PROFILE, {"emergency_phone": "699001122"}, format="json").status_code == 400
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"phone": "abc"},
        {"phone": "12"},
        {"phone": "+" + "1" * 20},
        {"emergency_phone": "<script>"},
        {"preferred_language": "de"},
        {"address": "x" * 501},
        {"phone": 699},
    ],
)
def test_invalid_values_are_explained_per_field(w, payload):
    r = as_(w.parent).patch(PROFILE, payload, format="json")
    assert r.status_code == 400 and next(iter(payload)) in r.json()["error"]["details"]


def test_suspended_member_and_other_school(w):
    w.parent.status = MembershipStatus.SUSPENDED
    w.parent.save(update_fields=["status"])
    assert as_(w.parent).get(PROFILE).status_code == 403
    assert as_(w.parent).patch(PROFILE, {"phone": "699001122"}, format="json").status_code == 403
    # A member of another school only ever sees and edits ITS membership; the school header cannot switch.
    other = member_with_role(SchoolFactory(), "PARENT")
    r = as_(other).get(PROFILE, HTTP_X_SCHOOL_CODE=w.school.code)
    assert r.status_code == 403
    assert as_(other).get(PROFILE).json()["data"]["school_code"] != w.school.code


# --- photo ---------------------------------------------------------------------------------


def test_photo_is_normalised_private_and_owner_only(w):
    r = as_(w.guardian).post(PHOTO, {"photo": jpeg(exif=True)}, format="multipart")
    assert r.status_code == 200 and r.json()["data"]["has_photo"] is True
    w.guardian.user.refresh_from_db()
    name = w.guardian.user.profile_photo.name
    assert name.startswith("users/photos/") and name.endswith(".jpg") and "moi" not in name
    got = as_(w.guardian).get(PHOTO)
    assert got.status_code == 200 and got["Cache-Control"] == "private, no-store"
    stored = Image.open(io.BytesIO(b"".join(got.streaming_content)))
    assert stored.format == "JPEG" and not stored.getexif()
    # Another member asking for "my photo" gets their own (none): never someone else's.
    assert as_(w.parent).get(PHOTO).status_code == 404
    assert as_(w.guardian).delete(PHOTO).json()["data"]["has_photo"] is False
    assert as_(w.guardian).get(PHOTO).status_code == 404
    assert set(AuditLog.objects.filter(actor=w.guardian).values_list("action", flat=True)) == {
        "PROFILE_PHOTO_SET",
        "PROFILE_PHOTO_REMOVED",
    }


@pytest.mark.parametrize(
    "upload,rule",
    [
        (SimpleUploadedFile("x.jpg", b"MZ\x90\x00 not an image", content_type="image/jpeg"), "photo_invalid"),
        (lambda: jpeg(size=(60, 60)), "photo_too_small"),
        (SimpleUploadedFile("x.jpg", b"0" * (3 * 1024 * 1024 + 1), content_type="image/jpeg"), "photo_too_large"),
    ],
)
def test_invalid_photos_are_refused(w, upload, rule):
    upload = upload() if callable(upload) else upload
    r = as_(w.parent).post(PHOTO, {"photo": upload}, format="multipart")
    assert r.status_code == 400 and r.json()["error"]["details"]["rule"] == rule
    w.parent.user.refresh_from_db()
    assert not w.parent.user.profile_photo


# --- password and sessions (existing endpoints, from the profile screens) ----------------------


def test_password_change_keeps_this_device_and_revokes_the_others(w):
    user = w.parent.user
    phone = login(user, "phone")
    tablet = login(user, "tablet")
    sessions = phone.get("/api/v1/auth/sessions/").json()["data"]
    assert len(sessions) == 2 and sum(s["is_current"] for s in sessions) == 1
    wrong = phone.post(
        "/api/v1/auth/password/change/",
        {"current_password": "nope", "new_password": "Un-Autre-Mot-2026!"},
        format="json",
    )
    assert wrong.status_code == 400
    ok = phone.post(
        "/api/v1/auth/password/change/",
        {"current_password": DEFAULT_PASSWORD, "new_password": "Un-Autre-Mot-2026!"},
        format="json",
    )
    assert ok.status_code == 200
    assert phone.get(PROFILE).status_code == 200
    assert tablet.get(PROFILE).status_code == 401  # the other device is disconnected
    assert len(phone.get("/api/v1/auth/sessions/").json()["data"]) == 1


def test_revoking_one_session_and_never_someone_elses(w):
    user = w.parent.user
    phone = login(user, "phone")
    tablet = login(user, "tablet")
    tablet_id = next(s["id"] for s in phone.get("/api/v1/auth/sessions/").json()["data"] if not s["is_current"])
    intruder = login(w.other_parent.user, "intruder")
    assert intruder.post(f"/api/v1/auth/sessions/{tablet_id}/revoke/").status_code == 404
    assert tablet.get(PROFILE).status_code == 200
    assert phone.post(f"/api/v1/auth/sessions/{tablet_id}/revoke/").status_code == 200
    assert tablet.get(PROFILE).status_code == 401
    assert phone.get(PROFILE).status_code == 200
