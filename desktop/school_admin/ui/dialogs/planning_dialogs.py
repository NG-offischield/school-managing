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

from ...i18n import Tr, tr
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


def _reason(placeholder=None):
    placeholder = (
        tr("Motif (obligatoire, visible dans l'historique)") if placeholder is None else placeholder
    )  # read now: follows the language
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
            tr("Nouveau créneau"),
            tr(
                "Un créneau répète un cours chaque semaine. Les conflits (classe, enseignant, salle) sont vérifiés "
                "par le serveur."
            ),
            parent,
            width=600,
        )
        self.check_fn = check
        self.result = None
        course = QComboBox()
        course.addItem(tr(CHOOSE_COURSE), None)
        for item in courses:
            course.addItem(f"{item.subject_code} — {item.class_name} · {item.teacher_name}", item.id)
        self.course = self.add_field("course", tr("Cours"), course, required=True, width="long")
        self.weekday = self.add_field("weekday", tr("Jour"), _weekday_combo(), required=True, width="short")
        self.start_time = self.add_field(
            "start", tr("Début"), time_field(QTime(8, 0)), required=True, width="short", beside=True
        )
        self.end_time = self.add_field(
            "end", tr("Fin"), time_field(QTime(10, 0)), required=True, width="short", beside=True
        )
        self.room = self.add_field(
            "room",
            tr("Salle"),
            _rooms_combo(rooms, tr(MAIN_ROOM)),
            width="medium",
            help_text=tr("Par défaut : la salle principale."),
        )
        self.effective_from = self.add_field(
            "effective_from", tr("À partir du"), _optional_date(tr(YEAR_START)), width="short"
        )
        self.effective_to = self.add_field(
            "effective_to", tr("Jusqu'au"), _optional_date(tr(YEAR_END)), width="short", beside=True
        )
        self.check_button = button(tr("Vérifier les conflits"))
        self.body.addWidget(self.check_button, 0, Qt.AlignLeft)
        self.verdict = QLabel("", objectName="banner")
        self.verdict.setWordWrap(True)
        self.verdict.hide()
        self.body.addWidget(self.verdict)
        self.force = self.add_field(
            "force", tr("Indisponibilité déclarée"), QCheckBox(tr("Programmer malgré tout (motif requis)"))
        )
        self.reason = self.add_field("reason", tr("Motif"), _reason(tr("Motif de la dérogation à la disponibilité")))
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
            kind, text = "warning", tr("Conflits : ") + explain_conflicts(conflicts) + "."
        else:
            kind, text = "success", tr("Aucun conflit de classe, d'enseignant ou de salle.")
        if unavailable:
            kind = "warning"
            text += tr(" L'enseignant s'est déclaré indisponible sur ce créneau.")
        self.force.setEnabled(bool(unavailable))
        self.verdict.setProperty("kind", kind)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        self.verdict.setText(text)
        self.verdict.show()

    def missing_fields(self):
        if not hasattr(self, "reason"):
            return []
        missing = [] if self.course.currentData() else [tr("Cours")]
        if not self._times_ok():
            missing.append(tr("une heure de fin après le début"))
        if self.force.isChecked() and not self.reason.toPlainText().strip():
            missing.append(tr("Motif"))
        return missing

    def values(self):
        values = self.payload()
        if self.force.isChecked():
            values |= {"force_availability": True, "reason": self.reason.toPlainText().strip()}
        return values


class EndSlotDialog(FormDialog):
    def __init__(self, slot, parent=None):
        super().__init__(
            tr("Terminer le créneau"),
            tr(
                "{0} · {1}. Les séances après la dernière date sont annulées (familles prévenues).",
                slot.code,
                slot.when,
            ),
            parent,
            save_text=tr("Terminer"),
        )
        self.last_date = self.add_field("last_date", tr("Dernier jour"), date_field(), required=True, width="short")
        self.last_date.setDate(QDate.currentDate())
        self.reason = self.add_field("reason", tr("Motif"), _reason(), required=True)
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [] if self.reason.toPlainText().strip() else [tr("Motif")]

    def values(self):
        return {"last_date": self.last_date.date().toPython(), "reason": self.reason.toPlainText().strip()}


