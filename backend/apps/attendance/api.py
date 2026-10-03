"""Attendance & QR API (spec §6.7, ADR 0011).

Gate scanning (Flutter, guardians / staff / admins):
    POST /qr/scans/                         {token, device_id?}  -> 201 {result, student?, attendance?}
    GET  /guardians/scans/                  the caller's own scans (?date=)

Families:
    GET  /students/{id}/attendance/         daily records + alert summary (admin, verified parent, class teacher)
    GET  /students/{id}/scans/              accepted scans of the child (admin, verified parent)
    GET  /parents/convocations/             the caller's convocations

Administration (PySide6, ADMIN / SUPER_ADMIN):
    GET  /admin/scans/                      all scans (?date= ?student= ?result=)
    GET  /admin/attendance/dashboard/       ?date=  counts + students at YELLOW or above
    POST /admin/attendance/finalize/        {date}
    POST /admin/attendance/{id}/correct/    {status, reason, arrival_time?}
    GET  /admin/attendance/policies/        PUT /admin/attendance/policies/{day_of_week}/
    GET  /admin/qr-codes/                   ?student= ?status=   (tokens visible: card printing)
    POST /admin/qr-codes/issue/             {student}
    POST /admin/qr-codes/issue-class/       {school_class}
    POST /admin/qr-codes/reissue/           {student, reason}
    POST /admin/qr-codes/{id}/revoke/       {reason}
    GET/POST /admin/convocations/           POST /admin/convocations/{id}/status/ {status, notes?}

Every write goes through services.py. Ids in bodies / URLs are resolved
inside the current school (404 otherwise). The QR token is only ever returned
by the admin QR endpoints.
"""

from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.academics.models import AcademicYear, SchoolClass
from apps.accounts.models import UserDevice
from apps.finance import services as finance_services
from apps.people.api import StudentVisibilityMixin
from apps.people.models import ParentProfile, Student
from common.permissions import HasSchoolRole
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import services
from .models import (
    AttendancePolicy,
    Convocation,
    DailyStatus,
    GuardianScan,
    ScanResult,
    StudentDailyAttendance,
    StudentQRCode,
)

ADMIN = {"ADMIN", "SUPER_ADMIN"}


def scoped(model, pk, request):
    return get_object_or_404(scope_to_current_school(model.objects.all(), request), pk=pk)


class AdminMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN


def date_param(view, name="date"):
    raw = view.request.query_params.get(name)
    if not raw:
        return None
    field = serializers.DateField()
    try:
        return field.to_internal_value(raw)
    except serializers.ValidationError:
        raise serializers.ValidationError({name: ["Must be a date (YYYY-MM-DD)."]}) from None


# =============================================================================
# Serializers
# =============================================================================


class ScanSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", default=None, read_only=True)

    class Meta:
        model = GuardianScan
        fields = ["id", "scanned_at", "result", "student", "student_name", "scanned_by"]


class ChildScanSerializer(serializers.ModelSerializer):
    """What a parent sees: when the child was scanned — not who scanned."""

    class Meta:
        model = GuardianScan
        fields = ["id", "scanned_at", "result"]


class DailySerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentDailyAttendance
        fields = [
            "id",
            "student",
            "date",
            "status",
            "arrival_time",
            "late_minutes",
            "absence_hours",
            "source",
            "finalized_at",
            "note",
        ]


class QRSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentQRCode
        fields = [
            "id",
            "student",
            "academic_year",
            "token",
            "version",
            "status",
            "issued_at",
            "revoked_at",
            "revocation_reason",
        ]


class PolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendancePolicy
        fields = [
            "id",
            "day_of_week",
            "late_after_time",
            "morning_absence_cutoff",
            "day_absence_trigger",
            "absence_hours",
            "active",
        ]
        read_only_fields = ["id", "day_of_week"]


class ConvocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Convocation
        fields = [
            "id",
            "student",
            "parent",
            "scheduled_start",
            "scheduled_end",
            "reason",
            "alert_level",
            "status",
            "notes",
        ]


class ScanInput(serializers.Serializer):
    token = serializers.CharField(max_length=256)
    device_id = serializers.UUIDField(required=False, allow_null=True)


