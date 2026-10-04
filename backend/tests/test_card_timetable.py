"""Student card and timetable PDFs (ADR 0016 §7–8): built from the existing
pupil / annual QR and scheduling data, in the central document registry."""

import json
from datetime import date, time

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.attendance import services as att
from apps.audit.models import AuditLog
from apps.communication.attachments import private_storage
from apps.documents import rendering
from apps.documents import services as docs
from apps.documents.models import Document, DocumentDownload
from apps.people import services as people
from apps.scheduling import services as planning

from .communication_world import make_communication_world, png, verified_parent
from .conftest import DB
from .factories import SchoolFactory, StudentFactory
from .planning_world import MONDAY

pytestmark = DB


@pytest.fixture
def w(school):
    return make_communication_world(school)


def as_(member):
    client = APIClient()
    client.force_authenticate(member.user)
    return client


def pdf_bytes(document):
    with private_storage().open(document.storage_path, "rb") as handle:
        return handle.read()


def spy_qr(monkeypatch):
    """Record the value the card's QR encodes (no QR decoder needed)."""
    seen = []
    real = rendering.QrCodeWidget

    def widget(value, *args, **kwargs):
        seen.append(value)
        return real(value, *args, **kwargs)

    monkeypatch.setattr(rendering, "QrCodeWidget", widget)
    return seen


# =============================================================================
# Student card
# =============================================================================


def test_card_requires_the_existing_annual_qr(w):
    with pytest.raises(ValidationError) as exc:
        docs.generate("STUDENT_CARD", w.students[0], actor=w.admin)
    assert exc.value.code == "document_source_not_final"
    assert not Document.objects.exists()


def test_card_content_qr_and_privacy(w, monkeypatch):
    seen = spy_qr(monkeypatch)
    qr = att.issue_qr_code(w.students[0], actor=w.admin)
    student = w.students[0]
    student.photo = png("photo.png")
    student.address = "Rue privée 12"
    student.save()
    card, created = docs.generate("STUDENT_CARD", student, actor=w.admin)
    fields = dict(card.content["fields"])
    assert (created, card.status) == (True, "OFFICIAL")
    assert (fields["Nom"], fields["Prénom"], fields["Classe"], fields["Année scolaire"]) == (
        student.last_name,
        student.first_name,
        "3e A",
        "2025-2026",
    )
    assert fields["Sexe"] == "Féminin" and fields["Né(e) le"] == "04/05/2012"
    assert fields["Carte n°"] == f"{student.student_number}-V1"
    assert card.content["qr"]["id"] == str(qr.pk)
    assert [c[0] for c in card.content["emergency"]] == [w.parent.user.full_name]  # verified parents only
    # The card encodes the EXISTING opaque token, which is never copied into the registry.
    assert seen == [qr.token]
    assert qr.token not in json.dumps(card.content) and qr.token not in card.title
    assert "Rue privée" not in json.dumps(card.content)  # no unneeded personal data
    raw = pdf_bytes(card)
    assert raw.startswith(b"%PDF") and b"/Count 2" in raw and b"/Subtype /Image" in raw  # recto/verso, photo
    assert AuditLog.objects.filter(action="DOCUMENT_GENERATED", entity_id=card.pk).exists()


def test_card_is_idempotent_and_follows_qr_reissue(w):
    att.issue_qr_code(w.students[0], actor=w.admin)
    first, _ = docs.generate("STUDENT_CARD", w.students[0], actor=w.admin)
    again, created = docs.generate("STUDENT_CARD", w.students[0], actor=w.parent)
    assert (again.pk, created) == (first.pk, False)
    new_qr = att.reissue_qr_code(w.students[0], actor=w.admin, reason="Carte perdue")
    reissued, created = docs.generate("STUDENT_CARD", w.students[0], actor=w.admin)
    assert created and reissued.pk != first.pk and reissued.content["qr"]["id"] == str(new_qr.pk)
    first.refresh_from_db()
    assert first.status == "OFFICIAL"  # history kept, never rewritten
    with pytest.raises(ValidationError):
        docs.regenerate(reissued, actor=w.admin)


