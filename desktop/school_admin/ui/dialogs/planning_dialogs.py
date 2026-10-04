"""Planning dialogs (ADR 0021), all on FormDialog (scrollable form, fixed
buttons, fit 1280×720 and smaller).

The client never decides a conflict: « Vérifier les conflits » sends the
slot to POST /admin/schedules/check/ and shows exactly what the server
found; every save may still be refused (409 planning_conflict, explained
in plain French by messages.explain_conflicts).
"""

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QWidget

from ...messages import explain_conflicts
from ...models import BREAK_TYPES, ROOM_TYPES, WEEKDAY_NAMES
from ..widgets import FormDialog, button, date_field, time_field

CHOOSE_COURSE = "Choisir un cours…"
MAIN_ROOM = "Salle principale de la classe"
NO_ROOM = "Aucune salle"
YEAR_START = "Début de l'année"
YEAR_END = "Fin de l'année"
EARLIEST = QDate(2000, 1, 1)


def _qdate(value):
    return QDate(value.year, value.month, value.day)


def _qtime(text):
    hours, minutes = (int(x) for x in text[:5].split(":"))
    return QTime(hours, minutes)


def _reason(placeholder="Motif (obligatoire, visible dans l'historique)"):
    field = QPlainTextEdit(placeholderText=placeholder)
    field.setFixedHeight(60)
    field.setTabChangesFocus(True)
    return field


def _rooms_combo(rooms, first):
    combo = QComboBox()
    combo.addItem(first, None)
    for room in rooms:
        combo.addItem(room.label, room.id)
    return combo


def _weekday_combo():
    combo = QComboBox()
    for number, name in WEEKDAY_NAMES.items():
        combo.addItem(name, number)
    return combo


def _optional_date(text):
    field = date_field()
    field.setMinimumDate(EARLIEST)
    field.setSpecialValueText(text)  # EARLIEST = not given (server default)
    field.setDate(EARLIEST)
    return field


def _grid(pairs):
    widget = QWidget()
    grid = QGridLayout(widget)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(6)
    for index, (label, value) in enumerate(pairs):
        grid.addWidget(QLabel(label, objectName="fieldLabel"), index, 0, Qt.AlignTop)
        text = QLabel(str(value), objectName="fieldValue")
        text.setWordWrap(True)
        grid.addWidget(text, index, 1)
    grid.setColumnStretch(1, 1)
    return widget


class _TimesMixin:
    def _times_ok(self):
        return self.end_time.time() > self.start_time.time()


# =============================================================================
# Slots
# =============================================================================


