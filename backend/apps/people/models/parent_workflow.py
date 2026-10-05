"""Parent registration and verified parent–student linking (spec §6.3, §6.5,
§9; ADR 0026).

    RegistrationRequest       a parent created their account from the app;
                              the administration approves (membership ACTIVE +
                              role PARENT + ParentProfile) or rejects it.
    IdentityVerification      the identity check of a link request. Only an
                              HMAC of the identity document number is kept
                              (never the number, never an image): at the
                              school, the administration checks the physical
                              document and types its number, the server
                              compares the HMACs.
    ParentStudentLinkRequest  "this is my child": child designation (recorded
                              by the administration — pupils have no
                              account), optional sponsorship by a VERIFIED
                              parent of the child through a short-lived
                              challenge (accounts.VerificationChallenge), and
                              the final administrative decision, which creates
                              the VERIFIED ParentStudent link with its rights.

Nothing here grants access by itself: only an APPROVED request produces a
verified link, and every read API keeps filtering on verified links.
"""

from django.db import models
from django.db.models import Q

from common.models import TenantModel

from .parents import ParentProfile, RelationshipType


class RegistrationStatus(models.TextChoices):
    PENDING = "PENDING", "En attente"
    APPROVED = "APPROVED", "Validée"
    REJECTED = "REJECTED", "Refusée"


class RegistrationRequest(TenantModel):
    """Public registration request of a parent (spec §6.3)."""

    user = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="registration_requests")
    membership = models.OneToOneField(
        "accounts.SchoolMembership", on_delete=models.PROTECT, related_name="registration_request"
    )
    requested_role = models.CharField(max_length=30, default="PARENT")
    status = models.CharField(
        max_length=30, choices=RegistrationStatus.choices, default=RegistrationStatus.PENDING, db_index=True
    )
    applicant_name = models.CharField(max_length=240)
    applicant_email = models.EmailField()
    applicant_phone = models.CharField(max_length=40, blank=True, null=True)
    submitted_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    rejection_reason = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=RegistrationStatus.values), name="registration_status_valid"),
            models.CheckConstraint(condition=Q(requested_role="PARENT"), name="registration_role_supported"),
            models.CheckConstraint(
                condition=(Q(status=RegistrationStatus.PENDING) & Q(reviewed_at__isnull=True))
                | (~Q(status=RegistrationStatus.PENDING) & Q(reviewed_at__isnull=False)),
                name="registration_review_consistent",
            ),
            models.CheckConstraint(
                condition=~Q(status=RegistrationStatus.REJECTED) | Q(rejection_reason__isnull=False),
                name="registration_rejection_has_reason",
            ),
        ]

    def __str__(self):
        return f"Inscription {self.applicant_email} ({self.status})"


class IdentityMethod(models.TextChoices):
    ID_DOCUMENT = "ID_DOCUMENT", "Pièce d'identité vérifiée à l'école"
    SPONSOR_2FA = "SPONSOR_2FA", "Parrainage par un parent vérifié (code à usage unique)"


class IdentityStatus(models.TextChoices):
    PENDING = "PENDING", "À vérifier"
    VERIFIED = "VERIFIED", "Vérifiée"
    REJECTED = "REJECTED", "Refusée"


class DocumentType(models.TextChoices):
    CNI = "CNI", "Carte nationale d'identité"
    PASSPORT = "PASSPORT", "Passeport"
    RESIDENCE_PERMIT = "RESIDENCE_PERMIT", "Titre de séjour"
    OTHER = "OTHER", "Autre pièce officielle"


