"""Academic core API (spec §6.6).

    GET  /courses/                       admin: all — teacher: own courses
    GET  /assessments/                   admin: all — teacher: own courses
    POST /assessments/                   course teacher or admin, open leaf period
    GET  /grades/                        admin: all — teacher: own courses — parent: verified children
    POST /grades/bulk/                   course teacher or admin (all-or-nothing)
    PUT  /grades/{id}/                   course teacher or admin; reason required; logged
    GET  /students/{id}/evolution/       same visibility as the student
    GET  /report-cards/, /{id}/          admin: all — parent: VALIDATED cards of verified children
    POST /report-cards/generate/         admin (addition, ADR 0009)
    POST /report-cards/{id}/validate/    admin, period must be closed
    GET  /classes/{id}/dashboard/        admin or the class's principal teacher (read-only)

Objects referenced in a request body (course, period, student...) are looked
up inside the current school only: an id of another school is a 404.
Business rules are enforced by services.py (400 BUSINESS_RULE_VIOLATION,
403, 409); this module only parses, scopes and formats.
"""

from decimal import Decimal

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import AcademicPeriod, AcademicYear, SchoolClass
from apps.people.api import StudentVisibilityMixin
from apps.people.models import Student
from common.permissions import membership_has_role
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import services
from .models import Assessment, AssessmentType, Course, Grade, ReportCard, ReportCardLine, ReportCardStatus

# =============================================================================
# Serializers
# =============================================================================


class CourseSerializer(serializers.ModelSerializer):
    class_name = serializers.CharField(source="school_class.name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    teacher_name = serializers.CharField(source="teacher.employee.membership.user.full_name", read_only=True)

    class Meta:
        model = Course
        fields = [
            "id",
            "school_class",
            "class_name",
            "subject",
            "subject_code",
            "teacher",
            "teacher_name",
            "academic_year",
            "grading_scale",
            "coefficient",
            "weekly_hours",
            "active",
        ]


class AssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assessment
        fields = [
            "id",
            "course",
            "academic_period",
            "name",
            "assessment_type",
            "max_score",
            "weight",
            "assessment_date",
            "status",
        ]


class AssessmentCreateSerializer(serializers.Serializer):
    course = serializers.UUIDField()
    academic_period = serializers.UUIDField()
    name = serializers.CharField(max_length=120)
    assessment_type = serializers.ChoiceField(choices=AssessmentType.choices)
    max_score = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("0.01"))
    weight = serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0.01"), required=False, default=1
    )
    assessment_date = serializers.DateField(required=False, allow_null=True)


class GradeSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)

    class Meta:
        model = Grade
        fields = [
            "id",
            "assessment",
            "student",
            "student_name",
            "score",
            "max_score",
            "coefficient_override",
            "comment",
            "entered_at",
        ]


class GradeEntrySerializer(serializers.Serializer):
    student = serializers.UUIDField()
    score = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0)
    comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    coefficient_override = serializers.DecimalField(
        max_digits=6, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True
    )


class GradeBulkSerializer(serializers.Serializer):
    assessment = serializers.UUIDField()
    grades = GradeEntrySerializer(many=True, allow_empty=False)


class GradeUpdateSerializer(serializers.Serializer):
    score = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0)
    reason = serializers.CharField()
    # Optimistic concurrency: the score the client last saw (optional).
    expected_score = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, allow_null=True)


class ReportCardLineSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)

    class Meta:
        model = ReportCardLine
        fields = [
            "subject",
            "subject_code",
            "subject_name",
            "average",
            "coefficient",
            "weighted_average",
            "teacher_name_snapshot",
            "appreciation",
        ]


class ReportCardSerializer(serializers.ModelSerializer):
    lines = ReportCardLineSerializer(many=True, read_only=True)
    period_name = serializers.CharField(source="academic_period.name", read_only=True)

    class Meta:
        model = ReportCard
        fields = [
            "id",
            "student",
            "academic_period",
            "period_name",
            "status",
            "general_average",
            "scale_max_score",
            "rank",
            "class_size",
            "generated_at",
            "validated_at",
            "lines",
        ]


class GenerateSerializer(serializers.Serializer):
    school_class = serializers.UUIDField()
    academic_period = serializers.UUIDField()


# =============================================================================
# Helpers
# =============================================================================


