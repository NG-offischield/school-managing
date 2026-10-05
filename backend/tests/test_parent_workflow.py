"""Parent registration and verified linking (ADR 0026): the server decides,
the app only asks.

registration (no enumeration, admin approval) -> link request (pupil number
+ date of birth, identity document as an HMAC) -> identity checked against
the physical document -> pupil's approval -> admin approval with rights
(sponsored second parent: one-time code from a verified parent, never more
rights than the sponsor) -> exactly the access the link grants."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import (
    MembershipStatus,
    SecurityEvent,
    SecurityEventType,
    User,
    VerificationChallenge,
)
from apps.people import parent_workflow as workflow
from apps.people.models import (
    IdentityMethod,
    IdentityStatus,
    IdentityVerification,
    LinkRequestStatus,
    ParentStudent,
    ParentStudentLinkRequest,
    RegistrationRequest,
    VerificationMethod,
)

from .communication_world import make_communication_world
from .conftest import DB, DEVICE
from .factories import SchoolFactory, admin_of

pytestmark = DB
STRONG = "Parent-Kribi-2026!"
DOCUMENT = "CM 1234-5678"


@pytest.fixture
def w(school):
    return make_communication_world(school)


def as_(membership_or_user):
    client = APIClient()
    client.force_authenticate(getattr(membership_or_user, "user", membership_or_user))
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def rule(response, expected):
    assert response.status_code == expected, response.json()
    return response.json()["error"]["details"]["rule"]


def register(email="maman.awa@example.cm", password=STRONG, **extra):
    body = {"first_name": "Awa", "last_name": "Mbarga", "email": email, "password": password, **extra}
    return APIClient().post("/api/v1/registrations/parent/", body, format="json")


def approved_parent(w, email):
    """A parent account created from the app and approved by the school."""
    assert register(email).status_code == 202
    request = RegistrationRequest.objects.get(applicant_email=email)
    workflow.approve_registration(request, actor=w.admin)
    request.membership.refresh_from_db()
    return request.membership


def ask_link(member, student, *, document=DOCUMENT, relationship="MOTHER", dob=None):
    return as_(member).post(
        "/api/v1/parents/link-requests/",
        {
            "student_number": student.student_number.lower(),  # case does not matter
            "date_of_birth": str(dob or student.date_of_birth),
            "relationship_type": relationship,
            "document_type": "CNI",
            "document_number": document,
        },
        format="json",
    )


def admin_url(request_id, action=""):
    return f"/api/v1/admin/link-requests/{request_id}/{action}"


def fully_checked(w, request_id, document=DOCUMENT):
    admin = as_(w.admin)
    data(admin.post(admin_url(request_id, "verify-identity/"), {"document_type": "CNI", "document_number": document}))
    data(admin.post(admin_url(request_id, "student-approval/"), {"decision": "APPROVED", "note": "Confirmé en classe"}))


# =============================================================================
# Registration
# =============================================================================


def test_registration_gives_the_same_answer_whatever_happens(school):
    first = register()
    assert first.status_code == 202
    duplicate = register(email="MAMAN.awa@example.cm")
    unknown_school = register(email="autre@example.cm", school_code="NOPE")
    for response in (duplicate, unknown_school):
        assert response.status_code == 202 and response.json() == first.json()
    assert RegistrationRequest.objects.count() == 1
    request = RegistrationRequest.objects.get()
    assert request.membership.status == MembershipStatus.PENDING and not request.membership.role_codes()
    assert SecurityEvent.objects.filter(event_type=SecurityEventType.PARENT_REGISTRATION_DUPLICATE).count() == 1
    # The password chosen by the parent is hashed (Argon2), never stored as such.
    user = request.user
    assert user.password.startswith("argon2") and STRONG not in user.password


def test_weak_password_is_refused_on_the_field(school):
    response = register(password="1234567890")
    assert response.status_code == 400
    assert response.json()["error"]["details"]["password"]
    assert not User.objects.filter(email="maman.awa@example.cm").exists()


def test_pending_applicant_logs_in_but_reaches_nothing_of_the_school(api, school):
    register()
    login = api.post(
        "/api/v1/auth/login/",
        {"identifier": "maman.awa@example.cm", "password": STRONG, "device": DEVICE},
        format="json",
    )
    assert login.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['data']['access_token']}")
    assert [r["status"] for r in data(api.get("/api/v1/registrations/me/"))] == ["PENDING"]
    memberships = data(api.get("/api/v1/auth/me/"))["memberships"]
    assert [(m["status"], m["roles"]) for m in memberships] == [("PENDING", [])]
    for url in ("/api/v1/parents/children/", "/api/v1/parents/link-requests/", "/api/v1/notifications/"):
        response = api.get(url)
        assert response.status_code == 403 and response.json()["error"]["code"] == "NO_ACTIVE_MEMBERSHIP"


def test_admin_approves_or_rejects_a_registration(w):
    register("a@example.cm")
    register("b@example.cm")
    admin = as_(w.admin)
    pending = data(admin.get("/api/v1/admin/registrations/?status=PENDING"))
    by_email = {r["applicant_email"]: r["id"] for r in pending}
    assert set(by_email) == {"a@example.cm", "b@example.cm"}
    searched = data(admin.get("/api/v1/admin/registrations/?search=B@EXAMPLE"))
    assert [r["applicant_email"] for r in searched] == ["b@example.cm"]

    data(admin.post(f"/api/v1/admin/registrations/{by_email['a@example.cm']}/approve/"))
    member = RegistrationRequest.objects.get(pk=by_email["a@example.cm"]).membership
    member.refresh_from_db()
    assert member.status == MembershipStatus.ACTIVE and member.role_codes() == {"PARENT"}
    assert hasattr(member, "parent_profile")
    assert rule(admin.post(f"/api/v1/admin/registrations/{by_email['a@example.cm']}/approve/"), 409) == (
        "registration_not_pending"
    )

    rejected = admin.post(f"/api/v1/admin/registrations/{by_email['b@example.cm']}/reject/", {}, format="json")
    assert rejected.status_code == 400  # a reason is required
    data(admin.post(f"/api/v1/admin/registrations/{by_email['b@example.cm']}/reject/", {"reason": "Inconnu"}))
    assert not User.objects.get(email="b@example.cm").is_active  # can no longer log in


def test_only_the_administration_of_this_school_decides_registrations(w):
    register()
    request = RegistrationRequest.objects.get()
    for member in (w.parent, w.tm_member):
        assert as_(member).get("/api/v1/admin/registrations/").status_code == 403
        assert as_(member).post(f"/api/v1/admin/registrations/{request.pk}/approve/").status_code == 403
    foreign_admin = admin_of(SchoolFactory())
    assert as_(foreign_admin).get(f"/api/v1/admin/registrations/{request.pk}/").status_code == 404
    assert as_(foreign_admin).post(f"/api/v1/admin/registrations/{request.pk}/approve/").status_code == 404
    request.refresh_from_db()
    assert request.status == "PENDING"


# =============================================================================
# Link request + identity document
# =============================================================================


def test_link_request_needs_number_and_birth_date_and_keeps_only_an_hmac(w):
    member = approved_parent(w, "p@example.cm")
    child = w.students[2]
    wrong_dob = ask_link(member, child, dob=child.date_of_birth - timedelta(days=1))
    assert rule(wrong_dob, 400) == "student_not_found"
    foreign_child = make_communication_world(SchoolFactory()).students[0]
    assert rule(ask_link(member, foreign_child), 400) == "student_not_found"  # other school: same answer

    created = data(ask_link(member, child), 201)
    assert (created["status"], created["identity_status"], created["student_approval_status"]) == (
        "PENDING",
        "PENDING",
        "PENDING",
    )
    identity = IdentityVerification.objects.get()
    assert identity.document_reference_hash == workflow.document_hash("cm12345678")
    stored = json.dumps(
        list(IdentityVerification.objects.values()) + list(ParentStudentLinkRequest.objects.values()), default=str
    )
    listed = json.dumps(data(as_(member).get("/api/v1/parents/link-requests/")))
    for text in (stored, listed, json.dumps(created)):
        assert "1234" not in text  # the document number is never stored nor returned
    assert identity.document_reference_hash not in listed
    assert rule(ask_link(member, child), 409) == "link_request_pending"


def test_identity_is_checked_against_the_physical_document(w):
    member = approved_parent(w, "p@example.cm")
    request_id = data(ask_link(member, w.students[2]), 201)["id"]
    admin = as_(w.admin)
    url = admin_url(request_id, "verify-identity/")
    for _ in range(2):
        assert rule(admin.post(url, {"document_type": "CNI", "document_number": "CM 0000-0000"}), 409) == (
            "identity_mismatch"
        )
    assert rule(admin.post(url, {"document_type": "PASSPORT", "document_number": DOCUMENT}), 409) == (
        "identity_mismatch"  # same number, other kind of document
    )
    identity = IdentityVerification.objects.get()
    assert (identity.failed_checks, identity.status) == (3, IdentityStatus.REJECTED)  # mismatches stay counted
    assert rule(admin.post(url, {"document_type": "CNI", "document_number": DOCUMENT}), 409) == "identity_rejected"
    assert SecurityEvent.objects.filter(event_type=SecurityEventType.LINK_IDENTITY_MISMATCH).count() == 3


def test_matching_document_written_differently_is_verified(w):
    member = approved_parent(w, "p@example.cm")
    request_id = data(ask_link(member, w.students[2]), 201)["id"]
    checked = data(
        as_(w.admin).post(
            admin_url(request_id, "verify-identity/"), {"document_type": "CNI", "document_number": "cm12345678"}
        )
    )
    assert checked["identity_status"] == "VERIFIED" and checked["identity_failed_checks"] == 0


def test_approval_needs_verified_identity_and_the_pupils_designation(w):
    member = approved_parent(w, "p@example.cm")
    request_id = data(ask_link(member, w.students[2]), 201)["id"]
    admin = as_(w.admin)
    assert rule(admin.post(admin_url(request_id, "approve/")), 409) == "identity_not_verified"
    data(admin.post(admin_url(request_id, "verify-identity/"), {"document_type": "CNI", "document_number": DOCUMENT}))
    assert rule(admin.post(admin_url(request_id, "approve/")), 409) == "student_approval_required"
    data(admin.post(admin_url(request_id, "student-approval/"), {"decision": "REJECTED"}))
    assert rule(admin.post(admin_url(request_id, "approve/")), 409) == "student_approval_required"
    assert not ParentStudent.objects.filter(parent__membership=member).exists()


def test_approved_request_gives_exactly_the_granted_access(w):
    member = approved_parent(w, "p@example.cm")
    child, other_child = w.students[0], w.students[1]
    client = as_(member)
    request_id = data(ask_link(member, child), 201)["id"]

    # Before the decision: nothing about the child.
    assert data(client.get("/api/v1/parents/children/")) == []
    for url in (
        f"/api/v1/students/{child.pk}/attendance/",
        f"/api/v1/students/{child.pk}/sessions/",
        f"/api/v1/finance/students/{child.pk}/obligations/",
        f"/api/v1/parents/children/{child.pk}/teachers/",
    ):
        assert client.get(url).status_code in (403, 404), url

    fully_checked(w, request_id)
    approved = data(as_(w.admin).post(admin_url(request_id, "approve/"), {"can_pay": False}, format="json"))
    assert approved["status"] == "APPROVED"
    link = ParentStudent.objects.get(parent__membership=member)
    assert link.identity_verified and link.verification_method == VerificationMethod.ID_DOCUMENT
    assert (link.can_pay, link.can_view_financial_data) == (False, False)

    children = data(client.get("/api/v1/parents/children/"))
    assert [c["student"]["id"] for c in children] == [str(child.pk)]
    assert children[0]["enrollment"]["class_name"] == "3e A"
    assert children[0]["enrollment"]["academic_year_name"] == "2025-2026"
    teachers = data(client.get(f"/api/v1/parents/children/{child.pk}/teachers/"))
    assert {t["member"]: t["subjects"] for t in teachers} == {
        str(w.tm.employee.membership_id): ["MATH"],
        str(w.tf.employee.membership_id): ["FR"],
    }
    assert client.get(f"/api/v1/students/{child.pk}/attendance/").status_code == 200
    # can_view_financial_data = false: finance is refused, even though the child is visible.
    assert client.get(f"/api/v1/finance/students/{child.pk}/obligations/").status_code == 403
    # Another pupil of the same class stays invisible.
    for url in (
        f"/api/v1/students/{other_child.pk}/attendance/",
        f"/api/v1/parents/children/{other_child.pk}/teachers/",
    ):
        assert client.get(url).status_code == 404


def test_rights_are_granted_by_the_administration_only(w):
    member = approved_parent(w, "p@example.cm")
    request_id = data(ask_link(member, w.students[0]), 201)["id"]
    fully_checked(w, request_id)
    body = {"can_pay": True, "can_view_financial_data": True}
    assert as_(member).post(admin_url(request_id, "approve/"), body, format="json").status_code == 403
    data(as_(w.admin).post(admin_url(request_id, "approve/"), body, format="json"))
    obligations = data(as_(member).get(f"/api/v1/finance/students/{w.students[0].pk}/obligations/"))
    assert obligations["can_pay"] is True


def test_parent_requests_are_private_to_their_author(w):
    alice, bob = approved_parent(w, "alice@example.cm"), approved_parent(w, "bob@example.cm")
    request_id = data(ask_link(alice, w.students[2]), 201)["id"]
    assert data(as_(bob).get("/api/v1/parents/link-requests/")) == []
    for action in ("cancel/", "sponsor/"):
        response = as_(bob).post(f"/api/v1/parents/link-requests/{request_id}/{action}", {"code": "X"}, format="json")
        assert response.status_code == 404
    cancelled = data(as_(alice).post(f"/api/v1/parents/link-requests/{request_id}/cancel/"))
    assert cancelled["status"] == "CANCELLED"
    data(ask_link(alice, w.students[2]), 201)  # a new request is possible after a cancellation


def test_other_school_administration_sees_no_link_request(w):
    member = approved_parent(w, "p@example.cm")
    request_id = data(ask_link(member, w.students[2]), 201)["id"]
    foreign = as_(admin_of(SchoolFactory()))
    assert foreign.get(admin_url(request_id)).status_code == 404
    body = {"document_type": "CNI", "document_number": DOCUMENT}
    assert foreign.post(admin_url(request_id, "verify-identity/"), body).status_code == 404
    assert foreign.post(admin_url(request_id, "approve/")).status_code == 404
    assert IdentityVerification.objects.get().status == IdentityStatus.PENDING


def test_admin_list_shows_the_check_context_without_secrets(w):
    member = approved_parent(w, "p@example.cm")
    data(ask_link(member, w.students[2]), 201)
    rows = data(as_(w.admin).get("/api/v1/admin/link-requests/?status=PENDING&search=Mbarga"))
    assert len(rows) == 1 and rows[0]["parent"]["email"] == "p@example.cm" and rows[0]["class_name"] == "3e A"
    text = json.dumps(rows)
    assert "1234" not in text and IdentityVerification.objects.get().document_reference_hash not in text


# =============================================================================
# Sponsorship of a second parent (one-time code, "2FA")
# =============================================================================


def sponsor_code(member, student):
    response = as_(member).post(f"/api/v1/parents/children/{student.pk}/sponsor-codes/")
    assert response.status_code == 201, response.json()
    assert response["Cache-Control"] == "no-store"
    return response.json()["data"]["code"]


def test_only_a_verified_parent_of_the_child_issues_a_code(w):
    child = w.students[0]
    for member in (w.unverified, w.other_parent, w.tm_member):
        assert as_(member).post(f"/api/v1/parents/children/{child.pk}/sponsor-codes/").status_code in (403, 404)
    code = sponsor_code(w.parent, child)
    assert len(code) == 9 and code[4] == "-"
    challenge = VerificationChallenge.objects.get()
    assert code.replace("-", "") not in challenge.challenge_hash  # only a hash is kept
    assert SecurityEvent.objects.filter(event_type=SecurityEventType.LINK_SPONSOR_CODE_ISSUED).exists()
    sponsor_code(w.parent, child)  # a new code replaces the previous one
    assert VerificationChallenge.objects.filter(consumed_at__isnull=True).count() == 1


def test_sponsored_second_parent(w):
    child = w.students[0]
    ParentStudent.objects.filter(parent__membership=w.parent).update(can_pay=True, can_view_financial_data=False)
    second = approved_parent(w, "papa@example.cm")
    request_id = data(ask_link(second, child, relationship="FATHER", document="CM 9999-0000"), 201)["id"]
    code = sponsor_code(w.parent, child)
    url = f"/api/v1/parents/link-requests/{request_id}/sponsor/"
    assert rule(as_(second).post(url, {"code": "AAAA-AAAA"}), 400) == "sponsor_code_invalid"
    assert VerificationChallenge.objects.get(consumed_at__isnull=True).attempt_count == 1  # counted, committed

    sponsored = data(as_(second).post(url, {"code": code.lower()}))
    assert sponsored["sponsored"] is True and sponsored["identity_method"] == IdentityMethod.SPONSOR_2FA
    assert sponsored["identity_status"] == "VERIFIED"
    assert rule(as_(second).post(url, {"code": code}), 409) == "already_sponsored"

    data(as_(w.admin).post(admin_url(request_id, "student-approval/"), {"decision": "NOT_REQUIRED"}))
    too_much = {"can_pay": True, "can_view_financial_data": True}
    assert rule(as_(w.admin).post(admin_url(request_id, "approve/"), too_much, format="json"), 409) == (
        "rights_exceed_sponsor"
    )
    sponsor_link = ParentStudent.objects.filter(parent__membership=w.parent)
    sponsor_link.update(can_pay=False)  # the sponsor may not pay: neither may the sponsored parent
    assert rule(as_(w.admin).post(admin_url(request_id, "approve/"), {"can_pay": True}, format="json"), 409) == (
        "rights_exceed_sponsor"
    )
    sponsor_link.update(can_pay=True)
    data(as_(w.admin).post(admin_url(request_id, "approve/"), {"can_pay": True}, format="json"))
    link = ParentStudent.objects.get(parent__membership=second)
    assert link.identity_verified and link.verification_method == VerificationMethod.SPONSOR_2FA
    assert (link.can_pay, link.can_view_financial_data) == (True, False)


def test_used_expired_or_overused_codes_are_refused(w):
    child = w.students[0]
    second, third = approved_parent(w, "papa@example.cm"), approved_parent(w, "tata@example.cm")
    first_request = data(ask_link(second, child, relationship="FATHER"), 201)["id"]
    other_request = data(ask_link(third, child, relationship="TUTOR"), 201)["id"]

    code = sponsor_code(w.parent, child)
    data(as_(second).post(f"/api/v1/parents/link-requests/{first_request}/sponsor/", {"code": code}))
    other_url = f"/api/v1/parents/link-requests/{other_request}/sponsor/"
    assert rule(as_(third).post(other_url, {"code": code}), 400) == "sponsor_code_invalid"  # single use

    code = sponsor_code(w.parent, child)
    past = timezone.now() - timedelta(minutes=11)  # issued 11 min ago: lived 10 min
    VerificationChallenge.objects.filter(consumed_at__isnull=True).update(
        created_at=past, expires_at=past + workflow.SPONSOR_CODE_LIFETIME
    )
    assert rule(as_(third).post(other_url, {"code": code}), 400) == "sponsor_code_invalid"  # expired

    code = sponsor_code(w.parent, child)
    VerificationChallenge.objects.filter(consumed_at__isnull=True).update(attempt_count=5)
    assert rule(as_(third).post(other_url, {"code": code}), 400) == "sponsor_code_invalid"  # too many attempts
    assert ParentStudentLinkRequest.objects.get(pk=other_request).sponsor_challenge_verified is False


def test_a_sponsor_who_lost_verification_cannot_carry_a_request(w):
    child = w.students[0]
    second = approved_parent(w, "papa@example.cm")
    request_id = data(ask_link(second, child, relationship="FATHER"), 201)["id"]
    code = sponsor_code(w.parent, child)
    data(as_(second).post(f"/api/v1/parents/link-requests/{request_id}/sponsor/", {"code": code}))
    data(as_(w.admin).post(admin_url(request_id, "student-approval/"), {"decision": "NOT_REQUIRED"}))
    ParentStudent.objects.filter(parent__membership=w.parent).update(active=False)
    assert rule(as_(w.admin).post(admin_url(request_id, "approve/")), 409) == "sponsor_not_verified"


def test_reject_link_request_requires_a_reason_and_grants_nothing(w):
    member = approved_parent(w, "p@example.cm")
    request_id = data(ask_link(member, w.students[2]), 201)["id"]
    admin = as_(w.admin)
    assert admin.post(admin_url(request_id, "reject/"), {}, format="json").status_code == 400
    rejected = data(admin.post(admin_url(request_id, "reject/"), {"reason": "Pièce illisible"}))
    assert rejected["status"] == LinkRequestStatus.REJECTED
    assert not ParentStudent.objects.filter(parent__membership=member).exists()
    assert rule(admin.post(admin_url(request_id, "approve/")), 409) == "request_not_pending"


# =============================================================================
# Isolation of the parent read APIs the app uses
# =============================================================================


def test_parent_a_never_reaches_parent_bs_child(w):
    from .test_notifications import late_scan

    child_b = w.students[1]  # w.other_parent's child
    late_scan(w, child_b)
    client = as_(w.parent)
    assert data(client.get(f"/api/v1/students/{child_b.pk}/scans/")) == []
    assert data(as_(w.other_parent).get(f"/api/v1/students/{child_b.pk}/scans/"))  # B sees them
    for url in (
        f"/api/v1/students/{child_b.pk}/",
        f"/api/v1/students/{child_b.pk}/attendance/",
        f"/api/v1/students/{child_b.pk}/sessions/",
        f"/api/v1/students/{child_b.pk}/timetable/",
        f"/api/v1/finance/students/{child_b.pk}/obligations/",
        f"/api/v1/parents/children/{child_b.pk}/teachers/",
    ):
        assert client.get(url).status_code in (403, 404), url
    assert data(client.get(f"/api/v1/report-cards/?student={child_b.pk}")) == []


def test_unverified_link_and_suspended_account_see_nothing(w):
    child = w.students[0]
    assert data(as_(w.unverified).get("/api/v1/parents/children/")) == []
    assert as_(w.unverified).get(f"/api/v1/students/{child.pk}/attendance/").status_code == 404
    w.parent.status = MembershipStatus.SUSPENDED
    w.parent.save(update_fields=["status"])
    response = as_(w.parent).get("/api/v1/parents/children/")
    assert response.status_code == 403 and response.json()["error"]["code"] == "NO_ACTIVE_MEMBERSHIP"


def test_parent_never_learns_who_scanned_the_child(w):
    from .test_notifications import late_scan

    late_scan(w, w.students[0])
    scans = data(as_(w.parent).get(f"/api/v1/students/{w.students[0].pk}/scans/"))
    assert scans and all(set(s) <= {"id", "scanned_at", "result"} for s in scans)
    text = json.dumps(scans)
    assert w.guardian.user.last_name not in text and str(w.guardian.pk) not in text


def test_sponsor_code_service_refuses_an_unverified_parent(w):
    """Defence in depth: the service checks the verified link itself, not
    only the API's child lookup."""
    from django.core.exceptions import PermissionDenied

    for member in (w.unverified, w.other_parent):
        with pytest.raises(PermissionDenied):
            workflow.create_sponsor_code(member, w.students[0])
    assert not VerificationChallenge.objects.exists()
