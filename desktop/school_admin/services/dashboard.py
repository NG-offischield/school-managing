"""Dashboard indicators — only what the API really returns, nothing invented.

    école                GET /school/
    année active         GET /academic-years/ (is_current)
    classes              GET /classes/?academic_year=<current>          meta.count
    élèves               GET /students/                                 meta.count
    enseignants          GET /teachers/                                 meta.count
    séances (semaine)    GET /sessions/?date_from=&date_to=             meta.count
    présence (jour)      GET /admin/attendance/dashboard/?date=today    counts

Each indicator is loaded on its own: one failing source (no current year,
feature not configured...) shows "indisponible" with the reason instead of
breaking the whole page. Authentication errors still propagate (-> login).
"""

from datetime import date, timedelta

from ..api.errors import ApiError, NetworkError, Unauthorized
from ..models import DashboardData, Metric

ATTENDANCE_LABELS = {"PRESENT": "présents", "LATE": "retards", "ABSENT": "absents", "EXCUSED": "excusés"}


class DashboardService:
    def __init__(self, api, *, today=None):
        self.api = api
        self.today = today or date.today

    def _metric(self, label, loader, hint=""):
        try:
            return Metric(label, loader(), hint)
        except (Unauthorized, NetworkError):
            raise
        except ApiError as exc:
            return Metric(label, None, hint, error=exc.message)

    def load(self):
        school = self.api.get("school/")
        data = DashboardData(school_name=school.get("name", ""), school_city=school.get("city", ""))
        years = self.api.list_all("academic-years/")
        current = next((y for y in years if y.get("is_current")), None)
        data.year_name = current["name"] if current else ""
        today = self.today()
        monday = today - timedelta(days=today.weekday())
        data.metrics = [
            Metric(
                "Année scolaire active",
                current["name"] if current else None,
                f"{current['start_date']} → {current['end_date']}" if current else "",
                error=None if current else "Aucune année scolaire courante n'est définie.",
            ),
            self._metric(
                "Classes",
                lambda: str(self.api.count("classes/", academic_year=current["id"] if current else None)),
                "de l'année active" if current else "toutes années",
            ),
            self._metric("Élèves", lambda: str(self.api.count("students/"))),
            self._metric("Enseignants", lambda: str(self.api.count("teachers/"))),
            self._metric(
                "Séances cette semaine",
                lambda: str(
                    self.api.count(
                        "sessions/", date_from=monday.isoformat(), date_to=(monday + timedelta(days=6)).isoformat()
                    )
                ),
                f"du {monday:%d/%m} au {monday + timedelta(days=6):%d/%m}",
            ),
            self._metric("Présence aujourd'hui", lambda: self._attendance(today), f"{today:%d/%m/%Y}"),
        ]
        return data

    def _attendance(self, day):
        counts = self.api.get("admin/attendance/dashboard/", date=day.isoformat()).get("counts", {})
        parts = [f"{counts.get(k, 0)} {label}" for k, label in ATTENDANCE_LABELS.items()]
        return " · ".join(parts)