def test_card_permissions_and_isolation(w):
    att.issue_qr_code(w.students[0], actor=w.admin)
    card, _ = docs.generate("STUDENT_CARD", w.students[0], actor=w.parent)
    for outsider in (w.other_parent, w.unverified, w.tm_member, w.staff_member, w.guardian):
        with pytest.raises(PermissionDenied):
            docs.generate("STUDENT_CARD", w.students[0], actor=outsider)
        assert not docs.can_read(outsider, card)
    other = make_communication_world(SchoolFactory())
    assert not docs.can_access(other.admin, "STUDENT_CARD", w.students[0])
    client = as_(other.admin)
    assert client.post(f"/api/v1/students/{w.students[0].pk}/card/").status_code == 404
    assert client.get(f"/api/v1/documents/{card.pk}/download/").status_code == 404
    assert client.get(f"/api/v1/reports/student-card/{w.students[0].pk}.pdf/").status_code == 404
    # Authorised parent: through the spec endpoints, private download, traced.
    response = as_(w.parent).get(f"/api/v1/reports/student-card/{w.students[0].pk}.pdf/")
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response["Cache-Control"] == "private, no-store"
    assert DocumentDownload.objects.filter(document=card, actor=w.parent).exists()
    assert APIClient().get(f"/media/{card.storage_path}").status_code == 404
    assert as_(w.other_parent).get(f"/api/v1/reports/student-card/{w.students[0].pk}.pdf/").status_code == 404


# =============================================================================
# Timetable
# =============================================================================


def with_slots(w):
    planning.create_slot(w.course_maths, actor=w.admin, weekday=5, start_time=time(10), end_time=time(12))
    planning.create_slot(w.course_french, actor=w.admin, weekday=1, start_time=time(10), end_time=time(12))


def test_class_timetable_from_scheduling(w):
    with_slots(w)
    document, created = docs.generate("TIMETABLE", w.klass, actor=w.parent, date=MONDAY)
    grid, changes = document.content["tables"]
    assert created and document.status == "OFFICIAL"  # a past week, as it was applied
    assert grid["columns"] == ["Horaire", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
    row = grid["rows"][0]
    assert row[0] == "10:00–12:00"
    assert row[1] == f"Français\n{w.tf_member.user.full_name}\nSalle 12"
    assert row[5] == f"Mathématiques\n{w.tm_member.user.full_name}\nSalle 12"
    assert any(change[3] == "Séance annulée" for change in changes["rows"])  # the week's change
    assert dict(document.content["fields"])["Semaine"] == "06/10/2025 – 12/10/2025"
    again, created = docs.generate("TIMETABLE", w.klass, actor=w.admin, date=date(2025, 10, 9))
    assert (again.pk, created) == (document.pk, False)  # same week -> same document
    assert pdf_bytes(document).startswith(b"%PDF")


def test_teacher_timetable_is_their_own(w):
    with_slots(w)
    mine, _ = docs.generate("TIMETABLE", w.tm, actor=w.tm_member, date=MONDAY)
    rows = mine.content["tables"][0]["rows"]
    assert rows == [["10:00–12:00", "", "", "", "", "Mathématiques\n3e A\nSalle 12"]]
    for outsider in (w.tf_member, w.parent, w.staff_member):
        with pytest.raises(PermissionDenied):
            docs.generate("TIMETABLE", w.tm, actor=outsider, date=MONDAY)
        assert not docs.can_read(outsider, mine)
    with pytest.raises(PermissionDenied):  # a teacher: their own timetable, not a class's
        docs.generate("TIMETABLE", w.klass, actor=w.tm_member, date=MONDAY)


def test_timetable_parent_scope_and_isolation(w):
    with_slots(w)
    pupil_b = StudentFactory(school=w.school)
    people.enroll_student(pupil_b, w.klass_b)
    parent_b = verified_parent(w, pupil_b)
    with pytest.raises(PermissionDenied):  # parent of a pupil of ANOTHER class
        docs.generate("TIMETABLE", w.klass, actor=parent_b, date=MONDAY)
    document, _ = docs.generate("TIMETABLE", w.klass, actor=w.other_parent, date=MONDAY)  # s1 is in 3e A
    assert [d.pk for d in docs.visible_documents(w.other_parent).filter(kind="TIMETABLE")] == [document.pk]
    assert not docs.visible_documents(parent_b).filter(kind="TIMETABLE").exists()
    other = make_communication_world(SchoolFactory())
    assert not docs.can_access(other.admin, "TIMETABLE", w.klass)
    assert not docs.can_access(other.admin, "TIMETABLE", w.tm)
    client = as_(other.admin)
    url = f"/api/v1/reports/schedule.pdf/?school_class={w.klass.pk}&date=2025-10-06"
    assert client.get(url).status_code == 404
    assert client.get(f"/api/v1/reports/schedule.pdf/?teacher={w.tm.pk}&date=2025-10-06").status_code == 404
    response = as_(w.parent).get(url)
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert as_(parent_b).get(url).status_code == 404
    created = as_(w.admin).post(
        "/api/v1/documents/", {"kind": "TIMETABLE", "teacher": str(w.tm.pk), "date": "2025-10-06"}, format="json"
    )
    assert created.status_code == 201 and created.json()["data"]["kind"] == "TIMETABLE"
