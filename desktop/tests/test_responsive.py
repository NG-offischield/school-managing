"""Global UI rule: no dialog, form or input panel leaves the screen.

Every dialog is checked at 1366×768, 1280×720, 1024×768 and on a very
small screen: it fits, the buttons stay visible and reachable (mouse and
keyboard), the form scrolls instead of growing, fields have a width that
matches their data, side-by-side fields stack when the dialog is narrow."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from school_admin.models import (
    AcademicYear,
    AccountSummary,
    Category,
    Complaint,
    Course,
    Document,
    Enrollment,
    FeeType,
    ForumSpace,
    Invoice,
    Level,
    LinkRequest,
    Member,
    Notification,
    Payment,
    Payroll,
    Post,
    Qualification,
    Room,
    SchoolBreak,
    SchoolClass,
    Session,
    Slot,
    Student,
    Subject,
    Teacher,
    Thread,
    UnavailabilityRequest,
    Wallet,
)
from school_admin.ui.dialogs.category_dialog import CategoryDialog
from school_admin.ui.dialogs.class_dialog import ClassDialog
from school_admin.ui.dialogs.communication_dialogs import (
    AddParticipantDialog,
    ComplaintDialog,
    ComplaintStatusDialog,
    NewConversationDialog,
    NotificationDialog,
    SpaceDialog,
    ThreadDialog,
    ThreadViewDialog,
)
from school_admin.ui.dialogs.course_dialogs import CourseDialog, CourseRecordDialog
from school_admin.ui.dialogs.document_dialogs import (
    ComputeReportCardsDialog,
    DocumentDetailDialog,
    GenerateDocumentDialog,
    VerifyDialog,
)
from school_admin.ui.dialogs.finance_dialogs import (
    FeeTypeDialog,
    InvoiceDetailDialog,
    InvoiceDialog,
    PaymentDetailDialog,
    PaymentDialog,
    RefundDialog,
)
from school_admin.ui.dialogs.level_dialog import LevelDialog
from school_admin.ui.dialogs.parent_dialogs import (
    IdentityCheckDialog,
    LinkApprovalDialog,
    LinkRequestDialog,
    StudentApprovalDialog,
)
from school_admin.ui.dialogs.payroll_dialogs import (
    AdjustmentDialog,
    PayDialog,
    PayrollDetailDialog,
    PeriodDialog,
    TeacherPayDialog,
)
from school_admin.ui.dialogs.planning_dialogs import (
    BreakDialog,
    DecisionDialog,
    EndSlotDialog,
    GenerateDialog,
    MainRoomDialog,
    MoveDialog,
    RescheduleDialog,
    RoomChangeDialog,
    RoomDialog,
    SessionDialog,
    SlotDialog,
    SubstituteDialog,
)
from school_admin.ui.dialogs.student_dialogs import (
    ChangeClassDialog,
    EnrollDialog,
    StudentDialog,
    StudentRecordDialog,
)
from school_admin.ui.dialogs.subject_dialog import SubjectDialog
from school_admin.ui.dialogs.teacher_dialogs import (
    ActivationCodeDialog,
    QualificationsDialog,
    ReasonDialog,
    TeacherDialog,
    TeacherRecordDialog,
)
from school_admin.ui.dialogs.year_dialog import YearDialog
from school_admin.ui.tasks import ImmediateRunner
from school_admin.ui.widgets import FIELD_WIDTHS, SCREEN_MARGIN, ConfirmDialog

YEARS = [AcademicYear("y1", "2025-2026", "ACTIVE", True, date(2025, 9, 1), date(2026, 7, 31))]
LEVELS = [Level("l6", "6E", "Sixième", 1, True)]
ROOMS = [Room("r1", "R12", "Salle 12 du bâtiment principal (rez-de-chaussée)", 40, True)]
CATEGORIES = [Category("c1", "SCI", "Scientifique", "", True)]

CLASSES = [SchoolClass("c1", "6e A", "l6", "", "y1", "", 40, None, "", False, True)]
STUDENT = Student("s1", "MAT-1", "INS-1", "Awa", "Ndiaye", date(2013, 2, 1), "F", "ACTIVE", "Douala", "Akwa", 140)
ENROLLMENT = Enrollment("e1", "y1", "2025-2026", "c1", "6e A", "l6", "6E", "Sixième", "ACTIVE", date(2025, 9, 2))

SUBJECTS = [Subject("s1", "MATH", "Mathématiques", "c1", "SCI — Scientifique", "THEORETICAL", False, True)]
TEACHER = Teacher(
    "t1",
    "ENS-1",
    "Jean",
    "Mbarga",
    "j@ecole.test",
    "",
    "c1",
    "SCI — Scientifique",
    "s1",
    "MATH — Mathématiques",
    ("MATH",),
    "ACTIVE",
    "ACTIVE",
    True,
    None,
    "Akwa",
    "",
    "",
    False,
    2,
    5,
)
COURSE = Course(
    "k1",
    "s1",
    "MATH",
    "Mathématiques",
    "t1",
    "ENS-1",
    "Mbarga Jean",
    "c1",
    "6e A",
    "6E",
    "y1",
    "2025-2026",
    "4.00",
    "5.00",
    True,
)
QUALS = [Qualification("q1", "s1", "MATH", "Mathématiques", "VERIFIED", "ADMIN", "COMPATIBLE", "COMPATIBLE")]
SLOT = Slot(
    "sl1",
    "k1",
    "MATH",
    "Mathématiques",
    "c1",
    "6e A",
    "t1",
    "Mbarga Jean",
    "r1",
    "R12",
    1,
    "08:00",
    "10:00",
    date(2025, 9, 1),
    None,
    "PUBLISHED",
)
SESSION = Session(
    "se1",
    "k1",
    "MATH",
    "Mathématiques",
    "c1",
    "6e A",
    "t2",
    "Ngo Marie",
    "t1",
    "Mbarga Jean",
    "r1",
    "R12",
    date(2026, 3, 2),
    datetime(2026, 3, 2, 8),
    datetime(2026, 3, 2, 10),
    "SCHEDULED",
    True,
    False,
)
REQUEST = UnavailabilityRequest("u1", "t1", date(2026, 3, 2), "08:00", "12:00", "Rendez-vous médical " * 4, "PENDING")
BREAK = SchoolBreak("b1", "y1", "Vacances de Pâques", datetime(2026, 4, 6), datetime(2026, 4, 20), "HOLIDAY", True)

FEE_TYPES = [FeeType("f1", "SCOL", "Scolarité annuelle du premier cycle")]
WALLETS = [
    Wallet.from_api(
        {
            "id": "w1",
            "owner": "m1",
            "owner_name": "Ada Admin",
            "provider_code": "FAKE_ORANGE",
            "wallet_identifier": "690000001",
            "balance": "50000.00",
            "currency": "XAF",
            "status": "ACTIVE",
        }
    )
]
INVOICE = Invoice.from_api(
    {
        "id": "i1",
        "invoice_number": "F25-000001",
        "student": "s1",
        "student_name": "Awa Ndiaye",
        "issue_date": "2025-09-15",
        "due_date": "2025-10-15",
        "status": "ISSUED",
        "total_amount": "60000.00",
        "amount_paid": "0.00",
        "balance_due": "60000.00",
        "currency": "XAF",
        "lines": [{"description": "Scolarité", "total": "60000.00"}] * 4,
    }
)
PAYMENT = Payment.from_api(
    {
        "id": "p1",
        "payment_reference": "PAY-000001",
        "student": "s1",
        "student_name": "Awa Ndiaye",
        "amount": "60000.00",
        "refunded_amount": "10000.00",
        "currency": "XAF",
        "payment_method": "CASH",
        "provider": "CASH",
        "status": "PARTIALLY_REFUNDED",
        "initiated_at": "2026-03-04T10:00:00+01:00",
        "completed_at": "2026-03-04T10:00:01+01:00",
        "allocations": [{"invoice_number": "F25-000001", "amount": "60000.00"}],
        "refunds": [
            {
                "id": "r1",
                "amount": "10000.00",
                "reason": "Trop perçu " * 6,
                "status": "COMPLETED",
                "completed_at": "2026-03-05T10:00:00+01:00",
            }
        ],
    }
)
LINE = {
    "version": 1,
    "kind": "EARNED",
    "session_date": "2025-10-06",
    "duration_minutes": 120,
    "rate": "5000.00",
    "amount": "5000.00",
}
PAYROLL = Payroll.from_api(
    {
        "id": "pr1",
        "kind": "TEACHER",
        "employee": "e1",
        "employee_name": "Jean Mbarga",
        "period": "p1",
        "period_name": "Octobre 2025",
        "status": "CALCULATED",
        "version": 2,
        "adjustments_amount": "5000.00",
        "payable_amount": "15000.00",
        "currency": "XAF",
        "programmed_amount": "20000.00",
        "earned_amount": "10000.00",
        "lines": [LINE] * 12,
        "reconstructible": False,
    }
)


def _no_search(text, done):
    done([("s1", "Ndiaye Awa (MAT-001)")])


def _obligations(student_id, done):
    done([INVOICE] * 6)


MEMBERS = [Member(f"m{i}", f"Membre numéro {i} avec un nom long", ("TEACHER",)) for i in range(12)]
NOTE = Notification.from_api(
    {
        "id": "n1",
        "notification_type": "PAYMENT",
        "severity": "INFO",
        "title": "Paiement reçu",
        "message": "Votre paiement de 60 000 XAF a été reçu. " * 6,
        "is_read": False,
        "created_at": "2026-03-04T10:00:00+01:00",
    }
)
SPACES = [ForumSpace.from_api({"id": "s1", "name": "Annonces", "audience": "SCHOOL", "roles": ["TEACHER"]})]
THREAD = Thread.from_api(
    {
        "id": "t1",
        "space": "s1",
        "title": "Rentrée 2026",
        "status": "OPEN",
        "author_name": "Ada Admin",
        "created_at": "2026-03-04T10:00:00+01:00",
    }
)
POSTS = [
    Post.from_api(
        {
            "id": f"p{i}",
            "author_name": "Jean Mbarga",
            "body": "Texte du message. " * 10,
            "created_at": "2026-03-04T10:00:00+01:00",
        }
    )
    for i in range(8)
]
COMPLAINT = Complaint.from_api(
    {
        "id": "c1",
        "author": "m1",
        "category": "ADMINISTRATIVE",
        "subject": "Cantine froide",
        "description": "Description détaillée. " * 12,
        "status": "OPEN",
        "history": [
            {
                "old_status": "DRAFT",
                "new_status": "OPEN",
                "changed_by": "m1",
                "comment": "Soumise",
                "at": "2026-03-04T10:00:00+01:00",
            }
        ]
        * 6,
        "attachments": [{"id": "a1", "name": "photo.png", "mime_type": "image/png", "size_bytes": 2048}] * 3,
    }
)
DOCUMENT = Document.from_api(
    {
        "id": "d1",
        "kind": "PAYMENT_RECEIPT",
        "status": "PROVISIONAL",
        "title": "Reçu PAY-000001 — Awa Ndiaye",
        "version": 2,
        "file_name": "recu.pdf",
        "size_bytes": 20480,
        "sha256": "ab" * 32,
        "verification_code": "V001-CODE",
        "generated_at": "2026-03-04T10:00:00+01:00",
    }
)
DOC_SOURCES = {
    "search_students": _no_search,
    "load_cards": lambda student, done: done([{"id": "rc1", "period_name": "Trimestre 1", "status": "DRAFT"}]),
    "find_payments": lambda text, done: done([PAYMENT]),
    "classes": CLASSES,
    "teachers": [TEACHER],
    "payrolls": [PAYROLL],
}


ACCOUNT = AccountSummary("m1", "Jean Mbarga", "jean.mbarga@ecole.test", "PENDING_ACTIVATION")
ISSUED = type("Issued", (), {"code": "7KQ2-M9XA-4TZP-QH3W-B8NC", "expires_at": None, "account": ACCOUNT})()
LINK_REQUEST = LinkRequest(
    "lr1",
    "s0",
    "Élève Zéro Avec Un Très Long Nom Composé",
    "MAT00001",
    "3e A",
    "Marie-Christine Ndiaye Mbarga",
    "marie.ndiaye@example.cm",
    "+237 600 00 00 00",
    "LEGAL_GUARDIAN",
    "PENDING",
    "VERIFIED",
    "SPONSOR_2FA",
    "CNI",
    2,
    "APPROVED",
    "Confirmé en classe " * 8,
    True,
    "Paul Mbarga",
    None,
    "",
)


class StubTeachers:
    """Answers of the API for the qualifications dialog (layout tests only)."""

    def qualifications(self, _teacher_id):
        return QUALS

    def rules(self, _teacher_id):
        return []

    def overrides(self, _teacher_id):
        return []


DIALOGS = {
    "catégorie": lambda: CategoryDialog(),
    "matière": lambda: SubjectDialog(CATEGORIES),
    "classe": lambda: ClassDialog(YEARS, LEVELS, ROOMS),
    "année": lambda: YearDialog(suggested=(date(2026, 9, 1), date(2027, 7, 31))),
    "niveau": lambda: LevelDialog(),
    "élève (ajout)": lambda: StudentDialog((YEARS, LEVELS, CLASSES)),
    "élève (modification)": lambda: StudentDialog(None, student=STUDENT),
    "inscription": lambda: EnrollDialog((YEARS, LEVELS, CLASSES), student=STUDENT),
    "changement de classe": lambda: ChangeClassDialog(([], LEVELS, CLASSES), enrollment=ENROLLMENT),
    "fiche élève": lambda: StudentRecordDialog(STUDENT, [ENROLLMENT], []),
    "enseignant (ajout)": lambda: TeacherDialog(CATEGORIES, SUBJECTS),
    "enseignant (modification)": lambda: TeacherDialog(CATEGORIES, SUBJECTS, teacher=TEACHER),
    "qualifications": lambda: QualificationsDialog(TEACHER, StubTeachers(), ImmediateRunner(), SUBJECTS, LEVELS),
    "dérogation": lambda: ReasonDialog("Accorder une dérogation ?", "Texte " * 30, with_expiry=True),
    "fiche enseignant": lambda: TeacherRecordDialog(TEACHER, QUALS, []),
    "cours (ajout)": lambda: CourseDialog((YEARS, CLASSES, SUBJECTS, []), lambda c, s, done: done(([], []))),
    "fiche cours": lambda: CourseRecordDialog(COURSE),
    "créneau": lambda: SlotDialog([COURSE], ROOMS, lambda payload, done: done({"conflicts": []})),
    "fin de créneau": lambda: EndSlotDialog(SLOT),
    "reprogrammation": lambda: RescheduleDialog(SLOT, ROOMS),
    "génération": lambda: GenerateDialog(CLASSES, date(2026, 3, 2)),
    "fiche séance": lambda: SessionDialog(SESSION),
    "déplacement": lambda: MoveDialog(SESSION),
    "salle de séance": lambda: RoomChangeDialog(SESSION, ROOMS),
    "remplacement": lambda: SubstituteDialog(SESSION, [TEACHER]),
    "salle": lambda: RoomDialog(),
    "salle principale": lambda: MainRoomDialog(CLASSES, ROOMS),
    "indisponibilité": lambda: DecisionDialog(REQUEST, "Mbarga Jean", [SESSION] * 6),
    "interruption": lambda: BreakDialog(YEARS, school_break=BREAK),
    "paiement": lambda: PaymentDialog(
        FEE_TYPES, WALLETS, _no_search, _obligations, student=("s1", "Awa"), invoice="i1"
    ),
    "remboursement": lambda: RefundDialog(PAYMENT),
    "facture": lambda: InvoiceDialog(FEE_TYPES, _no_search),
    "motif de frais": lambda: FeeTypeDialog(),
    "détail paiement": lambda: PaymentDetailDialog(PAYMENT, can_refund=True),
    "détail facture": lambda: InvoiceDetailDialog(INVOICE),
    "période de paie": lambda: PeriodDialog(YEARS),
    "versement": lambda: PayDialog(PAYROLL, WALLETS),
    "détail paie": lambda: PayrollDetailDialog(PAYROLL),
    "correction": lambda: AdjustmentDialog([("e1", "Mbarga Jean (ENS-001)")]),
    "code d'activation": lambda: ActivationCodeDialog("Mbarga Jean", ISSUED),
    "rattachement (fiche)": lambda: LinkRequestDialog(LINK_REQUEST),
    "vérification d'identité": lambda: IdentityCheckDialog(LINK_REQUEST),
    "désignation par l'élève": lambda: StudentApprovalDialog(LINK_REQUEST),
    "validation du rattachement": lambda: LinkApprovalDialog(LINK_REQUEST),
    "fiche enseignant (compte)": lambda: TeacherRecordDialog(TEACHER, QUALS, [], account=ACCOUNT),
    "notification": lambda: NotificationDialog(NOTE),
    "nouvelle conversation": lambda: NewConversationDialog(MEMBERS),
    "participant": lambda: AddParticipantDialog(MEMBERS),
    "espace de forum": lambda: SpaceDialog(CLASSES),
    "publication": lambda: ThreadDialog(SPACES),
    "sujet du forum": lambda: ThreadViewDialog(THREAD, POSTS),
    "réclamation": lambda: ComplaintDialog(COMPLAINT, {"m1": "Parent Ndiaye"}),
    "statut de réclamation": lambda: ComplaintStatusDialog(COMPLAINT, MEMBERS),
    "document (détail)": lambda: DocumentDetailDialog(DOCUMENT),
    "vérification": lambda: VerifyDialog(),
    "calcul des bulletins": lambda: ComputeReportCardsDialog(CLASSES, [{"id": "p1", "name": "Trimestre 1"}]),
    **{
        f"génération {kind}": (lambda kind=kind: GenerateDocumentDialog(kind, DOC_SOURCES))
        for kind in (
            "REPORT_CARD",
            "STUDENT_CARD",
            "TIMETABLE",
            "PAYMENT_RECEIPT",
            "PAYSLIP",
            "STUDENT_ATTENDANCE",
            "CLASS_ATTENDANCE",
        )
    },
    "rémunération": lambda: TeacherPayDialog(
        TEACHER,
        {"programmed_amount": Decimal("20000"), "earned_unpaid_amount": Decimal("10000"), "paid_amount": Decimal("0")},
        [PAYROLL] * 5,
        2,
        date(2025, 9, 1),
        date(2026, 7, 31),
    ),
    "confirmation": lambda: ConfirmDialog("Désactiver ?", "Texte explicatif " * 20, danger=True),
}
SCREENS = [QSize(1366, 768), QSize(1280, 720), QSize(1024, 768), QSize(800, 480)]


def on_screen(dialog, screen):
    """Show the dialog as it would open on a screen of size `screen`."""
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    dialog.fit_to(screen)
    dialog.layout().activate()
    QApplication.processEvents()
    return dialog


def inside(widget, dialog):
    top_left = widget.mapTo(dialog, widget.rect().topLeft())
    bottom_right = widget.mapTo(dialog, widget.rect().bottomRight())
    return dialog.rect().contains(top_left) and dialog.rect().contains(bottom_right)


@pytest.mark.parametrize("screen", SCREENS, ids=lambda s: f"{s.width()}x{s.height()}")
@pytest.mark.parametrize("name", DIALOGS)
def test_dialog_fits_and_keeps_its_buttons(qapp, name, screen):
    dialog = on_screen(DIALOGS[name](), screen)
    assert dialog.width() <= screen.width() - SCREEN_MARGIN and dialog.height() <= screen.height() - SCREEN_MARGIN
    for action in (dialog.cancel_button, dialog.save_button):
        if action.isHidden():  # the record has only « Fermer »
            continue
        assert action.isVisible() and inside(action, dialog), f"{action.text()} hors de la fenêtre"
        assert action.width() >= action.minimumSizeHint().width()
    assert inside(dialog.footer, dialog)
    # Nothing is cut sideways: the form never needs a horizontal scroll bar.
    assert dialog.content.width() <= dialog.scroll.viewport().width()
    for label in dialog.content.findChildren(QLabel):
        if label.isVisible():
            assert label.mapTo(dialog.content, label.rect().bottomRight()).x() <= dialog.content.width()
    dialog.close()


@pytest.mark.parametrize("name", ["catégorie", "matière", "classe", "année", "niveau"])
def test_no_scroll_needed_on_usual_screens(qapp, name):
    for screen in (QSize(1366, 768), QSize(1280, 720)):
        dialog = on_screen(DIALOGS[name](), screen)
        assert not dialog.scroll.verticalScrollBar().isVisible(), f"{name} défile à {screen}"
        dialog.close()


def test_dialogs_stay_reasonably_narrow(qapp):
    for name, factory in DIALOGS.items():
        dialog = on_screen(factory(), QSize(1920, 1080))
        assert dialog.width() <= 640, name  # never stretched across the screen
        dialog.close()


def test_long_form_scrolls_with_fixed_buttons_and_follows_the_focus(qapp):
    dialog = ClassDialog(YEARS, LEVELS, ROOMS)
    on_screen(dialog, QSize(1024, 420))  # very short screen: the form must scroll
    bar = dialog.scroll.verticalScrollBar()
    assert bar.isVisible() and bar.maximum() > 0
    assert dialog.save_button.isVisible() and inside(dialog.save_button, dialog)
    dialog.name.setText("6e A")
    dialog.level.setCurrentIndex(1)
    dialog.activateWindow()
    dialog.name.setFocus()
    for _ in range(12):  # Tab down to the last field
        if dialog.focusWidget() is dialog.public_visible:
            break
        QTest.keyClick(dialog.focusWidget(), Qt.Key_Tab)
    assert dialog.focusWidget() is dialog.public_visible
    assert bar.value() > 0  # the form scrolled to the focused field
    viewport = dialog.scroll.viewport()
    field = dialog.public_visible
    assert viewport.rect().contains(field.mapTo(viewport, field.rect().center()))
    QTest.keyClick(dialog.public_visible, Qt.Key_Return)  # Enter saves, even scrolled down
    assert dialog.result() == QDialog.Accepted


def test_escape_closes_a_scrolled_dialog(qapp):
    dialog = on_screen(LevelDialog(), QSize(1024, 400))
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert not dialog.isVisible() and dialog.result() == QDialog.Rejected


def test_field_widths_match_their_data(qapp):
    level = on_screen(LevelDialog(), QSize(1366, 768))
    assert level.code.width() <= FIELD_WIDTHS["short"] and level.order.width() <= FIELD_WIDTHS["short"]
    assert level.name.width() <= FIELD_WIDTHS["medium"] and level.prefix.width() <= FIELD_WIDTHS["short"]
    year = on_screen(YearDialog(), QSize(1366, 768))
    assert year.start.width() <= FIELD_WIDTHS["short"] and year.end.width() <= FIELD_WIDTHS["short"]
    category = on_screen(CategoryDialog(), QSize(1366, 768))
    assert category.description.width() > category.code.width() * 2  # free text keeps the width
    for dialog in (level, year, category):
        dialog.close()


def test_side_by_side_fields_stack_on_a_narrow_dialog(qapp):
    dialog = on_screen(ClassDialog(YEARS, LEVELS, ROOMS), QSize(1366, 768))
    assert not dialog.rows[0].stacked  # Nom | Capacité
    assert (
        dialog.name.mapTo(dialog, dialog.name.rect().topLeft()).y()
        == dialog.capacity.mapTo(dialog, dialog.capacity.rect().topLeft()).y()
    )
    on_screen(dialog, QSize(470, 700))  # narrow screen: one column
    assert dialog.rows[0].stacked and dialog.rows[1].stacked
    assert (
        dialog.capacity.mapTo(dialog, dialog.capacity.rect().topLeft()).y()
        > dialog.name.mapTo(dialog, dialog.name.rect().bottomLeft()).y()
    )
    assert inside(dialog.save_button, dialog)
    dialog.close()


def test_long_list_items_do_not_widen_the_form(qapp):
    rooms = [Room("r1", "R12", "Salle polyvalente du bâtiment des sciences, aile nord, premier étage", 40, True)]
    dialog = on_screen(ClassDialog(YEARS, LEVELS, rooms), QSize(1280, 720))
    assert dialog.main_room.width() <= FIELD_WIDTHS["medium"]
    dialog.main_room.setCurrentIndex(1)
    assert dialog.main_room.toolTip().startswith("R12 — Salle polyvalente")  # full text on hover
    assert dialog.main_room.view().minimumWidth() > dialog.main_room.width()  # open list shows it whole
    dialog.close()


@pytest.mark.parametrize("screen", [QSize(1366, 768), QSize(1280, 720)], ids=["1366x768", "1280x720"])
def test_long_student_form_scrolls_with_buttons_always_visible(qapp, screen):
    dialog = on_screen(StudentDialog((YEARS, LEVELS, CLASSES)), screen)
    bar = dialog.scroll.verticalScrollBar()
    assert dialog.height() <= screen.height() - SCREEN_MARGIN
    assert bar.isVisible() and bar.maximum() > 0  # the FORM scrolls, not the window
    assert inside(dialog.save_button, dialog) and inside(dialog.cancel_button, dialog)
    for field in (dialog.student_number, dialog.registration_number, dialog.date_of_birth, dialog.height_cm):
        assert field.width() <= FIELD_WIDTHS["short"]  # short data, short field
    for field in (dialog.last_name, dialog.first_name):
        assert field.width() <= FIELD_WIDTHS["medium"]
    dialog.activateWindow()
    dialog.student_number.setFocus()
    for _ in range(30):  # Tab down to the class list at the bottom of the form
        if dialog.focusWidget() is dialog.enroll:
            break
        QTest.keyClick(dialog.focusWidget(), Qt.Key_Tab)
    assert dialog.focusWidget() is dialog.enroll and bar.value() > 0
    viewport = dialog.scroll.viewport()
    assert viewport.rect().contains(dialog.enroll.mapTo(viewport, dialog.enroll.rect().center()))
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert dialog.result() == QDialog.Rejected


@pytest.mark.parametrize("screen", [QSize(1280, 720), QSize(1024, 768)], ids=["1280x720", "1024x768"])
def test_long_teacher_form_scrolls_with_buttons_always_visible(qapp, screen):
    dialog = on_screen(TeacherDialog(CATEGORIES, SUBJECTS, teacher=TEACHER), screen)
    bar = dialog.scroll.verticalScrollBar()
    assert dialog.height() <= screen.height() - SCREEN_MARGIN
    assert bar.isVisible() and bar.maximum() > 0
    assert inside(dialog.save_button, dialog) and inside(dialog.cancel_button, dialog)
    assert dialog.employee_number.width() <= FIELD_WIDTHS["short"] and dialog.phone.width() <= FIELD_WIDTHS["short"]
    assert dialog.email.width() <= FIELD_WIDTHS["medium"] and dialog.last_name.width() <= FIELD_WIDTHS["medium"]
    dialog.activateWindow()
    dialog.last_name.setFocus()
    for _ in range(30):  # Tab down to the last field
        if dialog.focusWidget() is dialog.bio:
            break
        QTest.keyClick(dialog.focusWidget(), Qt.Key_Tab)
    assert dialog.focusWidget() is dialog.bio and bar.value() > 0
    viewport = dialog.scroll.viewport()
    assert viewport.rect().contains(dialog.bio.mapTo(viewport, dialog.bio.rect().center()))
    dialog.close()


def test_course_form_scrolls_with_buttons_always_visible(qapp):
    dialog = CourseDialog((YEARS, CLASSES, SUBJECTS, []), lambda c, s, done: done(([], [])))
    on_screen(dialog, QSize(1024, 520))
    bar = dialog.scroll.verticalScrollBar()
    assert bar.isVisible() and bar.maximum() > 0
    assert inside(dialog.save_button, dialog) and inside(dialog.cancel_button, dialog)
    assert dialog.coefficient.width() <= FIELD_WIDTHS["short"] and dialog.weekly_hours.width() <= FIELD_WIDTHS["short"]
    dialog.activateWindow()
    dialog.year.setFocus()
    for _ in range(20):  # Tab down to the last field
        if dialog.focusWidget() is dialog.scale:
            break
        QTest.keyClick(dialog.focusWidget(), Qt.Key_Tab)
    assert dialog.focusWidget() is dialog.scale and bar.value() > 0
    dialog.close()


def test_slot_form_scrolls_with_buttons_always_visible(qapp):
    dialog = SlotDialog([COURSE], ROOMS, lambda payload, done: done({"conflicts": []}))
    on_screen(dialog, QSize(800, 480))
    assert inside(dialog.save_button, dialog) and inside(dialog.cancel_button, dialog)
    assert dialog.start_time.width() <= FIELD_WIDTHS["short"] and dialog.end_time.width() <= FIELD_WIDTHS["short"]
    dialog.close()


def test_payment_form_scrolls_with_buttons_always_visible(qapp):
    dialog = PaymentDialog(FEE_TYPES, WALLETS, _no_search, _obligations, student=("s1", "Awa"), invoice="i1")
    on_screen(dialog, QSize(800, 480))
    assert inside(dialog.save_button, dialog) and inside(dialog.cancel_button, dialog)
    assert dialog.amount.width() <= FIELD_WIDTHS["short"]
    dialog.close()
