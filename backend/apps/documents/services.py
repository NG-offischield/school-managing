"""Document services (ADR 0016).

generate(): source -> build content -> fingerprint ->
    same fingerprint as the current document   -> that document (idempotent)
    current document OFFICIAL                  -> that document, never regenerated
    current PROVISIONAL, source changed        -> new version, previous SUPERSEDED
    nothing yet                                -> version 1
The PDF goes to the private storage under a random name; generation is
audited (AuditLog), downloads are traced (DocumentDownload).

Rights (spec §8, reusing the existing relations — nothing copied):
    admin of the school      every document of the school (provisional ones included)
    parent                   official report cards and attendance statements of a
                             child (ACTIVE + VERIFIED link); receipts with the link's
                             `can_view_financial_data`
    payer                    the receipts of the payments they made
    employee                 their own payslips
    teacher                  the attendance register of a class they teach
    anybody else             nothing (404)
"""

import hashlib
import json
import secrets
import uuid
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import record_audit
from apps.communication import access as relations
from apps.communication.attachments import private_storage
from apps.finance.services import can_view_finance
from apps.payroll.models import TeacherPayroll
from apps.people.models import ParentStudent
from common.permissions import membership_has_role

from . import builders, rendering
from .models import Document, DocumentDownload, DocumentKind, DocumentStatus


def fingerprint(content):
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# =============================================================================
# Sources and rights
# =============================================================================


def _source_filter(kind, source, params_key=""):
    columns = {
        DocumentKind.REPORT_CARD: "report_card",
        DocumentKind.PAYMENT_RECEIPT: "payment",
        DocumentKind.STUDENT_ATTENDANCE: "student",
        DocumentKind.CLASS_ATTENDANCE: "school_class",
    }
    if kind == DocumentKind.PAYSLIP:
        column = "teacher_payroll" if isinstance(source, TeacherPayroll) else "staff_payroll"
    else:
        column = columns[kind]
    return {"kind": kind, column: source, "params_key": params_key}


def _employee_membership_id(payroll):
    employee = payroll.teacher.employee if isinstance(payroll, TeacherPayroll) else payroll.staff.employee
    return employee.membership_id


def can_access(member, kind, source, *, official=True):
    """May `member` obtain the document of `kind` for `source`? `official`
    False = a provisional document (administration only for report cards)."""
    if member is None or source.school_id != member.school_id:
        return False
    if relations.is_admin(member):
        return True
    if kind == DocumentKind.REPORT_CARD:
        return official and relations.parent_of(member, source.student)
    if kind == DocumentKind.PAYMENT_RECEIPT:
        return source.payer_id == member.pk or (
            relations.parent_of(member, source.student) and can_view_finance(member, source.student)
        )
    if kind == DocumentKind.PAYSLIP:
        return _employee_membership_id(source) == member.pk
    if kind == DocumentKind.STUDENT_ATTENDANCE:
        return relations.parent_of(member, source)
    if kind == DocumentKind.CLASS_ATTENDANCE:
        return (
            membership_has_role(member, {"TEACHER"})
            and source.courses.filter(active=True, teacher__employee__membership=member).exists()
        )
    return False


def _source_of(document):
    for field in ("report_card", "payment", "teacher_payroll", "staff_payroll", "student", "school_class"):
        value = getattr(document, field)
        if value is not None:
            return value
    raise ValueError("document without source")


def can_read(member, document):
    if member is None or document.school_id != member.school_id:
        return False
    if document.kind == DocumentKind.REPORT_CARD and not relations.is_admin(member):
        if document.status != DocumentStatus.OFFICIAL:
            return False  # provisional bulletins stay with the administration
    return can_access(member, document.kind, _source_of(document))


def visible_documents(member):
    """Documents the member may list (same rules as can_read, as a query)."""
    documents = Document.objects.filter(school=member.school)
    if relations.is_admin(member):
        return documents
    children = ParentStudent.objects.filter(parent__membership=member, active=True, identity_verified=True)
    finance_children = children.filter(can_view_financial_data=True).values("student_id")
    return documents.filter(
        Q(
            kind=DocumentKind.REPORT_CARD,
            status=DocumentStatus.OFFICIAL,
            report_card__student__in=children.values("student_id"),
        )
        | Q(kind=DocumentKind.PAYMENT_RECEIPT, payment__payer=member)
        | Q(kind=DocumentKind.PAYMENT_RECEIPT, payment__student__in=finance_children)
        | Q(kind=DocumentKind.PAYSLIP, teacher_payroll__teacher__employee__membership=member)
        | Q(kind=DocumentKind.PAYSLIP, staff_payroll__staff__employee__membership=member)
        | Q(kind=DocumentKind.STUDENT_ATTENDANCE, student__in=children.values("student_id"))
        | Q(
            kind=DocumentKind.CLASS_ATTENDANCE,
            school_class__courses__active=True,
            school_class__courses__teacher__employee__membership=member,
        )
    ).distinct()


# =============================================================================
# Generation
# =============================================================================


def _build(kind, source, params):
    if kind == DocumentKind.REPORT_CARD:
        return builders.report_card(source)
    if kind == DocumentKind.PAYMENT_RECEIPT:
        return builders.payment_receipt(source)
    if kind == DocumentKind.PAYSLIP:
        return builders.payslip(source)
    if kind == DocumentKind.STUDENT_ATTENDANCE:
        return builders.student_attendance(source, params["date_from"], params["date_to"])
    if kind == DocumentKind.CLASS_ATTENDANCE:
        return builders.class_attendance(source, params["date"])
    raise ValidationError("Unknown document kind.", code="invalid_kind")


