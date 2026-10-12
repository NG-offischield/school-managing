"""Students (backend people/student_api.py, ADR 0018). Thin client: the
server enforces every rule (unique matricule, one class per year, class of
the same year and school, full class, archived student, photo type/size…);
the only checks here are that required fields are filled before a call.

    list     GET /students/?search=&status=&academic_year=&level=&school_class=&enrollment_status=
             (one page at a time: the API paginates)
    write    POST /students/   PATCH /students/{id}/   POST /students/{id}/archive/ | /reactivate/
    school   GET|POST /students/{id}/enrollments/
             POST /enrollments/{id}/change-class/ | /withdraw/
    photo    GET|POST|DELETE /students/{id}/photo/      history  GET /students/{id}/history/
"""

from datetime import datetime

from ..api.errors import NotFound, ValidationFailed
from ..i18n import Labels, tr
from ..models import Enrollment, HistoryEntry, Student

REQUIRED = Labels(
    {
        "student_number": "Matricule",
        "registration_number": "N° d'inscription",
        "last_name": "Nom",
        "first_name": "Prénom(s)",
        "date_of_birth": "Date de naissance",
        "sex": "Sexe",
    }
)
PHOTO_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
PHOTO_MAX_BYTES = 3 * 1024 * 1024  # same limit as the server (which decides)


def _payload(fields):
    out = {}
    for name, value in fields.items():
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif isinstance(value, str):
            value = value.strip() or (None if name in ("birth_place", "address") else "")
        out[name] = value
    return out


class StudentService:
    PATH = "students/"
    PAGE_SIZE = 50

    def __init__(self, api):
        self.api = api

    # --- list / read ---------------------------------------------------------------
    def page(
        self,
        *,
        page=1,
        search=None,
        status=None,
        academic_year_id=None,
        level_id=None,
        class_id=None,
        enrollment_status=None,
    ):
        """One page of students and the total count (server-side pagination)."""
        rows, total = self.api.page(
            self.PATH,
            page=page,
            page_size=self.PAGE_SIZE,
            search=(search or "").strip() or None,
            status=status or None,
            academic_year=academic_year_id or None,
            level=level_id or None,
            school_class=class_id or None,
            enrollment_status=enrollment_status or None,
        )
        return [Student.from_api(row) for row in rows], total

    def get(self, student_id):
        return Student.from_api(self.api.get(f"{self.PATH}{student_id}/"))

    def enrollments(self, student_id):
        return [Enrollment.from_api(row) for row in self.api.list_all(f"{self.PATH}{student_id}/enrollments/")]

    def history(self, student_id):
        rows = self.api.get(f"{self.PATH}{student_id}/history/") or []
        return [
            HistoryEntry(
                datetime.fromisoformat(r["at"]) if r.get("at") else None,
                r["action"],
                r.get("summary", ""),
                r.get("actor", ""),
            )
            for r in rows
        ]

    def photo(self, student_id):
        """JPEG bytes of the photo, or None."""
        try:
            return self.api.get_bytes(f"{self.PATH}{student_id}/photo/")
        except NotFound:
            return None

    # --- write ------------------------------------------------------------------------
    @staticmethod
    def _require(fields, creating):
        errors = {
            name: [tr("Obligatoire.")]
            for name in REQUIRED
            if (creating or name in fields) and not (str(fields.get(name) or "").strip())
        }
        if errors:
            raise ValidationFailed("Formulaire incomplet.", details=errors)

    def create(self, *, class_id=None, enrollment_date=None, **fields):
        """Create the student, enrolled in `class_id` in the same server
        transaction when given (both or nothing)."""
        self._require(fields, creating=True)
        payload = _payload(fields)
        if class_id:
            payload["enrollment"] = {
                "school_class": class_id,
                "enrollment_date": enrollment_date.isoformat() if enrollment_date else None,
            }
        return Student.from_api(self.api.post(self.PATH, payload))

    def update(self, student_id, **fields):
        self._require(fields, creating=False)
        return Student.from_api(self.api.patch(f"{self.PATH}{student_id}/", _payload(fields)))

    def archive(self, student_id):
        return Student.from_api(self.api.post(f"{self.PATH}{student_id}/archive/"))

    def reactivate(self, student_id):
        return Student.from_api(self.api.post(f"{self.PATH}{student_id}/reactivate/"))

    def enroll(self, student_id, class_id, enrollment_date=None):
        if not class_id:
            raise ValidationFailed("Formulaire incomplet.", details={"school_class": [tr("Choisissez une classe.")]})
        payload = {"school_class": class_id}
        if enrollment_date:
            payload["enrollment_date"] = enrollment_date.isoformat()
        return Enrollment.from_api(self.api.post(f"{self.PATH}{student_id}/enrollments/", payload))

    def change_class(self, enrollment_id, class_id):
        if not class_id:
            raise ValidationFailed("Formulaire incomplet.", details={"school_class": [tr("Choisissez une classe.")]})
        return Enrollment.from_api(
            self.api.post(f"enrollments/{enrollment_id}/change-class/", {"school_class": class_id})
        )

    def withdraw(self, enrollment_id, end_date=None):
        payload = {"end_date": end_date.isoformat()} if end_date else {}
        return Enrollment.from_api(self.api.post(f"enrollments/{enrollment_id}/withdraw/", payload))

    def set_photo(self, student_id, content, extension):
        """Send the image bytes (never the local path). The server checks the
        real type and size, re-encodes it and keeps it private."""
        extension = extension.lower().lstrip(".")
        if extension not in PHOTO_TYPES:
            raise ValidationFailed("Utilisez une image JPEG, PNG ou WebP.", details={"photo": [tr("Format.")]})
        row = self.api.upload(
            f"{self.PATH}{student_id}/photo/",
            "photo",
            content,
            filename=f"photo.{extension}",
            content_type=PHOTO_TYPES[extension],
        )
        return Student.from_api(row)

    def remove_photo(self, student_id):
        return Student.from_api(self.api.delete(f"{self.PATH}{student_id}/photo/"))
