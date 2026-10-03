"""Planning (spec §4.5, ADR 0012).

    Course (gradebook)        WHAT is taught: subject + teacher + class + year
      └── ScheduleSlot        WHEN, recurring: "Monday 08:00–10:00, room R12"
            └── TeachingSession   a DATED occurrence: "2026-10-12 08:00–10:00",
                                  planned teacher, actual (substitute) teacher,
                                  room, status, original time if moved
    TeacherAvailability            recurring (un)availability declared by a teacher
    TeacherAvailabilityException   dated unavailability request, decided by an admin
    SchoolBreak                    holidays / interruptions: no session generated
    ScheduleChange                 immutable history of every planning change, also
                                   the notification outbox (notify / notification_status)

Conflicts guaranteed by PostgreSQL (exclusion constraints, btree_gist): two
PUBLISHED slots, or two SCHEDULED sessions, never overlap in time for the same
class, the same teacher or the same room. The constraints are DEFERRABLE so a
swap of two sessions can be done inside one transaction; services force the
check (SET CONSTRAINTS ... IMMEDIATE) before returning.
"""

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import Deferrable, F, Func, Q
from django.utils import timezone

from common.models import TenantModel


class TimeOfDayRange(Func):
    """SQL `tsrange(DATE '2000-01-03' + start, DATE '2000-01-03' + end, '[)')`.

    PostgreSQL has no range type for TIME; anchoring both times to the same
    fixed day turns a weekly time window into a timestamp range. Half-open
    '[)': 08:00–10:00 and 10:00–12:00 do NOT overlap.
    """

    output_field = DateTimeRangeField()

    def __init__(self, start, end, **extra):
        super().__init__(start, end, **extra)

    def as_sql(self, compiler, connection, **extra):
        start_sql, start_params = compiler.compile(self.source_expressions[0])
        end_sql, end_params = compiler.compile(self.source_expressions[1])
        sql = f"tsrange(DATE '2000-01-03' + {start_sql}, DATE '2000-01-03' + {end_sql}, '[)')"
        return sql, (*start_params, *end_params)


class DateSpan(Func):
    """SQL `daterange(start, end, '[]')`; a NULL end means "open-ended"."""

    function = "DATERANGE"
    output_field = DateRangeField()


class TimestampSpan(Func):
    """SQL `tstzrange(start, end, '[)')`."""

    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


def _weekly_window():
    return TimeOfDayRange("start_time", "end_time")


def _effective_dates():
    return DateSpan("effective_from", "effective_to", RangeBoundary(inclusive_lower=True, inclusive_upper=True))


def _session_span():
    return TimestampSpan("scheduled_start", "scheduled_end", RangeBoundary(inclusive_lower=True, inclusive_upper=False))


# =============================================================================
# Recurring timetable
# =============================================================================


class SlotStatus(models.TextChoices):
    PUBLISHED = "PUBLISHED", "Publié"  # part of the timetable
    ARCHIVED = "ARCHIVED", "Archivé"  # ended / replaced (history kept)


class ScheduleSlot(TenantModel):
    """A recurring weekly slot of a Course: "Monday 08:00–10:00, room R12".

    `Course` stays THE pedagogical relation (subject + teacher + class +
    year); a slot only schedules it in time — no parallel teacher↔class
    assignment table. `teacher`, `school_class` and `academic_year` are
    copies of the course's values, kept equal by composite foreign keys, so
    that PostgreSQL can forbid overlaps per class / teacher / room.

    A change of time is never an in-place edit: the slot is ended
    (effective_to) or archived, and a new slot created — history is kept.
    """

    course = models.ForeignKey("gradebook.Course", on_delete=models.PROTECT, related_name="schedule_slots")
    teacher = models.ForeignKey("people.TeacherProfile", on_delete=models.PROTECT, related_name="schedule_slots")
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT, related_name="schedule_slots")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="schedule_slots")
    room = models.ForeignKey(
        "academics.Room", on_delete=models.SET_NULL, blank=True, null=True, related_name="schedule_slots"
    )
    weekday = models.PositiveSmallIntegerField()  # ISO: 1 = Monday ... 7 = Sunday
    start_time = models.TimeField()
    end_time = models.TimeField()
    effective_from = models.DateField()
    effective_to = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=SlotStatus.choices, default=SlotStatus.PUBLISHED, db_index=True)
    created_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )

    class Meta:
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(condition=Q(weekday__gte=1, weekday__lte=7), name="slot_weekday_valid"),
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="slot_times_ordered"),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="slot_effective_dates_ordered",
            ),
            models.CheckConstraint(condition=Q(status__in=SlotStatus.values), name="slot_status_valid"),
            *[
                ExclusionConstraint(
                    name=f"slot_{who}_no_overlap",
                    expressions=[
                        (who, RangeOperators.EQUAL),
                        ("weekday", RangeOperators.EQUAL),
                        (_weekly_window(), RangeOperators.OVERLAPS),
                        (_effective_dates(), RangeOperators.OVERLAPS),
                    ],
                    condition=Q(status=SlotStatus.PUBLISHED),
                    deferrable=Deferrable.DEFERRED,
                )
                for who in ("school_class", "teacher", "room")
            ],
        ]

    def __str__(self):
        return f"{self.course} — j{self.weekday} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