class SlotDialog(FormDialog, _TimesMixin):
    """New recurring slot. `check(payload, done)` asks the server (dry run)."""

    def __init__(self, courses, rooms, check, parent=None):
        super().__init__(
            "Nouveau créneau",
            "Un créneau répète un cours chaque semaine. Les conflits (classe, enseignant, salle) sont "
            "vérifiés par le serveur.",
            parent,
            width=600,
        )
        self.check_fn = check
        self.result = None
        course = QComboBox()
        course.addItem(CHOOSE_COURSE, None)
        for item in courses:
            course.addItem(f"{item.subject_code} — {item.class_name} · {item.teacher_name}", item.id)
        self.course = self.add_field("course", "Cours", course, required=True, width="long")
        self.weekday = self.add_field("weekday", "Jour", _weekday_combo(), required=True, width="short")
        self.start_time = self.add_field(
            "start", "Début", time_field(QTime(8, 0)), required=True, width="short", beside=True
        )
        self.end_time = self.add_field(
            "end", "Fin", time_field(QTime(10, 0)), required=True, width="short", beside=True
        )
        self.room = self.add_field(
            "room",
            "Salle",
            _rooms_combo(rooms, MAIN_ROOM),
            width="medium",
            help_text="Par défaut : la salle principale.",
        )
        self.effective_from = self.add_field("effective_from", "À partir du", _optional_date(YEAR_START), width="short")
        self.effective_to = self.add_field(
            "effective_to", "Jusqu'au", _optional_date(YEAR_END), width="short", beside=True
        )
        self.check_button = button("Vérifier les conflits")
        self.body.addWidget(self.check_button, 0, Qt.AlignLeft)
        self.verdict = QLabel("", objectName="banner")
        self.verdict.setWordWrap(True)
        self.verdict.hide()
        self.body.addWidget(self.verdict)
        self.force = self.add_field(
            "force", "Indisponibilité déclarée", QCheckBox("Programmer malgré tout (motif requis)")
        )
        self.reason = self.add_field("reason", "Motif", _reason("Motif de la dérogation à la disponibilité"))
        self.force.setEnabled(False)
        self.check_button.clicked.connect(self.check)
        for signal in (
            self.course.currentIndexChanged,
            self.weekday.currentIndexChanged,
            self.start_time.timeChanged,
            self.end_time.timeChanged,
            self.room.currentIndexChanged,
            self.force.toggled,
            self.reason.textChanged,
        ):
            signal.connect(self.refresh_state)
        self.finish()

    def payload(self):
        start, end = self.effective_from.date(), self.effective_to.date()
        return {
            "course_id": self.course.currentData(),
            "weekday": self.weekday.currentData(),
            "start_time": self.start_time.time().toPython(),
            "end_time": self.end_time.time().toPython(),
            "room_id": self.room.currentData(),
            "effective_from": None if start == EARLIEST else start.toPython(),
            "effective_to": None if end == EARLIEST else end.toPython(),
        }

    def check(self):
        if self.course.currentData():
            self.check_fn(self.payload(), self.show_check)

    def show_check(self, result):
        """Display the server's dry-run answer exactly."""
        self.result = result
        conflicts = result.get("conflicts") or []
        unavailable = result.get("teacher_declared_unavailable")
        if conflicts:
            kind, text = "warning", "Conflits : " + explain_conflicts(conflicts) + "."
        else:
            kind, text = "success", "Aucun conflit de classe, d'enseignant ou de salle."
        if unavailable:
            kind = "warning"
            text += " L'enseignant s'est déclaré indisponible sur ce créneau."
        self.force.setEnabled(bool(unavailable))
        self.verdict.setProperty("kind", kind)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        self.verdict.setText(text)
        self.verdict.show()

    def missing_fields(self):
        if not hasattr(self, "reason"):
            return []
        missing = [] if self.course.currentData() else ["Cours"]
        if not self._times_ok():
            missing.append("une heure de fin après le début")
        if self.force.isChecked() and not self.reason.toPlainText().strip():
            missing.append("Motif")
        return missing

    def values(self):
        values = self.payload()
        if self.force.isChecked():
            values |= {"force_availability": True, "reason": self.reason.toPlainText().strip()}
        return values


class EndSlotDialog(FormDialog):
    def __init__(self, slot, parent=None):
        super().__init__(
            "Terminer le créneau",
            f"{slot.code} · {slot.when}. Les séances après la dernière date sont annulées (familles prévenues).",
            parent,
            save_text="Terminer",
        )
        self.last_date = self.add_field("last_date", "Dernier jour", date_field(), required=True, width="short")
        self.last_date.setDate(QDate.currentDate())
        self.reason = self.add_field("reason", "Motif", _reason(), required=True)
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [] if self.reason.toPlainText().strip() else ["Motif"]

    def values(self):
        return {"last_date": self.last_date.date().toPython(), "reason": self.reason.toPlainText().strip()}


