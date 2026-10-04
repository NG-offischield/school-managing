"""Finance API (spec §6.9, ADR 0013).

Payers and families:
    GET  /finance/students/{id}/obligations/   open invoices + balance of a child
    GET  /finance/invoices/   /finance/invoices/{id}/      (?student=, ?status=, ?search=,
                                                            ?date_from=, ?date_to= on the issue date)
    POST /finance/payments/                    initiate (Idempotency-Key header or body field)
    GET  /finance/payments/   /finance/payments/{id}/      history / result (?student=, ?status=,
                                                            ?payment_method=, ?search=, ?date_from=, ?date_to=)
    GET  /finance/wallets/                     the caller's own wallets

Administration (PySide6):
    GET/POST /admin/finance/fee-types/         GET/POST /admin/finance/fee-schedules/
    POST /admin/finance/invoices/              POST /admin/finance/invoices/generate/
    POST /admin/finance/invoices/{id}/cancel/
    POST /admin/finance/payments/{id}/refund/   GET /admin/finance/refunds/ (?search=, ?date_from=, ?date_to=)
    GET/POST /admin/finance/wallets/           POST /admin/finance/wallets/{id}/fund/
    GET  /admin/finance/treasury/              POST /admin/finance/treasury/credit/
    GET  /admin/finance/dashboard/

Visibility: ADMIN/SUPER_ADMIN everything of their school. Anybody else only
the invoices / payments of children linked to them by an ACTIVE, VERIFIED
link with `can_view_financial_data`, plus the payments they made themselves.
Members without financial rights (teacher, staff, guardian...) see nothing.
Ids of another school, or outside the caller's visibility, answer 404.

Payment initiation answers 201 with the payment whatever its outcome
(SUCCEEDED, DECLINED, INSUFFICIENT_FUNDS, TIMEOUT, PROVIDER_ERROR): a failed
payment is a result, not an error. A replay of the same idempotency key
answers 200 with the original payment; the same key for a different request
answers 409 CONFLICT (rule idempotency_conflict).
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import AcademicYear, Level, SchoolClass
from apps.accounts.models import SchoolMembership
from apps.people.models import ParentStudent, Student
from common.permissions import HasSchoolRole
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import services
from .models import (
    FeeSchedule,
    FeeType,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentRefund,
    SimulationBehavior,
    TreasuryTransaction,
    Wallet,
)

ADMIN = {"ADMIN", "SUPER_ADMIN"}
MONEY = {"max_digits": 18, "decimal_places": 2}


def scoped(model, pk, request):
    return get_object_or_404(scope_to_current_school(model.objects.all(), request), pk=pk)


def optional_scoped(model, pk, request):
    return scoped(model, pk, request) if pk else None


class AdminMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN


class FinanceVisibility(SchoolScopedMixin):
    def finance_student_ids(self):
        """Children whose finances the caller may read."""
        return ParentStudent.objects.filter(
            parent__membership=self.membership(), active=True, identity_verified=True, can_view_financial_data=True
        ).values("student_id")

    search_fields = ()  # text search (?search=), case-insensitive
    date_field = None  # ?date_from= / ?date_to= (inclusive)

    def filter_params(self, queryset):
        params = self.request.query_params
        student = self.uuid_param("student")
        if student:
            queryset = queryset.filter(student_id=student)
        status_param = params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)
        if params.get("payment_method") and "payment_method" in {f.name for f in queryset.model._meta.fields}:
            queryset = queryset.filter(payment_method=params["payment_method"])
        return filter_search_and_dates(queryset, params, self.search_fields, self.date_field)


def filter_search_and_dates(queryset, params, search_fields, date_field):
    """Narrowing only: visibility was applied before (restrict)."""
    search = (params.get("search") or "").strip()
    if search and search_fields:
        condition = Q()
        for name in search_fields:
            condition |= Q(**{f"{name}__icontains": search})
        queryset = queryset.filter(condition)
    if date_field:
        field = serializers.DateField()
        for key, lookup in (("date_from", "gte"), ("date_to", "lte")):
            if params.get(key):
                queryset = queryset.filter(**{f"{date_field}__{lookup}": field.to_internal_value(params[key])})
    return queryset


STUDENT_SEARCH = ("student__first_name", "student__last_name", "student__student_number")


# =============================================================================
# Serializers
# =============================================================================


class FeeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeType
        fields = ["id", "code", "name", "description", "active"]


class FeeScheduleSerializer(serializers.ModelSerializer):
    fee_type_code = serializers.CharField(source="fee_type.code", read_only=True)

    class Meta:
        model = FeeSchedule
        fields = [
            "id",
            "fee_type",
            "fee_type_code",
            "academic_year",
            "level",
            "school_class",
            "amount",
            "due_date",
            "mandatory",
            "active",
        ]


class InvoiceLineSerializer(serializers.ModelSerializer):
    fee_type_code = serializers.CharField(source="fee_type.code", read_only=True)

    class Meta:
        model = InvoiceLine
        fields = ["id", "fee_type", "fee_type_code", "description", "quantity", "unit_price", "total"]


class InvoiceSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "student",
            "student_name",
            "academic_year",
            "issue_date",
            "due_date",
            "status",
            "total_amount",
            "amount_paid",
            "balance_due",
            "currency",
            "cancelled_reason",
            "lines",
        ]


class AllocationSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = PaymentAllocation
        fields = ["id", "invoice", "invoice_number", "amount", "refund", "allocated_at"]


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRefund
        fields = ["id", "payment", "amount", "reason", "status", "completed_at", "inverse_transaction_reference"]


class RefundListSerializer(RefundSerializer):
    """A refund with its original payment (administration list)."""

    payment_reference = serializers.CharField(source="payment.payment_reference", read_only=True)
    payment_amount = serializers.DecimalField(source="payment.amount", read_only=True, **MONEY)
    payment_method = serializers.CharField(source="payment.payment_method", read_only=True)
    student_name = serializers.CharField(source="payment.student.full_name", read_only=True)
    currency = serializers.CharField(source="payment.currency", read_only=True)

    class Meta(RefundSerializer.Meta):
        fields = [
            *RefundSerializer.Meta.fields,
            "payment_reference",
            "payment_amount",
            "payment_method",
            "student_name",
            "currency",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    allocations = AllocationSerializer(many=True, read_only=True)
    refunds = RefundSerializer(many=True, read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "payment_reference",
            "student",
            "student_name",
            "payer",
            "initiated_by",
            "fee_type",
            "wallet",
            "amount",
            "refunded_amount",
            "currency",
            "payment_method",
            "provider",
            "status",
            "initiated_at",
            "completed_at",
            "failure_reason",
            "provider_reference",
            "allocations",
            "refunds",
        ]


class WalletSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.user.full_name", read_only=True)

    class Meta:
        model = Wallet
        fields = [
            "id",
            "owner",
            "owner_name",
            "wallet_type",
            "provider_code",
            "wallet_identifier",
            "balance",
            "currency",
            "status",
            "simulation_behavior",
        ]


class TreasuryTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TreasuryTransaction
        fields = [
            "id",
            "transaction_type",
            "direction",
            "amount",
            "reference",
            "balance_before",
            "balance_after",
            "created_at",
        ]


# =============================================================================
# Families / payers
# =============================================================================


class StudentObligations(FinanceVisibility, APIView):
    def get(self, request, pk):
        student = scoped(Student, pk, request)
        membership = self.membership()
        if not services.can_view_finance(membership, student):
            linked = ParentStudent.objects.filter(
                parent__membership=membership, student=student, active=True, identity_verified=True
            ).exists()
            if linked:
                raise PermissionDenied("This link does not grant access to financial data.")
            raise Http404
        invoices = Invoice.objects.filter(
            student=student, status__in=[InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID]
        ).order_by("due_date", "invoice_number")
        return Response(
            {
                "student": str(student.pk),
                "currency": student.school.currency,
                "balance_due": money(sum((i.balance_due for i in invoices), services.ZERO)),
                "solvency": services.solvency(student),
                "can_pay": services.can_pay(membership, student),
                "open_invoices": InvoiceSerializer(invoices.prefetch_related("lines__fee_type"), many=True).data,
            }
        )


class InvoiceVisibility(FinanceVisibility):
    queryset = (
        Invoice.objects.select_related("student")
        .prefetch_related("lines__fee_type")
        .order_by("due_date", "invoice_number")
    )
    serializer_class = InvoiceSerializer
    search_fields = ("invoice_number", *STUDENT_SEARCH)
    date_field = "issue_date"

    def restrict(self, queryset):
        if not self.is_admin():
            queryset = queryset.filter(student_id__in=self.finance_student_ids())
        return self.filter_params(queryset)


class InvoiceList(InvoiceVisibility, generics.ListAPIView):
    pass


class InvoiceDetail(InvoiceVisibility, generics.RetrieveAPIView):
    pass


def money(value):
    """Decimal -> "1234.50": amounts never travel as JSON floats."""
    return str(value)


class PaymentInput(serializers.Serializer):
    student = serializers.UUIDField()
    amount = serializers.DecimalField(**MONEY)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    wallet = serializers.UUIDField(required=False, allow_null=True)
    invoices = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    fee_type = serializers.UUIDField(required=False, allow_null=True)
    payer = serializers.UUIDField(required=False, allow_null=True)  # cash at the desk only
    idempotency_key = serializers.CharField(max_length=120, required=False)


class PaymentVisibility(FinanceVisibility):
    queryset = (
        Payment.objects.select_related("student")
        .prefetch_related("allocations__invoice", "refunds")
        .order_by("-initiated_at")
    )
    serializer_class = PaymentSerializer
    search_fields = ("payment_reference", *STUDENT_SEARCH)
    date_field = "initiated_at__date"

    def restrict(self, queryset):
        if not self.is_admin():
            # Children with finance rights, plus what the caller paid themselves.
            queryset = queryset.filter(Q(student_id__in=self.finance_student_ids()) | Q(payer=self.membership()))
        return self.filter_params(queryset)


class PaymentList(PaymentVisibility, generics.ListAPIView):
    def post(self, request):
        data = PaymentInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        key = request.headers.get("Idempotency-Key") or v.get("idempotency_key")
        if not key:
            raise serializers.ValidationError({"idempotency_key": ["Required (body field or Idempotency-Key header)."]})
        outcome = services.initiate_payment(
            scoped(Student, v["student"], request),
            actor=self.membership(),
            amount=v["amount"],
            payment_method=v["payment_method"],
            idempotency_key=key,
            wallet=optional_scoped(Wallet, v.get("wallet"), request),
            invoices=[scoped(Invoice, pk, request) for pk in v["invoices"]],
            fee_type=optional_scoped(FeeType, v.get("fee_type"), request),
            payer=optional_scoped(SchoolMembership, v.get("payer"), request),
        )
        payment = Payment.objects.prefetch_related("allocations__invoice", "refunds").get(pk=outcome.payment.pk)
        body = PaymentSerializer(payment).data
        body["replayed"] = outcome.replayed
        return Response(body, status=status.HTTP_200_OK if outcome.replayed else status.HTTP_201_CREATED)


class PaymentDetail(PaymentVisibility, generics.RetrieveAPIView):
    pass


class MyWallets(SchoolScopedMixin, generics.ListAPIView):
    queryset = Wallet.objects.order_by("provider_code")
    serializer_class = WalletSerializer

    def restrict(self, queryset):
        return queryset.filter(owner=self.membership())


# =============================================================================
# Administration
# =============================================================================


class FeeTypeInput(serializers.Serializer):
    code = serializers.CharField(max_length=30)
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class AdminFeeTypes(AdminMixin, generics.ListAPIView):
    queryset = FeeType.objects.order_by("code")
    serializer_class = FeeTypeSerializer

    def post(self, request):
        data = FeeTypeInput(data=request.data)
        data.is_valid(raise_exception=True)
        fee_type = services.create_fee_type(self.membership().school, actor=self.membership(), **data.validated_data)
        return Response(FeeTypeSerializer(fee_type).data, status=status.HTTP_201_CREATED)


class FeeScheduleInput(serializers.Serializer):
    fee_type = serializers.UUIDField()
    academic_year = serializers.UUIDField()
    level = serializers.UUIDField(required=False, allow_null=True)
    school_class = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.DecimalField(**MONEY)
    due_date = serializers.DateField()
    mandatory = serializers.BooleanField(default=True)


class AdminFeeSchedules(AdminMixin, generics.ListAPIView):
    queryset = FeeSchedule.objects.select_related("fee_type").order_by("due_date")
    serializer_class = FeeScheduleSerializer

    def post(self, request):
        data = FeeScheduleInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        schedule = services.create_fee_schedule(
            scoped(FeeType, v["fee_type"], request),
            actor=self.membership(),
            academic_year=scoped(AcademicYear, v["academic_year"], request),
            level=optional_scoped(Level, v.get("level"), request),
            school_class=optional_scoped(SchoolClass, v.get("school_class"), request),
            amount=v["amount"],
            due_date=v["due_date"],
            mandatory=v["mandatory"],
        )
        return Response(FeeScheduleSerializer(schedule).data, status=status.HTTP_201_CREATED)


class InvoiceLineInput(serializers.Serializer):
    fee_type = serializers.UUIDField()
    description = serializers.CharField(max_length=255, required=False)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, default="1.00")
    unit_price = serializers.DecimalField(**MONEY)


class InvoiceInput(serializers.Serializer):
    student = serializers.UUIDField()
    due_date = serializers.DateField()
    lines = InvoiceLineInput(many=True)


class AdminInvoiceIssue(AdminMixin, APIView):
    def post(self, request):
        data = InvoiceInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        lines = [{**line, "fee_type": scoped(FeeType, line["fee_type"], request)} for line in v["lines"]]
        invoice = services.issue_invoice(
            scoped(Student, v["student"], request), actor=self.membership(), lines=lines, due_date=v["due_date"]
        )
        return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)


class GenerateInput(serializers.Serializer):
    school_class = serializers.UUIDField()


class AdminInvoiceGenerate(AdminMixin, APIView):
    def post(self, request):
        data = GenerateInput(data=request.data)
        data.is_valid(raise_exception=True)
        school_class = scoped(SchoolClass, data.validated_data["school_class"], request)
        invoices = services.generate_invoices(school_class, actor=self.membership())
        return Response(
            {"created": len(invoices), "invoices": [str(i.pk) for i in invoices]}, status=status.HTTP_201_CREATED
        )


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class AdminInvoiceCancel(AdminMixin, APIView):
    def post(self, request, pk):
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        invoice = services.cancel_invoice(
            scoped(Invoice, pk, request), actor=self.membership(), reason=data.validated_data["reason"]
        )
        return Response(InvoiceSerializer(invoice).data)


class RefundInput(ReasonInput):
    amount = serializers.DecimalField(**MONEY)


class AdminPaymentRefund(AdminMixin, APIView):
    def post(self, request, pk):
        data = RefundInput(data=request.data)
        data.is_valid(raise_exception=True)
        refund = services.refund_payment(
            scoped(Payment, pk, request),
            actor=self.membership(),
            amount=data.validated_data["amount"],
            reason=data.validated_data["reason"],
        )
        return Response(RefundSerializer(refund).data, status=status.HTTP_201_CREATED)


class AdminRefunds(AdminMixin, generics.ListAPIView):
    """Every refund of the school, newest first, with its original payment."""

    queryset = PaymentRefund.objects.select_related("payment__student").order_by("-completed_at")
    serializer_class = RefundListSerializer

    def restrict(self, queryset):
        return filter_search_and_dates(
            queryset,
            self.request.query_params,
            ("payment__payment_reference", "reason", *(f"payment__{f}" for f in STUDENT_SEARCH)),
            "completed_at__date",
        )


class WalletInput(serializers.Serializer):
    owner = serializers.UUIDField()
    provider_code = serializers.CharField(max_length=30)
    wallet_identifier = serializers.CharField(max_length=120)
    simulation_behavior = serializers.ChoiceField(choices=SimulationBehavior.choices, default="NORMAL")


class AdminWallets(AdminMixin, generics.ListAPIView):
    queryset = Wallet.objects.order_by("provider_code", "wallet_identifier")
    serializer_class = WalletSerializer

    def post(self, request):
        data = WalletInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        wallet = services.create_wallet(
            scoped(SchoolMembership, v["owner"], request),
            actor=self.membership(),
            provider_code=v["provider_code"],
            wallet_identifier=v["wallet_identifier"],
            simulation_behavior=v["simulation_behavior"],
        )
        return Response(WalletSerializer(wallet).data, status=status.HTTP_201_CREATED)


class AmountInput(serializers.Serializer):
    amount = serializers.DecimalField(**MONEY)


class AdminWalletFund(AdminMixin, APIView):
    def post(self, request, pk):
        data = AmountInput(data=request.data)
        data.is_valid(raise_exception=True)
        entry = services.fund_wallet(
            scoped(Wallet, pk, request), data.validated_data["amount"], actor=self.membership()
        )
        return Response({"wallet": str(pk), "balance": money(entry.balance_after)}, status=status.HTTP_201_CREATED)


class AdminTreasury(AdminMixin, APIView):
    def get(self, request):
        treasury = services.get_treasury(self.membership().school)
        recent = treasury.transactions.order_by("-created_at")[:50]
        return Response(
            {
                "balance": money(treasury.balance),
                "currency": treasury.currency,
                "recent_transactions": TreasuryTransactionSerializer(recent, many=True).data,
            }
        )


class AdminTreasuryCredit(AdminMixin, APIView):
    def post(self, request):
        data = AmountInput(data=request.data)
        data.is_valid(raise_exception=True)
        entry = services.credit_treasury(
            self.membership().school, data.validated_data["amount"], actor=self.membership()
        )
        return Response({"balance": money(entry.balance_after)}, status=status.HTTP_201_CREATED)


class AdminDashboard(AdminMixin, APIView):
    def get(self, request):
        data = services.dashboard(self.membership().school)
        for key in ("treasury_balance", "collected", "refunded", "net_collected", "invoiced_total", "outstanding"):
            data[key] = money(data[key])
        return Response(data)


urlpatterns = [
    path("finance/students/<uuid:pk>/obligations/", StudentObligations.as_view()),
    path("finance/invoices/", InvoiceList.as_view()),
    path("finance/invoices/<uuid:pk>/", InvoiceDetail.as_view()),
    path("finance/payments/", PaymentList.as_view()),
    path("finance/payments/<uuid:pk>/", PaymentDetail.as_view()),
    path("finance/wallets/", MyWallets.as_view()),
    path("admin/finance/fee-types/", AdminFeeTypes.as_view()),
    path("admin/finance/fee-schedules/", AdminFeeSchedules.as_view()),
    path("admin/finance/invoices/", AdminInvoiceIssue.as_view()),
    path("admin/finance/invoices/generate/", AdminInvoiceGenerate.as_view()),
    path("admin/finance/invoices/<uuid:pk>/cancel/", AdminInvoiceCancel.as_view()),
    path("admin/finance/payments/<uuid:pk>/refund/", AdminPaymentRefund.as_view()),
    path("admin/finance/refunds/", AdminRefunds.as_view()),
    path("admin/finance/wallets/", AdminWallets.as_view()),
    path("admin/finance/wallets/<uuid:pk>/fund/", AdminWalletFund.as_view()),
    path("admin/finance/treasury/", AdminTreasury.as_view()),
    path("admin/finance/treasury/credit/", AdminTreasuryCredit.as_view()),
    path("admin/finance/dashboard/", AdminDashboard.as_view()),
]