# =============================================================================
# Gate scanning
# =============================================================================


class ScanCreate(SchoolScopedMixin, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "qr-scan"

    def post(self, request):
        data = ScanInput(data=request.data)
        data.is_valid(raise_exception=True)
        device = None
        if data.validated_data.get("device_id"):
            # Only one of the caller's own devices can be attached.
            device = UserDevice.objects.filter(pk=data.validated_data["device_id"], user=request.user).first()
        outcome = services.scan(data.validated_data["token"], actor=self.membership(), device=device)
        scan = outcome.scan
        payload = {
            "scan_id": str(scan.pk),
            "result": scan.result,
            "scanned_at": scan.scanned_at,
            "student": None,
            "attendance": None,
            # Spec §7: UP_TO_DATE / OVERDUE only — never amounts (ADR 0013).
            "solvency": None,
        }
        if outcome.attendance is not None:
            payload["solvency"] = finance_services.solvency(scan.student)
            enrollment = (
                scan.student.enrollments.filter(academic_year=scan.academic_year).select_related("school_class").first()
            )
            payload["student"] = {
                "id": str(scan.student.pk),
                "name": scan.student.full_name,
                "class": enrollment.school_class.name if enrollment else None,
            }
            payload["attendance"] = {
                "status": outcome.attendance.status,
                "arrival_time": outcome.attendance.arrival_time,
                "late_minutes": outcome.attendance.late_minutes,
            }
        return Response(payload, status=status.HTTP_201_CREATED)


class MyScans(SchoolScopedMixin, generics.ListAPIView):
    queryset = GuardianScan.objects.select_related("student").order_by("-scanned_at")
    serializer_class = ScanSerializer

    def restrict(self, queryset):
        queryset = queryset.filter(scanned_by=self.membership())
        day = date_param(self)
        if day:
            start, end = services.day_window(self.membership().school, day)
            queryset = queryset.filter(scanned_at__gte=start, scanned_at__lt=end)
        return queryset


# =============================================================================
# Families
# =============================================================================


class StudentAttendance(StudentVisibilityMixin, generics.GenericAPIView):
    """?academic_year=<uuid> (default: current year)."""

    queryset = Student.objects.all()

    def restrict(self, queryset):
        return self.visible_students(queryset)

    def get(self, request, pk):
        student = self.get_object()
        year_id = self.uuid_param("academic_year")
        years = scope_to_current_school(AcademicYear.objects.all(), request)
        year = get_object_or_404(years, pk=year_id) if year_id else years.filter(is_current=True).first()
        if year is None:
            return Response({"student": str(student.pk), "academic_year": None, "summary": None, "records": []})
        records = StudentDailyAttendance.objects.filter(student=student, academic_year=year).order_by("-date")
        return Response(
            {
                "student": str(student.pk),
                "academic_year": str(year.pk),
                "summary": services.absence_summary(student, year),
                "records": DailySerializer(records, many=True).data,
            }
        )


class StudentScans(SchoolScopedMixin, generics.ListAPIView):
    """Accepted scans of one child: admins, or a parent with a VERIFIED link."""

    queryset = GuardianScan.objects.order_by("-scanned_at")
    serializer_class = ChildScanSerializer

    def restrict(self, queryset):
        student = scoped(Student, self.kwargs["pk"], self.request)
        if not self.is_admin():
            linked = Student.objects.filter(
                pk=student.pk,
                parent_links__parent__membership=self.membership(),
                parent_links__active=True,
                parent_links__identity_verified=True,
            ).exists()
            if not linked:
                return queryset.none()
        return queryset.filter(student=student, result__in=[ScanResult.ACCEPTED, ScanResult.ALREADY_PRESENT])


class ParentConvocations(SchoolScopedMixin, generics.ListAPIView):
    queryset = Convocation.objects.order_by("-scheduled_start")
    serializer_class = ConvocationSerializer

    def restrict(self, queryset):
        return queryset.filter(parent__membership=self.membership())


# =============================================================================
# Administration
# =============================================================================


class AdminScans(AdminMixin, generics.ListAPIView):
    queryset = GuardianScan.objects.select_related("student").order_by("-scanned_at")
    serializer_class = ScanSerializer

    def restrict(self, queryset):
        day = date_param(self)
        if day:
            start, end = services.day_window(self.membership().school, day)
            queryset = queryset.filter(scanned_at__gte=start, scanned_at__lt=end)
        student = self.uuid_param("student")
        if student:
            queryset = queryset.filter(student_id=student)
        result = self.request.query_params.get("result")
        if result:
            if result not in ScanResult.values:
                raise serializers.ValidationError({"result": ["Unknown result."]})
            queryset = queryset.filter(result=result)
        return queryset


class AttendanceDashboard(AdminMixin, APIView):
    def get(self, request):
        school = self.membership().school
        day = date_param(self)
        if day is None:
            raise serializers.ValidationError({"date": ["This query parameter is required."]})
        year = services.current_year(school)
        counts = {s: 0 for s in DailyStatus.values}
        for row in StudentDailyAttendance.objects.filter(school=school, date=day).values_list("status", flat=True):
            counts[row] += 1
        alerts = []
        for student in Student.objects.filter(school=school, daily_attendance__academic_year=year).distinct():
            summary = services.absence_summary(student, year)
            if summary["alert_level"] != "NONE":
                alerts.append({"student": str(student.pk), "name": student.full_name, **summary})
        alerts.sort(key=lambda a: a["unexcused_absence_hours"], reverse=True)
        return Response({"date": day, "academic_year": str(year.pk), "counts": counts, "alerts": alerts})


class FinalizeInput(serializers.Serializer):
    date = serializers.DateField()


class AttendanceFinalize(AdminMixin, APIView):
    def post(self, request):
        data = FinalizeInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            services.finalize_day(self.membership().school, data.validated_data["date"], actor=self.membership())
        )


class CorrectInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=[s for s in DailyStatus.values if s != DailyStatus.PENDING])
    reason = serializers.CharField()
    arrival_time = serializers.DateTimeField(required=False, allow_null=True)


class AttendanceCorrect(AdminMixin, APIView):
    def post(self, request, pk):
        record = scoped(StudentDailyAttendance, pk, request)
        data = CorrectInput(data=request.data)
        data.is_valid(raise_exception=True)
        record = services.correct_attendance(record, actor=self.membership(), **data.validated_data)
        return Response(DailySerializer(record).data)


class PolicyList(AdminMixin, generics.ListAPIView):
    queryset = AttendancePolicy.objects.order_by("day_of_week")
    serializer_class = PolicySerializer


class PolicySet(AdminMixin, APIView):
    def put(self, request, day):
        if not 1 <= day <= 7:
            raise serializers.ValidationError({"day_of_week": ["Must be between 1 (Monday) and 7 (Sunday)."]})
        data = PolicySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        policy = services.set_policy(self.membership().school, day, actor=self.membership(), **data.validated_data)
        return Response(PolicySerializer(policy).data)


class QRList(AdminMixin, generics.ListAPIView):
    queryset = StudentQRCode.objects.order_by("-issued_at")
    serializer_class = QRSerializer

    def restrict(self, queryset):
        student = self.uuid_param("student")
        if student:
            queryset = queryset.filter(student_id=student)
        qr_status = self.request.query_params.get("status")
        if qr_status:
            queryset = queryset.filter(status=qr_status)
        return queryset


class StudentInput(serializers.Serializer):
    student = serializers.UUIDField()
    reason = serializers.CharField(required=False)


class QRIssue(AdminMixin, APIView):
    def post(self, request):
        data = StudentInput(data=request.data)
        data.is_valid(raise_exception=True)
        qr = services.issue_qr_code(scoped(Student, data.validated_data["student"], request), actor=self.membership())
        return Response(QRSerializer(qr).data, status=status.HTTP_201_CREATED)


class QRReissue(AdminMixin, APIView):
    def post(self, request):
        data = StudentInput(data=request.data)
        data.is_valid(raise_exception=True)
        qr = services.reissue_qr_code(
            scoped(Student, data.validated_data["student"], request),
            actor=self.membership(),
            reason=data.validated_data.get("reason", ""),
        )
        return Response(QRSerializer(qr).data, status=status.HTTP_201_CREATED)


