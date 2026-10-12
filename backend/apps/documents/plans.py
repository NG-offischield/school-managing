"""School plans: import, versions, publication, distribution, access.

    draft plan ──add_version──▶ version DRAFT ──publish──▶ plan PUBLISHED,
                                                           version PUBLISHED (current)
    new version ──publish──▶ previous version SUPERSEDED (kept), new one current
    withdraw ──▶ plan WITHDRAWN: gone from every list, downloads refused;
                 versions and history kept (rows are never deleted)

Who may see a PUBLISHED plan — decided HERE, at each read and download
(nothing is granted once and for all: a withdrawn plan or a lost right
closes the access at the next request):
    administrators (ADMIN / SUPER_ADMIN) of the school: always;
    AUTO:   verified parents of the school (an active, verified link) and
            active teachers of the school;
    MANUAL: the audience rows — all verified parents / all active teachers of
            the school, the verified parents of the pupils of a class, the
            teachers with an active course in a class.
Never guardians or staff (not in this scope), never another school.

Notifications (type PLAN, the one notification service): when a version is
PUBLISHED (first publication or a new version), to the parents / teachers
who can see it — once per version (event key). Nothing for a draft, a
withdrawal or a metadata change.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import MembershipStatus, SchoolMembership
from apps.audit.services import record_audit
from apps.communication.models import NotificationType
from apps.communication.notifications import notify_many
from apps.gradebook.models import Course
from apps.people.models import EnrollmentStatus, ParentStudent, ProfessionalStatus, StudentEnrollment, TeacherProfile
from common.permissions import ADMIN_ROLES, membership_has_role, require_role

from . import plan_files
from .models import (
    CLASS_TARGETS,
    PlanAudienceTarget,
    PlanDistribution,
    PlanStatus,
    PlanVersionStatus,
    SchoolPlan,
    SchoolPlanAudience,
    SchoolPlanVersion,
)

META_FIELDS = ("title", "description", "building", "floor", "display_order", "distribution")


def _audit(action, actor, plan, **new):
    record_audit(action, actor=actor, entity=plan, new=new or None)


def _text(value, field, limit, *, required=False):
    value = (value or "").strip()
    if required and not value:
        raise ValidationError(f"{field} is required.", code=f"{field}_required")
    if len(value) > limit:
        raise ValidationError(f"{field} is too long.", code=f"{field}_too_long")
    return value


# --- relations (read from the existing domains, never copied) -----------------------


def _verified_children(member):
    return ParentStudent.objects.filter(
        school=member.school, parent__membership=member, active=True, identity_verified=True
    ).values("student")


def is_verified_parent(member):
    return membership_has_role(member, {"PARENT"}) and _verified_children(member).exists()


def is_active_teacher(member):
    return (
        membership_has_role(member, {"TEACHER"})
        and TeacherProfile.objects.filter(
            employee__membership=member,
            professional_status__in=(ProfessionalStatus.ACTIVE, ProfessionalStatus.PROBATION),  # working
        ).exists()
    )


def _parent_class_ids(member):
    return set(
        StudentEnrollment.objects.filter(
            student__in=_verified_children(member), status=EnrollmentStatus.ACTIVE
        ).values_list("school_class_id", flat=True)
    )


def _teacher_class_ids(member):
    return set(
        Course.objects.filter(active=True, teacher__employee__membership=member).values_list(
            "school_class_id", flat=True
        )
    )


def audience_allows(member, plan):
    """Does the plan's distribution reach this (non-admin) member?"""
    parent, teacher = is_verified_parent(member), is_active_teacher(member)
    if not (parent or teacher):
        return False  # guardians, staff, unverified parents, inactive teachers
    if plan.distribution == PlanDistribution.AUTO:
        return True
    rows = list(plan.audience.all())
    targets = {row.target for row in rows}
    if parent and PlanAudienceTarget.SCHOOL_PARENTS in targets:
        return True
    if teacher and PlanAudienceTarget.SCHOOL_TEACHERS in targets:
        return True
    class_parents = {r.school_class_id for r in rows if r.target == PlanAudienceTarget.CLASS_PARENTS}
    if parent and class_parents & _parent_class_ids(member):
        return True
    class_teachers = {r.school_class_id for r in rows if r.target == PlanAudienceTarget.CLASS_TEACHERS}
    return bool(teacher and class_teachers & _teacher_class_ids(member))


def can_view(member, plan):
    if member is None or member.school_id != plan.school_id or member.status != MembershipStatus.ACTIVE:
        return False
    if plan.status != PlanStatus.PUBLISHED or plan.current_version_id is None:
        return False
    if membership_has_role(member, ADMIN_ROLES):
        return True
    return audience_allows(member, plan)