class RescheduleDialog(FormDialog, _TimesMixin):
    def __init__(self, slot, rooms, parent=None):
        super().__init__(
            tr("Reprogrammer le créneau"),
            tr("{0} · {1}. L'ancien créneau s'arrête la veille, un nouveau commence.", slot.code, slot.when),
            parent,
            save_text=tr("Reprogrammer"),
        )
        self.from_date = self.add_field("from_date", tr("À partir du"), date_field(), required=True, width="short")
        self.from_date.setDate(QDate.currentDate())
        self.weekday = self.add_field(
            "weekday", tr("Jour"), _weekday_combo(), required=True, width="short", beside=True
        )
        self.weekday.setCurrentIndex(max(0, self.weekday.findData(slot.weekday)))
        self.start_time = self.add_field(
            "start", tr("Début"), time_field(_qtime(slot.start_time)), required=True, width="short"
        )
        self.end_time = self.add_field(
            "end", tr("Fin"), time_field(_qtime(slot.end_time)), required=True, width="short", beside=True
        )
        self.room = self.add_field("room", tr("Salle"), _rooms_combo(rooms, tr(MAIN_ROOM)), width="medium")
        self.room.setCurrentIndex(max(0, self.room.findData(slot.room_id)))
        self.reason = self.add_field("reason", tr("Motif"), _reason(), required=True)
        for signal in (self.reason.textChanged, self.start_time.timeChanged, self.end_time.timeChanged):
            signal.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = [] if self.reason.toPlainText().strip() else [tr("Motif")]
        if not self._times_ok():
            missing.append(tr("une heure de fin après le début"))
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
            tr("Générer les séances"),
            tr(
                "Crée les séances des créneaux publiés sur la période (vacances exclues, séances existantes "
                "conservées)."
            ),
            parent,
            save_text=tr("Générer"),
        )
        self.date_from = self.add_field("date_from", tr("Du"), date_field(), required=True, width="short")
        self.date_to = self.add_field("date_to", tr("Au"), date_field(), required=True, width="short", beside=True)
        self.date_from.setDate(_qdate(monday))
        self.date_to.setDate(_qdate(monday + timedelta(days=6)))
        school_class = QComboBox()
        school_class.addItem(tr("Toutes les classes"), None)
        for item in classes:
            school_class.addItem(item.name, item.id)
        self.school_class = self.add_field("school_class", tr("Classe"), school_class, width="medium")
        for signal in (self.date_from.dateChanged, self.date_to.dateChanged):
            signal.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [] if self.date_to.date() >= self.date_from.date() else [tr("une date de fin après le début")]

    def values(self):
        return {
            "date_from": self.date_from.date().toPython(),
            "date_to": self.date_to.date().toPython(),
            "class_id": self.school_class.currentData(),
        }


class MoveDialog(FormDialog, _TimesMixin):
    def __init__(self, session, parent=None):
        super().__init__(
            tr("Déplacer la séance"),
            tr(
                "{0} · {1:%d/%m/%Y} {2}. Les conflits sont vérifiés par le serveur.",
                session.code,
                session.date,
                session.hours,
            ),
            parent,
            save_text=tr("Déplacer"),
        )
        self.day = self.add_field("day", tr("Nouvelle date"), date_field(), required=True, width="short")
        self.day.setDate(_qdate(session.date))
        self.start_time = self.add_field(
            "start",
            tr("Début"),
            time_field(QTime(session.start.hour, session.start.minute)),
            required=True,
            width="short",
            beside=True,
        )
        self.end_time = self.add_field(
            "end",
            tr("Fin"),
            time_field(QTime(session.end.hour, session.end.minute)),
            required=True,
            width="short",
            beside=True,
        )
        self.reason = self.add_field("reason", tr("Motif"), _reason(), required=True)
        for signal in (self.reason.textChanged, self.start_time.timeChanged, self.end_time.timeChanged):
            signal.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = [] if self.reason.toPlainText().strip() else [tr("Motif")]
        if not self._times_ok():
            missing.append(tr("une heure de fin après le début"))
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
            tr("Changer de salle"),
            tr(
                "{0} · {1:%d/%m/%Y} {2} · salle actuelle : {3}",
                session.code,
                session.date,
                session.hours,
                session.room_code or "—",
            ),
            parent,
            save_text=tr("Changer de salle"),
        )
        self.room = self.add_field("room", tr("Nouvelle salle"), _rooms_combo(rooms, tr(NO_ROOM)), width="medium")
        self.room.setCurrentIndex(max(0, self.room.findData(session.room_id)))
        self.reason = self.add_field("reason", tr("Motif"), _reason(), required=True)
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [] if self.reason.toPlainText().strip() else [tr("Motif")]

    def values(self):
        return {"room_id": self.room.currentData(), "reason": self.reason.toPlainText().strip()}


