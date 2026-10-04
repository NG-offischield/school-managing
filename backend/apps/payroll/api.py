"""Payroll API (spec §6.10, ADR 0014).

Administration (PySide6) — ADMIN / SUPER_ADMIN of the school:
    GET/POST /admin/payroll/periods/            GET /admin/payroll/periods/{id}/
    POST     /admin/payroll/periods/{id}/close/
    POST     /admin/payroll/calculate/          {period}  prepare / re-prepare (idempotent)
    GET      /admin/payroll/                    (?period=, ?status=, ?kind=TEACHER|STAFF, ?employee=)
    GET      /admin/payroll/{id}/               lines of every version, settlements, reconstructible
    POST     /admin/payroll/{id}/approve/ | /pay/ {payout_method, wallet?} | /cancel/ {reason}
    GET/POST /admin/payroll/teacher-rates/      GET/POST /admin/payroll/staff-salaries/
    GET/POST /admin/payroll/adjustments/        corrections
    GET      /admin/payroll/check-ins/          (?status=PENDING|VALIDATED|REJECTED, ?teacher=)
    POST     /admin/sessions/{id}/validate/     POST /admin/sessions/{id}/reject/ {reason}
    GET      /admin/payroll/remuneration/?employee=&date_from=&date_to=

Employees (teacher / staff / guardian with an employee profile) — self only:
    GET  /teacher/payroll/                      spec summary: own approved/paid payrolls (+ live
                                                programmed / earned with ?date_from=&date_to=)
    GET  /payroll/me/   /payroll/me/{id}/       own APPROVED or PAID payrolls and their lines
    POST /teacher/sessions/{id}/check-in/       {status: PRESENT|ABSENT} self-report

A prepared (CALCULATED) or cancelled payroll is internal to the
administration: employees see their remuneration once it is approved.
Everything else — another employee's payroll, another school's id — is 404.
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import AcademicYear
from apps.finance.models import Wallet
from apps.people.models import EmployeeProfile, StaffProfile, TeacherProfile
from apps.scheduling.models import TeachingSession
from common.permissions import HasSchoolRole
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import services
from .models import (
    PayoutMethod,
    PayrollLine,
    PayrollPeriod,
    PayrollStatus,
    SalaryAdjustment,
    StaffCompensationProfile,
    StaffPayroll,
    TeacherCompensationProfile,
    TeacherPayroll,
    TeacherSessionCheckIn,
    VerificationStatus,
)

ADMIN = {"ADMIN", "SUPER_ADMIN"}
MONEY = {"max_digits": 14, "decimal_places": 2}
VISIBLE_TO_EMPLOYEE = [PayrollStatus.APPROVED, PayrollStatus.PAID]


def scoped(model, pk, request):
    return get_object_or_404(scope_to_current_school(model.objects.all(), request), pk=pk)


def optional_scoped(model, pk, request):
    return scoped(model, pk, request) if pk else None


def money(value):
    return None if value is None else str(value)


class AdminMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN


# =============================================================================
# Serialization (two payroll tables, one representation)
# =============================================================================


def line_data(line):
    return {
        "id": str(line.id),
        "version": line.version,
        "kind": line.kind,
        "session": str(line.teaching_session_id) if line.teaching_session_id else None,
        "session_date": line.session_date,
        "duration_minutes": line.duration_minutes,
        "vacation_minutes": line.vacation_minutes,
        "rate": money(line.rate),
        "amount": money(line.amount),
        "late": line.late,
        "adjustment": str(line.adjustment_id) if line.adjustment_id else None,
    }


def payroll_data(payroll, *, lines=None, admin=False):
    teacher = isinstance(payroll, TeacherPayroll)
    employee = payroll.teacher.employee if teacher else payroll.staff.employee
    data = {
        "id": str(payroll.id),
        "kind": "TEACHER" if teacher else "STAFF",
        "employee": str(employee.pk),
        "employee_name": employee.membership.user.full_name,
        "period": str(payroll.payroll_period_id),
        "period_name": payroll.payroll_period.name,
        "status": payroll.status,
        "version": payroll.version,
        "adjustments_amount": money(payroll.adjustments_amount),
        "payable_amount": money(payroll.payable_amount),
        "approved_amount": money(payroll.approved_amount),
        "approved_at": payroll.approved_at,
        "paid_at": payroll.paid_at,
        "payout_method": payroll.payout_method,
        "payment_reference": payroll.payment_reference,
        "currency": payroll.currency,
    }
    if teacher:
        data.update(
            programmed_amount=money(payroll.programmed_amount),
            earned_amount=money(payroll.earned_amount),
            scheduled_sessions_count=payroll.scheduled_sessions_count,
            completed_sessions_count=payroll.completed_sessions_count,
            payable_sessions_count=payroll.payable_sessions_count,
        )
    else:
        data.update(base_salary=money(payroll.base_salary), gross_amount=money(payroll.gross_amount))
    if admin:
        data.update(calculated_at=payroll.calculated_at, cancelled_reason=payroll.cancelled_reason)
    if lines is not None:
        data["lines"] = [line_data(line) for line in lines]
    return data


def lines_of(payroll, *, all_versions=False):
    owner = "teacher_payroll" if isinstance(payroll, TeacherPayroll) else "staff_payroll"
    lines = PayrollLine.objects.filter(**{owner: payroll})
    return lines if all_versions else lines.filter(version=payroll.version)


def find_payroll(pk, queryset_filter):
    """A payroll id may belong to either table (UUIDs never collide)."""
    for model in (TeacherPayroll, StaffPayroll):
        found = model.objects.select_related("payroll_period").filter(queryset_filter(model), pk=pk).first()
        if found is not None:
            return found
    raise Http404


# =============================================================================
# Administration
# =============================================================================


class PeriodInput(serializers.Serializer):
    academic_year = serializers.UUIDField()
    name = serializers.CharField(max_length=80)
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class PeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollPeriod
        fields = ["id", "academic_year", "name", "start_date", "end_date", "status", "closed_at"]


class AdminPeriods(AdminMixin, generics.ListAPIView):
    queryset = PayrollPeriod.objects.order_by("start_date")
    serializer_class = PeriodSerializer

    def post(self, request):
        data = PeriodInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        period = services.create_period(
            scoped(AcademicYear, v["academic_year"], request),
            actor=self.membership(),
            name=v["name"],
            start_date=v["start_date"],
            end_date=v["end_date"],
        )
        return Response(PeriodSerializer(period).data, status=status.HTTP_201_CREATED)


class AdminPeriodDetail(AdminMixin, APIView):
    def get(self, request, pk):
        period = scoped(PayrollPeriod, pk, request)
        payrolls = [
            payroll_data(p, admin=True)
            for model in (TeacherPayroll, StaffPayroll)
            for p in model.objects.filter(payroll_period=period).select_related("payroll_period")
        ]
        return Response({**PeriodSerializer(period).data, "payrolls": payrolls})


class AdminPeriodClose(AdminMixin, APIView):
    def post(self, request, pk):
        period = services.close_period(scoped(PayrollPeriod, pk, request), actor=self.membership())
        return Response(PeriodSerializer(period).data)


class CalculateInput(serializers.Serializer):
    period = serializers.UUIDField()


class AdminCalculate(AdminMixin, APIView):
    def post(self, request):
        data = CalculateInput(data=request.data)
        data.is_valid(raise_exception=True)
        summary = services.calculate_period(
            scoped(PayrollPeriod, data.validated_data["period"], request), actor=self.membership()
        )
        return Response(summary)


class AdminPayrollList(AdminMixin, APIView):
    def get(self, request):
        school_filter = Q(school=self.membership().school)
        period = self.uuid_param("period")
        if period:
            school_filter &= Q(payroll_period_id=period)
        if request.query_params.get("status"):
            school_filter &= Q(status=request.query_params["status"])
        kinds = {"TEACHER": [TeacherPayroll], "STAFF": [StaffPayroll]}.get(
            request.query_params.get("kind"), [TeacherPayroll, StaffPayroll]
        )
        employee = self.uuid_param("employee")

        def rows(model):
            queryset = model.objects.filter(school_filter).select_related("payroll_period")
            if employee:
                owner = "teacher__employee_id" if model is TeacherPayroll else "staff__employee_id"
                queryset = queryset.filter(**{owner: employee})
            return queryset.order_by("-payroll_period__start_date", "id")

        return Response([payroll_data(p, admin=True) for model in kinds for p in rows(model)])


class AdminPayrollBase(AdminMixin, APIView):
    def payroll(self, pk):
        school = self.membership().school
        return find_payroll(pk, lambda model: Q(school=school))


class AdminPayrollDetail(AdminPayrollBase):
    def get(self, request, pk):
        payroll = self.payroll(pk)
        data = payroll_data(payroll, lines=lines_of(payroll, all_versions=True), admin=True)
        data["reconstructible"] = services.reconstruct(payroll)
        if isinstance(payroll, TeacherPayroll):
            data["settled_sessions"] = [str(s.teaching_session_id) for s in payroll.settlements.all()]
        return Response(data)


class AdminPayrollApprove(AdminPayrollBase):
    def post(self, request, pk):
        return Response(payroll_data(services.approve_payroll(self.payroll(pk), actor=self.membership()), admin=True))


class PayInput(serializers.Serializer):
    payout_method = serializers.ChoiceField(choices=PayoutMethod.choices)
    wallet = serializers.UUIDField(required=False, allow_null=True)


class AdminPayrollPay(AdminPayrollBase):
    def post(self, request, pk):
        data = PayInput(data=request.data)
        data.is_valid(raise_exception=True)
        payroll = services.pay_payroll(
            self.payroll(pk),
            actor=self.membership(),
            payout_method=data.validated_data["payout_method"],
            wallet=optional_scoped(Wallet, data.validated_data.get("wallet"), request),
        )
        return Response(payroll_data(payroll, admin=True))


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)


class AdminPayrollCancel(AdminPayrollBase):
    def post(self, request, pk):
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        payroll = services.cancel_payroll(
            self.payroll(pk), actor=self.membership(), reason=data.validated_data["reason"]
        )
        return Response(payroll_data(payroll, admin=True))


class TeacherRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherCompensationProfile
        fields = [
            "id",
            "teacher",
            "academic_year",
            "vacation_rate",
            "vacation_minutes",
            "currency",
            "effective_from",
            "effective_to",
            "active",
        ]


class TeacherRateInput(serializers.Serializer):
    teacher = serializers.UUIDField()
    academic_year = serializers.UUIDField()
    vacation_rate = serializers.DecimalField(**MONEY)
    effective_from = serializers.DateField()


class AdminTeacherRates(AdminMixin, generics.ListAPIView):
    queryset = TeacherCompensationProfile.objects.order_by("teacher_id", "effective_from")
    serializer_class = TeacherRateSerializer

    def restrict(self, queryset):
        teacher = self.uuid_param("teacher")
        return queryset.filter(teacher_id=teacher) if teacher else queryset

    def post(self, request):
        data = TeacherRateInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        profile = services.set_teacher_rate(
            scoped(TeacherProfile, v["teacher"], request),
            actor=self.membership(),
            academic_year=scoped(AcademicYear, v["academic_year"], request),
            vacation_rate=v["vacation_rate"],
            effective_from=v["effective_from"],
        )
        return Response(TeacherRateSerializer(profile).data, status=status.HTTP_201_CREATED)


class StaffSalarySerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffCompensationProfile
        fields = ["id", "staff", "monthly_salary", "currency", "effective_from", "effective_to", "active"]


class StaffSalaryInput(serializers.Serializer):
    staff = serializers.UUIDField()
    monthly_salary = serializers.DecimalField(**MONEY)
    effective_from = serializers.DateField()


class AdminStaffSalaries(AdminMixin, generics.ListAPIView):
    queryset = StaffCompensationProfile.objects.order_by("staff_id", "effective_from")
    serializer_class = StaffSalarySerializer

    def post(self, request):
        data = StaffSalaryInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        profile = services.set_staff_salary(
            scoped(StaffProfile, v["staff"], request),
            actor=self.membership(),
            monthly_salary=v["monthly_salary"],
            effective_from=v["effective_from"],
        )
        return Response(StaffSalarySerializer(profile).data, status=status.HTTP_201_CREATED)


class AdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalaryAdjustment
        fields = [
            "id",
            "employee",
            "amount",
            "reason",
            "effective_date",
            "source",
            "teaching_session",
            "settled_teacher_payroll",
            "settled_staff_payroll",
            "created_at",
        ]


class AdjustmentInput(serializers.Serializer):
    employee = serializers.UUIDField()
    amount = serializers.DecimalField(**MONEY)
    reason = serializers.CharField(max_length=1000)
    effective_date = serializers.DateField(required=False)


class AdminAdjustments(AdminMixin, generics.ListAPIView):
    queryset = SalaryAdjustment.objects.order_by("-created_at")
    serializer_class = AdjustmentSerializer

    def restrict(self, queryset):
        employee = self.uuid_param("employee")
        return queryset.filter(employee_id=employee) if employee else queryset

    def post(self, request):
        data = AdjustmentInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        adjustment = services.create_adjustment(
            scoped(EmployeeProfile, v["employee"], request),
            actor=self.membership(),
            amount=v["amount"],
            reason=v["reason"],
            effective_date=v.get("effective_date"),
        )
        return Response(AdjustmentSerializer(adjustment).data, status=status.HTTP_201_CREATED)


class CheckInSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherSessionCheckIn
        fields = [
            "id",
            "teaching_session",
            "teacher",
            "self_reported_status",
            "self_reported_at",
            "verified_status",
            "verified_at",
            "verified_by",
            "verification_reason",
        ]


class AdminCheckIns(AdminMixin, generics.ListAPIView):
    queryset = TeacherSessionCheckIn.objects.order_by("-created_at")
    serializer_class = CheckInSerializer

    def restrict(self, queryset):
        wanted = self.request.query_params.get("status")
        if wanted in VerificationStatus.values:
            queryset = queryset.filter(verified_status=wanted)
        teacher = self.uuid_param("teacher")
        return queryset.filter(teacher_id=teacher) if teacher else queryset


class ValidateInput(serializers.Serializer):
    actual_start = serializers.DateTimeField(required=False)
    actual_end = serializers.DateTimeField(required=False)
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class AdminSessionValidate(AdminMixin, APIView):
    def post(self, request, pk):
        data = ValidateInput(data=request.data)
        data.is_valid(raise_exception=True)
        check_in = services.validate_session(
            scoped(TeachingSession, pk, request), actor=self.membership(), **data.validated_data
        )
        return Response(CheckInSerializer(check_in).data)


class AdminSessionReject(AdminMixin, APIView):
    def post(self, request, pk):
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        check_in = services.reject_session(
            scoped(TeachingSession, pk, request), actor=self.membership(), reason=data.validated_data["reason"]
        )
        return Response(CheckInSerializer(check_in).data)


class RangeMixin:
    def date_range(self, required=True):
        raw_from, raw_to = self.request.query_params.get("date_from"), self.request.query_params.get("date_to")
        if not (raw_from and raw_to):
            if required:
                raise serializers.ValidationError({"date_from": ["Required."], "date_to": ["Required."]})
            return None
        field = serializers.DateField()
        return field.to_internal_value(raw_from), field.to_internal_value(raw_to)


def remuneration_data(summary):
    return {k: money(v) if k.endswith("_amount") or k == "monthly_salary" else v for k, v in summary.items()}


class AdminRemuneration(AdminMixin, RangeMixin, APIView):
    def get(self, request):
        employee = scoped(EmployeeProfile, self.uuid_param("employee"), request)
        return Response(remuneration_data(services.remuneration(employee, *self.date_range())))


# =============================================================================
# Employees: their own remuneration only
# =============================================================================


class OwnPayrollMixin(SchoolScopedMixin):
    def own_filter(self):
        membership = self.membership()

        def build(model):
            owner = "teacher__employee__membership" if model is TeacherPayroll else "staff__employee__membership"
            return Q(school=membership.school, status__in=VISIBLE_TO_EMPLOYEE, **{owner: membership})

        return build


class MyPayrolls(OwnPayrollMixin, APIView):
    def get(self, request):
        build = self.own_filter()
        return Response(
            [
                payroll_data(p)
                for model in (TeacherPayroll, StaffPayroll)
                for p in model.objects.filter(build(model)).select_related("payroll_period").order_by("-paid_at")
            ]
        )


class MyPayrollDetail(OwnPayrollMixin, APIView):
    def get(self, request, pk):
        payroll = find_payroll(pk, self.own_filter())
        return Response(payroll_data(payroll, lines=lines_of(payroll)))


class TeacherPayrollSummary(OwnPayrollMixin, RangeMixin, APIView):
    """Spec: GET /api/v1/teacher/payroll/ — own approved/paid payrolls, and the
    live programmed / earned amounts for a date range when given."""

    def get(self, request):
        membership = self.membership()
        teacher = TeacherProfile.objects.filter(employee__membership=membership).first()
        if teacher is None:
            raise PermissionDenied("This summary is for teachers.")
        build = self.own_filter()
        payrolls = TeacherPayroll.objects.filter(build(TeacherPayroll)).select_related("payroll_period")
        body = {"payrolls": [payroll_data(p) for p in payrolls.order_by("-paid_at")], "live": None}
        dates = self.date_range(required=False)
        if dates:
            body["live"] = remuneration_data(services.remuneration(teacher.employee, *dates))
        return Response(body)


class CheckInInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=["PRESENT", "ABSENT"])


class TeacherSelfCheckIn(SchoolScopedMixin, APIView):
    def post(self, request, pk):
        data = CheckInInput(data=request.data)
        data.is_valid(raise_exception=True)
        session = get_object_or_404(
            scope_to_current_school(TeachingSession.objects.all(), request),
            pk=pk,
            teacher__employee__membership=self.membership(),  # someone else's session: 404
        )
        check_in = services.self_check_in(session, actor=self.membership(), status=data.validated_data["status"])
        return Response(CheckInSerializer(check_in).data, status=status.HTTP_201_CREATED)


urlpatterns = [
    path("admin/payroll/periods/", AdminPeriods.as_view()),
    path("admin/payroll/periods/<uuid:pk>/", AdminPeriodDetail.as_view()),
    path("admin/payroll/periods/<uuid:pk>/close/", AdminPeriodClose.as_view()),
    path("admin/payroll/calculate/", AdminCalculate.as_view()),
    path("admin/payroll/teacher-rates/", AdminTeacherRates.as_view()),
    path("admin/payroll/staff-salaries/", AdminStaffSalaries.as_view()),
    path("admin/payroll/adjustments/", AdminAdjustments.as_view()),
    path("admin/payroll/check-ins/", AdminCheckIns.as_view()),
    path("admin/payroll/remuneration/", AdminRemuneration.as_view()),
    path("admin/payroll/", AdminPayrollList.as_view()),
    path("admin/payroll/<uuid:pk>/", AdminPayrollDetail.as_view()),
    path("admin/payroll/<uuid:pk>/approve/", AdminPayrollApprove.as_view()),
    path("admin/payroll/<uuid:pk>/pay/", AdminPayrollPay.as_view()),
    path("admin/payroll/<uuid:pk>/cancel/", AdminPayrollCancel.as_view()),
    path("admin/sessions/<uuid:pk>/validate/", AdminSessionValidate.as_view()),
    path("admin/sessions/<uuid:pk>/reject/", AdminSessionReject.as_view()),
    path("teacher/payroll/", TeacherPayrollSummary.as_view()),
    path("teacher/sessions/<uuid:pk>/check-in/", TeacherSelfCheckIn.as_view()),
    path("payroll/me/", MyPayrolls.as_view()),
    path("payroll/me/<uuid:pk>/", MyPayrollDetail.as_view()),
]
