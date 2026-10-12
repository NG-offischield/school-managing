"""Classes (backend academics/class_api.py) and the reference lists their form
needs. Thin client: the server enforces every rule (unique name in the year,
same-school level / year / room, closed year, class still in use…); the
only check here is that the required fields are filled before a call.

Reference lists come from the API, never typed by hand:
    years   GET /academic-years/   (open ones — planned / current — for a new class)
    levels  GET /levels/           (active ones)
    rooms   GET /rooms/?active=true
    regimes GET /timetable-regimes/   (optional day / evening windows of a year)

Default room: optional; one class per year holds it, unless both classes follow
explicit, non-overlapping regimes (server rule, 409 room_default_taken /
room_default_regimes_overlap). Changing it moves no planned slot or session.
"""

from ..api.errors import ValidationFailed
from ..i18n import tr
from ..models import AcademicYear, Level, Room, SchoolClass, TimetableRegime


def _active_param(active):
    return None if active is None else ("true" if active else "false")


class ReferenceService:
    def __init__(self, api):
        self.api = api

    def years(self, *, open_only=False):
        years = [AcademicYear.from_api(row) for row in self.api.list_all("academic-years/")]
        years.sort(key=lambda y: (not y.is_current, y.name), reverse=False)
        return [y for y in years if y.open] if open_only else years

    def levels(self, *, active_only=True):
        levels = sorted((Level.from_api(row) for row in self.api.list_all("levels/")), key=lambda lv: lv.order_index)
        return [lv for lv in levels if lv.active] if active_only else levels

    def rooms(self):
        return [Room.from_api(row) for row in self.api.list_all("rooms/", active="true")]

    def regimes(self, *, academic_year_id=None, active_only=True):
        rows = self.api.list_all(
            "timetable-regimes/", academic_year=academic_year_id or None, active="true" if active_only else None
        )
        return [TimetableRegime.from_api(row) for row in rows]

    def classes(self, *, academic_year_id=None):
        """Active classes (all years, or one year): the student forms filter
        them by the chosen year and level."""
        rows = self.api.list_all("classes/", active="true", academic_year=academic_year_id or None)
        return sorted((SchoolClass.from_api(row) for row in rows), key=lambda c: c.name)


class ClassService:
    PATH = "classes/"

    def __init__(self, api):
        self.api = api

    def list(self, *, search=None, active=None, academic_year_id=None, level_id=None):
        rows = self.api.list_all(
            self.PATH,
            search=(search or "").strip() or None,
            active=_active_param(active),
            academic_year=academic_year_id or None,
            level=level_id or None,
        )
        return [SchoolClass.from_api(row) for row in rows]

    @staticmethod
    def _require(name, level_id, year_id=None, creating=True):
        errors = {}
        if not (name or "").strip():
            errors["name"] = [tr("Obligatoire.")]
        if not level_id:
            errors["level"] = [tr("Choisissez un niveau.")]
        if creating and not year_id:
            errors["academic_year"] = [tr("Choisissez une année scolaire.")]
        if errors:
            raise ValidationFailed("Formulaire incomplet.", details=errors)

    def create(
        self,
        *,
        name,
        level_id,
        academic_year_id,
        main_room_id=None,
        regime_id=None,
        capacity=None,
        public_visible=False,
    ):
        self._require(name, level_id, academic_year_id)
        payload = {
            "name": name.strip(),
            "level": level_id,
            "academic_year": academic_year_id,
            "main_room": main_room_id or None,
            "regime": regime_id or None,
            "capacity": capacity or None,
            "public_visible": bool(public_visible),
        }
        return SchoolClass.from_api(self.api.post(self.PATH, payload))

    def update(
        self, class_id, *, name, level_id, main_room_id=None, regime_id=None, capacity=None, public_visible=False
    ):
        """The academic year is fixed at creation (server rule): not sent."""
        self._require(name, level_id, creating=False)
        payload = {
            "name": name.strip(),
            "level": level_id,
            "main_room": main_room_id or None,
            "regime": regime_id or None,
            "capacity": capacity or None,
            "public_visible": bool(public_visible),
        }
        return SchoolClass.from_api(self.api.patch(f"{self.PATH}{class_id}/", payload))

    def deactivate(self, class_id):
        return SchoolClass.from_api(self.api.post(f"{self.PATH}{class_id}/deactivate/"))

    def reactivate(self, class_id):
        return SchoolClass.from_api(self.api.post(f"{self.PATH}{class_id}/reactivate/"))


class RegimeService:
    """Timetable regimes (backend academics/class_api.py). Thin client: hours,
    unique name, overlaps with shared rooms and slots are checked by the server."""

    PATH = "timetable-regimes/"

    def __init__(self, api):
        self.api = api

    def list(self, *, academic_year_id=None):
        rows = self.api.list_all(self.PATH, academic_year=academic_year_id or None)
        return [TimetableRegime.from_api(row) for row in rows]

    def create(self, *, academic_year_id, name, start, end):
        if not (name or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"name": [tr("Obligatoire.")]})
        payload = {"academic_year": academic_year_id, "name": name.strip(), "start_time": start, "end_time": end}
        return TimetableRegime.from_api(self.api.post(self.PATH, payload))

    def update(self, regime_id, **changes):
        mapping = {"name": "name", "start": "start_time", "end": "end_time", "active": "active"}
        payload = {mapping[k]: v for k, v in changes.items() if k in mapping}
        return TimetableRegime.from_api(self.api.patch(f"{self.PATH}{regime_id}/", payload))