class SubstituteDialog(FormDialog):
    def __init__(self, session, teachers, parent=None):
        super().__init__(
            tr("Remplacer l'enseignant"),
            tr(
                "{0} · {1:%d/%m/%Y} {2}. Enseignant prévu : {3}. Le serveur vérifie compatibilité et disponibilité.",
                session.code,
                session.date,
                session.hours,
                session.planned_teacher_name,
            ),
            parent,
            save_text=tr("Remplacer"),
        )
        teacher = QComboBox()
        teacher.addItem(tr("Choisir un remplaçant…"), None)
        for item in teachers:
            if item.id != session.teacher_id:
                teacher.addItem(f"{item.name} ({item.number})", item.id)
        self.teacher = self.add_field("teacher", tr("Remplaçant"), teacher, required=True, width="medium")
        self.reason = self.add_field("reason", tr("Motif"), _reason(), required=True)
        self.teacher.currentIndexChanged.connect(self.refresh_state)
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        if not hasattr(self, "reason"):
            return []
        missing = [] if self.teacher.currentData() else [tr("Remplaçant")]
        if not self.reason.toPlainText().strip():
            missing.append(tr("Motif"))
        return missing

    def values(self):
        return {"teacher_id": self.teacher.currentData(), "reason": self.reason.toPlainText().strip()}


def action_allowed(name, session, now=None):
    """What can be done with a session (the server re-checks every rule):
    planning changes while it is SCHEDULED; the teacher's presence once it is
    over — validated (payable) while not yet validated, or marked not taught
    (also after a validation, as a correction)."""
    if name in ("validate", "reject"):
        if session.end is None or session.status == "CANCELLED":
            return False
        over = session.end <= (now or datetime.now(session.end.tzinfo))
        return over and (session.status == "SCHEDULED" if name == "validate" else True)
    return session.status == "SCHEDULED" and (name != "restore" or session.is_substituted)


class SessionDialog(FormDialog):
    """Record of a session; buttons close it with `action` set."""

    ACTIONS = Tr(
        (
            ("move", "Déplacer…"),
            ("room", "Changer de salle…"),
            ("substitute", "Remplacer l'enseignant…"),
            ("restore", "Restaurer l'enseignant prévu…"),
            ("cancel", "Annuler la séance…"),
            ("validate", "Valider la présence de l'enseignant…"),
            ("reject", "Séance non assurée…"),
        )
    )

    def __init__(self, session, parent=None):
        super().__init__(tr("Séance — {0}", session.code), "", parent, save_text=tr("Fermer"), width=560)
        self.action = None
        self.cancel_button.hide()
        self.add_section(tr("Séance"))
        self.body.addWidget(
            _grid(
                [
                    (tr("Matière"), f"{session.subject_code} — {session.subject_name}"),
                    (tr("Classe"), session.class_name),
                    (tr("Date"), f"{session.date:%d/%m/%Y}" if session.date else "—"),
                    (tr("Heure"), session.hours),
                    (tr("Salle"), session.room_code or "—"),
                    (tr("Enseignant prévu"), session.planned_teacher_name),
                    (tr("Enseignant réel"), session.teacher_name),
                    (tr("Statut"), session.status_label),
                ]
            )
        )
        self.add_section(tr("Actions"))
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.buttons = {}
        scheduled = session.status == "SCHEDULED"
        for index, (name, text) in enumerate(self.ACTIONS):
            widget = button(text, "danger" if name in ("cancel", "reject") else "secondary")
            widget.setEnabled(action_allowed(name, session))
            widget.clicked.connect(lambda _=False, n=name: self._start(n))
            grid.addWidget(widget, index // 2, index % 2)
            self.buttons[name] = widget
        self.body.addWidget(holder)
        if not scheduled:
            self.body.addWidget(QLabel(tr("Séance annulée ou réalisée : plus modifiable."), objectName="help"))
        elif not action_allowed("validate", session):
            self.body.addWidget(
                QLabel(tr("La présence de l'enseignant se valide une fois la séance terminée."), objectName="help")
            )
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
            tr("Modifier la salle") if editing else tr("Nouvelle salle"),
            tr("Salle de l'école utilisée par les créneaux et les séances."),
            parent,
        )
        self.code = self.add_field(
            "code", tr("Code"), QLineEdit(placeholderText=tr("Ex. R12"), maxLength=30), required=True, width="short"
        )
        self.name = self.add_field(
            "name",
            tr("Nom"),
            QLineEdit(placeholderText=tr("Ex. Salle 12"), maxLength=100),
            required=True,
            width="medium",
            beside=True,
        )
        room_type = QComboBox()
        for value, label in ROOM_TYPES.items():
            room_type.addItem(label, value)
        self.room_type = self.add_field("room_type", tr("Type"), room_type, width="medium")
        self.capacity = self.add_field(
            "capacity", tr("Capacité"), QLineEdit(placeholderText=tr("Ex. 40"), maxLength=4), width="short"
        )
        self.bench_count = self.add_field(
            "bench_count",
            tr("Bancs"),
            QLineEdit(placeholderText=tr("Facultatif"), maxLength=4),
            width="short",
            beside=True,
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
        return [label for field, label in ((self.code, tr("Code")), (self.name, tr("Nom"))) if not field.text().strip()]

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
            tr("Salle principale d'une classe"),
            tr("Salle utilisée par défaut par les créneaux de la classe. Le serveur vérifie la capacité."),
            parent,
            save_text=tr("Enregistrer"),
        )
        school_class = QComboBox()
        school_class.addItem(tr("Choisir une classe…"), None)
        for item in classes:
            school_class.addItem(tr("{0} — salle actuelle : {1}", item.name, item.main_room_label or "aucune"), item.id)
        self.school_class = self.add_field("school_class", tr("Classe"), school_class, required=True, width="long")
        self.room = self.add_field(
            "room", tr("Salle principale"), _rooms_combo(rooms, tr("Aucune salle principale")), width="medium"
        )
        self.school_class.currentIndexChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [] if self.school_class.currentData() else [tr("Classe")]

    def values(self):
        return {"class_id": self.school_class.currentData(), "room_id": self.room.currentData()}


