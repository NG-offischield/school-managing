"""Parents / tutors and their link to students (spec §4.3)."""

from django.db import models
from django.db.models import Q

from common.models import TenantModel


class Language(models.TextChoices):
    FRENCH = "fr", "Français"
    ENGLISH = "en", "English"


class ParentProfile(TenantModel):
    """School-scoped profile of a parent or tutor.

    Chain: User (the person, global) → SchoolMembership (the person in this
    school, with role PARENT) → ParentProfile (parent-specific data).
    `school` is stored directly as well (spec §3 allows it for filtering) and
    the database guarantees it equals the membership's school (composite FK).

    A parent may have several children and a child several parents: that
    many-to-many lives in ParentStudent.
    """

    membership = models.OneToOneField(
        "accounts.SchoolMembership", on_delete=models.PROTECT, related_name="parent_profile"
    )
    occupation = models.CharField(max_length=150, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    emergency_phone = models.CharField(max_length=40, blank=True, null=True)
    preferred_language = models.CharField(max_length=10, choices=Language.choices, default=Language.FRENCH)
    # Pays the school fees for the family (finance phase).
    financial_responsible = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(preferred_language__in=Language.values), name="parent_language_supported"
            ),
        ]

    def __str__(self):
        return f"Parent {self.membership.user.full_name}"


class RelationshipType(models.TextChoices):
    FATHER = "FATHER", "Père"
    MOTHER = "MOTHER", "Mère"
    LEGAL_GUARDIAN = "LEGAL_GUARDIAN", "Tuteur légal"
    TUTOR = "TUTOR", "Tuteur"
    OTHER = "OTHER", "Autre"


class VerificationMethod(models.TextChoices):
    """How a parent–student link was verified (the full CNI / 2FA workflow
    of spec §6.5 — ParentStudentLinkRequest, IdentityVerification — comes in
    a later phase; these values already name its outcomes)."""

    ADMIN_IN_PERSON = "ADMIN_IN_PERSON", "Vérification en personne par l'administration"
    ID_DOCUMENT = "ID_DOCUMENT", "Pièce d'identité"
    SPONSOR_2FA = "SPONSOR_2FA", "Parrainage par un parent vérifié (2FA)"
    LEGACY = "LEGACY", "Reprise d'un ancien système"
    OTHER = "OTHER", "Autre"


class ParentStudent(TenantModel):
    """Link between a parent/tutor and a student, with the parent's rights.

    DECLARED vs VERIFIED (spec §9: "Parent/student association is a verified
    workflow, not a name match"):

    - declared:  identity_verified = False — the link is recorded but grants
                 NO access to the child's data;
    - verified:  identity_verified = True + verification_method + verified_at
                 (+ optional verification_reference).

    Rights (can_pay, can_view_financial_data...) are per link, so a mother and
    a father of the same child may have different rights.

    Rules enforced by PostgreSQL:
    - one link per (parent, student);
    - verified <=> method and date are present (no half-verified link);
    - financial rights (pay / view finance) require a verified link;
    - at most one ACTIVE primary contact per student;
    - parent and student belong to the link's school (composite FKs).

    Deviation from spec §4.3 (ADR 0008): the spec's ParentStudent holds only
    *verified* links (verified_at NOT NULL); here verified_at is nullable and
    the declared/verified state is explicit, as requested for this phase.
    """

    parent = models.ForeignKey(ParentProfile, on_delete=models.PROTECT, related_name="children_links")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="parent_links")
    relationship_type = models.CharField(max_length=30, choices=RelationshipType.choices)
    is_primary_contact = models.BooleanField(default=False)
    can_receive_notifications = models.BooleanField(default=True)
    can_view_financial_data = models.BooleanField(default=False)
    can_pay = models.BooleanField(default=False)
    can_submit_complaints = models.BooleanField(default=True)
    active = models.BooleanField(default=True, db_index=True)
    # --- verification ---
    identity_verified = models.BooleanField(default=False, db_index=True)
    verification_method = models.CharField(max_length=30, choices=VerificationMethod.choices, blank=True, null=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    # Reference of the check (case number, sponsor challenge id...). NEVER a
    # raw identity-document number: spec §4.3 keeps only hashes of those.
    verification_reference = models.CharField(max_length=120, blank=True, null=True)
    verified_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parent", "student"], name="parent_student_unique"),
            models.CheckConstraint(
                condition=Q(relationship_type__in=RelationshipType.values), name="parent_student_relationship_valid"
            ),
            models.CheckConstraint(
                condition=Q(verification_method__isnull=True) | Q(verification_method__in=VerificationMethod.values),
                name="parent_student_method_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(identity_verified=True) & Q(verification_method__isnull=False) & Q(verified_at__isnull=False)
                )
                | (Q(identity_verified=False) & Q(verified_at__isnull=True)),
                name="parent_student_verification_consistent",
            ),
            models.CheckConstraint(
                condition=Q(identity_verified=True) | (Q(can_pay=False) & Q(can_view_financial_data=False)),
                name="parent_student_financial_rights_need_verification",
            ),
            models.UniqueConstraint(
                fields=["student"],
                condition=Q(is_primary_contact=True, active=True),
                name="parent_student_one_primary_contact",
            ),
        ]

    def __str__(self):
        state = "vérifié" if self.identity_verified else "déclaré"
        return f"{self.parent} ↔ {self.student} ({state})"
