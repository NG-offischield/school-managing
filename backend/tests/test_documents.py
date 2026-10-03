"""Official documents (ADR 0016): report cards, receipts, payslips,
attendance; official vs provisional, idempotence, versions, branding,
rights, isolation, private storage, traces."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.attendance import services as att
from apps.audit.models import AuditLog
from apps.communication.attachments import private_storage
from apps.documents import services as docs
from apps.documents.models import Document, DocumentDownload
from apps.finance import services as fin
from apps.finance.models import Payment
from apps.gradebook import services as gb
from apps.gradebook.models import ReportCard
from apps.payroll import services as pay
from apps.payroll.models import StaffPayroll, TeacherPayroll

from .communication_world import make_communication_world, png, verified_parent
from .conftest import DB
from .factories import SchoolFactory
from .planning_world import MONDAY, at
from .test_gradebook import fill_t1

pytestmark = DB


@pytest.fixture
def w(school):
    return make_communication_world(school)


def as_(member):
    client = APIClient()
    client.force_authenticate(member.user)
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def error(response, expected):
    assert response.status_code == expected, response.json()
    return response.json()["error"]


def card_of(w, student=0):
    fill_t1(w)
    cards = gb.generate_report_cards(w.klass, w.t1, actor=w.admin)
    return next(c for c in cards if c.student == w.students[student])


def validated_card(w):
    card = card_of(w)
    gb.close_period(w.t1, actor=w.admin)
    gb.validate_report_card(card, actor=w.admin)
    card.refresh_from_db()
    return card


def paid_payment(w):
    tuition = fin.create_fee_type(w.school, actor=w.admin, code="TUI", name="Scolarité")
    invoice = fin.issue_invoice(
        w.students[0], actor=w.admin, due_date=date(2025, 10, 1), lines=[{"fee_type": tuition, "unit_price": "75000"}]
    )
    w.parent.parent_profile.children_links.update(can_pay=True)
    wallet = fin.create_wallet(w.parent, actor=w.admin, provider_code="FAKE", wallet_identifier="611111111")
    fin.fund_wallet(wallet, "100000", actor=w.admin)
    return fin.initiate_payment(
        w.students[0],
        actor=w.parent,
        amount="75000",
        payment_method="WALLET",
        idempotency_key="doc-1",
        wallet=wallet,
        invoices=[invoice],
    ).payment


def teacher_payroll(w, pay_it=True):
    pay.validate_session(w.sessions[0], actor=w.admin)
    pay.calculate_period(w.october, actor=w.admin)
    payroll = TeacherPayroll.objects.get(teacher=w.tm)
    pay.approve_payroll(payroll, actor=w.admin)
    if pay_it:
        pay.pay_payroll(payroll, actor=w.admin, payout_method="CASH")
    payroll.refresh_from_db()
    return payroll


def pdf_bytes(document):
    with private_storage().open(document.storage_path, "rb") as handle:
        return handle.read()


# =============================================================================
# Report cards
# =============================================================================


def test_draft_report_card_is_provisional_and_administration_only(w):
    card = card_of(w)
    document, created = docs.generate("REPORT_CARD", card, actor=w.admin)
    assert (created, document.status, document.version) == (True, "PROVISIONAL", 1)
    content = document.content
    assert dict(content["fields"])["Classe"] == "3e A" and dict(content["fields"])["Élève"] == w.students[0].full_name
    maths = next(row for row in content["tables"][0]["rows"] if row[0] == "Mathématiques")
    assert maths[2] == "13.00" and dict(content["summary"])["Moyenne générale"] == "12.00 / 20"
    assert "non validé" in content["statement"]
    assert pdf_bytes(document).startswith(b"%PDF") and document.size_bytes == len(pdf_bytes(document))
    with pytest.raises(ValidationError) as exc:  # a parent never gets a draft bulletin
        docs.generate("REPORT_CARD", card, actor=w.parent)
    assert exc.value.code == "document_source_not_final"
    assert not docs.can_read(w.parent, document)


def test_validated_report_card_is_official_frozen_and_shared_with_parents(w):
    card = card_of(w)
    draft, _ = docs.generate("REPORT_CARD", card, actor=w.admin)
    gb.close_period(w.t1, actor=w.admin)
    gb.validate_report_card(card, actor=w.admin)
    official, created = docs.generate("REPORT_CARD", card, actor=w.parent)
    draft.refresh_from_db()
    assert (created, official.status, official.version, draft.status) == (True, "OFFICIAL", 2, "SUPERSEDED")
    assert "validé le" in official.content["statement"]
    again, created_again = docs.generate("REPORT_CARD", card, actor=w.admin)
    assert (again.pk, created_again) == (official.pk, False)  # idempotent, never regenerated
    with pytest.raises(ValidationError) as exc:
        docs.regenerate(official, actor=w.admin)
    assert exc.value.code == "document_official"
    for outsider in (w.other_parent, w.unverified, w.tm_member, w.staff_member, w.guardian):
        assert not docs.can_read(outsider, official)


def test_source_modified_after_generation(w):
    card = card_of(w)
    first, _ = docs.generate("REPORT_CARD", card, actor=w.admin)
    assert docs.regenerate(first, actor=w.admin) == (first, False)  # nothing changed
    grade = w.students[0].grades.filter(assessment__course=w.course_french).first()
    gb.update_grade(grade, Decimal("16"), actor=w.tf_member, reason="Erreur de saisie")
    gb.generate_report_cards(w.klass, w.t1, actor=w.admin)  # the draft card is recomputed
    second, created = docs.regenerate(first, actor=w.admin)
    first.refresh_from_db()
    assert (created, second.version, first.status) == (True, 2, "SUPERSEDED")
    assert first.content != second.content and first.fingerprint != second.fingerprint
    with pytest.raises(ValidationError) as exc:
        docs.regenerate(first, actor=w.admin)
    assert exc.value.code == "document_superseded"
    with pytest.raises(PermissionDenied):
        docs.regenerate(second, actor=w.tm_member)
    # History is never rewritten nor deleted.
    for attempt in (
        lambda: Document.objects.filter(pk=first.pk).update(status="PROVISIONAL"),
        lambda: Document.objects.filter(pk=second.pk).update(content={}),
        lambda: Document.objects.filter(pk=second.pk).delete(),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            attempt()


# =============================================================================
# Finance and payroll
# =============================================================================


def test_payment_receipt_uses_finance_data_without_touching_it(w):
    payment = paid_payment(w)
    before = Payment.objects.filter(pk=payment.pk).values().get()
    receipt, _ = docs.generate("PAYMENT_RECEIPT", payment, actor=w.parent)
    fields = dict(receipt.content["fields"])
    assert receipt.status == "OFFICIAL"
    assert (fields["Référence"], fields["Montant"], fields["Payeur"]) == (
        payment.payment_reference,
        "75 000.00 XAF",
        w.parent.user.full_name,
    )
    assert fields["Élève"].startswith(w.students[0].full_name) and fields["Statut"] == "Paiement reçu"
    after = Payment.objects.filter(pk=payment.pk).values().get()
    assert before == after  # producing the PDF changed nothing in finance
    fin.refund_payment(payment, actor=w.admin, amount="5000", reason="Trop-perçu")
    same, created = docs.generate("PAYMENT_RECEIPT", payment, actor=w.admin)
    assert (same.pk, created) == (receipt.pk, False)  # the receipt of a transaction never changes


def test_receipts_are_strictly_protected(w):
    payment = paid_payment(w)
    viewer_without_finance = verified_parent(w, w.students[0])  # verified, no can_view_financial_data
    for outsider in (viewer_without_finance, w.other_parent, w.tm_member, w.staff_member, w.guardian):
        with pytest.raises(PermissionDenied):
            docs.generate("PAYMENT_RECEIPT", payment, actor=outsider)
    finance_viewer = verified_parent(w, w.students[0], can_view_financial_data=True)
    receipt, _ = docs.generate("PAYMENT_RECEIPT", payment, actor=finance_viewer)
    assert docs.can_read(finance_viewer, receipt) and not docs.can_read(viewer_without_finance, receipt)


def test_failed_payment_has_no_receipt(w):
    tuition = fin.create_fee_type(w.school, actor=w.admin, code="TUI", name="Scolarité")
    w.parent.parent_profile.children_links.update(can_pay=True)
    wallet = fin.create_wallet(
        w.parent, actor=w.admin, provider_code="FAKE", wallet_identifier="633", simulation_behavior="DECLINE"
    )
    declined = fin.initiate_payment(
        w.students[0],
        actor=w.parent,
        amount="100",
        payment_method="WALLET",
        idempotency_key="doc-d",
        wallet=wallet,
        fee_type=tuition,
    ).payment
    with pytest.raises(ValidationError) as exc:
        docs.generate("PAYMENT_RECEIPT", declined, actor=w.admin)
    assert exc.value.code == "document_source_not_final"


def test_payslip_provisional_then_official_for_the_employee_only(w):
    payroll = teacher_payroll(w, pay_it=False)
    provisional, _ = docs.generate("PAYSLIP", payroll, actor=w.tm_member)
    assert provisional.status == "PROVISIONAL"
    pay.pay_payroll(payroll, actor=w.admin, payout_method="CASH")
    payroll.refresh_from_db()
    official, created = docs.generate("PAYSLIP", payroll, actor=w.tm_member)
    summary = dict(official.content["summary"])
    assert (created, official.status, official.version) == (True, "OFFICIAL", 2)
    assert summary["Rémunération acquise"] == "5 000.00 XAF" and summary["Montant payé"] == "5 000.00 XAF"
    assert summary["Référence financière"] == payroll.payment_reference
    assert official.content["tables"][0]["rows"][0][1] == "120"
    for outsider in (w.tf_member, w.staff_member, w.parent):
        with pytest.raises(PermissionDenied):
            docs.generate("PAYSLIP", payroll, actor=outsider)
        assert not docs.can_read(outsider, official)
    pay.calculate_period(w.october, actor=w.admin)
    staff = StaffPayroll.objects.get(staff=w.staff)
    with pytest.raises(ValidationError):  # a prepared payroll has no payslip
        docs.generate("PAYSLIP", staff, actor=w.admin)


# =============================================================================
# Attendance
# =============================================================================


def test_attendance_documents(w):
    att.set_policy(
        w.school,
        MONDAY.isoweekday(),
        actor=w.admin,
        late_after_time=at(7, 30).time(),
        morning_absence_cutoff=at(10, 0).time(),
        absence_hours=Decimal("8.00"),
    )
    token = att.issue_qr_code(w.students[0], actor=w.admin).token
    att.scan(token, actor=w.guardian, at=at(8, 5))
    statement, _ = docs.generate("STUDENT_ATTENDANCE", w.students[0], actor=w.parent, date_from=MONDAY, date_to=MONDAY)
    assert statement.status == "PROVISIONAL" and statement.content["tables"][0]["rows"][0][1] == "En retard"
    att.finalize_day(w.school, MONDAY, actor=w.admin)
    final, _ = docs.generate("STUDENT_ATTENDANCE", w.students[0], actor=w.parent, date_from=MONDAY, date_to=MONDAY)
    assert (final.status, final.version) == ("OFFICIAL", 2)
    register, _ = docs.generate("CLASS_ATTENDANCE", w.klass, actor=w.tm_member, date=MONDAY)
    students, sessions = register.content["tables"]
    assert len(students["rows"]) == 3 and {r[2] for r in students["rows"]} == {"En retard", "Absent"}
    assert sessions["rows"][0][1] == "Mathématiques"  # from scheduling, no new attendance system
    for outsider, kind, source, params in (
        (w.other_parent, "STUDENT_ATTENDANCE", w.students[0], {"date_from": MONDAY, "date_to": MONDAY}),
        (w.parent, "CLASS_ATTENDANCE", w.klass, {"date": MONDAY}),
        (w.outsider_teacher, "CLASS_ATTENDANCE", w.klass, {"date": MONDAY}),
    ):
        with pytest.raises(PermissionDenied):
            docs.generate(kind, source, actor=outsider, **params)


# =============================================================================
# Branding, storage, API, isolation, traces
# =============================================================================


def test_branding_comes_from_the_school(w):
    w.school.logo = SimpleUploadedFile("logo.png", png().read(), content_type="image/png")
    w.school.phone = "+237 600 00 00 00"
    w.school.save()
    w.school.branding.primary_color = "#8B0000"
    w.school.branding.save()
    document, _ = docs.generate("REPORT_CARD", card_of(w), actor=w.admin)
    school = document.content["school"]
    assert (school["name"], school["phone"], school["primary_color"]) == (w.school.name, "+237 600 00 00 00", "#8B0000")
    assert school["logo"] and b"/Subtype /Image" in pdf_bytes(document)
    other = make_communication_world(SchoolFactory())
    plain, _ = docs.generate("REPORT_CARD", card_of(other), actor=other.admin)
    assert plain.content["school"]["name"] == other.school.name and b"/Subtype /Image" not in pdf_bytes(plain)


def test_api_private_download_traces_and_isolation(w):
    card = validated_card(w)
    parent = as_(w.parent)
    created = data(
        parent.post("/api/v1/documents/", {"kind": "REPORT_CARD", "report_card": str(card.pk)}, format="json"), 201
    )
    again = data(
        parent.post("/api/v1/documents/", {"kind": "REPORT_CARD", "report_card": str(card.pk)}, format="json"), 200
    )
    assert again["id"] == created["id"]
    response = parent.get(f"/api/v1/documents/{created['id']}/download/")
    assert response.status_code == 200 and b"".join(response.streaming_content).startswith(b"%PDF")
    assert response["Content-Type"] == "application/pdf" and response["Cache-Control"] == "private, no-store"
    document = Document.objects.get(pk=created["id"])
    assert DocumentDownload.objects.filter(document=document, actor=w.parent).count() == 1
    assert AuditLog.objects.filter(action="DOCUMENT_GENERATED", entity_id=document.pk).count() == 1
    # Private storage: no public URL, no anonymous access.
    assert APIClient().get(f"/media/{document.storage_path}").status_code == 404
    assert APIClient().get(f"/api/v1/documents/{document.pk}/download/").status_code == 401
    # Others: 404 (never a hint), lists empty.
    other = make_communication_world(SchoolFactory())
    # The rules themselves refuse another school's administrator (mutation target),
    # not only the school-scoped lookups.
    assert not docs.can_access(other.admin, "REPORT_CARD", card)
    assert not docs.can_read(other.admin, document)
    for outsider in (w.other_parent, w.tm_member, other.admin):
        client = as_(outsider)
        assert error(client.get(f"/api/v1/documents/{document.pk}/"), 404)["code"] == "NOT_FOUND"
        assert client.get(f"/api/v1/documents/{document.pk}/download/").status_code == 404
        assert data(client.get("/api/v1/documents/")) == []
    err = error(
        as_(other.admin).post(
            "/api/v1/documents/", {"kind": "REPORT_CARD", "report_card": str(card.pk)}, format="json"
        ),
        404,
    )
    assert err["code"] == "NOT_FOUND"
    err = error(as_(w.admin).post(f"/api/v1/documents/{document.pk}/regenerate/"), 409)
    assert err["details"]["rule"] == "document_official"
    # Authenticity check of a printed document: same school only.
    verified = data(as_(w.tm_member).get(f"/api/v1/documents/verify/?code={document.verification_code}"))
    assert verified["valid"] and verified["title"] is None  # exists, but no content for the teacher
    assert error(as_(other.admin).get(f"/api/v1/documents/verify/?code={document.verification_code}"), 404)


def test_spec_pdf_shortcuts(w):
    card = validated_card(w)
    response = as_(w.parent).get(f"/api/v1/reports/report-card/{card.pk}.pdf/")
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert as_(w.other_parent).get(f"/api/v1/report-cards/{card.pk}/pdf/").status_code == 404
    payroll = teacher_payroll(w)
    assert as_(w.tm_member).get(f"/api/v1/payroll/{payroll.pk}/payslip.pdf/").status_code == 200
    assert as_(w.tf_member).get(f"/api/v1/payroll/{payroll.pk}/payslip.pdf/").status_code == 404
    draft = ReportCard.objects.get(student=w.students[1], academic_period=w.t1)  # still a draft
    linked = verified_parent(w, w.students[1])
    err = error(as_(linked).get(f"/api/v1/report-cards/{draft.pk}/pdf/"), 409)
    assert err["details"]["rule"] in ("document_source_not_final",)
    url = f"/api/v1/reports/attendance.pdf/?student={w.students[0].pk}&date_from=2025-10-06&date_to=2025-10-10"
    assert as_(w.parent).get(url).status_code == 200
    assert as_(w.other_parent).get(url).status_code == 404
