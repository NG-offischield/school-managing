"""Pedagogical catalogue (backend academics/catalog_api.py, ADR 0010).

Thin client services: they only shape requests and payloads. Rules (code
immutable, duplicate code, category still in use, inactive category...) are
the server's; their errors come back as ApiError and are shown as is.
The one check done here is input completeness before a call — a subject
needs a category chosen from the existing ones (the form offers only a
list, never free text); the backend enforces it too.
"""

from ..api.errors import ValidationFailed
from ..models import Category, Subject


def _active_param(active):
    return None if active is None else ("true" if active else "false")


def _clean(text):
    return (text or "").strip()


class CategoryService:
    PATH = "pedagogical-categories/"

    def __init__(self, api):
        self.api = api

    def list(self, *, search=None, active=None):
        rows = self.api.list_all(self.PATH, search=_clean(search) or None, active=_active_param(active))
        return [Category.from_api(row) for row in rows]

    def create(self, *, code, name, description=""):
        code, name = _clean(code), _clean(name)
        if not code or not name:
            raise ValidationFailed(
                "Le code et le nom sont obligatoires.",
                details={"code": ["Obligatoire."]} if not code else {"name": ["Obligatoire."]},
            )
        payload = {"code": code, "name": name, "description": _clean(description) or None}
        return Category.from_api(self.api.post(self.PATH, payload))

    def update(self, category_id, *, name, description=""):
        """The code is immutable server-side: only name and description change."""
        name = _clean(name)
        if not name:
            raise ValidationFailed("Le nom est obligatoire.", details={"name": ["Obligatoire."]})
        payload = {"name": name, "description": _clean(description) or None}
        return Category.from_api(self.api.patch(f"{self.PATH}{category_id}/", payload))

    def deactivate(self, category_id):
        return Category.from_api(self.api.post(f"{self.PATH}{category_id}/deactivate/"))

    def reactivate(self, category_id):
        return Category.from_api(self.api.post(f"{self.PATH}{category_id}/reactivate/"))


class SubjectService:
    PATH = "subjects/"

    def __init__(self, api):
        self.api = api

    def list(self, *, search=None, active=None, category_id=None):
        rows = self.api.list_all(
            self.PATH, search=_clean(search) or None, active=_active_param(active), category=category_id or None
        )
        return [Subject.from_api(row) for row in rows]

    @staticmethod
    def _require(code=None, name=None, category_id=None, creating=True):
        errors = {}
        if creating and not _clean(code):
            errors["code"] = ["Obligatoire."]
        if not _clean(name):
            errors["name"] = ["Obligatoire."]
        if not category_id:
            errors["category"] = ["Choisissez une catégorie existante."]
        if errors:
            raise ValidationFailed(
                "Formulaire incomplet : une matière appartient toujours à une catégorie.", details=errors
            )

    def create(self, *, code, name, category_id, subject_type="THEORETICAL", public_visible=False):
        self._require(code, name, category_id)
        payload = {
            "code": _clean(code),
            "name": _clean(name),
            "category": category_id,
            "subject_type": subject_type,
            "public_visible": bool(public_visible),
        }
        return Subject.from_api(self.api.post(self.PATH, payload))

    def update(self, subject_id, *, name, category_id, subject_type, public_visible):
        self._require(name=name, category_id=category_id, creating=False)
        payload = {
            "name": _clean(name),
            "category": category_id,
            "subject_type": subject_type,
            "public_visible": bool(public_visible),
        }
        return Subject.from_api(self.api.patch(f"{self.PATH}{subject_id}/", payload))

    def deactivate(self, subject_id):
        return Subject.from_api(self.api.post(f"{self.PATH}{subject_id}/deactivate/"))

    def reactivate(self, subject_id):
        return Subject.from_api(self.api.post(f"{self.PATH}{subject_id}/reactivate/"))
