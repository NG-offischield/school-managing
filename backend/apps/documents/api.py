"""Documents API (spec §6.12, ADR 0016).

    POST /documents/                     generate (or get the current) document
                                         {kind, report_card | payment | payroll | student | school_class,
                                          date_from/date_to (student attendance), date (class register)}
    GET  /documents/                     documents the caller may see (?kind=, ?status=)  paginated
    GET  /documents/{id}/                metadata (no content for others: 404)
    GET  /documents/{id}/download/       the PDF, after the permission check (traced)
    POST /documents/{id}/regenerate/     administration, provisional documents only
    GET  /documents/verify/?code=        authenticity of a printed document (same school)

Spec shortcuts (generate-or-get, then stream the PDF):
    GET /reports/report-card/{id}.pdf/   GET /report-cards/{id}/pdf/
    GET /payroll/{id}/payslip.pdf/       GET /payments/{id}/receipt.pdf/
    GET /reports/attendance.pdf/?student=&date_from=&date_to=   or   ?school_class=&date=

Answers: another school's id, or a source the caller may not see -> 404;
a source that cannot be documented yet (draft report card for a parent,
unpaid payment...) -> 409 document_source_not_final; regenerating an
official document -> 409 document_official; a non-admin regenerating -> 403.
"""

from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import SchoolClass
from apps.finance.models import Payment
from apps.gradebook.models import ReportCard
from apps.payroll.models import StaffPayroll, TeacherPayroll
from apps.people.models import Student
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import services
from .models import Document, DocumentKind


def scoped(model, pk, request):
    return get_object_or_404(scope_to_current_school(model.objects.all(), request), pk=pk)


def scoped_payroll(pk, request):
    for model in (TeacherPayroll, StaffPayroll):
        found = scope_to_current_school(model.objects.all(), request).filter(pk=pk).first()
        if found is not None:
            return found
    raise Http404


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id",
            "kind",
            "status",
            "title",
            "version",
            "params",
            "file_name",
            "size_bytes",
            "sha256",
            "verification_code",
            "generated_at",
        ]


class GenerateInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=DocumentKind.choices)
    report_card = serializers.UUIDField(required=False)
    payment = serializers.UUIDField(required=False)
    payroll = serializers.UUIDField(required=False)
    student = serializers.UUIDField(required=False)
    school_class = serializers.UUIDField(required=False)
    date = serializers.DateField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    REQUIRED = {
        DocumentKind.REPORT_CARD: ("report_card",),
        DocumentKind.PAYMENT_RECEIPT: ("payment",),
        DocumentKind.PAYSLIP: ("payroll",),
        DocumentKind.STUDENT_ATTENDANCE: ("student", "date_from", "date_to"),
        DocumentKind.CLASS_ATTENDANCE: ("school_class", "date"),
    }

    def validate(self, attrs):
        missing = [f for f in self.REQUIRED[attrs["kind"]] if not attrs.get(f)]
        if missing:
            raise serializers.ValidationError({f: ["Required for this kind."] for f in missing})
        return attrs


def resolve(kind, values, request):
    """(source, params) from validated input, always inside the caller's school."""
    if kind == DocumentKind.REPORT_CARD:
        return scoped(ReportCard, values["report_card"], request), {}
    if kind == DocumentKind.PAYMENT_RECEIPT:
        return scoped(Payment, values["payment"], request), {}
    if kind == DocumentKind.PAYSLIP:
        return scoped_payroll(values["payroll"], request), {}
    if kind == DocumentKind.STUDENT_ATTENDANCE:
        return scoped(Student, values["student"], request), {
            "date_from": values["date_from"],
            "date_to": values["date_to"],
        }
    return scoped(SchoolClass, values["school_class"], request), {"date": values["date"]}


def generate_visible(kind, source, member, params):
    """Generation where 'not allowed' answers 404 (never confirms that a
    source the caller may not see exists)."""
    try:
        return services.generate(kind, source, actor=member, **params)
    except PermissionDenied:
        raise Http404 from None


