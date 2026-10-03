"""Content builders (ADR 0016): source rows -> the exact data a PDF shows.

Each builder only READS its source domain and returns a Built(content,
status, title, file_name). `content` is plain JSON (strings, numbers),
deterministic for a given source state: its sha256 is the document's
fingerprint, so "same source, same document" and "source changed, new
version" are decided by comparing fingerprints. Nothing here writes to the
source domains.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.attendance.models import DailyStatus, StudentDailyAttendance
from apps.finance.models import MONEY_RECEIVED, PaymentAllocation
from apps.gradebook.models import ReportCardStatus
from apps.payroll.models import LineKind, PayrollLine, PayrollStatus, TeacherPayroll
from apps.people.models import EnrollmentStatus, StudentEnrollment
from apps.scheduling.models import TeachingSession

from .models import DocumentStatus

MAX_ATTENDANCE_DAYS = 366


@dataclass
class Built:
    content: dict
    status: str
    title: str
    file_name: str


def not_final(message):
    return ValidationError(message, code="document_source_not_final")


def _money(value, currency):
    return f"{value:,.2f} {currency}".replace(",", " ")


def _num(value):
    """Decimal without useless zeros: 20.00 -> "20", 2.50 -> "2.5"."""
    return format(value.normalize(), "f")


def _d(value):
    return value.strftime("%d/%m/%Y") if value else ""


def _dt(value):
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if value else ""


def school_block(school):
    """Identity and branding, read from School / SchoolBranding (never hard-coded)."""
    branding = getattr(school, "branding", None)
    return {
        "name": school.name,
        "legal_name": school.legal_name or "",
        "short_name": school.short_name or "",
        "address": school.address,
        "city": school.city,
        "country": school.country,
        "phone": school.phone or "",
        "email": school.email or "",
        "website": school.website or "",
        "primary_color": branding.primary_color if branding else "#173B73",
        "secondary_color": branding.secondary_color if branding else "#36A2EB",
        "logo": school.logo.name if school.logo else "",
    }


def _student_class(student, academic_year):
    enrollment = (
        StudentEnrollment.objects.filter(student=student, academic_year=academic_year)
        .select_related("school_class")
        .first()
    )
    return enrollment.school_class.name if enrollment else ""


# =============================================================================
# Report card (gradebook)
# =============================================================================


def report_card(card):
    period = card.academic_period
    scale = _num(card.scale_max_score)
    lines = sorted(card.lines.select_related("subject"), key=lambda line: line.subject.name)
    validated = card.status == ReportCardStatus.VALIDATED
    content = {
        "kind": "REPORT_CARD",
        "title": "Bulletin de notes",
        "subtitle": f"{period.name} — {period.academic_year.name}",
        "school": school_block(card.school),
        "fields": [
            ["Élève", card.student.full_name],
            ["Matricule", card.student.student_number],
            ["Né(e) le", _d(card.student.date_of_birth)],
            ["Classe", _student_class(card.student, period.academic_year)],
            ["Année scolaire", period.academic_year.name],
            ["Période", period.name],
        ],
        "tables": [
            {
                "title": "Résultats",
                "columns": ["Matière", "Enseignant", f"Moyenne /{scale}", "Coef.", "Points", "Appréciation"],
                "rows": [
                    [
                        line.subject.name,
                        line.teacher_name_snapshot or "",
                        f"{line.average:.2f}",
                        _num(line.coefficient),
                        f"{line.weighted_average:.2f}",
                        line.appreciation or "",
                    ]
                    for line in lines
                ],
            }
        ],
        "summary": [
            ["Moyenne générale", f"{card.general_average:.2f} / {scale}" if card.general_average is not None else "—"],
            ["Rang", f"{card.rank} / {card.class_size}" if card.rank else "—"],
        ],
        "statement": (
            f"Bulletin validé le {_d(card.validated_at)} par "
            f"{card.validated_by.user.full_name if card.validated_by else 'l’administration'}."
            if validated
            else "Bulletin non validé : résultats provisoires, susceptibles de changer."
        ),
    }
    status = DocumentStatus.OFFICIAL if validated else DocumentStatus.PROVISIONAL
    name = f"bulletin-{card.student.student_number}-{period.name}".replace(" ", "-")
    return Built(content, status, f"Bulletin — {card.student.full_name} — {period.name}", f"{name}.pdf")


# =============================================================================
# Payment receipt (finance)
# =============================================================================


def payment_receipt(payment):
    """Only the immutable facts of the transaction: the receipt of a payment
    never changes, whatever happens later (refunds have their own record)."""
    if payment.status not in MONEY_RECEIVED:
        raise not_final("Only a received payment has a receipt.")
    currency = payment.currency
    allocations = (
        PaymentAllocation.objects.filter(payment=payment, refund__isnull=True)
        .select_related("invoice")
        .order_by("invoice__invoice_number")
    )
    reason = payment.fee_type.name if payment.fee_type else ", ".join(a.invoice.invoice_number for a in allocations)
    content = {
        "kind": "PAYMENT_RECEIPT",
        "title": "Reçu de paiement",
        "subtitle": payment.payment_reference,
        "school": school_block(payment.school),
        "fields": [
            ["Référence", payment.payment_reference],
            ["Référence fournisseur", payment.provider_reference or ""],
            ["Date", _dt(payment.completed_at)],
            ["Payeur", payment.payer.user.full_name],
            ["Élève", f"{payment.student.full_name} ({payment.student.student_number})"],
            ["Motif", reason],
            ["Moyen de paiement", f"{payment.get_payment_method_display()} — {payment.provider}"],
            ["Statut", "Paiement reçu"],
            ["Montant", _money(payment.amount, currency)],
        ],
        "tables": [
            {
                "title": "Affectation aux factures",
                "columns": ["Facture", "Montant affecté"],
                "rows": [[a.invoice.invoice_number, _money(a.amount, currency)] for a in allocations],
            }
        ]
        if allocations
        else [],
        "summary": [["Montant payé", _money(payment.amount, currency)]],
        "statement": "Reçu établi à partir de la transaction enregistrée ; il ne vaut pas facture.",
    }
    return Built(
        content, DocumentStatus.OFFICIAL, f"Reçu {payment.payment_reference}", f"recu-{payment.payment_reference}.pdf"
    )


# =============================================================================
# Payslip (payroll)
# =============================================================================


def payslip(payroll):
    if payroll.status not in (PayrollStatus.APPROVED, PayrollStatus.PAID):
        raise not_final("Only an approved or paid payroll has a payslip.")
    teacher = isinstance(payroll, TeacherPayroll)
    employee = payroll.teacher.employee if teacher else payroll.staff.employee
    period = payroll.payroll_period
    currency = payroll.currency
    owner = {"teacher_payroll": payroll} if teacher else {"staff_payroll": payroll}
    lines = PayrollLine.objects.filter(**owner, version=payroll.version).select_related("adjustment")
    tables = []
    if teacher:
        earned = lines.filter(kind=LineKind.EARNED).order_by("session_date", "id")
        tables.append(
            {
                "title": "Séances validées (rémunération acquise)",
                "columns": ["Date", "Durée (min)", "Taux / vacation", "Montant", "Rattrapage"],
                "rows": [
                    [
                        _d(line.session_date),
                        str(line.duration_minutes),
                        _money(line.rate, currency),
                        _money(line.amount, currency),
                        "oui" if line.late else "",
                    ]
                    for line in earned
                ],
            }
        )
    adjustments = lines.filter(kind=LineKind.ADJUSTMENT).order_by("id")
    if adjustments:
        tables.append(
            {
                "title": "Ajustements",
                "columns": ["Motif", "Montant"],
                "rows": [[line.adjustment.reason, _money(line.amount, currency)] for line in adjustments],
            }
        )
    summary = (
        [
            ["Rémunération programmée", _money(payroll.programmed_amount, currency)],
            ["Rémunération acquise", _money(payroll.earned_amount, currency)],
        ]
        if teacher
        else [["Salaire de base", _money(payroll.base_salary, currency)]]
    )
    summary += [
        ["Ajustements", _money(payroll.adjustments_amount, currency)],
        ["Net validé", _money(payroll.approved_amount, currency)],
    ]
    paid = payroll.status == PayrollStatus.PAID
    if paid:
        summary += [
            ["Montant payé", _money(payroll.approved_amount, currency)],
            ["Référence financière", payroll.payment_reference],
            ["Payé le", _dt(payroll.paid_at)],
        ]
    content = {
        "kind": "PAYSLIP",
        "title": "Bulletin de paie",
        "subtitle": f"{period.name} ({_d(period.start_date)} – {_d(period.end_date)})",
        "school": school_block(payroll.school),
        "fields": [
            ["Employé", employee.membership.user.full_name],
            ["Matricule", employee.employee_number],
            ["Fonction", "Enseignant" if teacher else "Personnel"],
            ["Période", period.name],
            ["Statut", payroll.get_status_display()],
        ],
        "tables": tables,
        "summary": summary,
        "statement": (
            f"Paie validée le {_d(payroll.approved_at)} et versée le {_d(payroll.paid_at)}."
            if paid
            else f"Paie validée le {_d(payroll.approved_at)}, en attente de paiement."
        ),
    }
    status = DocumentStatus.OFFICIAL if paid else DocumentStatus.PROVISIONAL
    return Built(
        content,
        status,
        f"Bulletin de paie — {employee.membership.user.full_name} — {period.name}",
        f"paie-{employee.employee_number}-{period.name}.pdf".replace(" ", "-"),
    )


# =============================================================================
# Attendance (attendance + scheduling)
# =============================================================================


def _check_range(date_from, date_to):
    if date_to < date_from or (date_to - date_from).days >= MAX_ATTENDANCE_DAYS:
        raise ValidationError("Invalid date range.", code="invalid_range")


def _final(records, last_day):
    """Official only for a past range whose records are all finalised."""
    return last_day < timezone.localdate() and records and all(r.finalized_at for r in records)


def student_attendance(student, date_from, date_to):
    _check_range(date_from, date_to)
    records = list(
        StudentDailyAttendance.objects.filter(student=student, date__gte=date_from, date__lte=date_to).order_by("date")
    )
    counts = {status: sum(1 for r in records if r.status == status) for status in DailyStatus.values}
    content = {
        "kind": "STUDENT_ATTENDANCE",
        "title": "Relevé de présence",
        "subtitle": f"Du {_d(date_from)} au {_d(date_to)}",
        "school": school_block(student.school),
        "fields": [
            ["Élève", student.full_name],
            ["Matricule", student.student_number],
            ["Période", f"{_d(date_from)} – {_d(date_to)}"],
        ],
        "tables": [
            {
                "title": "Journal",
                "columns": ["Date", "Statut", "Arrivée", "Retard (min)", "Heures d'absence"],
                "rows": [
                    [
                        _d(r.date),
                        r.get_status_display(),
                        _dt(r.arrival_time)[-5:] if r.arrival_time else "",
                        str(r.late_minutes or ""),
                        _num(r.absence_hours) if r.absence_hours else "",
                    ]
                    for r in records
                ],
            }
        ],
        "summary": [
            ["Présences", str(counts[DailyStatus.PRESENT])],
            ["Retards", str(counts[DailyStatus.LATE])],
            ["Absences", str(counts[DailyStatus.ABSENT])],
            ["Absences justifiées", str(counts[DailyStatus.EXCUSED])],
            ["Heures d'absence", _num(sum((r.absence_hours for r in records), Decimal("0")))],
        ],
        "statement": (
            "Relevé établi à partir des journées clôturées."
            if _final(records, date_to)
            else "Relevé provisoire : certaines journées ne sont pas encore clôturées."
        ),
    }
    status = DocumentStatus.OFFICIAL if _final(records, date_to) else DocumentStatus.PROVISIONAL
    return Built(
        content,
        status,
        f"Relevé de présence — {student.full_name}",
        f"presence-{student.student_number}-{date_from}-{date_to}.pdf",
    )


def class_attendance(school_class, day):
    enrollments = (
        StudentEnrollment.objects.filter(school_class=school_class)
        .exclude(status=EnrollmentStatus.WITHDRAWN)
        .select_related("student")
        .order_by("student__last_name", "student__first_name")
    )
    records = {
        r.student_id: r
        for r in StudentDailyAttendance.objects.filter(student__in=[e.student for e in enrollments], date=day)
    }
    final = _final(list(records.values()), day)
    sessions = (
        TeachingSession.objects.filter(school_class=school_class, date=day)
        .select_related("subject", "teacher__employee__membership__user")
        .order_by("scheduled_start")
    )
    content = {
        "kind": "CLASS_ATTENDANCE",
        "title": "Registre de présence",
        "subtitle": f"{school_class.name} — {_d(day)}",
        "school": school_block(school_class.school),
        "fields": [["Classe", school_class.name], ["Date", _d(day)], ["Effectif", str(len(enrollments))]],
        "tables": [
            {
                "title": "Élèves",
                "columns": ["Élève", "Matricule", "Statut", "Arrivée", "Retard (min)"],
                "rows": [
                    [
                        e.student.full_name,
                        e.student.student_number,
                        records[e.student_id].get_status_display() if e.student_id in records else "Non relevé",
                        _dt(records[e.student_id].arrival_time)[-5:]
                        if e.student_id in records and records[e.student_id].arrival_time
                        else "",
                        str(records[e.student_id].late_minutes or "") if e.student_id in records else "",
                    ]
                    for e in enrollments
                ],
            },
            {
                "title": "Séances du jour",
                "columns": ["Horaire", "Matière", "Enseignant", "Statut"],
                "rows": [
                    [
                        f"{timezone.localtime(s.scheduled_start):%H:%M}–{timezone.localtime(s.scheduled_end):%H:%M}",
                        s.subject.name,
                        s.teacher.employee.membership.user.full_name,
                        s.get_status_display(),
                    ]
                    for s in sessions
                ],
            },
        ],
        "summary": [],
        "statement": ("Journée clôturée." if final else "Journée non clôturée : registre provisoire."),
    }
    status = DocumentStatus.OFFICIAL if final else DocumentStatus.PROVISIONAL
    return Built(
        content,
        status,
        f"Registre — {school_class.name} — {_d(day)}",
        f"registre-{school_class.name}-{day}.pdf".replace(" ", "-"),
    )