# =============================================================================
# Dated sessions
# =============================================================================


class SessionStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Planifiée"
    COMPLETED = "COMPLETED", "Réalisée"
    CANCELLED = "CANCELLED", "Annulée"


class TeachingSession(TenantModel):
    """A dated occurrence of teaching — the unit future per-session
    attendance (call sheets, teacher check-in) will hang on.

    Few statuses on purpose; the other situations are facts on the row:
    - substituted:  teacher != planned_teacher (both kept);
    - moved / exceptional end:  original_start / original_end are set;
    - exceptional session:  schedule_slot is NULL (not generated from a slot).

    Copies of the course's school_class / subject / planned teacher / year are
    kept equal to the course by composite foreign keys; they let PostgreSQL
    forbid overlaps and let clients filter cheaply.
    """

    schedule_slot = models.ForeignKey(
        ScheduleSlot, on_delete=models.PROTECT, blank=True, null=True, related_name="sessions"
    )
    course = models.ForeignKey("gradebook.Course", on_delete=models.PROTECT, related_name="sessions")
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT, related_name="sessions")
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="sessions")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="sessions")
    academic_period = models.ForeignKey(
        "academics.AcademicPeriod", on_delete=models.PROTECT, blank=True, null=True, related_name="sessions"
    )
    planned_teacher = models.ForeignKey("people.TeacherProfile", on_delete=models.PROTECT, related_name="+")
    teacher = models.ForeignKey("people.TeacherProfile", on_delete=models.PROTECT, related_name="sessions")
    room = models.ForeignKey(
        "academics.Room", on_delete=models.SET_NULL, blank=True, null=True, related_name="sessions"
    )
    date = models.DateField(db_index=True)
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    original_start = models.DateTimeField(blank=True, null=True)
    original_end = models.DateTimeField(blank=True, null=True)
    actual_start = models.DateTimeField(blank=True, null=True)
    actual_end = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=SessionStatus.choices, default=SessionStatus.SCHEDULED, db_index=True
    )
    created_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )

    class Meta:
        ordering = ["scheduled_start"]
        constraints = [
            models.CheckConstraint(condition=Q(scheduled_end__gt=F("scheduled_start")), name="session_times_ordered"),
            models.CheckConstraint(condition=Q(status__in=SessionStatus.values), name="session_status_valid"),
            models.CheckConstraint(
                condition=(Q(original_start__isnull=True) & Q(original_end__isnull=True))
                | (Q(original_start__isnull=False) & Q(original_end__isnull=False)),
                name="session_original_times_paired",
            ),
            # Generation is idempotent: one session per slot and date.
            models.UniqueConstraint(fields=["schedule_slot", "date"], name="session_slot_date_unique"),
            *[
                ExclusionConstraint(
                    name=f"session_{who}_no_overlap",
                    expressions=[(who, RangeOperators.EQUAL), (_session_span(), RangeOperators.OVERLAPS)],
                    condition=Q(status=SessionStatus.SCHEDULED),
                    deferrable=Deferrable.DEFERRED,
                )
                for who in ("school_class", "teacher", "room")
            ],
        ]

    @property
    def is_substituted(self):
        return self.teacher_id != self.planned_teacher_id

    @property
    def is_moved(self):
        return self.original_start is not None

    def __str__(self):
        return f"{self.course} {self.scheduled_start:%Y-%m-%d %H:%M}"


# Names of the deferrable exclusion constraints (see services._check_now).
CONFLICT_CONSTRAINTS = [
    *(f"slot_{w}_no_overlap" for w in ("school_class", "teacher", "room")),
    *(f"session_{w}_no_overlap" for w in ("school_class", "teacher", "room")),
]


# =============================================================================
# Teacher availability
# =============================================================================


class TeacherAvailability(TenantModel):
    """Recurring (un)availability declared by a teacher: "not available on
    Wednesday afternoons". Informative for planning: creating a slot that
    collides with a declared UNavailability is refused unless an administrator
    explicitly forces it (audited). Withdrawn rather than deleted (`active`)."""

    teacher = models.ForeignKey("people.TeacherProfile", on_delete=models.PROTECT, related_name="availabilities")
    weekday = models.PositiveSmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    available = models.BooleanField(default=True)
    reason = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["weekday", "start_time"]
        verbose_name_plural = "teacher availabilities"
        constraints = [
            models.CheckConstraint(condition=Q(weekday__gte=1, weekday__lte=7), name="availability_weekday_valid"),
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="availability_times_ordered"),
        ]


class ExceptionStatus(models.TextChoices):
    PENDING = "PENDING", "Soumise"
    APPROVED = "APPROVED", "Validée"
    REJECTED = "REJECTED", "Refusée"
    CHANGES_REQUESTED = "CHANGES_REQUESTED", "Modification proposée"
    CANCELLED = "CANCELLED", "Retirée par l'enseignant"


