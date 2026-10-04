"""Dashboard indicators and charts — only what the API really returns.

Indicators (cards):
    école                GET /school/
    année active         GET /academic-years/ (is_current)
    classes              GET /classes/?academic_year=<current>          meta.count
    élèves               GET /students/                                 meta.count
    enseignants          GET /admin/dashboard/teachers/                 active, by_category
    séances (semaine)    GET /sessions/?date_from=&date_to=             meta.count
    séances (jour)       GET /sessions/?date_from=today&date_to=today   en cours, annulées
    changements          GET /planning/changes/?date_from=today-6       7 derniers jours
    présence (jour)      GET /admin/attendance/dashboard/?date=today    counts
    encaissements        GET /admin/finance/dashboard/                  net_collected, outstanding
    paies versées        GET /admin/payroll/                            approved amounts of PAID payrolls

Charts (backend core/dashboard_api.py, ADR 0017):
    présences            GET /admin/dashboard/attendance-trend/?days=14
    élèves par niveau,
    par classe, effectifs GET /admin/dashboard/enrollments/
    activité récente     GET /admin/dashboard/activity/?limit=8
    finances             GET /admin/finance/dashboard/ payments_by_status, GET /admin/payroll/ (counts)

Each indicator and each chart is loaded on its own: one failing source
shows "Indisponible" with the reason instead of breaking the whole page.
No value is computed from nothing: a chart without data says so.
Authentication errors still propagate (-> login).
"""

from datetime import date, datetime, timedelta

from ..api.errors import ApiError, NetworkError, Unauthorized
from ..messages import explain
from ..models import (
    PAYMENT_STATUSES,
    PAYROLL_STATUSES,
    Activity,
    ChartData,
    DashboardCharts,
    DashboardData,
    Metric,
    Point,
)
from ..money import ZERO, format_money, to_decimal

ATTENDANCE_LABELS = {"PRESENT": "présents", "LATE": "retards", "ABSENT": "absents", "EXCUSED": "excusés"}
TREND_DAYS = 14
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MONTH_NAMES = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

# Administrative audit actions shown in "Activité récente" (an unknown one is
# shown as its code, never hidden).
ACTIVITY_LABELS = {
    "ACADEMIC_YEAR_CREATED": "Année scolaire créée",
    "ACADEMIC_YEAR_UPDATED": "Année scolaire modifiée",
    "ACADEMIC_YEAR_SET_CURRENT": "Année courante définie",
    "ACADEMIC_YEAR_CLOSED": "Année scolaire clôturée",
    "LEVEL_CREATED": "Niveau créé",
    "LEVEL_UPDATED": "Niveau modifié",
    "LEVEL_ACTIVATED": "Niveau réactivé",
    "LEVEL_DEACTIVATED": "Niveau désactivé",
    "CLASS_CREATED": "Classe créée",
    "CLASS_UPDATED": "Classe modifiée",
    "CLASS_ACTIVATED": "Classe réactivée",
    "CLASS_DEACTIVATED": "Classe désactivée",
    "CLASS_MAIN_ROOM_SET": "Salle principale attribuée",
    "CATEGORY_CREATED": "Catégorie créée",
    "CATEGORY_UPDATED": "Catégorie modifiée",
    "CATEGORY_ACTIVATED": "Catégorie réactivée",
    "CATEGORY_DEACTIVATED": "Catégorie désactivée",
    "SUBJECT_CREATED": "Matière créée",
    "SUBJECT_UPDATED": "Matière modifiée",
    "SUBJECT_ACTIVATED": "Matière réactivée",
    "SUBJECT_DEACTIVATED": "Matière désactivée",
    "ROOM_CREATED": "Salle créée",
    "FEE_TYPE_CREATED": "Type de frais créé",
    "FEE_SCHEDULE_CREATED": "Échéancier de frais créé",
}


money = format_money  # '1250000.00', 'XAF' -> '1 250 000 XAF'


def relative_time(moment, now=None):
    """'à l'instant', 'il y a 5 min', 'il y a 2 h', 'hier à 14:05', '12/03 à 09:10'."""
    if moment is None:
        return ""
    now = now or datetime.now(moment.tzinfo)
    seconds = (now - moment).total_seconds()
    local = moment.astimezone() if moment.tzinfo else moment
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        return f"il y a {int(seconds // 60)} min"
    if seconds < 6 * 3600:
        return f"il y a {int(seconds // 3600)} h"
    today = (now.astimezone() if now.tzinfo else now).date()
    if local.date() == today:
        return f"aujourd'hui à {local:%H:%M}"
    if local.date() == today - timedelta(days=1):
        return f"hier à {local:%H:%M}"
    return f"{local:%d/%m} à {local:%H:%M}"


def activity_text(activity, now=None):
    """(title, detail, when) of one row of « Activité récente »."""
    title = ACTIVITY_LABELS.get(activity.action, activity.action)
    when = relative_time(activity.at, now)
    return title, activity.label, f"{when} · {activity.actor}" if activity.actor else when