def visible_plans(member):
    plans = SchoolPlan.objects.filter(school=member.school, status=PlanStatus.PUBLISHED).select_related(
        "current_version"
    )
    return [plan for plan in plans if can_view(member, plan)]


def readers(plan):
    """Parents and teachers who can see the plan once published (notification
    recipients, and the administration's « who has access » list)."""
    candidates = (
        SchoolMembership.objects.filter(
            school=plan.school,
            status=MembershipStatus.ACTIVE,
            membership_roles__active=True,
            membership_roles__role__code__in=["PARENT", "TEACHER"],
        )
        .distinct()
        .select_related("user")
        .order_by("user__last_name", "user__first_name")
    )
    return [member for member in candidates if audience_allows(member, plan)]


# --- administration ------------------------------------------------------------------------


@transaction.atomic
def create_plan(school, *, actor, title, description="", building="", floor="", display_order=0, distribution=None):
    require_role(actor, ADMIN_ROLES, school=school)
    distribution = distribution or PlanDistribution.AUTO
    if distribution not in PlanDistribution.values:
        raise ValidationError("Unknown distribution.", code="invalid_distribution")
    plan = SchoolPlan.objects.create(
        school=school,
        title=_text(title, "title", 200, required=True),
        description=_text(description, "description", 4000),
        building=_text(building, "building", 100),
        floor=_text(floor, "floor", 60),
        display_order=display_order or 0,
        distribution=distribution,
        created_by=actor,
    )
    _audit("SCHOOL_PLAN_CREATED", actor, plan, title=plan.title, distribution=plan.distribution)
    return plan


@transaction.atomic
def update_plan(plan, *, actor, **changes):
    """Metadata and distribution mode. Never notifies anyone (a typo fix is not news)."""
    require_role(actor, ADMIN_ROLES, school=plan.school)
    plan = SchoolPlan.objects.select_for_update().get(pk=plan.pk)
    limits = {"title": 200, "description": 4000, "building": 100, "floor": 60}
    for field, value in changes.items():
        if field not in META_FIELDS:
            continue
        if field in limits:
            value = _text(value, field, limits[field], required=field == "title")
        if field == "distribution" and value not in PlanDistribution.values:
            raise ValidationError("Unknown distribution.", code="invalid_distribution")
        if field == "display_order":
            value = value or 0
        setattr(plan, field, value)
    if plan.status == PlanStatus.PUBLISHED and plan.distribution == PlanDistribution.MANUAL:
        _require_audience(plan)
    plan.save()
    _audit("SCHOOL_PLAN_UPDATED", actor, plan, **{f: str(getattr(plan, f)) for f in changes if f in META_FIELDS})
    return plan


@transaction.atomic
def add_version(plan, *, actor, upload):
    """Import a file as a NEW version (DRAFT): nothing changes for readers until
    it is explicitly published."""
    require_role(actor, ADMIN_ROLES, school=plan.school)
    checked = plan_files.check(upload)
    plan = SchoolPlan.objects.select_for_update().get(pk=plan.pk)  # one numbering at a time
    number = (plan.versions.aggregate(n=Max("number"))["n"] or 0) + 1
    path, stored_name, digest, size = plan_files.store(checked, plan.school)
    try:
        version = SchoolPlanVersion.objects.create(
            school=plan.school,
            plan=plan,
            number=number,
            original_name=checked.original_name,
            stored_name=stored_name,
            storage_path=path,
            mime_type=checked.mime_type,
            size_bytes=size,
            sha256=digest,
            width=checked.width,
            height=checked.height,
            page_count=checked.page_count,
            uploaded_by=actor,
        )
    except Exception:
        plan_files.delete_file(path)  # no orphan file when the row is refused
        raise
    _audit("SCHOOL_PLAN_VERSION_ADDED", actor, plan, version=number, sha256=digest, mime_type=checked.mime_type)
    return version


def _require_audience(plan):
    if not plan.audience.exists():
        raise ValidationError(
            "Choose who may see this plan before publishing it (manual distribution).", code="plan_audience_empty"
        )