def scoped(model, pk, request, **extra):
    """Object of the current school or 404 (ids of other schools included)."""
    return get_object_or_404(scope_to_current_school(model.objects.filter(**extra), request), pk=pk)


class TeacherScopeMixin(SchoolScopedMixin):
    def is_teacher(self):
        return membership_has_role(self.membership(), {"TEACHER"})

    def own_courses_q(self, prefix=""):
        return Q(**{f"{prefix}teacher__employee__membership": self.membership()})


# =============================================================================
# Courses & assessments
# =============================================================================


class CourseList(TeacherScopeMixin, generics.ListAPIView):
    """Filters: ?school_class=, ?academic_year="""

    queryset = Course.objects.select_related("school_class", "subject", "teacher__employee__membership__user").order_by(
        "school_class__name", "subject__name"
    )
    serializer_class = CourseSerializer

    def restrict(self, queryset):
        for name in ("school_class", "academic_year"):
            value = self.uuid_param(name)
            if value:
                queryset = queryset.filter(**{f"{name}_id": value})
        if self.is_admin():
            return queryset
        if self.is_teacher():
            return queryset.filter(self.own_courses_q())
        return queryset.none()


class AssessmentListCreate(TeacherScopeMixin, generics.ListAPIView):
    """Filters: ?course=, ?academic_period="""

    queryset = Assessment.objects.order_by("academic_period__start_date", "created_at")
    serializer_class = AssessmentSerializer

    def restrict(self, queryset):
        for name in ("course", "academic_period"):
            value = self.uuid_param(name)
            if value:
                queryset = queryset.filter(**{f"{name}_id": value})
        if self.is_admin():
            return queryset
        if self.is_teacher():
            return queryset.filter(self.own_courses_q("course__"))
        return queryset.none()

    def post(self, request):
        data = AssessmentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        assessment = services.create_assessment(
            scoped(Course, v["course"], request),
            scoped(AcademicPeriod, v["academic_period"], request),
            actor=self.membership(),
            name=v["name"],
            assessment_type=v["assessment_type"],
            max_score=v["max_score"],
            weight=v["weight"],
            assessment_date=v.get("assessment_date"),
        )
        return Response(AssessmentSerializer(assessment).data, status=status.HTTP_201_CREATED)


# =============================================================================
# Grades
# =============================================================================


class GradeVisibilityMixin(TeacherScopeMixin):
    def visible_grades(self, queryset):
        if self.is_admin():
            return queryset
        membership = self.membership()
        scope = Q(
            student__parent_links__parent__membership=membership,
            student__parent_links__active=True,
            student__parent_links__identity_verified=True,
        )
        if self.is_teacher():
            scope |= self.own_courses_q("assessment__course__")
        return queryset.filter(pk__in=Grade.objects.filter(scope).values("pk"))


class GradeList(GradeVisibilityMixin, generics.ListAPIView):
    """Filters: ?assessment=, ?student="""

    queryset = Grade.objects.select_related("student").order_by("student__last_name", "student__first_name")
    serializer_class = GradeSerializer

    def restrict(self, queryset):
        for name in ("assessment", "student"):
            value = self.uuid_param(name)
            if value:
                queryset = queryset.filter(**{f"{name}_id": value})
        return self.visible_grades(queryset)


class GradeBulkCreate(SchoolScopedMixin, APIView):
    def post(self, request):
        data = GradeBulkSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        assessment = scoped(Assessment, v["assessment"], request)
        entries = [{**entry, "student": scoped(Student, entry["student"], request)} for entry in v["grades"]]
        grades = services.enter_grades_bulk(assessment, entries, actor=self.membership())
        return Response(GradeSerializer(grades, many=True).data, status=status.HTTP_201_CREATED)


class GradeUpdate(GradeVisibilityMixin, generics.GenericAPIView):
    queryset = Grade.objects.all()

    def restrict(self, queryset):
        return self.visible_grades(queryset)

    def put(self, request, pk):
        grade = self.get_object()  # 404 outside the caller's visibility
        data = GradeUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        grade = services.update_grade(
            grade,
            v["score"],
            actor=self.membership(),
            reason=v["reason"],
            expected_score=v.get("expected_score"),
        )
        return Response(GradeSerializer(grade).data)


# =============================================================================
# Evolution & report cards
# =============================================================================