class RescheduleDialog(FormDialog, _TimesMixin):
    def __init__(self, slot, rooms, parent=None):
        super().__init__(
            "Reprogrammer le créneau",
            f"{slot.code} · {slot.when}. L'ancien créneau s'arrête la veille, un nouveau commence.",
            parent,
            save_text="Reprogrammer",
        )
        self.from_date = self.add_field("from_date", "À partir du", date_field(), required=True, width="short")
        self.from_date.setDate(QDate.currentDate())
        self.weekday = self.add_field("weekday", "Jour", _weekday_combo(), required=True, width="short", beside=True)
        self.weekday.setCurrentIndex(max(0, self.weekday.findData(slot.weekday)))
        self.start_time = self.add_field(
            "start", "Début", time_field(_qtime(slot.start_time)), required=True, width="short"
        )
        self.end_time = self.add_field(
            "end", "Fin", time_field(_qtime(slot.end_time)), required=True, width="short", beside=True
        )
        self.room = self.add_field("room", "Salle", _rooms_combo(rooms, MAIN_ROOM), width="medium")
        self.room.setCurrentIndex(max(0, self.room.findData(slot.room_id)))
        self.reason = self.add_field("reason", "Motif", _reason(), required=True)
        for signal in (self.reason.textChanged, self.start_time.timeChanged, self.end_time.timeChanged):
            signal.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = [] if self.reason.toPlainText().strip() else ["Motif"]
        if not self._times_ok():
            missing.append("une heure de fin après le début")
        return missing

    def values(self):
        return {
            "from_date": self.from_date.date().toPython(),
            "weekday": self.weekday.currentData(),
            "start_time": self.start_time.time().toPython(),
            "end_time": self.end_time.time().toPython(),
            "room_id": self.room.currentData(),
            "reason": self.reason.toPlainText().strip(),
        }


# =============================================================================
# Sessions
# =============================================================================


class GenerateDialog(FormDialog):
    def __init__(self, classes, monday, parent=None):
        super().__init__(
            "Générer les séances",
            "Crée les séances des créneaux publiés sur la période (vacances exclues, séances existantes conservées).",
            parent,
            save_text="Générer",
        )
        self.date_from = self.add_field("date_from", "Du", date_field(), required=True, width="short")
        self.date_to = self.add_field("date_to", "Au", date_field(), required=True, width="short", beside=True)
        self.date_from.setDate(_qdate(monday))
        self.date_to.setDate(_qdate(monday + timedelta(days=6)))
        school_class = QComboBox()
        school_class.addItem("Toutes les classes", None)
        for item in classes:
            school_class.addItem(item.name, item.id)
        self.school_class = self.add_field("school_class", "Classe", school_class, width="medium")
        for signal in (self.date_from.dateChanged, self.date_to.dateChanged):
            signal.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [] if self.date_to.date() >= self.date_from.date() else ["une date de fin après le début"]

    def values(self):
        return {
            "date_from": self.date_from.date().toPython(),
            "date_to": self.date_to.date().toPython(),
            "class_id": self.school_class.currentData(),
        }


class MoveDialog(FormDialog, _TimesMixin):
    def __init__(self, session, parent=None):
        super().__init__(
            "Déplacer la séance",
            f"{session.code} · {session.date:%d/%m/%Y} {session.hours}. Les conflits sont vérifiés par le serveur.",
            parent,
            save_text="Déplacer",
        )
        self.day = self.add_field("day", "Nouvelle date", date_field(), required=True, width="short")
        self.day.setDate(_qdate(session.date))
        self.start_time = self.add_field(
            "start",
            "Début",
            time_field(QTime(session.start.hour, session.start.minute)),
            required=True,
            width="short",
            beside=True,
        )
        self.end_time = self.add_field(
            "end",
            "Fin",
            time_field(QTime(session.end.hour, session.end.minute)),
            required=True,
            width="short",
            beside=True,
        )
        self.reason = self.add_field("reason", "Motif", _reason(), required=True)
        for signal in (self.reason.textChanged, self.start_time.timeChanged, self.end_time.timeChanged):
            signal.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = [] if self.reason.toPlainText().strip() else ["Motif"]
        if not self._times_ok():
            missing.append("une heure de fin après le début")
        return missing

    def values(self):
        day = self.day.date().toPython()
        return {
            "new_start": datetime.combine(day, self.start_time.time().toPython()),
            "new_end": datetime.combine(day, self.end_time.time().toPython()),
            "reason": self.reason.toPlainText().strip(),
        }