class ClassInput(serializers.Serializer):
    school_class = serializers.UUIDField()


class QRIssueClass(AdminMixin, APIView):
    def post(self, request):
        data = ClassInput(data=request.data)
        data.is_valid(raise_exception=True)
        codes = services.issue_class_qr_codes(
            scoped(SchoolClass, data.validated_data["school_class"], request), actor=self.membership()
        )
        return Response(QRSerializer(codes, many=True).data, status=status.HTTP_201_CREATED)


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField()


class QRRevoke(AdminMixin, APIView):
    def post(self, request, pk):
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        qr = services.revoke_qr_code(scoped(StudentQRCode, pk, request), actor=self.membership(), **data.validated_data)
        return Response(QRSerializer(qr).data)


class ConvocationInput(serializers.Serializer):
    student = serializers.UUIDField()
    parent = serializers.UUIDField()
    scheduled_start = serializers.DateTimeField()
    scheduled_end = serializers.DateTimeField()
    reason = serializers.CharField()


class AdminConvocations(AdminMixin, generics.ListAPIView):
    queryset = Convocation.objects.order_by("-scheduled_start")
    serializer_class = ConvocationSerializer

    def restrict(self, queryset):
        student = self.uuid_param("student")
        return queryset.filter(student_id=student) if student else queryset

    def post(self, request):
        data = ConvocationInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        convocation = services.create_convocation(
            scoped(Student, v["student"], request),
            scoped(ParentProfile, v["parent"], request),
            actor=self.membership(),
            scheduled_start=v["scheduled_start"],
            scheduled_end=v["scheduled_end"],
            reason=v["reason"],
        )
        return Response(ConvocationSerializer(convocation).data, status=status.HTTP_201_CREATED)


class ConvocationStatusInput(serializers.Serializer):
    status = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class ConvocationStatusUpdate(AdminMixin, APIView):
    def post(self, request, pk):
        data = ConvocationStatusInput(data=request.data)
        data.is_valid(raise_exception=True)
        convocation = services.set_convocation_status(
            scoped(Convocation, pk, request),
            data.validated_data["status"],
            actor=self.membership(),
            notes=data.validated_data.get("notes"),
        )
        return Response(ConvocationSerializer(convocation).data)


urlpatterns = [
    path("qr/scans/", ScanCreate.as_view(), name="qr-scan"),
    path("guardians/scans/", MyScans.as_view(), name="guardian-scans"),
    path("students/<uuid:pk>/attendance/", StudentAttendance.as_view(), name="student-attendance"),
    path("students/<uuid:pk>/scans/", StudentScans.as_view(), name="student-scans"),
    path("parents/convocations/", ParentConvocations.as_view(), name="parent-convocations"),
    path("admin/scans/", AdminScans.as_view(), name="admin-scans"),
    path("admin/attendance/dashboard/", AttendanceDashboard.as_view(), name="attendance-dashboard"),
    path("admin/attendance/finalize/", AttendanceFinalize.as_view(), name="attendance-finalize"),
    path("admin/attendance/<uuid:pk>/correct/", AttendanceCorrect.as_view(), name="attendance-correct"),
    path("admin/attendance/policies/", PolicyList.as_view(), name="attendance-policies"),
    path("admin/attendance/policies/<int:day>/", PolicySet.as_view(), name="attendance-policy"),
    path("admin/qr-codes/", QRList.as_view(), name="qr-codes"),
    path("admin/qr-codes/issue/", QRIssue.as_view(), name="qr-issue"),
    path("admin/qr-codes/issue-class/", QRIssueClass.as_view(), name="qr-issue-class"),
    path("admin/qr-codes/reissue/", QRReissue.as_view(), name="qr-reissue"),
    path("admin/qr-codes/<uuid:pk>/revoke/", QRRevoke.as_view(), name="qr-revoke"),
    path("admin/convocations/", AdminConvocations.as_view(), name="admin-convocations"),
    path("admin/convocations/<uuid:pk>/status/", ConvocationStatusUpdate.as_view(), name="convocation-status"),
]
