"""Courses (backend gradebook/course_api.py, ADR 0020). Thin client: a course
is subject + teacher + class + year (the year is the class's year); the
server decides every rule, and in particular WHICH teachers may teach a
subject in a class (GET /courses/eligible-teachers/): this module never
evaluates compatibility, it relays the server's lists.

    list     GET /courses/?search=&status=&academic_year=&school_class=&subject=   (one page at a time)
    write    POST /courses/   PATCH /courses/{id}/   POST /courses/{id}/deactivate/ | /reactivate/
    teachers GET /courses/eligible-teachers/?school_class=&subject=
    scales   GET /grading-scales/
"""

from ..api.errors import ValidationFailed
from ..models import Course, EligibleTeacher

REQUIRED = {"class_id": "Classe", "subject_id": "Matière", "teacher_id": "Enseignant"}


class CourseService:
    PATH = "courses/"
    PAGE_SIZE = 50

    def __init__(self, api):
        self.api = api

    def page(self, *, page=1, search=None, status=None, academic_year_id=None, class_id=None, subject_id=None):
        rows, total = self.api.page(
            self.PATH,
            page=page,
            page_size=self.PAGE_SIZE,
            search=(search or "").strip() or None,
            status=status or None,
            academic_year=academic_year_id or None,
            school_class=class_id or None,
            subject=subject_id or None,
        )
        return [Course.from_api(row) for row in rows], total

    def all(self, *, status="active", academic_year_id=None):
        rows = self.api.list_all(self.PATH, status=status or None, academic_year=academic_year_id or None)
        return [Course.from_api(row) for row in rows]

    def get(self, course_id):
        return Course.from_api(self.api.get(f"{self.PATH}{course_id}/"))

    def eligible_teachers(self, class_id, subject_id):
        """(eligible, excluded) as decided by the server; excluded rows carry the rule code."""
        answer = self.api.get(f"{self.PATH}eligible-teachers/", school_class=class_id, subject=subject_id) or {}
        return (
            [EligibleTeacher.from_api(r) for r in answer.get("eligible", [])],
            [EligibleTeacher.from_api(r) for r in answer.get("excluded", [])],
        )

    def scales(self):
        return [s for s in self.api.list_all("grading-scales/") if s.get("active", True)]

    @staticmethod
    def _payload(fields):
        out = {}
        renames = {
            "class_id": "school_class",
            "subject_id": "subject",
            "teacher_id": "teacher",
            "scale_id": "grading_scale",
        }
        for name, value in fields.items():
            if name in ("coefficient", "weekly_hours") and value not in (None, ""):
                value = str(value).replace(",", ".")
            if name == "scale_id":
                value = value or None  # no scale: the subject's, then the school's default
            out[renames.get(name, name)] = value
        return out

    def create(self, *, class_id, subject_id, teacher_id, coefficient=None, weekly_hours=None, scale_id=None):
        values = {"class_id": class_id, "subject_id": subject_id, "teacher_id": teacher_id}
        missing = {name: ["Obligatoire."] for name in REQUIRED if not values[name]}
        if missing:
            raise ValidationFailed("Formulaire incomplet.", details=missing)
        fields = dict(values)
        if coefficient not in (None, ""):
            fields["coefficient"] = coefficient
        if weekly_hours not in (None, ""):
            fields["weekly_hours"] = weekly_hours
        fields["scale_id"] = scale_id
        return Course.from_api(self.api.post(self.PATH, self._payload(fields)))

    def update(self, course_id, **fields):
        """Editable: teacher, coefficient, weekly hours, grading scale (class,
        subject and year are fixed by the server)."""
        if "teacher_id" in fields and not fields["teacher_id"]:
            raise ValidationFailed("Formulaire incomplet.", details={"teacher": ["Obligatoire."]})
        return Course.from_api(self.api.patch(f"{self.PATH}{course_id}/", self._payload(fields)))

    def deactivate(self, course_id):
        return Course.from_api(self.api.post(f"{self.PATH}{course_id}/deactivate/"))

    def reactivate(self, course_id):
        return Course.from_api(self.api.post(f"{self.PATH}{course_id}/reactivate/"))