def _parse_datetime(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _plural(count, singular, plural=None):
    return f"{count} {singular if count < 2 else (plural or singular + 's')}"


def _month(key):
    """'2026-09' -> ('sept. 26', 'septembre 2026')."""
    index = int(key[5:7]) - 1
    return f"{MONTHS[index]} {key[2:4]}", f"{MONTH_NAMES[index]} {key[:4]}"


class DashboardService:
    def __init__(self, api, *, today=None):
        self.api = api
        self.today = today or date.today

    def _metric(self, label, loader, hint=""):
        try:
            value = loader()
            if isinstance(value, tuple):  # (value, hint computed with the value)
                value, hint = value
            return Metric(label, value, hint)
        except (Unauthorized, NetworkError):
            raise
        except ApiError as exc:
            return Metric(label, None, hint, error=explain(exc))

    def _chart(self, loader):
        try:
            return loader()
        except (Unauthorized, NetworkError):
            raise
        except ApiError as exc:
            return ChartData(error=explain(exc))

    # --- indicators ---------------------------------------------------------------
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
            self._metric("Élèves", lambda: str(self.api.count("students/", status="ACTIVE")), "actifs"),
            self._metric("Enseignants", self._teachers, "actifs"),
            self._metric(
                "Séances cette semaine",
                lambda: str(
                    self.api.count(
                        "sessions/", date_from=monday.isoformat(), date_to=(monday + timedelta(days=6)).isoformat()
                    )
                ),
                f"du {monday:%d/%m} au {monday + timedelta(days=6):%d/%m}",
            ),
            self._metric("Séances aujourd'hui", lambda: self._sessions_today(today), f"{today:%d/%m/%Y}"),
            self._metric(
                "Changements de planning",
                lambda: str(
                    len(self.api.list_all("planning/changes/", date_from=f"{today - timedelta(days=6):%Y-%m-%d}"))
                ),
                "7 derniers jours",
            ),
            self._metric("Présence aujourd'hui", lambda: self._attendance(today), f"{today:%d/%m/%Y}"),
            self._metric("Encaissements", self._finance, "net des remboursements"),
            self._metric("Paies versées", self._payroll, ""),
        ]
        return data

    def _sessions_today(self, day):
        """Today's sessions from the planning API; « en cours » compares the
        server's own start / end with the current time (display only)."""
        rows = self.api.list_all("sessions/", date_from=day.isoformat(), date_to=day.isoformat())
        cancelled = sum(1 for r in rows if r.get("status") == "CANCELLED")
        running = 0
        for row in rows:
            if row.get("status") != "SCHEDULED" or not row.get("scheduled_start"):
                continue
            start, end = datetime.fromisoformat(row["scheduled_start"]), datetime.fromisoformat(row["scheduled_end"])
            if start <= datetime.now(start.tzinfo) < end:
                running += 1
        return str(len(rows) - cancelled), f"{running} en cours · {cancelled} annulée(s)"

    def _attendance(self, day):
        """Big value = presence rate of the pupils already checked today;
        the detail (present, late, absent, excused) goes in the hint."""
        counts = self.api.get("admin/attendance/dashboard/", date=day.isoformat()).get("counts", {})
        checked = sum(counts.get(k, 0) for k in ATTENDANCE_LABELS)
        if not checked:
            return "—", f"aucun élève pointé le {day:%d/%m/%Y}"
        rate = 100 * (counts.get("PRESENT", 0) + counts.get("LATE", 0)) / checked
        detail = " · ".join(f"{counts.get(k, 0)} {label}" for k, label in ATTENDANCE_LABELS.items())
        return f"{rate:.0f} %", detail

    def _teachers(self):
        """Active teachers (teaching and employed) and the split by category."""
        data = self.api.get("admin/dashboard/teachers/")
        split = " · ".join(f"{c['code']} {c['count']}" for c in data.get("by_category", []))
        return str(data.get("active", 0)), f"actifs · {split}" if split else "actifs"

    def _finance(self):
        data = self.api.get("admin/finance/dashboard/")
        currency = data.get("currency", "")
        overdue = data.get("overdue_invoices", 0) or 0
        hint = f"reste à encaisser : {money(data.get('outstanding', 0), currency)}"
        if overdue:
            hint += f" · {_plural(overdue, 'facture')} en retard"
        return money(data.get("net_collected", 0), currency), hint

    def _payroll(self):
        """Sum (Decimal) of the approved amounts of the PAID payrolls, as stored by the server."""
        rows = self.api.get("admin/payroll/") or []
        paid = [r for r in rows if r.get("status") == "PAID"]
        waiting = sum(1 for r in rows if r.get("status") == "APPROVED")
        currency = next((r.get("currency") for r in rows if r.get("currency")), "")
        total = sum((to_decimal(r.get("approved_amount")) or ZERO for r in paid), ZERO)
        return money(total, currency), f"{_plural(len(paid), 'paie')} payée(s) · {waiting} approuvée(s) à payer"

    # --- charts ---------------------------------------------------------------------
    def load_charts(self):
        charts = DashboardCharts()
        charts.payments = self._chart(self._payments_by_status)
        charts.payrolls = self._chart(self._payrolls_by_status)
        charts.attendance = self._chart(self._attendance_trend)
        enrollments = self._chart(lambda: self.api.get("admin/dashboard/enrollments/"))
        if isinstance(enrollments, ChartData):  # the API failed: the three charts say why
            charts.by_level = charts.by_class = charts.enrollment_trend = enrollments
        else:
            charts.by_level, charts.by_class, charts.enrollment_trend = self._enrollment_charts(enrollments)
        try:
            charts.activity = [
                Activity(
                    _parse_datetime(row.get("at")),
                    row["action"],
                    row.get("entity_type", ""),
                    row.get("label", ""),
                    row.get("actor", ""),
                )
                for row in self.api.get("admin/dashboard/activity/", limit=8)
            ]
        except (Unauthorized, NetworkError):
            raise
        except ApiError as exc:
            charts.activity_error = explain(exc)
        return charts

    def _payments_by_status(self):
        counts = self.api.get("admin/finance/dashboard/").get("payments_by_status") or {}
        points = [
            Point(label, (counts[code],), f"{label} : {_plural(counts[code], 'paiement')}")
            for code, label in PAYMENT_STATUSES.items()
            if counts.get(code)
        ]
        return ChartData(
            series=("Paiements",), points=points, note="Nombre de paiements par résultat", empty_text="Aucun paiement."
        )

    def _payrolls_by_status(self):
        rows = self.api.get("admin/payroll/") or []
        points = []
        for code, label in PAYROLL_STATUSES.items():
            count = sum(1 for r in rows if r.get("status") == code)
            if count:
                points.append(Point(label, (count,), f"{label} : {_plural(count, 'paie')}"))
        return ChartData(
            series=("Paies",), points=points, note="Nombre de paies par étape", empty_text="Aucune paie calculée."
        )

    def _attendance_trend(self):
        data = self.api.get("admin/dashboard/attendance-trend/", days=TREND_DAYS)
        points = []
        for day in data.get("days", []):
            late, excused = day.get("LATE", 0), day.get("EXCUSED", 0)
            present = day.get("PRESENT", 0) + late
            absent = day.get("ABSENT", 0) + excused
            checked = present + absent  # PENDING = not finalised yet: not counted
            if not checked:
                continue
            moment = date.fromisoformat(day["date"])
            rate, absent_rate = 100 * present / checked, 100 * absent / checked
            tooltip = (
                f"{WEEKDAYS[moment.weekday()].capitalize()} {moment:%d/%m} : {rate:.0f} % présents "
                f"({present} sur {_plural(checked, 'élève')} pointés) · {_plural(late, 'retard')} · "
                f"{_plural(absent, 'absent')} dont {excused} justifiés"
            )
            points.append(Point(f"{moment:%d/%m}", (round(rate, 1), round(absent_rate, 1)), tooltip))
        return ChartData(
            series=("Présents", "Absents"),
            points=points,
            unit="%",
            maximum=100,
            empty_text=f"Aucune présence pointée sur les {TREND_DAYS} derniers jours.",
            note=f"{TREND_DAYS} derniers jours, en % des élèves pointés",
        )

    def _enrollment_charts(self, data):
        if not data.get("academic_year"):
            message = "Aucune année scolaire courante n'est définie."
            return tuple(ChartData(empty_text=message) for _ in range(3))
        year = data.get("academic_year_name") or ""
        empty = f"Aucun élève inscrit en {year}."
        by_level = ChartData(
            series=("Élèves",),
            points=[
                Point(r["code"], (r["count"],), f"{r['name']} ({r['code']}) : {_plural(r['count'], 'élève')} inscrits")
                for r in data.get("by_level", [])
            ],
            note=f"Élèves inscrits par niveau, année {year}",
            empty_text=empty,
        )
        classes = data.get("by_class", [])
        by_class = ChartData(
            series=("Élèves",),
            points=[
                Point(
                    r["name"],
                    (r["count"],),
                    f"{r['name']} : {_plural(r['count'], 'élève')}"
                    + (f" pour {r['capacity']} places" if r.get("capacity") else ""),
                )
                for r in classes
            ]
            if any(r["count"] for r in classes)
            else [],
            note=f"Élèves inscrits par classe active, année {year}",
            empty_text=empty if classes else f"Aucune classe active en {year}.",
        )
        months = data.get("by_month", [])
        trend = ChartData(
            series=("Élèves inscrits",),
            points=[
                Point(
                    _month(m["month"])[0],
                    (m["enrolled"],),
                    f"Fin {_month(m['month'])[1]} : {_plural(m['enrolled'], 'élève')} inscrits",
                )
                for m in months
            ]
            if any(m["enrolled"] for m in months)
            else [],
            note=f"Élèves inscrits à la fin de chaque mois, année {year}",
            empty_text=empty,
        )
        return by_level, by_class, trend
