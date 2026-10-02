"""Read-only endpoints for people (spec §6.4, §6.5, §6.6).

Visibility follows the permission matrix of spec §8, restricted to what
exists in this phase:

    resource            ADMIN/SUPER_ADMIN   TEACHER          PARENT                 others
    ------------------  -----------------   --------------   --------------------   ------
    students            all                 none yet (*)     own VERIFIED children  none
    parents/children    —                   —                own VERIFIED children  —
    teachers            all                 self             none                   none
    teacher quals       all                 self             none                   none
    staff               all                 none             none                   self (STAFF)

(*) "R scoped" for teachers means "students of the classes I teach": that
scope needs Course / TeacherClassAssignment, which arrive with the next
academic phase. Until then a teacher sees no student — fail closed.

Out-of-scope objects are filtered out of the queryset, so they answer 404
exactly like ids that do not exist.
"""

from django.urls import path
from rest_framework import generics, serializers

from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from .models import (
    ParentStudent,
    StaffProfile,
    Student,
    StudentEnrollment,
    TeacherProfile,
    TeacherSubjectQualification,
)

# -----------------------------------------------------------------------------
# Serializers
# -----------------------------------------------------------------------------


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            "id",
            "student_number",
            "registration_number",
            "first_name",
            "last_name",
            "date_of_birth",
            "sex",
            "birth_place",
            "status",
            "archived_at",
        ]


class EnrollmentSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source="academic_year.name", read_only=True)
    class_name = serializers.CharField(source="school_class.name", read_only=True)

    class Meta:
        model = StudentEnrollment
        fields = [
            "id",
            "academic_year",
            "academic_year_name",
            "school_class",
            "class_name",
            "enrollment_date",
            "end_date",
            "status",
            "promotion_status",
            "decision_date",
        ]


class ChildLinkSerializer(serializers.ModelSerializer):
    student = StudentSerializer(read_only=True)

    class Meta:
        model = ParentStudent
        fields = [
            "id",
            "student",
            "relationship_type",
            "is_primary_contact",
            "can_receive_notifications",
            "can_view_financial_data",
            "can_pay",
            "can_submit_complaints",
            "verified_at",
        ]


class TeacherSerializer(serializers.ModelSerializer):
    teacher_number = serializers.CharField(read_only=True)
    first_name = serializers.CharField(source="employee.membership.user.first_name", read_only=True)
    last_name = serializers.CharField(source="employee.membership.user.last_name", read_only=True)
    category_code = serializers.CharField(source="pedagogical_category.code", read_only=True)
    primary_subject_code = serializers.CharField(source="primary_subject.code", read_only=True)

    class Meta:
        model = TeacherProfile
        fields = [
            "id",
            "teacher_number",
            "first_name",
            "last_name",
            "pedagogical_category",
            "category_code",
            "primary_subject",
            "primary_subject_code",
            "professional_status",
        ]


class QualificationSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source="subject.code", read_only=True)

    class Meta:
        model = TeacherSubjectQualification
        fields = [
            "id",
            "subject",
            "subject_code",
            "status",
            "verified",
            "verified_at",
            "source",
            "computed_compatibility",
        ]


class StaffSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source="employee.membership.user.first_name", read_only=True)
    last_name = serializers.CharField(source="employee.membership.user.last_name", read_only=True)
    employee_number = serializers.CharField(source="employee.employee_number", read_only=True)
    functions = serializers.SerializerMethodField()

    class Meta:
        model = StaffProfile
        fields = ["id", "staff_number", "employee_number", "first_name", "last_name", "functions"]

    def get_functions(self, obj):
        return sorted(a.function.code for a in obj.function_assignments.all() if a.active)


# -----------------------------------------------------------------------------
# Visibility helpers
# -----------------------------------------------------------------------------