def stream(document, member):
    try:
        handle = services.open_for_download(document, actor=member)
    except PermissionDenied:
        raise Http404 from None
    response = FileResponse(handle, as_attachment=True, filename=document.file_name, content_type="application/pdf")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class Documents(SchoolScopedMixin, generics.ListAPIView):
    serializer_class = DocumentSerializer

    def get_queryset(self):
        queryset = services.visible_documents(self.membership()).order_by("-generated_at")
        for param in ("kind", "status"):
            if self.request.query_params.get(param):
                queryset = queryset.filter(**{param: self.request.query_params[param]})
        return queryset

    def post(self, request):
        data = GenerateInput(data=request.data)
        data.is_valid(raise_exception=True)
        kind = data.validated_data["kind"]
        source, params = resolve(kind, data.validated_data, request)
        document, created = generate_visible(kind, source, self.membership(), params)
        return Response(DocumentSerializer(document).data, status=status.HTTP_201_CREATED if created else 200)


class DocumentMixin(SchoolScopedMixin):
    def document(self, pk):
        document = scoped(Document, pk, self.request)
        if not services.can_read(self.membership(), document):
            raise Http404
        return document


class DocumentDetail(DocumentMixin, APIView):
    def get(self, request, pk):
        return Response(DocumentSerializer(self.document(pk)).data)


class DocumentDownloadView(DocumentMixin, APIView):
    def get(self, request, pk):
        return stream(self.document(pk), self.membership())


class DocumentRegenerate(DocumentMixin, APIView):
    def post(self, request, pk):
        document, created = services.regenerate(self.document(pk), actor=self.membership())
        return Response(DocumentSerializer(document).data, status=status.HTTP_201_CREATED if created else 200)


class DocumentVerify(SchoolScopedMixin, APIView):
    def get(self, request):
        result = services.verify(request.query_params.get("code"), actor=self.membership())
        if result is None:
            raise Http404
        return Response(result)


class ShortcutMixin(SchoolScopedMixin):
    def deliver(self, kind, source, params=None):
        document, _ = generate_visible(kind, source, self.membership(), params or {})
        return stream(document, self.membership())


class ReportCardPdf(ShortcutMixin, APIView):
    def get(self, request, pk):
        return self.deliver(DocumentKind.REPORT_CARD, scoped(ReportCard, pk, request))


class PayslipPdf(ShortcutMixin, APIView):
    def get(self, request, pk):
        return self.deliver(DocumentKind.PAYSLIP, scoped_payroll(pk, request))


class ReceiptPdf(ShortcutMixin, APIView):
    def get(self, request, pk):
        return self.deliver(DocumentKind.PAYMENT_RECEIPT, scoped(Payment, pk, request))


class AttendancePdf(ShortcutMixin, APIView):
    def get(self, request):
        params = request.query_params
        field = serializers.DateField()
        try:
            if params.get("school_class"):
                return self.deliver(
                    DocumentKind.CLASS_ATTENDANCE,
                    scoped(SchoolClass, self.uuid_param("school_class"), request),
                    {"date": field.to_internal_value(params.get("date"))},
                )
            return self.deliver(
                DocumentKind.STUDENT_ATTENDANCE,
                scoped(Student, self.uuid_param("student"), request),
                {
                    "date_from": field.to_internal_value(params.get("date_from")),
                    "date_to": field.to_internal_value(params.get("date_to")),
                },
            )
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({"date": exc.detail}) from None


urlpatterns = [
    path("documents/", Documents.as_view()),
    path("documents/verify/", DocumentVerify.as_view()),
    path("documents/<uuid:pk>/", DocumentDetail.as_view()),
    path("documents/<uuid:pk>/download/", DocumentDownloadView.as_view()),
    path("documents/<uuid:pk>/regenerate/", DocumentRegenerate.as_view()),
    path("reports/report-card/<uuid:pk>.pdf/", ReportCardPdf.as_view()),
    path("report-cards/<uuid:pk>/pdf/", ReportCardPdf.as_view()),
    path("payroll/<uuid:pk>/payslip.pdf/", PayslipPdf.as_view()),
    path("payments/<uuid:pk>/receipt.pdf/", ReceiptPdf.as_view()),
    path("reports/attendance.pdf/", AttendancePdf.as_view()),
]
