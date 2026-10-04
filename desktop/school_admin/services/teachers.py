"""Teachers (backend people/teacher_api.py, ADR 0019). Thin client: the
server builds the account chain, judges compatibility (people/compatibility.py)
and enforces every rule; this module only checks that required fields are
filled and relays the server's verdicts — it never decides that a teacher
may teach a subject.

    list     GET /teachers/?search=&status=active|inactive&category=&subject=   (one page at a time)
    write    POST /teachers/   PATCH /teachers/{id}/   POST /teachers/{id}/deactivate/ | /reactivate/
    subjects GET|POST /teachers/{id}/qualifications/
             POST /teacher-qualifications/{id}/verify/ | /reject/
    verdict  GET /teachers/{id}/compatibility/?subject=&level=
             GET /teachers/{id}/compatibility-rules/    GET|POST /teachers/{id}/overrides/
    pay      GET /admin/payroll/teacher-rates/?teacher=   (read only: payroll stays in its module)
"""

from ..api.errors import ValidationFailed
from ..models import CompatibilityVerdict, Qualification, Teacher

REQUIRED = {
    "last_name": "Nom",
    "first_name": "Prénom(s)",
    "email": "E-mail",
    "employee_number": "Matricule",
    "category_id": "Catégorie pédagogique",
    "primary_subject_id": "Matière principale",
}


def _payload(fields):
    renames = {"category_id": "pedagogical_category", "primary_subject_id": "primary_subject"}
    out = {}
    for name, value in fields.items():
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif isinstance(value, str):
            value = value.strip()
        out[renames.get(name, name)] = value
    return out


class TeacherService:
    PATH = "teachers/"
    PAGE_SIZE = 50

    def __init__(self, api):
        self.api = api

    # --- list / read ---------------------------------------------------------------
    def page(self, *, page=1, search=None, status=None, category_id=None, subject_id=None):
        rows, total = self.api.page(
            self.PATH,
            page=page,
            page_size=self.PAGE_SIZE,
            search=(search or "").strip() or None,
            status=status or None,
            category=category_id or None,
            subject=subject_id or None,
        )
        return [Teacher.from_api(row) for row in rows], total

    def get(self, teacher_id):
        return Teacher.from_api(self.api.get(f"{self.PATH}{teacher_id}/"))

    def qualifications(self, teacher_id):
        return [Qualification.from_api(r) for r in self.api.list_all(f"{self.PATH}{teacher_id}/qualifications/")]

    def compatibility(self, teacher_id, subject_id, level_id=None):
        row = self.api.get(f"{self.PATH}{teacher_id}/compatibility/", subject=subject_id, level=level_id or None)
        return CompatibilityVerdict.from_api(row)

    def rules(self, teacher_id):
        return self.api.get(f"{self.PATH}{teacher_id}/compatibility-rules/") or []

    def overrides(self, teacher_id):
        return self.api.get(f"{self.PATH}{teacher_id}/overrides/") or []

    def rates(self, teacher_id):
        """Vacation rates already exposed by the payroll module (read only)."""
        return self.api.list_all("admin/payroll/teacher-rates/", teacher=teacher_id)

    # --- write ------------------------------------------------------------------------
    @staticmethod
    def _require(fields, creating):
        errors = {
            name: ["Obligatoire."]
            for name in REQUIRED
            if (creating or name in fields) and not str(fields.get(name) or "").strip()
        }
        if errors:
            raise ValidationFailed("Formulaire incomplet.", details=errors)

    def create(self, **fields):
        """One server transaction: account (no password), membership with the
        TEACHER role, employee, teacher, primary subject judged by the engine."""
        self._require(fields, creating=True)
        return Teacher.from_api(self.api.post(self.PATH, _payload(fields)))

    def update(self, teacher_id, **fields):
        self._require(fields, creating=False)
        return Teacher.from_api(self.api.patch(f"{self.PATH}{teacher_id}/", _payload(fields)))

    def deactivate(self, teacher_id):
        return Teacher.from_api(self.api.post(f"{self.PATH}{teacher_id}/deactivate/"))

    def reactivate(self, teacher_id):
        return Teacher.from_api(self.api.post(f"{self.PATH}{teacher_id}/reactivate/"))

    def add_qualification(self, teacher_id, subject_id, level_id=None, notes=None):
        if not subject_id:
            raise ValidationFailed("Formulaire incomplet.", details={"subject": ["Choisissez une matière."]})
        payload = {"subject": subject_id, "level": level_id or None, "notes": (notes or "").strip() or None}
        return Qualification.from_api(self.api.post(f"{self.PATH}{teacher_id}/qualifications/", payload))

    def verify(self, qualification_id):
        return Qualification.from_api(self.api.post(f"teacher-qualifications/{qualification_id}/verify/"))

    def reject(self, qualification_id, reason):
        if not (reason or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"reason": ["Indiquez le motif."]})
        return Qualification.from_api(
            self.api.post(f"teacher-qualifications/{qualification_id}/reject/", {"reason": reason.strip()})
        )

    def grant_override(self, teacher_id, subject_id, reason, *, level_id=None, expires_at=None):
        if not (reason or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"reason": ["Indiquez le motif."]})
        payload = {
            "subject": subject_id,
            "level": level_id or None,
            "reason": reason.strip(),
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
        return self.api.post(f"{self.PATH}{teacher_id}/overrides/", payload)