class StudentVisibilityMixin(SchoolScopedMixin):
    """Admins see every student of the school; a parent sees only children
    linked to them by an ACTIVE and VERIFIED ParentStudent; others none."""

    def visible_students(self, queryset):
        if self.is_admin():
            return queryset
        membership = self.membership()
        return queryset.filter(
            parent_links__parent__membership=membership,
            parent_links__active=True,
            parent_links__identity_verified=True,
        ).distinct()


# -----------------------------------------------------------------------------
# Views
# -----------------------------------------------------------------------------


class StudentList(StudentVisibilityMixin, generics.ListAPIView):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer

    def restrict(self, queryset):
        return self.visible_students(queryset)


class StudentDetail(StudentVisibilityMixin, generics.RetrieveAPIView):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer

    def restrict(self, queryset):
        return self.visible_students(queryset)


class StudentEnrollmentList(StudentVisibilityMixin, generics.ListAPIView):
    """GET /students/{id}/enrollments/ — the year-by-year history."""

    queryset = StudentEnrollment.objects.select_related("academic_year", "school_class")
    serializer_class = EnrollmentSerializer

    def restrict(self, queryset):
        students = self.visible_students(scope_to_current_school(Student.objects.all(), self.request))
        return queryset.filter(student_id=self.kwargs["pk"], student__in=students)


class ParentChildrenList(SchoolScopedMixin, generics.ListAPIView):
    """GET /parents/children/ (spec §6.5) — the caller's verified children."""

    queryset = ParentStudent.objects.select_related("student").order_by("student__last_name", "student__first_name")
    serializer_class = ChildLinkSerializer

    def restrict(self, queryset):
        return queryset.filter(parent__membership=self.membership(), active=True, identity_verified=True)


class TeacherVisibilityMixin(SchoolScopedMixin):
    queryset = TeacherProfile.objects.select_related(
        "employee__membership__user", "pedagogical_category", "primary_subject"
    ).order_by("employee__employee_number")
    serializer_class = TeacherSerializer

    def visible_teachers(self, queryset):
        if self.is_admin():
            return queryset
        return queryset.filter(employee__membership=self.membership())

    def restrict(self, queryset):
        return self.visible_teachers(queryset)


# NB: list and detail are two distinct views sharing the mixin. (A first
# version made the detail view inherit the list view: its get() then served
# the LIST on /teachers/{id}/ — caught by the cross-school isolation test.)
class TeacherList(TeacherVisibilityMixin, generics.ListAPIView):
    pass


class TeacherDetail(TeacherVisibilityMixin, generics.RetrieveAPIView):
    pass


class TeacherQualificationList(TeacherVisibilityMixin, generics.ListAPIView):
    queryset = TeacherSubjectQualification.objects.select_related("subject").order_by("subject__name")
    serializer_class = QualificationSerializer

    def restrict(self, queryset):
        teachers = self.visible_teachers(scope_to_current_school(TeacherProfile.objects.all(), self.request))
        return queryset.filter(teacher_id=self.kwargs["pk"], teacher__in=teachers)


class StaffList(SchoolScopedMixin, generics.ListAPIView):
    queryset = (
        StaffProfile.objects.select_related("employee__membership__user")
        .prefetch_related("function_assignments__function")
        .order_by("staff_number")
    )
    serializer_class = StaffSerializer

    def restrict(self, queryset):
        if self.is_admin():
            return queryset
        return queryset.filter(employee__membership=self.membership())


urlpatterns = [
    path("students/", StudentList.as_view(), name="students"),
    path("students/<uuid:pk>/", StudentDetail.as_view(), name="student"),
    path("students/<uuid:pk>/enrollments/", StudentEnrollmentList.as_view(), name="student-enrollments"),
    path("parents/children/", ParentChildrenList.as_view(), name="parent-children"),
    path("teachers/", TeacherList.as_view(), name="teachers"),
    path("teachers/<uuid:pk>/", TeacherDetail.as_view(), name="teacher"),
    path("teachers/<uuid:pk>/qualifications/", TeacherQualificationList.as_view(), name="teacher-qualifications"),
    path("staff/", StaffList.as_view(), name="staff"),
]