class TeacherAvailabilityException(TenantModel):
    """Dated unavailability request ("absent on 2026-10-12 08:00–12:00,
    medical appointment"). Submitted by the teacher (or recorded by an admin),
    decided by an administrator who is NOT that teacher. An approved request
    does not silently cancel anything: the impacted sessions are listed so the
    administration organises a substitution, a swap or a cancellation."""

    teacher = models.ForeignKey("people.TeacherProfile", on_delete=models.PROTECT, related_name="unavailabilities")
    date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    available = models.BooleanField(default=False)
    reason = models.TextField()
    status = models.CharField(
        max_length=20, choices=ExceptionStatus.choices, default=ExceptionStatus.PENDING, db_index=True
    )
    requested_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    decided_at = models.DateTimeField(blank=True, null=True)
    decision_comment = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-date", "start_time"]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="unavailability_times_ordered"),
            models.CheckConstraint(condition=~Q(reason=""), name="unavailability_reason_required"),
            models.CheckConstraint(condition=Q(status__in=ExceptionStatus.values), name="unavailability_status_valid"),
            # A decision is always dated and attributed... and a decided row is
            # never PENDING.
            models.CheckConstraint(
                condition=Q(status__in=[ExceptionStatus.PENDING, ExceptionStatus.CANCELLED])
                | Q(decided_at__isnull=False),
                name="unavailability_decision_dated",
            ),
        ]


# =============================================================================
# Breaks
# =============================================================================


class BreakType(models.TextChoices):
    HOLIDAY = "HOLIDAY", "Vacances"
    PUBLIC_HOLIDAY = "PUBLIC_HOLIDAY", "Jour férié"
    EXAM = "EXAM", "Examens"
    OTHER = "OTHER", "Autre"


class SchoolBreak(TenantModel):
    """Holidays and school-wide interruptions: no session is generated while
    a break with `affects_scheduling` covers it."""

    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="breaks")
    name = models.CharField(max_length=120)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    break_type = models.CharField(max_length=30, choices=BreakType.choices, default=BreakType.HOLIDAY)
    affects_scheduling = models.BooleanField(default=True)

    class Meta:
        ordering = ["start_datetime"]
        constraints = [
            models.CheckConstraint(condition=Q(end_datetime__gt=F("start_datetime")), name="break_times_ordered"),
            models.CheckConstraint(condition=Q(break_type__in=BreakType.values), name="break_type_valid"),
        ]


# =============================================================================
# History / notification outbox
# =============================================================================


class ChangeType(models.TextChoices):
    SLOT_CREATED = "SLOT_CREATED"
    SLOT_ENDED = "SLOT_ENDED"
    SLOT_ARCHIVED = "SLOT_ARCHIVED"
    SESSION_CREATED = "SESSION_CREATED"  # exceptional session (no slot)
    SESSION_CANCELLED = "SESSION_CANCELLED"
    SESSION_MOVED = "SESSION_MOVED"  # new date/time and/or exceptional end
    SESSION_ROOM_CHANGED = "SESSION_ROOM_CHANGED"
    TEACHER_SUBSTITUTED = "TEACHER_SUBSTITUTED"
    TEACHER_RESTORED = "TEACHER_RESTORED"
    SESSIONS_SWAPPED = "SESSIONS_SWAPPED"


class NotificationStatus(models.TextChoices):
    NOT_REQUIRED = "NOT_REQUIRED", "Pas de notification"
    PENDING = "PENDING", "À notifier"
    SENT = "SENT", "Notifiée"


class ScheduleChange(TenantModel):
    """Immutable history of planning changes AND notification outbox.

    Every change keeps old/new values, reason and author: nothing is
    overwritten silently. Changes that matter to families / teachers
    (cancellation, move, substitution, swap) are created with
    notification_status = PENDING and the targets (class, teachers) needed by
    the future notification dispatcher (FCM phase), which will only flip
    PENDING -> SENT. A trigger forbids any other UPDATE and every DELETE.

    Generalises the spec's ScheduleChange (slot-only, ADR 0012).
    """

    change_type = models.CharField(max_length=40, choices=ChangeType.choices, db_index=True)
    schedule_slot = models.ForeignKey(
        ScheduleSlot, on_delete=models.PROTECT, blank=True, null=True, related_name="changes"
    )
    session = models.ForeignKey(
        TeachingSession, on_delete=models.PROTECT, blank=True, null=True, related_name="changes"
    )
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    teacher_ids = models.JSONField(default=list)  # teachers to inform
    old_data = models.JSONField(default=dict)
    new_data = models.JSONField(default=dict)
    reason = models.TextField(blank=True, null=True)
    changed_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)
    notification_status = models.CharField(
        max_length=20, choices=NotificationStatus.choices, default=NotificationStatus.NOT_REQUIRED, db_index=True
    )
    notified_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-changed_at"]
        constraints = [
            models.CheckConstraint(condition=Q(change_type__in=ChangeType.values), name="change_type_valid"),
            models.CheckConstraint(
                condition=Q(notification_status__in=NotificationStatus.values), name="change_notification_status_valid"
            ),
            models.CheckConstraint(
                condition=~Q(notification_status=NotificationStatus.SENT) | Q(notified_at__isnull=False),
                name="change_sent_is_dated",
            ),
        ]
