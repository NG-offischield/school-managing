"""Demo gate guardian (seed_demo + people.admin_create_guardian): created by
the administration's service, first password set through the real
activation flow, idempotent; the GUARDIAN rights are the backend's existing
ones (scan, own scans, no finance, no other guardian, no other school, no
grades)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import AccountActivation, MembershipRole, SchoolMembership, User
from apps.attendance import services as attendance
from apps.attendance.models import StudentQRCode
from apps.demo import dataset
from apps.demo.seed import seed
from apps.people import services as people
from apps.people.models import GuardianProfile

from .conftest import DB, DEVICE
from .factories import SchoolFactory, admin_of, make_teacher
from .test_demo_seed import PASSWORD

pytestmark = DB


@pytest.fixture
def w():
    return seed(password=PASSWORD)


def new_guardian(school, actor, email, number):
    return people.admin_create_guardian(
        school, actor=actor, first_name="Autre", last_name="Gardien", email=email, guardian_number=number
    )


def signed_in(identifier, password=PASSWORD):
    client = APIClient()
    response = client.post(
        "/api/v1/auth/login/", {"identifier": identifier, "password": password, "device": DEVICE}, format="json"
    )
    assert response.status_code == 200, response.json()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['data']['access_token']}")
    return client


def test_guardian_account_profile_role_and_activation(w):
    membership = w.guardian
    assert membership.school == w.school and membership.status == "ACTIVE"
    assert membership.user.username == "demo.guardian" and membership.user.email == "guardian@demo-ecole.test"
    assert membership.role_codes() == {"GUARDIAN"}
    profile = GuardianProfile.objects.get(membership=membership)
    assert (profile.guardian_number, profile.status) == ("G-DEMO-01", "ACTIVE")
    # First password through the activation flow (code issued, then used), never set directly.
    assert AccountActivation.objects.filter(membership=membership, used_at__isnull=False).count() == 1
    assert membership.user.check_password(PASSWORD)


def test_guardian_signs_in_with_login_or_email(w):
    for identifier in ("demo.guardian", "guardian@demo-ecole.test"):
        me = signed_in(identifier).get("/api/v1/auth/me/").json()["data"]
        assert me["memberships"][0]["school_code"] == "DEMO"
        assert "GUARDIAN" in me["memberships"][0]["roles"]


def test_every_demo_pupil_has_one_active_annual_qr(w):
    assert len(w.qr_codes) == 5
    for key, student in w.students.items():
        assert StudentQRCode.objects.filter(student=student, academic_year=w.year, status="ACTIVE").count() == 1
        assert w.qr_codes[key].student == student


def test_guardian_scans_and_sees_only_own_scans(w):
    client = signed_in("demo.guardian")
    answer = client.post("/api/v1/qr/scans/", {"token": w.qr_codes["S1"].token}, format="json")
    assert answer.status_code == 201, answer.json()
    data = answer.json()["data"]
    assert data["result"] == "ACCEPTED" and data["student"]["id"] == str(w.students["S1"].pk)
    assert data["solvency"] in ("UP_TO_DATE", "OVERDUE")  # a status for the gate, never an amount
    assert "75000" not in str(data) and "amount" not in str(data)
    other = new_guardian(w.school, w.admin, "g2@demo-ecole.test", "G2")
    attendance.scan(w.qr_codes["S2"].token, actor=other.membership)
    rows = client.get("/api/v1/guardians/scans/").json()["data"]
    assert [r["student"] for r in rows] == [str(w.students["S1"].pk)]  # not the other guardian's S2


def test_no_finance_for_the_guardian(w):
    client = signed_in("demo.guardian")
    assert client.get("/api/v1/finance/wallets/").json()["data"] == []
    assert client.get("/api/v1/finance/invoices/").json()["data"] == []
    assert client.get("/api/v1/finance/payments/").json()["data"] == []
    obligations = client.get(f"/api/v1/finance/students/{w.students['S1'].pk}/obligations/")
    assert obligations.status_code in (403, 404)
    invoice = w.invoices["F-S1-TUITION"]
    assert client.get(f"/api/v1/finance/invoices/{invoice.pk}/").status_code in (403, 404)


def test_no_grades_no_messaging_for_the_guardian(w):
    from apps.gradebook import services as gradebook

    client = signed_in("demo.guardian")
    assert client.get("/api/v1/grades/").json()["data"] == []
    assert client.get("/api/v1/report-cards/").json()["data"] == []
    # Writing grades: the gradebook's own guard (course teacher or administrator).
    teacher = make_teacher(w.school)
    course = gradebook.create_course(w.classes["6e A"], teacher.primary_subject, teacher, actor=w.admin)
    with pytest.raises(PermissionDenied):
        gradebook.require_course_access(w.guardian, course)
    message = {"conversation_type": "ADMINISTRATION", "body": "x"}
    assert client.post("/api/v1/conversations/", message, format="json").status_code == 403


def test_another_schools_data_stays_out_of_reach(w):
    other_school = SchoolFactory()
    other_admin = admin_of(other_school)
    stranger = new_guardian(other_school, other_admin, "g@other.test", "G-DEMO-01")
    # A DEMO pupil's QR scanned by another school's guardian: unknown there.
    outcome = attendance.scan(w.qr_codes["S1"].token, actor=stranger.membership)
    assert outcome.scan.result == "UNKNOWN_TOKEN" and outcome.scan.student is None
    client = signed_in("demo.guardian")
    assert client.get(f"/api/v1/students/{w.students['S1'].pk}/attendance/").status_code in (403, 404)
    rows = client.get("/api/v1/guardians/scans/").json()["data"]
    assert rows == []  # the other school's scan is not the DEMO guardian's


def test_second_run_changes_nothing_and_resets_no_password(w):
    demo_users = lambda: {u.username: u.password for u in User.objects.filter(email__endswith="@demo-ecole.test")}  # noqa: E731
    before = demo_users()
    counts = (
        SchoolMembership.objects.filter(school=w.school).count(),
        GuardianProfile.objects.filter(school=w.school).count(),
        StudentQRCode.objects.filter(school=w.school).count(),
        AccountActivation.objects.filter(school=w.school).count(),
    )
    again = seed()  # no password needed any more
    assert again.created == []
    assert again.guardian == w.guardian
    assert demo_users() == before  # no password changed (hashes identical)
    assert (
        SchoolMembership.objects.filter(school=w.school).count(),
        GuardianProfile.objects.filter(school=w.school).count(),
        StudentQRCode.objects.filter(school=w.school).count(),
        AccountActivation.objects.filter(school=w.school).count(),
    ) == counts


def test_admin_create_guardian_rules(w):
    with pytest.raises(PermissionDenied):
        new_guardian(w.school, w.parents["A"], "x@demo-ecole.test", "G9")  # only the administration
    with pytest.raises(ValidationError) as taken:
        new_guardian(w.school, w.admin, "parent.a@demo-ecole.test", "G9")
    assert taken.value.code == "email_in_use"
    with pytest.raises(ValidationError) as number:
        new_guardian(w.school, w.admin, "new@demo-ecole.test", "G-DEMO-01")
    assert number.value.code == "duplicate_guardian_number"
    fresh = new_guardian(w.school, w.admin, "new@demo-ecole.test", "G9")
    assert not fresh.membership.user.has_usable_password()  # activation code needed, no password from the admin
    assert MembershipRole.objects.get(membership=fresh.membership).role.code == "GUARDIAN"


def test_identifiers_owned_by_someone_else_are_never_taken_over(w):
    from django.core.exceptions import ImproperlyConfigured

    w.guardian.user.username = "renamed"
    w.guardian.user.save(update_fields=["username"])
    with pytest.raises(ImproperlyConfigured):
        seed()  # guardian@demo-ecole.test belongs to an account the seed no longer recognises
    assert dataset.GUARDIAN["username"] == "demo.guardian"


def test_older_demo_base_without_password_creates_nothing(w, monkeypatch):
    """A DEMO base seeded before the guardian existed, re-run WITHOUT DEMO_PASSWORD:
    refused, and the transaction leaves no half-created account."""
    from django.core.exceptions import ImproperlyConfigured

    newer = {**dataset.GUARDIAN, "username": "demo.guardian2", "email": "guardian2@demo-ecole.test"}
    monkeypatch.setattr(dataset, "GUARDIAN", {**newer, "guardian_number": "G-DEMO-02"})
    with pytest.raises(ImproperlyConfigured, match="DEMO_PASSWORD"):
        seed()
    assert not User.objects.filter(username="demo.guardian2").exists()
    assert not GuardianProfile.objects.filter(guardian_number="G-DEMO-02").exists()