def _params(kind, params):
    if kind == DocumentKind.STUDENT_ATTENDANCE:
        stored = {"date_from": params["date_from"].isoformat(), "date_to": params["date_to"].isoformat()}
        return stored, f"{stored['date_from']}:{stored['date_to']}"
    if kind == DocumentKind.CLASS_ATTENDANCE:
        return {"date": params["date"].isoformat()}, params["date"].isoformat()
    return {}, ""


def generate(kind, source, *, actor, **params):
    """Returns (document, created)."""
    if kind not in DocumentKind.values:
        raise ValidationError("Unknown document kind.", code="invalid_kind")
    if source.school_id != actor.school_id:
        raise PermissionDenied("Source of another school.")
    if not can_access(actor, kind, source):
        raise PermissionDenied("You cannot obtain this document.")
    built = _build(kind, source, params)  # re-reads the source; may refuse a non-final one
    if built.status != DocumentStatus.OFFICIAL and not can_access(actor, kind, source, official=False):
        raise ValidationError("This document is not official yet.", code="document_source_not_final")
    stored_params, params_key = _params(kind, params)
    lookup = _source_filter(kind, source, params_key)
    digest = fingerprint(built.content)
    try:
        with transaction.atomic():
            return _store(kind, source, actor, built, digest, stored_params, lookup)
    except IntegrityError:
        # Two simultaneous generations of the same document: the other won.
        current = Document.objects.exclude(status=DocumentStatus.SUPERSEDED).get(**lookup)
        return current, False


def _store(kind, source, actor, built, digest, stored_params, lookup):
    current = Document.objects.select_for_update().exclude(status=DocumentStatus.SUPERSEDED).filter(**lookup).first()
    if current is not None and (current.fingerprint == digest or current.status == DocumentStatus.OFFICIAL):
        return current, False  # idempotent / an official document is never regenerated
    version = 1
    if current is not None:
        version = current.version + 1
        current.status = DocumentStatus.SUPERSEDED
        current.save(update_fields=["status", "updated_at"])
    now = timezone.now()
    code = secrets.token_hex(8).upper()
    pdf = rendering.render(
        built.content,
        school=source.school,
        status=built.status,
        verification_code=code,
        generated_label=f"généré le {timezone.localtime(now):%d/%m/%Y %H:%M}",
    )
    path = private_storage().save(
        f"documents/{source.school_id.hex}/{now:%Y/%m}/{uuid.uuid4().hex}.pdf", ContentFile(pdf)
    )
    try:
        document = Document.objects.create(
            school=source.school,
            status=built.status,
            title=built.title[:200],
            params=stored_params,
            content=built.content,
            fingerprint=digest,
            version=version,
            verification_code=code,
            storage_path=path,
            file_name=built.file_name[:200],
            size_bytes=len(pdf),
            sha256=hashlib.sha256(pdf).hexdigest(),
            generated_by=actor,
            generated_at=now,
            **lookup,
        )
    except Exception:
        private_storage().delete(path)  # no orphan file
        raise
    record_audit(
        "DOCUMENT_GENERATED",
        actor=actor,
        entity=document,
        new={
            "kind": document.kind,
            "status": document.status,
            "version": version,
            "fingerprint": digest,
            "superseded": str(current.pk) if current else None,
        },
    )
    return document, True


def regenerate(document, *, actor):
    """Administration only, and only for a PROVISIONAL current document:
    an official document is frozen, a superseded one is history."""
    if not relations.is_admin(actor, document.school):
        raise PermissionDenied("Only the administration regenerates documents.")
    if document.status == DocumentStatus.OFFICIAL:
        raise ValidationError("An official document is never regenerated.", code="document_official")
    if document.status == DocumentStatus.SUPERSEDED:
        raise ValidationError("This document was replaced.", code="document_superseded")
    params = {}
    if document.kind == DocumentKind.STUDENT_ATTENDANCE:
        params = {"date_from": _date(document.params["date_from"]), "date_to": _date(document.params["date_to"])}
    elif document.kind == DocumentKind.CLASS_ATTENDANCE:
        params = {"date": _date(document.params["date"])}
    return generate(document.kind, _source_of(document), actor=actor, **params)


def _date(value):
    return date.fromisoformat(value)


def open_for_download(document, *, actor):
    if not can_read(actor, document):
        raise PermissionDenied("Not allowed.")
    DocumentDownload.objects.create(
        school=document.school, document=document, actor=actor, downloaded_at=timezone.now()
    )
    return private_storage().open(document.storage_path, "rb")


def verify(code, *, actor):
    """Authenticity check of a printed document: same school only, minimal
    metadata (no content)."""
    document = Document.objects.filter(school=actor.school, verification_code=(code or "").strip().upper()).first()
    if document is None:
        return None
    return {
        "valid": True,
        "kind": document.kind,
        "status": document.status,
        "title": document.title if can_read(actor, document) else None,
        "generated_at": document.generated_at,
        "sha256": document.sha256,
        "current": document.status != DocumentStatus.SUPERSEDED,
    }