class IdentityVerification(TenantModel):
    """Identity check without long-term retention of the raw document (spec)."""

    membership = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.PROTECT, related_name="identity_verifications"
    )
    method = models.CharField(max_length=30, choices=IdentityMethod.choices, default=IdentityMethod.ID_DOCUMENT)
    status = models.CharField(
        max_length=20, choices=IdentityStatus.choices, default=IdentityStatus.PENDING, db_index=True
    )
    document_type = models.CharField(max_length=30, choices=DocumentType.choices, blank=True, null=True)
    # HMAC-SHA256 (SECRET_KEY) of the normalised document number: comparable,
    # not reversible, useless without the server's key.
    document_reference_hash = models.CharField(max_length=128, blank=True, null=True)
    failed_checks = models.PositiveSmallIntegerField(default=0)
    verified_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    verified_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(method__in=IdentityMethod.values), name="identity_method_valid"),
            models.CheckConstraint(condition=Q(status__in=IdentityStatus.values), name="identity_status_valid"),
            models.CheckConstraint(
                condition=~Q(status=IdentityStatus.VERIFIED) | Q(verified_at__isnull=False),
                name="identity_verified_has_date",
            ),
            models.CheckConstraint(
                condition=~Q(method=IdentityMethod.ID_DOCUMENT) | Q(document_reference_hash__isnull=False),
                name="identity_document_has_hash",
            ),
        ]


class LinkRequestStatus(models.TextChoices):
    PENDING = "PENDING", "En cours"
    APPROVED = "APPROVED", "Validée"
    REJECTED = "REJECTED", "Refusée"
    CANCELLED = "CANCELLED", "Annulée"


class StudentApproval(models.TextChoices):
    PENDING = "PENDING", "À confirmer par l'élève"
    APPROVED = "APPROVED", "Confirmée par l'élève"
    REJECTED = "REJECTED", "Refusée par l'élève"
    NOT_REQUIRED = "NOT_REQUIRED", "Non requise"


class LinkInitiator(models.TextChoices):
    PARENT = "PARENT", "Parent"
    ADMIN = "ADMIN", "Administration"


class ParentStudentLinkRequest(TenantModel):
    """Strongly verified association workflow between a parent and a pupil."""

    parent = models.ForeignKey(ParentProfile, on_delete=models.PROTECT, related_name="link_requests")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="link_requests")
    relationship_type = models.CharField(max_length=30, choices=RelationshipType.choices)
    initiated_by = models.CharField(max_length=20, choices=LinkInitiator.choices, default=LinkInitiator.PARENT)
    identity_verification = models.ForeignKey(IdentityVerification, on_delete=models.PROTECT, related_name="+")
    student_approval_status = models.CharField(
        max_length=20, choices=StudentApproval.choices, default=StudentApproval.PENDING
    )
    student_approval_note = models.TextField(blank=True, null=True)
    sponsor_parent = models.ForeignKey(
        ParentProfile, on_delete=models.SET_NULL, blank=True, null=True, related_name="sponsored_requests"
    )
    sponsor_challenge_verified = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=LinkRequestStatus.choices, default=LinkRequestStatus.PENDING, db_index=True
    )
    decided_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    decided_at = models.DateTimeField(blank=True, null=True)
    decision_reason = models.TextField(blank=True, null=True)
    link = models.ForeignKey(
        "people.ParentStudent", on_delete=models.SET_NULL, blank=True, null=True, related_name="requests"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=LinkRequestStatus.values), name="link_request_status_valid"),
            models.CheckConstraint(
                condition=Q(student_approval_status__in=StudentApproval.values), name="link_request_approval_valid"
            ),
            models.CheckConstraint(
                condition=Q(relationship_type__in=RelationshipType.values), name="link_request_relationship_valid"
            ),
            models.CheckConstraint(
                condition=Q(sponsor_challenge_verified=False) | Q(sponsor_parent__isnull=False),
                name="link_request_sponsor_consistent",
            ),
            models.CheckConstraint(
                condition=~Q(status=LinkRequestStatus.APPROVED) | (Q(link__isnull=False) & Q(decided_at__isnull=False)),
                name="link_request_approved_has_link",
            ),
            # One request in progress per (parent, pupil).
            models.UniqueConstraint(
                fields=["parent", "student"],
                condition=Q(status=LinkRequestStatus.PENDING),
                name="link_request_one_pending",
            ),
        ]

    def __str__(self):
        return f"Rattachement {self.parent_id} → {self.student_id} ({self.status})"