class RoomChangeDialog(FormDialog):
    def __init__(self, session, rooms, parent=None):
        super().__init__(
            "Changer de salle",
            f"{session.code} · {session.date:%d/%m/%Y} {session.hours} · salle actuelle : {session.room_code or '—'}",
            parent,
            save_text="Changer de salle",
        )
        self.room = self.add_field("room", "Nouvelle salle", _rooms_combo(rooms, NO_ROOM), width="medium")
        self.room.setCurrentIndex(max(0, self.room.findData(session.room_id)))
        self.reason = self.add_field("reason", "Motif", _reason(), required=True)
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [] if self.reason.toPlainText().strip() else ["Motif"]

    def values(self):
        return {"room_id": self.room.currentData(), "reason": self.reason.toPlainText().strip()}


class SubstituteDialog(FormDialog):
    def __init__(self, session, teachers, parent=None):
        super().__init__(
            "Remplacer l'enseignant",
            f"{session.code} · {session.date:%d/%m/%Y} {session.hours}. Enseignant prévu : "
            f"{session.planned_teacher_name}. Le serveur vérifie compatibilité et disponibilité.",
            parent,
            save_text="Remplacer",
        )
        teacher = QComboBox()
        teacher.addItem("Choisir un remplaçant…", None)
        for item in teachers:
            if item.id != session.teacher_id:
                teacher.addItem(f"{item.name} ({item.number})", item.id)
        self.teacher = self.add_field("teacher", "Remplaçant", teacher, required=True, width="medium")
        self.reason = self.add_field("reason", "Motif", _reason(), required=True)
        self.teacher.currentIndexChanged.connect(self.refresh_state)
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        if not hasattr(self, "reason"):
            return []
        missing = [] if self.teacher.currentData() else ["Remplaçant"]
        if not self.reason.toPlainText().strip():
            missing.append("Motif")
        return missing

    def values(self):
        return {"teacher_id": self.teacher.currentData(), "reason": self.reason.toPlainText().strip()}


