"""Employees: teachers and staff (spec §4.3, §4.4).

    SchoolMembership (person in this school)
          └── EmployeeProfile  (common HR data: employee number, hire date...)
                 ├── TeacherProfile ── TeacherSubjectQualification (subjects)
                 │                  └─ CompatibilityOverride (audited exceptions)
                 └── StaffProfile ──── StaffFunctionAssignment ── StaffFunction

Why EmployeeProfile in the middle: teachers and staff share HR data (and,
later, payroll). Keeping the employee number only there avoids two sources
of truth (ADR 0003): the "teacher number" IS the employee number of the
teacher's EmployeeProfile.
"""

from decimal import Decimal

from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from common.models import TenantModel

# =============================================================================
# Employee (common part)
# =============================================================================


class EmployeeType(models.TextChoices):
    TEACHER = "TEACHER", "Enseignant"
    STAFF = "STAFF", "Personnel"


class EmploymentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Actif"
    ON_LEAVE = "ON_LEAVE", "En congé"
    SUSPENDED = "SUSPENDED", "Suspendu"
    TERMINATED = "TERMINATED", "Fin de contrat"


class EmployeeProfile(TenantModel):
    """HR record shared by teachers and staff.

    `employee_number` is unique per school (spec says globally unique; per
    school keeps the model multi-tenant, as for student numbers — ADR 0003).
    `base_salary` is a spec field; it is only *stored* here, payroll logic
    belongs to the payroll phase.
    """

    membership = models.OneToOneField(
        "accounts.SchoolMembership", on_delete=models.PROTECT, related_name="employee_profile"
    )
    employee_number = models.CharField(max_length=50, db_index=True)
    employee_type = models.CharField(max_length=20, choices=EmployeeType.choices, default=EmployeeType.STAFF)
    address = models.TextField(blank=True, null=True)
    hire_date = models.DateField(blank=True, null=True)
    employment_status = models.CharField(
        max_length=30, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVE
    )
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "employee_number"], name="employee_school_number_unique"),
            models.CheckConstraint(condition=Q(employee_type__in=EmployeeType.values), name="employee_type_valid"),
            models.CheckConstraint(
                condition=Q(employment_status__in=EmploymentStatus.values), name="employee_status_valid"
            ),
            models.CheckConstraint(condition=Q(base_salary__gte=0), name="employee_salary_not_negative"),
        ]

    def __str__(self):
        return f"{self.employee_number} — {self.membership.user.full_name}"


# =============================================================================
# Teachers
# =============================================================================


class ProfessionalStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "En activité"
    PROBATION = "PROBATION", "Période d'essai"
    SUSPENDED = "SUSPENDED", "Suspendu"
    INACTIVE = "INACTIVE", "Inactif"


class TeacherProfile(TenantModel):
    """Teaching-specific data of an employee.

    - `pedagogical_category`: the teacher's training family (SCIENTIFIC...);
    - `primary_subject`: the main subject; other subjects are declared in
      TeacherSubjectQualification and checked against the compatibility rules.

    Linked to EmployeeProfile (which holds the unique employee number = the
    "teacher number") instead of carrying its own membership/employee_number
    as in spec §4.3 (ADR 0003). The employee must be of type TEACHER
    (checked by services.create_teacher).
    """

    employee = models.OneToOneField(EmployeeProfile, on_delete=models.PROTECT, related_name="teacher_profile")
    pedagogical_category = models.ForeignKey(
        "academics.PedagogicalCategory", on_delete=models.PROTECT, related_name="teachers"
    )
    primary_subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="primary_teachers")
    professional_status = models.CharField(
        max_length=30, choices=ProfessionalStatus.choices, default=ProfessionalStatus.ACTIVE
    )
    qualification_summary = models.TextField(blank=True, null=True)
    bio = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(professional_status__in=ProfessionalStatus.values), name="teacher_status_valid"
            ),
        ]

    @property
    def teacher_number(self):
        return self.employee.employee_number

    def __str__(self):
        return f"Enseignant {self.employee}"


class CompatibilityResult(models.TextChoices):
    """Machine recommendation computed by apps/people/compatibility.py."""

    COMPATIBLE = "COMPATIBLE", "Compatible"
    REQUIRES_REVIEW = "REQUIRES_REVIEW", "À valider par l'administration"
    INCOMPATIBLE = "INCOMPATIBLE", "Incompatible"
    OVERRIDDEN = "OVERRIDDEN", "Autorisé par dérogation"


class QualificationStatus(models.TextChoices):
    DECLARED = "DECLARED", "Déclarée"  # declared, machine says compatible
    PENDING = "PENDING", "En attente de validation"  # needs an admin review
    VERIFIED = "VERIFIED", "Vérifiée"  # an admin confirmed it
    REJECTED = "REJECTED", "Rejetée"  # an admin refused it


class QualificationSource(models.TextChoices):
    DECLARATION = "DECLARATION", "Déclaration de l'enseignant"
    ADMIN = "ADMIN", "Saisie administrative"
    OVERRIDE = "OVERRIDE", "Dérogation"


