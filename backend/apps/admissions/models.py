"""Pre-enrollment requests from the public site (ADR 0032).

A pre-enrollment is a family's REQUEST, not an enrollment:
- accepting it does not create a pupil, does not link a parent to a child and
  opens no school data;
- the invitation it allows creates (or reuses nothing of) a parent ACCOUNT of
  the school: ACTIVE membership, role PARENT, parent profile, WITHOUT any
  child link — exactly what an approved parent registration gives (ADR 0026).
  Access to a pupil's data still requires the verified link workflow.

The invitation reuses the account activation of ADR 0024 (single-use code,
SHA-256 stored, expiry, revocation, anti-enumeration): the link sent to the
family carries that code. No second identity system.

Status and history are decided by the server only (services.py); every
change appends a PreEnrollmentEvent (never edited, never deleted).
"""

from django.db import models
from django.db.models import Q

from common.models import BaseModel, TenantModel


class PreEnrollmentStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Reçue"
    UNDER_REVIEW = "UNDER_REVIEW", "En cours d'examen"
    INFO_REQUESTED = "INFO_REQUESTED", "Informations complémentaires demandées"
    ACCEPTED = "ACCEPTED", "Acceptée"
    REJECTED = "REJECTED", "Refusée"


# Allowed transitions (the server refuses any other).
TRANSITIONS = {
    PreEnrollmentStatus.RECEIVED: {PreEnrollmentStatus.UNDER_REVIEW, PreEnrollmentStatus.REJECTED},
    PreEnrollmentStatus.UNDER_REVIEW: {
        PreEnrollmentStatus.INFO_REQUESTED,
        PreEnrollmentStatus.ACCEPTED,
        PreEnrollmentStatus.REJECTED,
    },
    PreEnrollmentStatus.INFO_REQUESTED: {
        PreEnrollmentStatus.UNDER_REVIEW,
        PreEnrollmentStatus.ACCEPTED,
        PreEnrollmentStatus.REJECTED,
    },
    PreEnrollmentStatus.ACCEPTED: set(),
    PreEnrollmentStatus.REJECTED: set(),
}


class GuardianRelationship(models.TextChoices):
    MOTHER = "MOTHER", "Mère"
    FATHER = "FATHER", "Père"
    LEGAL_GUARDIAN = "LEGAL_GUARDIAN", "Tuteur légal"
    OTHER = "OTHER", "Autre"


class PreEnrollment(TenantModel):
    reference = models.CharField(max_length=30)  # shown to the family, e.g. PRE-2026-0007
    # --- the person responsible (minimal data) ---
    guardian_first_name = models.CharField(max_length=100)
    guardian_last_name = models.CharField(max_length=100)
    guardian_phone = models.CharField(max_length=30)
    guardian_email = models.EmailField()
    relationship = models.CharField(max_length=20, choices=GuardianRelationship.choices)
    # --- the child (minimal data) ---
    child_first_name = models.CharField(max_length=100)
    child_last_name = models.CharField(max_length=100)
    child_birth_date = models.DateField(blank=True, null=True)
    requested_level = models.ForeignKey("academics.Level", on_delete=models.PROTECT, related_name="+")
    requested_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="+")
    previous_school = models.CharField(max_length=200, blank=True)
    comment = models.TextField(blank=True, max_length=1000)
    # --- consent (decided by the server at submission) ---
    consent_at = models.DateTimeField()
    consent_version = models.CharField(max_length=40)
    # --- workflow ---
    status = models.CharField(
        max_length=20, choices=PreEnrollmentStatus.choices, default=PreEnrollmentStatus.RECEIVED, db_index=True
    )
    submitted_at = models.DateTimeField()
    decided_at = models.DateTimeField(blank=True, null=True)
    decided_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    # What the family may read on the portal (the internal note stays in the history).
    message_to_family = models.CharField(max_length=500, blank=True)
    # The parent account created by the invitation (no child link).
    account = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.PROTECT, blank=True, null=True, related_name="pre_enrollments"
    )

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(fields=["school", "reference"], name="pre_enrollment_reference_unique"),
            models.CheckConstraint(
                condition=Q(status__in=PreEnrollmentStatus.values), name="pre_enrollment_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(relationship__in=GuardianRelationship.values), name="pre_enrollment_relationship_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=[PreEnrollmentStatus.ACCEPTED, PreEnrollmentStatus.REJECTED])
                | Q(decided_at__isnull=True),
                name="pre_enrollment_decision_only_when_decided",
            ),
            models.CheckConstraint(
                condition=Q(account__isnull=True) | Q(status=PreEnrollmentStatus.ACCEPTED),
                name="pre_enrollment_account_only_when_accepted",
            ),
        ]


class PreEnrollmentEvent(BaseModel):
    """Append-only history of a request (submission, transitions, invitations)."""

    pre_enrollment = models.ForeignKey(PreEnrollment, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=40)  # SUBMITTED, STATUS_CHANGED, INVITED, INVITATION_RESENT
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    actor = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    note = models.TextField(blank=True)  # internal: never shown to the family

    class Meta:
        ordering = ["created_at"]


class PortalInvitation(BaseModel):
    """One invitation sent for an accepted request: the link carries the
    activation code (accounts.AccountActivation, ADR 0024) of the parent
    account. Issuing a new one revokes the previous code (one pending code
    per account)."""

    pre_enrollment = models.ForeignKey(PreEnrollment, on_delete=models.PROTECT, related_name="invitations")
    activation = models.OneToOneField(
        "accounts.AccountActivation", on_delete=models.PROTECT, related_name="portal_invitation"
    )
    created_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at"]