class SessionDialog(FormDialog):
    """Record of a session; buttons close it with `action` set."""

    ACTIONS = (
        ("move", "Déplacer…"),
        ("room", "Changer de salle…"),
        ("substitute", "Remplacer l'enseignant…"),
        ("restore", "Restaurer l'enseignant prévu…"),
        ("cancel", "Annuler la séance…"),
    )

    def __init__(self, session, parent=None):
        super().__init__(f"Séance — {session.code}", "", parent, save_text="Fermer", width=560)
        self.action = None
        self.cancel_button.hide()
        self.add_section("Séance")
        self.body.addWidget(
            _grid(
                [
                    ("Matière", f"{session.subject_code} — {session.subject_name}"),
                    ("Classe", session.class_name),
                    ("Date", f"{session.date:%d/%m/%Y}" if session.date else "—"),
                    ("Heure", session.hours),
                    ("Salle", session.room_code or "—"),
                    ("Enseignant prévu", session.planned_teacher_name),
                    ("Enseignant réel", session.teacher_name),
                    ("Statut", session.status_label),
                ]
            )
        )
        self.add_section("Actions")
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.buttons = {}
        scheduled = session.status == "SCHEDULED"
        for index, (name, text) in enumerate(self.ACTIONS):
            widget = button(text, "danger" if name == "cancel" else "secondary")
            enabled = scheduled and (name != "restore" or session.is_substituted)
            widget.setEnabled(enabled)
            widget.clicked.connect(lambda _=False, n=name: self._start(n))
            grid.addWidget(widget, index // 2, index % 2)
            self.buttons[name] = widget
        self.body.addWidget(holder)
        if not scheduled:
            self.body.addWidget(QLabel("Séance annulée ou réalisée : plus modifiable.", objectName="help"))
        self.finish(required_note=False)
        self.save_button.setFocus()

    def _start(self, name):
        self.action = name
        self.accept()


# =============================================================================
# Rooms
# =============================================================================


class RoomDialog(FormDialog):
    def __init__(self, parent=None, room=None):
        editing = room is not None
        super().__init__(
            "Modifier la salle" if editing else "Nouvelle salle",
            "Salle de l'école utilisée par les créneaux et les séances.",
            parent,
        )
        self.code = self.add_field(
            "code", "Code", QLineEdit(placeholderText="Ex. R12", maxLength=30), required=True, width="short"
        )
        self.name = self.add_field(
            "name",
            "Nom",
            QLineEdit(placeholderText="Ex. Salle 12", maxLength=100),
            required=True,
            width="medium",
            beside=True,
        )
        room_type = QComboBox()
        for value, label in ROOM_TYPES.items():
            room_type.addItem(label, value)
        self.room_type = self.add_field("room_type", "Type", room_type, width="medium")
        self.capacity = self.add_field(
            "capacity", "Capacité", QLineEdit(placeholderText="Ex. 40", maxLength=4), width="short"
        )
        self.bench_count = self.add_field(
            "bench_count", "Bancs", QLineEdit(placeholderText="Facultatif", maxLength=4), width="short", beside=True
        )
        self.capacity.setValidator(QIntValidator(1, 9999, self.capacity))
        self.bench_count.setValidator(QIntValidator(0, 9999, self.bench_count))
        if editing:
            self.code.setText(room.code)
            self.code.setReadOnly(True)  # fixed at creation
            self.name.setText(room.name)
            self.room_type.setCurrentIndex(max(0, self.room_type.findData(room.room_type)))
            self.capacity.setText(str(room.capacity) if room.capacity else "")
            self.bench_count.setText("" if room.bench_count is None else str(room.bench_count))
        for field in (self.code, self.name):
            field.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [label for field, label in ((self.code, "Code"), (self.name, "Nom")) if not field.text().strip()]

    def values(self):
        return {
            "code": self.code.text().strip(),
            "name": self.name.text().strip(),
            "room_type": self.room_type.currentData(),
            "capacity": int(self.capacity.text()) if self.capacity.text().strip() else None,
            "bench_count": int(self.bench_count.text()) if self.bench_count.text().strip() else None,
        }


class MainRoomDialog(FormDialog):
    def __init__(self, classes, rooms, parent=None):
        super().__init__(
            "Salle principale d'une classe",
            "Salle utilisée par défaut par les créneaux de la classe. Le serveur vérifie la capacité.",
            parent,
            save_text="Enregistrer",
        )
        school_class = QComboBox()
        school_class.addItem("Choisir une classe…", None)
        for item in classes:
            school_class.addItem(f"{item.name} — salle actuelle : {item.main_room_label or 'aucune'}", item.id)
        self.school_class = self.add_field("school_class", "Classe", school_class, required=True, width="long")
        self.room = self.add_field(
            "room", "Salle principale", _rooms_combo(rooms, "Aucune salle principale"), width="medium"
        )
        self.school_class.currentIndexChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [] if self.school_class.currentData() else ["Classe"]

    def values(self):
        return {"class_id": self.school_class.currentData(), "room_id": self.room.currentData()}


# =============================================================================
# Availability requests, breaks
# =============================================================================


class DecisionDialog(FormDialog):
    """Decide a dated unavailability request; the impacted sessions listed
    are the server's (GET .../impacted-sessions/)."""

    DECISIONS = (("APPROVED", "Valider"), ("REJECTED", "Refuser"), ("CHANGES_REQUESTED", "Proposer une modification"))

    def __init__(self, request, teacher_name, impacted, parent=None):
        super().__init__(
            "Décider de la demande",
            f"{teacher_name} · {request.date:%d/%m/%Y} {request.start_time[:5]}–{request.end_time[:5]} · "
            f"« {request.reason} »",
            parent,
            save_text="Enregistrer la décision",
        )
        self.add_section(
            "Séances impactées", "Calculées par le serveur ; elles restent à réorganiser après validation."
        )
        if impacted:
            self.body.addWidget(
                _grid([(f"{s.date:%d/%m}", f"{s.hours} · {s.code} · salle {s.room_code or '—'}") for s in impacted])
            )
        else:
            self.body.addWidget(QLabel("Aucune séance impactée.", objectName="help"))
        self.add_section("Décision")
        decision = QComboBox()
        for value, label in self.DECISIONS:
            decision.addItem(label, value)
        self.decision = self.add_field("decision", "Décision", decision, required=True, width="medium")
        comment = QPlainTextEdit(placeholderText="Commentaire pour l'enseignant (facultatif)")
        comment.setFixedHeight(60)
        comment.setTabChangesFocus(True)
        self.comment = self.add_field("comment", "Commentaire", comment)
        self.finish()

    def values(self):
        return {"decision": self.decision.currentData(), "comment": self.comment.toPlainText().strip() or None}


class BreakDialog(FormDialog):
    def __init__(self, years, parent=None, school_break=None):
        editing = school_break is not None
        super().__init__(
            "Modifier l'interruption" if editing else "Nouvelle interruption",
            "Vacances, jours fériés, examens : la génération des séances les saute.",
            parent,
        )
        year = QComboBox()
        for item in years:
            year.addItem(item.short_label, item.id)
        self.year = self.add_field("academic_year", "Année scolaire", year, required=True, width="medium")
        self.name = self.add_field(
            "name",
            "Nom",
            QLineEdit(placeholderText="Ex. Vacances de Noël", maxLength=120),
            required=True,
            width="medium",
        )
        break_type = QComboBox()
        for value, label in BREAK_TYPES.items():
            break_type.addItem(label, value)
        self.break_type = self.add_field("break_type", "Type", break_type, width="short", beside=True)
        self.start_day = self.add_field("start_day", "Début", date_field(), required=True, width="short")
        self.start_time = self.add_field("start_time", "Heure", time_field(QTime(0, 0)), width="short", beside=True)
        self.end_day = self.add_field("end_day", "Fin", date_field(), required=True, width="short")
        self.end_time = self.add_field("end_time", "Heure", time_field(QTime(23, 59)), width="short", beside=True)
        self.affects = self.add_field("affects", "Planning", QCheckBox("Aucune séance générée pendant cette période"))
        self.affects.setChecked(True)
        if editing:
            self.year.setCurrentIndex(max(0, self.year.findData(school_break.year_id)))
            self.year.setEnabled(False)
            self.name.setText(school_break.name)
            self.break_type.setCurrentIndex(max(0, self.break_type.findData(school_break.break_type)))
            self.start_day.setDate(_qdate(school_break.start))
            self.start_time.setTime(QTime(school_break.start.hour, school_break.start.minute))
            self.end_day.setDate(_qdate(school_break.end))
            self.end_time.setTime(QTime(school_break.end.hour, school_break.end.minute))
            self.affects.setChecked(school_break.affects_scheduling)
        else:
            self.start_day.setDate(QDate.currentDate())
            self.end_day.setDate(QDate.currentDate().addDays(7))
        for signal in (
            self.name.textChanged,
            self.start_day.dateChanged,
            self.end_day.dateChanged,
            self.start_time.timeChanged,
            self.end_time.timeChanged,
        ):
            signal.connect(self.refresh_state)
        self.finish()

    def _start(self):
        return datetime.combine(self.start_day.date().toPython(), self.start_time.time().toPython())

    def _end(self):
        return datetime.combine(self.end_day.date().toPython(), self.end_time.time().toPython())

    def missing_fields(self):
        if not hasattr(self, "affects"):
            return []
        missing = [] if self.name.text().strip() else ["Nom"]
        if not self.year.currentData():
            missing.append("Année scolaire")
        if self._end() <= self._start():
            missing.append("une fin après le début")
        return missing

    def values(self):
        return {
            "year_id": self.year.currentData(),
            "name": self.name.text().strip(),
            "break_type": self.break_type.currentData(),
            "start": self._start(),
            "end": self._end(),
            "affects_scheduling": self.affects.isChecked(),
        }