# =============================================================================
# Availability requests, breaks
# =============================================================================


class DecisionDialog(FormDialog):
    """Decide a dated unavailability request; the impacted sessions listed
    are the server's (GET .../impacted-sessions/)."""

    DECISIONS = Tr(
        (("APPROVED", "Valider"), ("REJECTED", "Refuser"), ("CHANGES_REQUESTED", "Proposer une modification"))
    )

    def __init__(self, request, teacher_name, impacted, parent=None):
        super().__init__(
            tr("Décider de la demande"),
            f"{teacher_name} · {request.date:%d/%m/%Y} {request.start_time[:5]}–{request.end_time[:5]} · "
            f"« {request.reason} »",
            parent,
            save_text=tr("Enregistrer la décision"),
        )
        self.add_section(
            tr("Séances impactées"), tr("Calculées par le serveur ; elles restent à réorganiser après validation.")
        )
        if impacted:
            self.body.addWidget(
                _grid(
                    [
                        (f"{s.date:%d/%m}", tr("{0} · {1} · salle {2}", s.hours, s.code, s.room_code or "—"))
                        for s in impacted
                    ]
                )
            )
        else:
            self.body.addWidget(QLabel(tr("Aucune séance impactée."), objectName="help"))
        self.add_section(tr("Décision"))
        decision = QComboBox()
        for value, label in self.DECISIONS:
            decision.addItem(label, value)
        self.decision = self.add_field("decision", tr("Décision"), decision, required=True, width="medium")
        comment = QPlainTextEdit(placeholderText=tr("Commentaire pour l'enseignant (facultatif)"))
        comment.setFixedHeight(60)
        comment.setTabChangesFocus(True)
        self.comment = self.add_field("comment", tr("Commentaire"), comment)
        self.finish()

    def values(self):
        return {"decision": self.decision.currentData(), "comment": self.comment.toPlainText().strip() or None}


class BreakDialog(FormDialog):
    def __init__(self, years, parent=None, school_break=None):
        editing = school_break is not None
        super().__init__(
            tr("Modifier l'interruption") if editing else tr("Nouvelle interruption"),
            tr("Vacances, jours fériés, examens : la génération des séances les saute."),
            parent,
        )
        year = QComboBox()
        for item in years:
            year.addItem(item.short_label, item.id)
        self.year = self.add_field("academic_year", tr("Année scolaire"), year, required=True, width="medium")
        self.name = self.add_field(
            "name",
            tr("Nom"),
            QLineEdit(placeholderText=tr("Ex. Vacances de Noël"), maxLength=120),
            required=True,
            width="medium",
        )
        break_type = QComboBox()
        for value, label in BREAK_TYPES.items():
            break_type.addItem(label, value)
        self.break_type = self.add_field("break_type", tr("Type"), break_type, width="short", beside=True)
        self.start_day = self.add_field("start_day", tr("Début"), date_field(), required=True, width="short")
        self.start_time = self.add_field("start_time", tr("Heure"), time_field(QTime(0, 0)), width="short", beside=True)
        self.end_day = self.add_field("end_day", tr("Fin"), date_field(), required=True, width="short")
        self.end_time = self.add_field("end_time", tr("Heure"), time_field(QTime(23, 59)), width="short", beside=True)
        self.affects = self.add_field(
            "affects", tr("Planning"), QCheckBox(tr("Aucune séance générée pendant cette période"))
        )
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
        missing = [] if self.name.text().strip() else [tr("Nom")]
        if not self.year.currentData():
            missing.append(tr("Année scolaire"))
        if self._end() <= self._start():
            missing.append(tr("une fin après le début"))
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