class StudentEvolution(StudentVisibilityMixin, generics.GenericAPIView):
    """?academic_year=<uuid> (defaults to the school's current year)."""

    queryset = Student.objects.all()

    def restrict(self, queryset):
        return self.visible_students(queryset)

    def get(self, request, pk):
        student = self.get_object()
        year_id = self.uuid_param("academic_year")
        years = scope_to_current_school(AcademicYear.objects.all(), request)
        year = get_object_or_404(years, pk=year_id) if year_id else years.filter(is_current=True).first()
        evolution = services.student_evolution(student, year) if year else []
        return Response(
            {"student": str(student.pk), "academic_year": str(year.pk) if year else None, "periods": evolution}
        )


class ReportCardVisibilityMixin(SchoolScopedMixin):
    def visible_cards(self, queryset):
        if self.is_admin():
            return queryset
        # Parents only see official (VALIDATED) cards of verified children.
        return queryset.filter(
            status=ReportCardStatus.VALIDATED,
            pk__in=ReportCard.objects.filter(
                student__parent_links__parent__membership=self.membership(),
                student__parent_links__active=True,
                student__parent_links__identity_verified=True,
            ).values("pk"),
        )


class ReportCardList(ReportCardVisibilityMixin, generics.ListAPIView):
    """Filters: ?academic_period=, ?student="""

    queryset = (
        ReportCard.objects.select_related("academic_period")
        .prefetch_related("lines__subject")
        .order_by("academic_period__start_date", "rank")
    )
    serializer_class = ReportCardSerializer

    def restrict(self, queryset):
        for name in ("academic_period", "student"):
            value = self.uuid_param(name)
            if value:
                queryset = queryset.filter(**{f"{name}_id": value})
        return self.visible_cards(queryset)


class ReportCardDetail(ReportCardVisibilityMixin, generics.RetrieveAPIView):
    queryset = ReportCard.objects.select_related("academic_period").prefetch_related("lines__subject")
    serializer_class = ReportCardSerializer

    def restrict(self, queryset):
        return self.visible_cards(queryset)


class ReportCardGenerate(SchoolScopedMixin, APIView):
    def post(self, request):
        data = GenerateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        cards = services.generate_report_cards(
            scoped(SchoolClass, data.validated_data["school_class"], request),
            scoped(AcademicPeriod, data.validated_data["academic_period"], request),
            actor=self.membership(),
        )
        return Response(ReportCardSerializer(cards, many=True).data, status=status.HTTP_201_CREATED)


class ClassDashboard(SchoolScopedMixin, APIView):
    """GET /classes/{id}/dashboard/?academic_period=<uuid> (spec §6.4).
    Read-only; admins and the class's principal teacher only."""

    def get(self, request, pk):
        period_id = self.uuid_param("academic_period")
        if period_id is None:
            raise serializers.ValidationError({"academic_period": ["This query parameter is required."]})
        school_class = scoped(SchoolClass, pk, request)
        period = scoped(AcademicPeriod, period_id, request)
        return Response(services.class_dashboard(school_class, period, actor=self.membership()))


class ReportCardValidate(SchoolScopedMixin, APIView):
    def post(self, request, pk):
        card = services.validate_report_card(scoped(ReportCard, pk, request), actor=self.membership())
        return Response(ReportCardSerializer(card).data)


urlpatterns = [
    path("courses/", CourseList.as_view(), name="courses"),
    path("assessments/", AssessmentListCreate.as_view(), name="assessments"),
    path("grades/", GradeList.as_view(), name="grades"),
    path("grades/bulk/", GradeBulkCreate.as_view(), name="grades-bulk"),
    path("grades/<uuid:pk>/", GradeUpdate.as_view(), name="grade"),
    path("students/<uuid:pk>/evolution/", StudentEvolution.as_view(), name="student-evolution"),
    path("report-cards/", ReportCardList.as_view(), name="report-cards"),
    path("report-cards/generate/", ReportCardGenerate.as_view(), name="report-cards-generate"),
    path("report-cards/<uuid:pk>/", ReportCardDetail.as_view(), name="report-card"),
    path("report-cards/<uuid:pk>/validate/", ReportCardValidate.as_view(), name="report-card-validate"),
    path("classes/<uuid:pk>/dashboard/", ClassDashboard.as_view(), name="class-dashboard"),
]
