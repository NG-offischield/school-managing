"""Academic years and levels (backend academics/structure_api.py). Thin
client: the server enforces every rule (unique name, overlapping dates,
single current year, closing conditions, level still used by classes…);
the only checks here are that required fields are filled before a call.

    years   GET/POST /academic-years/   PATCH /academic-years/{id}/
            POST /academic-years/{id}/set-current/ | /close/
    levels  GET/POST /levels/           PATCH /levels/{id}/
            POST /levels/{id}/deactivate/ | /reactivate/
"""

from ..api.errors import ValidationFailed
from ..models import AcademicYear, Level

YEAR_FILTERS = {"open": ("PLANNED", "ACTIVE"), "closed": ("CLOSED", "ARCHIVED")}


def _active_param(active):
    return None if active is None else ("true" if active else "false")


class YearService:
    PATH = "academic-years/"

    def __init__(self, api):
        self.api = api

    def list(self, *, search=None, state=None):
        """state: None (all), "open" (planned / current) or "closed". Newest first."""
        years = [AcademicYear.from_api(row) for row in self.api.list_all(self.PATH)]
        if state in YEAR_FILTERS:
            years = [y for y in years if y.status in YEAR_FILTERS[state]]
        search = (search or "").strip().lower()
        if search:
            years = [y for y in years if search in y.name.lower()]
        return sorted(years, key=lambda y: y.start_date or y.name, reverse=True)

    @staticmethod
    def _require(name, start_date, end_date):
        errors = {}
        if not (name or "").strip():
            errors["name"] = ["Obligatoire."]
        if start_date is None:
            errors["start_date"] = ["Obligatoire."]
        if end_date is None:
            errors["end_date"] = ["Obligatoire."]
        if errors:
            raise ValidationFailed("Formulaire incomplet.", details=errors)

    def create(self, *, name, start_date, end_date):
        self._require(name, start_date, end_date)
        payload = {"name": name.strip(), "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
        return AcademicYear.from_api(self.api.post(self.PATH, payload))

    def update(self, year_id, *, name, start_date, end_date):
        self._require(name, start_date, end_date)
        payload = {"name": name.strip(), "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
        return AcademicYear.from_api(self.api.patch(f"{self.PATH}{year_id}/", payload))

    def set_current(self, year_id):
        return AcademicYear.from_api(self.api.post(f"{self.PATH}{year_id}/set-current/"))

    def close(self, year_id):
        return AcademicYear.from_api(self.api.post(f"{self.PATH}{year_id}/close/"))


class LevelService:
    PATH = "levels/"

    def __init__(self, api):
        self.api = api

    def list(self, *, search=None, active=None):
        rows = self.api.list_all(self.PATH, search=(search or "").strip() or None, active=_active_param(active))
        return sorted((Level.from_api(row) for row in rows), key=lambda lv: (lv.order_index, lv.code))

    @staticmethod
    def _require(code, name):
        errors = {}
        if not (code or "").strip():
            errors["code"] = ["Obligatoire."]
        if not (name or "").strip():
            errors["name"] = ["Obligatoire."]
        if errors:
            raise ValidationFailed("Formulaire incomplet.", details=errors)

    @staticmethod
    def _payload(name, cycle, order_index, first_character, public_visible):
        return {
            "name": name.strip(),
            "cycle": (cycle or "").strip(),
            "order_index": order_index or 0,
            "first_character": (first_character or "").strip() or None,
            "public_visible": bool(public_visible),
        }

    def create(self, *, code, name, cycle="", order_index=0, first_character="", public_visible=False):
        self._require(code, name)
        payload = self._payload(name, cycle, order_index, first_character, public_visible)
        payload["code"] = code.strip().upper()
        return Level.from_api(self.api.post(self.PATH, payload))

    def update(self, level_id, *, name, cycle="", order_index=0, first_character="", public_visible=False):
        """The code is fixed at creation (server rule): not sent."""
        self._require("-", name)
        payload = self._payload(name, cycle, order_index, first_character, public_visible)
        return Level.from_api(self.api.patch(f"{self.PATH}{level_id}/", payload))

    def deactivate(self, level_id):
        return Level.from_api(self.api.post(f"{self.PATH}{level_id}/deactivate/"))

    def reactivate(self, level_id):
        return Level.from_api(self.api.post(f"{self.PATH}{level_id}/reactivate/"))