@transaction.atomic
def publish(plan, *, actor, version):
    """Publish `version` (first publication, a new version, or back after a
    withdrawal). The previous current version is SUPERSEDED, never deleted.
    Readers are notified once per published version."""
    require_role(actor, ADMIN_ROLES, school=plan.school)
    plan = SchoolPlan.objects.select_for_update().get(pk=plan.pk)
    version = SchoolPlanVersion.objects.select_for_update().get(pk=version.pk)
    if version.plan_id != plan.pk:
        raise ValidationError("This version belongs to another plan.", code="plan_version_other_plan")
    if plan.distribution == PlanDistribution.MANUAL:
        _require_audience(plan)
    if plan.status == PlanStatus.PUBLISHED and plan.current_version_id == version.pk:
        return plan  # already what readers see: nothing to do, nobody to notify
    now = timezone.now()
    previous = plan.current_version
    if previous is not None and previous.pk != version.pk and previous.status == PlanVersionStatus.PUBLISHED:
        previous.status = PlanVersionStatus.SUPERSEDED
        previous.save(update_fields=["status", "updated_at"])
    version.status = PlanVersionStatus.PUBLISHED
    version.published_at = version.published_at or now
    version.save(update_fields=["status", "published_at", "updated_at"])
    plan.status, plan.current_version = PlanStatus.PUBLISHED, version
    plan.published_at, plan.published_by = now, actor
    plan.save(update_fields=["status", "current_version", "published_at", "published_by", "updated_at"])
    _audit("SCHOOL_PLAN_PUBLISHED", actor, plan, version=version.number)
    _notify(plan, version)
    return plan


def _notify(plan, version):
    first = version.number == 1 or not plan.versions.exclude(pk=version.pk).filter(published_at__isnull=False).exists()
    where = " · ".join(part for part in (plan.building, plan.floor) if part)
    notify_many(
        readers(plan),
        school=plan.school,
        notification_type=NotificationType.PLAN,
        title=(f"Plan publié : {plan.title}" if first else f"Plan mis à jour : {plan.title}")[:200],
        message=(f"{where} — version {version.number}." if where else f"Version {version.number}.")[:500],
        event_key=f"plan.version:{version.pk}",
        payload={"plan": str(plan.pk), "version": str(version.pk), "number": version.number},
        source=version,
    )


@transaction.atomic
def withdraw(plan, *, actor, reason=""):
    require_role(actor, ADMIN_ROLES, school=plan.school)
    plan = SchoolPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status != PlanStatus.PUBLISHED:
        raise ValidationError("Only a published plan can be withdrawn.", code="plan_not_published")
    plan.status = PlanStatus.WITHDRAWN
    plan.save(update_fields=["status", "updated_at"])
    _audit("SCHOOL_PLAN_WITHDRAWN", actor, plan, reason=_text(reason, "reason", 500))
    return plan


@transaction.atomic
def set_audience(plan, *, actor, entries):
    """Replace the MANUAL audience. `entries`: [(target, school_class or None)]."""
    require_role(actor, ADMIN_ROLES, school=plan.school)
    plan = SchoolPlan.objects.select_for_update().get(pk=plan.pk)
    rows, seen = [], set()
    for target, school_class in entries:
        if target not in PlanAudienceTarget.values:
            raise ValidationError("Unknown audience.", code="invalid_audience")
        if target in CLASS_TARGETS:
            if school_class is None:
                raise ValidationError("Choose the class.", code="audience_class_required")
            if school_class.school_id != plan.school_id:
                raise PermissionDenied("Class of another school.")
        else:
            school_class = None
        key = (target, getattr(school_class, "pk", None))
        if key not in seen:
            seen.add(key)
            rows.append(SchoolPlanAudience(school=plan.school, plan=plan, target=target, school_class=school_class))
    if not rows and plan.status == PlanStatus.PUBLISHED and plan.distribution == PlanDistribution.MANUAL:
        # Emptied while readers rely on it: refuse (withdraw the plan instead).
        raise ValidationError(
            "A published plan with manual distribution needs at least one audience.", code="plan_audience_empty"
        )
    plan.audience.all().delete()
    SchoolPlanAudience.objects.bulk_create(rows)
    _audit("SCHOOL_PLAN_AUDIENCE_SET", actor, plan, audience=[[t, str(c) if c else None] for t, c in seen])
    return plan


# --- files ----------------------------------------------------------------------------------


def open_current(plan, member):
    """The current published file for a reader; PermissionDenied otherwise."""
    if not can_view(member, plan):
        raise PermissionDenied("Plan not available.")
    return plan.current_version, plan_files.open_file(plan.current_version)


def open_any_version(version, member):
    """Any version (preview, history) — administration of the school only."""
    if member is None or member.school_id != version.school_id or not membership_has_role(member, ADMIN_ROLES):
        raise PermissionDenied("Administration only.")
    return plan_files.open_file(version)
