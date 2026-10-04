"""Documents (backend documents/api.py, ADR 0016 / 0023). Thin client of the
EXISTING `Document` registry: the server builds every PDF with the SCHOOL's
branding (SchoolBranding), decides provisional / official / superseded,
traces downloads and answers the authenticity checks. No PDF logic here.

    GET  /documents/?kind=&status=&search=   GET /documents/{id}/
    POST /documents/ {kind, report_card | payment | payroll | student | school_class | teacher,
                      date, date_from, date_to}         -> 201 new, 200 the current one
    GET  /documents/{id}/download/            POST /documents/{id}/regenerate/ (provisional only)
    GET  /documents/verify/?code=
    sources: GET /report-cards/?student=   POST /report-cards/generate/ {school_class, academic_period}
             GET /academic-periods/
"""

from ..api.errors import ValidationFailed
from ..models import Document

# Source fields required per kind (the server re-checks them).
SOURCES = {
    "REPORT_CARD": ("report_card",),
    "STUDENT_CARD": ("student",),
    "TIMETABLE": (),  # school_class OR teacher, + date
    "PAYMENT_RECEIPT": ("payment",),
    "PAYSLIP": ("payroll",),
    "STUDENT_ATTENDANCE": ("student", "date_from", "date_to"),
    "CLASS_ATTENDANCE": ("school_class", "date"),
}


class DocumentService:
    PAGE_SIZE = 50

    def __init__(self, api):
        self.api = api

    def documents(self, *, page=1, kind=None, status=None, search=None):
        rows, total = self.api.page(
            "documents/",
            page=page,
            page_size=self.PAGE_SIZE,
            kind=kind or None,
            status=status or None,
            search=(search or "").strip() or None,
        )
        return [Document.from_api(r) for r in rows], total

    def recent(self, limit=5):
        rows, total = self.api.page("documents/", page=1, page_size=limit)
        return [Document.from_api(r) for r in rows], total

    def document(self, document_id):
        return Document.from_api(self.api.get(f"documents/{document_id}/"))

    def generate(self, kind, **sources):
        """Generate (or get the current) document of `kind` for its source."""
        values = {k: v for k, v in sources.items() if v not in (None, "")}
        missing = [name for name in SOURCES.get(kind, ()) if name not in values]
        if kind == "TIMETABLE" and bool(values.get("school_class")) == bool(values.get("teacher")):
            missing.append("school_class")
        if missing:
            raise ValidationFailed("Formulaire incomplet.", details={name: ["Obligatoire."] for name in missing})
        payload = {"kind": kind, **{k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in values.items()}}
        return Document.from_api(self.api.post("documents/", payload))

    def regenerate(self, document_id):
        return Document.from_api(self.api.post(f"documents/{document_id}/regenerate/"))

    def download(self, document_id):
        """The PDF bytes (permission checked and traced by the server)."""
        return self.api.get_bytes(f"documents/{document_id}/download/")

    def verify(self, code):
        """{"valid", "kind", "status", "title", "generated_at", "sha256", "current"} or NotFound."""
        if not (code or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"code": ["Saisissez le code imprimé."]})
        return self.api.get("documents/verify/", code=code.strip())

    # --- sources ----------------------------------------------------------------------
    def report_cards(self, student_id):
        return self.api.list_all("report-cards/", student=student_id)

    def periods(self):
        return self.api.list_all("academic-periods/")

    def compute_report_cards(self, class_id, period_id):
        """Gradebook API: (re)compute the DRAFT report cards of a class for a period."""
        if not (class_id and period_id):
            raise ValidationFailed("Formulaire incomplet.", details={"school_class": ["Obligatoire."]})
        return self.api.post("report-cards/generate/", {"school_class": class_id, "academic_period": period_id})