class TeacherSubjectQualification(TenantModel):
    """A subject a teacher declares they can teach, and its review state.

    Lifecycle (services in apps/people/services.py):

        declare ──► DECLARED (machine: compatible)  ──► admin ──► VERIFIED
                └─► PENDING  (machine: review needed) ──► admin ──► VERIFIED / REJECTED
                └─► refused  (machine: incompatible, no override) — nothing stored

    The computed recommendation is kept in `computed_compatibility` so the
    administrator sees what the machine said when deciding (addition to the
    spec, ADR 0008). `verified` (spec field) must agree with status=VERIFIED.
    """

    teacher = models.ForeignKey(TeacherProfile, on_delete=models.PROTECT, related_name="qualifications")
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="qualifications")
    status = models.CharField(
        max_length=20, choices=QualificationStatus.choices, default=QualificationStatus.DECLARED, db_index=True
    )
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    verified_at = models.DateTimeField(blank=True, null=True)
    source = models.CharField(
        max_length=30, choices=QualificationSource.choices, default=QualificationSource.DECLARATION
    )
    computed_compatibility = models.CharField(max_length=20, choices=CompatibilityResult.choices)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["teacher", "subject"], name="qualification_teacher_subject_unique"),
            models.CheckConstraint(
                condition=Q(status__in=QualificationStatus.values), name="qualification_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(source__in=QualificationSource.values), name="qualification_source_valid"
            ),
            models.CheckConstraint(
                condition=Q(computed_compatibility__in=CompatibilityResult.values),
                name="qualification_compatibility_valid",
            ),
            # `verified` and status=VERIFIED can never disagree, and a
            # verification is always dated.
            models.CheckConstraint(
                condition=(Q(verified=True) & Q(status=QualificationStatus.VERIFIED) & Q(verified_at__isnull=False))
                | (Q(verified=False) & ~Q(status=QualificationStatus.VERIFIED)),
                name="qualification_verified_consistent",
            ),
        ]

    def __str__(self):
        return f"{self.teacher} — {self.subject} ({self.status})"


class CompatibilityOverride(TenantModel):
    """Audited administrative exception to the compatibility rules.

    Spec §9: "Administrative overrides must carry actor + reason + timestamp
    + target scope". Here:
    - actor     = approved_by (PROTECT: the approver's membership is kept);
    - reason    = reason (non-empty, enforced by PostgreSQL);
    - timestamp = created_at;
    - scope     = teacher + subject + level (NULL = every level);
    - optional expiry = expires_at (must be after creation).

    The row is the audit record: services only create overrides, never edit
    them (a revocation mechanism, if needed, will be added explicitly).
    """

    teacher = models.ForeignKey(TeacherProfile, on_delete=models.PROTECT, related_name="compatibility_overrides")
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="compatibility_overrides")
    level = models.ForeignKey(
        "academics.Level", on_delete=models.PROTECT, blank=True, null=True, related_name="compatibility_overrides"
    )
    approved_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    reason = models.TextField()
    expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~Q(reason=""), name="override_reason_required"),
            models.CheckConstraint(
                condition=Q(expires_at__isnull=True) | Q(expires_at__gt=F("created_at")),
                name="override_expires_after_creation",
            ),
        ]

    def is_active(self, now=None):
        now = now or timezone.now()
        return self.expires_at is None or self.expires_at > now

    def __str__(self):
        return f"Dérogation {self.teacher} — {self.subject}"


# =============================================================================
# Staff
# =============================================================================


class StaffProfile(TenantModel):
    """Non-teaching staff member (secretary, bursar, supervisor...)."""

    employee = models.OneToOneField(EmployeeProfile, on_delete=models.PROTECT, related_name="staff_profile")
    staff_number = models.CharField(max_length=50, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "staff_number"], name="staff_school_number_unique"),
        ]

    def __str__(self):
        return f"Personnel {self.staff_number}"


class StaffFunction(TenantModel):
    """Configurable catalogue of staff functions (SECRETARY, BURSAR,
    SUPERVISOR...). Data, not code: each school defines its own."""

    code = models.CharField(max_length=40, db_index=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "code"], name="staff_function_school_code_unique"),
        ]

    def __str__(self):
        return self.name


class StaffFunctionAssignment(TenantModel):
    """A function held by a staff member, with history.

    A person may hold several functions at once (secretary AND librarian).
    Ending a function sets `ended_at` and active=False — the row is kept,
    so "who was bursar in 2025?" stays answerable.

    Rules enforced by PostgreSQL:
    - active <=> not ended; ended_at >= assigned_at;
    - the same function is held at most once *at a time* by the same person
      (partial unique on active rows), while past periods remain.
    """

    staff = models.ForeignKey(StaffProfile, on_delete=models.PROTECT, related_name="function_assignments")
    function = models.ForeignKey(StaffFunction, on_delete=models.PROTECT, related_name="assignments")
    assigned_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(blank=True, null=True)
    assigned_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gte=F("assigned_at")),
                name="staff_assignment_dates_ordered",
            ),
            models.CheckConstraint(
                condition=(Q(active=True) & Q(ended_at__isnull=True)) | (Q(active=False) & Q(ended_at__isnull=False)),
                name="staff_assignment_active_consistent",
            ),
            models.UniqueConstraint(
                fields=["staff", "function"], condition=Q(active=True), name="staff_assignment_one_active"
            ),
        ]

    def __str__(self):
        return f"{self.staff} — {self.function}"
