"""Add / edit an academic year: Nom, Début, Fin (fields supported by the API).

A new year is created « planifiée »; it becomes « en cours » when it is
defined as the current year (list action). Compact: the name is short and
the two dates sit side by side (stacked on a narrow screen)."""

from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QLabel, QLineEdit

from ...i18n import tr
from ..widgets import FormDialog, date_field


def suggested_dates(years, today=None):
    """Start / end proposed for a new year: after the latest existing year,
    1 September → 31 July (editable)."""
    today = today or date.today()
    ends = [y.end_date for y in years if y.end_date]
    if ends:
        latest = max(ends)
        start = max(date(latest.year, 9, 1), latest + timedelta(days=1))
    else:
        start = date(today.year - (1 if today.month < 8 else 0), 9, 1)  # the running school year
    return start, date(start.year + 1, 7, 31)


def year_name(start, end):
    return f"{start.year}-{end.year}"


def _qdate(value):
    return QDate(value.year, value.month, value.day)


class YearDialog(FormDialog):
    def __init__(self, parent=None, year=None, *, suggested=None):
        editing = year is not None
        super().__init__(
            tr("Modifier l'année scolaire") if editing else tr("Nouvelle année scolaire"),
            tr("Les dates d'une année ne peuvent pas chevaucher celles d'une autre année de l'école."),
            parent,
            width=520,
        )
        self.name = self.add_field(
            "name",
            tr("Nom"),
            QLineEdit(placeholderText=tr("Ex. 2026-2027"), maxLength=30),
            required=True,
            width="short",
            help_text=tr("Proposé à partir des dates ; modifiable."),
        )
        self.start = self.add_field("start_date", tr("Début"), date_field(), required=True, width="short")
        self.end = self.add_field("end_date", tr("Fin"), date_field(), required=True, width="short", beside=True)
        if editing:
            state = tr("année courante") if year.is_current else year.status_label.lower()
            self.body.insertWidget(0, QLabel(tr("Statut actuel : {0}.", state), objectName="help"))
            self.name.setText(year.name)
            self.start.setDate(_qdate(year.start_date))
            self.end.setDate(_qdate(year.end_date))
        else:
            start, end = suggested or suggested_dates([])
            self.start.setDate(_qdate(start))
            self.end.setDate(_qdate(end))
            self.name.setText(year_name(start, end))
        self._name_follows_dates = not editing
        self.name.textEdited.connect(self._name_edited)
        for signal in (self.start.dateChanged, self.end.dateChanged):
            signal.connect(self._dates_changed)
        self.name.textChanged.connect(self.refresh_state)
        self.finish()
        self.name.setFocus()

    def _name_edited(self, _text):
        self._name_follows_dates = False  # the administrator chose a name: keep it

    def _dates_changed(self, _date=None):
        if self._name_follows_dates:
            self.name.setText(year_name(self.start.date().toPython(), self.end.date().toPython()))
        self.refresh_state()

    def missing_fields(self):
        missing = []
        if not self.name.text().strip():
            missing.append(tr("Nom"))
        if self.end.date() <= self.start.date():
            missing.append(tr("une date de fin après la date de début"))
        return missing

    def values(self):
        return {
            "name": self.name.text().strip(),
            "start_date": self.start.date().toPython(),
            "end_date": self.end.date().toPython(),
        }
