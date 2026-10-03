from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    """Official PDF documents: report cards, receipts, payslips, attendance
    statements (spec 6.12, ADR 0016)."""

    name = "apps.documents"
    label = "documents"
    verbose_name = "Documents officiels"
