"""Vie scolaire → Planning (ADR 0021): the admin face of the EXISTING planning
engine (Course, ScheduleSlot, TeachingSession, rooms, availability requests,
school breaks). Tabs:

    Semaine        week view of the sessions, filters, session actions
    Créneaux       recurring slots: new (with server conflict check), end, reschedule
    Salles         rooms: add, edit, (de)activate, main room of a class
    Disponibilités teachers' unavailability requests: impacted sessions, decision
    Vacances       school breaks: list, add, edit

Every rule (conflicts, compatibility, availability, breaks) is the server's:
the screens send requests and show the answers (409 conflicts explained).
"""

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
)

from ...models import BREAK_TYPES, REQUEST_STATUSES, ROOM_TYPES
from ...services.planning import monday_of
from ..dialogs.planning_dialogs import (
    BreakDialog,
    DecisionDialog,
    EndSlotDialog,
    GenerateDialog,
    MainRoomDialog,
    MoveDialog,
    RescheduleDialog,
    RoomChangeDialog,
    RoomDialog,
    SessionDialog,
    SlotDialog,
    SubstituteDialog,
)
from ..dialogs.teacher_dialogs import ask_reason
from ..theme import TOKENS
from ..week_view import LEGEND, STYLES, WeekView, style_key
from ..widgets import Page, button
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage

ALL = {
    "class": "Classe : toutes",
    "teacher": "Enseignant : tous",
    "room": "Salle : toutes",
    "subject": "Matière : toutes",
}


def _combo(name, first, width):
    combo = QComboBox()
    combo.setAccessibleName(name)
    combo.setToolTip(name)
    combo.setMinimumWidth(width)
    combo.addItem(first, None)
    return combo


def _refill(combo, first, items):
    chosen = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(first, None)
    for label, value in items:
        combo.addItem(label, value)
    combo.setCurrentIndex(max(0, combo.findData(chosen)))
    combo.blockSignals(False)


# =============================================================================
# Week
# =============================================================================


class WeekPage(Page):
    """Week of sessions. Session actions go through dialogs; `ask(kind, **ctx)`
    is overridable in tests."""

    title = "Semaine"

    def __init__(self, planning, references, teachers, subjects, courses, runner, parent=None, *, today=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.planning, self.references, self.teachers, self.subjects, self.courses = (
            planning,
            references,
            teachers,
            subjects,
            courses,
        )
        self.today = today or date.today
        self.monday = monday_of(self.today())
        self.sessions = []
        self.lists = {"rooms": [], "teachers": [], "classes": []}
        self._ready = False

        top = QHBoxLayout()
        self.previous_button = button("‹ Semaine précédente")
        self.today_button = button("Aujourd'hui")
        self.next_button = button("Semaine suivante ›")
        self.week_label = QLabel("", objectName="weekLabel")
        top.addWidget(self.week_label, 1)
        for widget in (self.previous_button, self.today_button, self.next_button):
            top.addWidget(widget)
        self.layout_.addLayout(top)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.class_filter = _combo("Filtrer par classe", ALL["class"], 140)
        self.teacher_filter = _combo("Filtrer par enseignant", ALL["teacher"], 160)
        self.room_filter = _combo("Filtrer par salle", ALL["room"], 130)
        self.subject_filter = _combo("Filtrer par matière", ALL["subject"], 140)
        for combo in (self.class_filter, self.teacher_filter, self.room_filter, self.subject_filter):
            filters.addWidget(combo, 1)
            combo.currentIndexChanged.connect(lambda _: self._ready and self.reload())
        self.layout_.addLayout(filters)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.generate_button = button("Générer les séances…", "primary")
        self.slot_button = button("Nouveau créneau…")
        self.session_button = button("Séance ▾")
        self.session_button.setToolTip("Actions sur la séance sélectionnée")
        self.view_button = button("Afficher la liste")
        for widget in (self.generate_button, self.slot_button, self.session_button):
            actions.addWidget(widget)
        actions.addStretch()
        actions.addWidget(self.view_button)
        self.layout_.addLayout(actions)
        self.layout_.addWidget(self.banner)

        legend = QHBoxLayout()
        legend.setSpacing(6)
        for label, key in LEGEND:
            chip = QLabel(label, objectName="legendChip")
            background, border, _ = STYLES[key]
            chip.setStyleSheet(f"background: {background}; border: 1px solid {border};")
            legend.addWidget(chip)
        legend.addStretch()
        self.count_label = QLabel("", objectName="countLabel")
        legend.addWidget(self.count_label)
        self.layout_.addLayout(legend)

        self.week = WeekView()
        scroll = QScrollArea(objectName="pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.week)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Date", "Heure", "Matière", "Classe", "Salle", "Enseignant", "Statut"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.stack = QStackedWidget()
        self.stack.addWidget(scroll)
        self.stack.addWidget(self.table)
        self.layout_.addWidget(self.stack, 1)

        self.previous_button.clicked.connect(lambda: self.go(-7))
        self.next_button.clicked.connect(lambda: self.go(7))
        self.today_button.clicked.connect(self.go_today)
        self.generate_button.clicked.connect(self.generate)
        self.slot_button.clicked.connect(self.new_slot)
        self.view_button.clicked.connect(self.toggle_view)
        self.week.selected.connect(lambda _: self._update_actions())
        self.week.activated.connect(lambda session: self.open_session(session))
        self.table.itemSelectionChanged.connect(self._table_selected)
        self.table.doubleClicked.connect(lambda _: self.current() and self.open_session(self.current()))
        menu = QMenu(self)
        for name, text in SessionDialog.ACTIONS:
            menu.addAction(text, lambda n=name: self.session_action(n))
        self.session_button.setMenu(menu)
        self._update_actions()

    # --- data ---------------------------------------------------------------------------
    def activate(self):
        self.call(self._load_lists, self._fill_filters, action="Impossible de charger les listes du planning")

    def _load_lists(self):
        return {
            "classes": self.references.classes(),
            "teachers": self.teachers.all(status="active"),
            "rooms": self.planning.rooms(active=True),
            "subjects": self.subjects.list(active=True),
        }

    def _fill_filters(self, lists):
        self.lists = lists
        self._ready = False
        _refill(self.class_filter, ALL["class"], [(c.name, c.id) for c in lists["classes"]])
        _refill(self.teacher_filter, ALL["teacher"], [(f"{t.name} ({t.number})", t.id) for t in lists["teachers"]])
        _refill(self.room_filter, ALL["room"], [(r.label, r.id) for r in lists["rooms"]])
        _refill(self.subject_filter, ALL["subject"], [(f"{s.code} — {s.name}", s.id) for s in lists["subjects"]])
        self._ready = True
        self.reload()

    def reload(self):
        monday = self.monday
        self.call(
            lambda: self.planning.week(
                monday,
                class_id=self.class_filter.currentData(),
                teacher_id=self.teacher_filter.currentData(),
                room_id=self.room_filter.currentData(),
                subject_id=self.subject_filter.currentData(),
            ),
            self.show_sessions,
            action="Impossible de charger les séances",
        )

    def show_sessions(self, sessions):
        self.sessions = sessions
        end = self.monday + timedelta(days=6)
        self.week_label.setText(f"Semaine du {self.monday:%d/%m} au {end:%d/%m/%Y}")
        self.week.set_week(self.monday, sessions)
        self.count_label.setText(f"{len(sessions)} séance{'s' if len(sessions) > 1 else ''}")
        self.table.setRowCount(len(sessions))
        for row, session in enumerate(sorted(sessions, key=lambda s: (s.start or s.date, s.class_name))):
            cells = [
                f"{session.date:%a %d/%m}" if session.date else "",
                session.hours,
                f"{session.subject_code} — {session.subject_name}",
                session.class_name,
                session.room_code or "—",
                session.teacher_name + (f" (prévu : {session.planned_teacher_name})" if session.is_substituted else ""),
                session.status_label,
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, session.id)
                item.setToolTip(text)
                if column == 6:
                    item.setForeground(QBrush(QColor(STYLES[style_key(session)][1])))
                    font = QFont()
                    font.setStrikeOut(session.status == "CANCELLED")
                    item.setFont(font)
                self.table.setItem(row, column, item)
        self._update_actions()

    def go(self, days):
        self.monday += timedelta(days=days)
        self.reload()

    def go_today(self):
        self.monday = monday_of(self.today())
        self.reload()

    def toggle_view(self):
        showing_list = self.stack.currentWidget() is self.table
        self.stack.setCurrentIndex(0 if showing_list else 1)
        self.view_button.setText("Afficher la liste" if showing_list else "Afficher la semaine")

    # --- selection ------------------------------------------------------------------------
    def current(self):
        if self.stack.currentWidget() is self.table:
            items = self.table.selectedItems()
            session_id = items[0].data(Qt.UserRole) if items else None
            return next((s for s in self.sessions if s.id == session_id), None)
        return self.week.current

    def _table_selected(self):
        session = self.current()
        if session is not None:
            self.week.current = session
        self._update_actions()

    def select(self, session_id):
        session = next((s for s in self.sessions if s.id == session_id), None)
        self.week.select(session)

    def _update_actions(self):
        session = self.current()
        self.session_button.setEnabled(session is not None and not self.busy)
        self.session_button.setToolTip(
            "Sélectionnez d'abord une séance (clic dans la semaine)." if session is None else session.code
        )
        if session is not None:
            for action, (name, _text) in zip(self.session_button.menu().actions(), SessionDialog.ACTIONS, strict=False):
                action.setEnabled(session.status == "SCHEDULED" and (name != "restore" or session.is_substituted))

    def set_busy(self, busy):
        super().set_busy(busy)
        if hasattr(self, "generate_button"):
            for widget in (self.generate_button, self.slot_button, self.previous_button, self.next_button):
                widget.setEnabled(not busy)
            self._update_actions()

    # --- dialogs (overridable in tests) --------------------------------------------------
    def ask(self, kind, **context):
        factories = {
            "session": lambda: SessionDialog(context["session"], self),
            "generate": lambda: GenerateDialog(self.lists["classes"], self.monday, self),
            "move": lambda: MoveDialog(context["session"], self),
            "room": lambda: RoomChangeDialog(context["session"], self.lists["rooms"], self),
            "substitute": lambda: SubstituteDialog(context["session"], self.lists["teachers"], self),
            "slot": lambda: SlotDialog(context["courses"], self.lists["rooms"], self.check_slot, self),
        }
        if kind in ("cancel", "restore"):
            title = "Annuler la séance ?" if kind == "cancel" else "Restaurer l'enseignant prévu ?"
            return ask_reason(
                self,
                title,
                f"{context['session'].code} · {context['session'].date:%d/%m/%Y} {context['session'].hours}",
                save_text="Annuler la séance" if kind == "cancel" else "Restaurer",
                danger=kind == "cancel",
            )
        dialog = factories[kind]()
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.action if kind == "session" else dialog.values()

    def check_slot(self, payload, done):
        self.call(lambda: self.planning.check_slot(**payload), done, action="Impossible de vérifier les conflits")

    # --- actions ----------------------------------------------------------------------------
    def open_session(self, session):
        action = self.ask("session", session=session)
        if action:
            self.session_action(action, session)

    def session_action(self, name, session=None):
        session = session or self.current()
        if session is None:
            return
        values = self.ask(name, session=session)
        if not values:
            return
        calls = {
            "cancel": (
                lambda: self.planning.cancel(session.id, values["reason"]),
                "Séance annulée.",
                "Impossible d'annuler la séance",
            ),
            "move": (
                lambda: self.planning.move(session.id, **values),
                "Séance déplacée.",
                "Impossible de déplacer la séance",
            ),
            "room": (
                lambda: self.planning.change_room(session.id, values["room_id"], values["reason"]),
                "Salle de la séance modifiée.",
                "Impossible de changer la salle",
            ),
            "substitute": (
                lambda: self.planning.substitute(session.id, values["teacher_id"], values["reason"]),
                "Enseignant remplacé pour cette séance.",
                "Impossible de remplacer l'enseignant",
            ),
            "restore": (
                lambda: self.planning.restore_teacher(session.id, values["reason"]),
                "Enseignant prévu restauré.",
                "Impossible de restaurer l'enseignant",
            ),
        }
        fn, message, action = calls[name]
        self.call(fn, lambda saved: self._done(saved, message), action=action)

    def _done(self, saved, message):
        self.success(message)
        if saved.date and monday_of(saved.date) != self.monday:  # moved to another week: follow it
            self.monday = monday_of(saved.date)
        self.call(
            lambda: self.planning.week(
                self.monday,
                class_id=self.class_filter.currentData(),
                teacher_id=self.teacher_filter.currentData(),
                room_id=self.room_filter.currentData(),
                subject_id=self.subject_filter.currentData(),
            ),
            lambda sessions: (self.show_sessions(sessions), self.select(saved.id)),
            action="Impossible de charger les séances",
        )

    def generate(self):
        values = self.ask("generate")
        if values:
            self.call(
                lambda: self.planning.generate(**values), self._generated, action="Impossible de générer les séances"
            )

    def _generated(self, summary):
        parts = [f"{summary.get('created', 0)} séance(s) créée(s)", f"{summary.get('existing', 0)} déjà présente(s)"]
        if summary.get("in_break"):
            parts.append(f"{summary['in_break']} pendant les vacances")
        conflicts = summary.get("conflicts") or []
        text = ", ".join(parts) + "."
        if conflicts:
            self.banner.show_message(
                "warning", f"{text} {len(conflicts)} séance(s) non créée(s) à cause d'un conflit.", title="Génération"
            )
        else:
            self.success(text)
        self.reload()

    def new_slot(self):
        def open_form(courses):
            values = self.ask("slot", courses=courses)
            if values:
                self.call(
                    lambda: self.planning.create_slot(**values),
                    lambda slot: (self.success(f"Créneau créé : {slot.code} · {slot.when}."), self.reload()),
                    action="Impossible de créer le créneau",
                )

        self.call(lambda: self.courses.all(status="active"), open_form, action="Impossible de charger les cours")


# =============================================================================
# Slots
# =============================================================================


class SlotsPage(CatalogPage):
    title = "Créneaux"
    description = "Cours répétés chaque semaine. Terminer ou reprogrammer garde l'historique."
    columns = ["Matière", "Classe", "Enseignant", "Jour et heures", "Salle", "Période", STATUS_COLUMN_TITLE]
    noun = "créneau"
    plural_noun = "créneaux"
    feminine = False
    search_placeholder = "Rechercher par matière, classe ou enseignant…"
    status_filters = [("Publiés", "PUBLISHED"), ("Archivés", "ARCHIVED")]
    has_toggle = False

    def __init__(self, planning, references, teachers, courses, runner, parent=None, week=None, **kwargs):
        self.planning, self.references, self.teachers, self.courses = planning, references, teachers, courses
        self.week_page = week
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.end_button.clicked.connect(self.end_slot)
        self.reschedule_button.clicked.connect(self.reschedule)

    def stretch_columns(self):
        return {0, 2}

    def extra_actions(self):
        self.end_button = button("Terminer…", "danger")
        self.reschedule_button = button("Reprogrammer…")
        return [self.reschedule_button, self.end_button]

    def add_filters(self, layout):
        self.class_filter = _combo("Filtrer par classe", ALL["class"], 140)
        self.teacher_filter = _combo("Filtrer par enseignant", ALL["teacher"], 150)
        for combo in (self.class_filter, self.teacher_filter):
            combo.currentIndexChanged.connect(lambda _: self.reload())
            layout.addWidget(combo)

    def update_extra_actions(self, row):
        if hasattr(self, "end_button"):
            for widget in (self.end_button, self.reschedule_button):
                widget.setEnabled(row is not None and row.active)
                widget.setToolTip("Sélectionnez un créneau publié." if row is None or not row.active else "")

    def status_cell(self, row):
        item = QTableWidgetItem("●  Publié" if row.active else "○  Archivé")
        item.setForeground(QBrush(QColor(TOKENS.success if row.active else TOKENS.text_secondary)))
        return item

    def activate(self):
        self.call(
            lambda: (self.references.classes(), self.teachers.all(status="active")),
            self._fill,
            action="Impossible de charger les classes et les enseignants",
        )

    def _fill(self, lists):
        classes, teachers = lists
        _refill(self.class_filter, ALL["class"], [(c.name, c.id) for c in classes])
        _refill(self.teacher_filter, ALL["teacher"], [(f"{t.name} ({t.number})", t.id) for t in teachers])
        self.reload()

    def fetch(self):
        rows = self.planning.slots(
            status=self.status.currentData(),
            class_id=self.class_filter.currentData(),
            teacher_id=self.teacher_filter.currentData(),
        )
        search = self.search.text().strip().lower()
        if search:  # narrowing what is displayed (not a rule)
            rows = [
                r
                for r in rows
                if search in f"{r.subject_code} {r.subject_name} {r.class_name} {r.teacher_name}".lower()
            ]
        return rows

    def cells(self, row):
        period = f"{row.effective_from:%d/%m/%Y} → " + (
            f"{row.effective_to:%d/%m/%Y}" if row.effective_to else "fin d'année"
        )
        return [
            f"{row.subject_code} — {row.subject_name}",
            row.class_name,
            row.teacher_name,
            (row.when, (row.weekday, row.start_time)),
            row.room_code or "—",
            period if row.effective_from else "—",
            "",
        ]

    def describe_row(self, row):
        return f"{row.code} · {row.when}"

    def ask(self, kind, **context):
        if kind == "end":
            dialog = EndSlotDialog(context["slot"], self)
        elif kind == "reschedule":
            dialog = RescheduleDialog(context["slot"], context["rooms"], self)
        else:
            dialog = SlotDialog(context["courses"], context["rooms"], self.check_slot, self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def check_slot(self, payload, done):
        self.call(lambda: self.planning.check_slot(**payload), done, action="Impossible de vérifier les conflits")

    def add(self):
        def open_form(lists):
            courses, rooms = lists
            values = self.ask("new", courses=courses, rooms=rooms)
            if values:
                self.call(
                    lambda: self.planning.create_slot(**values),
                    lambda slot: self._saved(slot, "créé"),
                    action="Impossible de créer le créneau",
                )

        self.call(
            lambda: (self.courses.all(status="active"), self.planning.rooms(active=True)),
            open_form,
            action="Impossible de charger les cours et les salles",
        )

    def end_slot(self):
        row = self.selected()
        if row is None:
            return
        values = self.ask("end", slot=row)
        if values:
            self.call(
                lambda: self.planning.end_slot(row.id, **values),
                lambda slot: self._saved(slot, "terminé"),
                action="Impossible de terminer le créneau",
            )

    def reschedule(self):
        row = self.selected()
        if row is None:
            return

        def open_form(rooms):
            values = self.ask("reschedule", slot=row, rooms=rooms)
            if values:
                self.call(
                    lambda: self.planning.reschedule_slot(row.id, **values),
                    lambda slot: self._saved(slot, "reprogrammé"),
                    action="Impossible de reprogrammer le créneau",
                )

        self.call(lambda: self.planning.rooms(active=True), open_form, action="Impossible de charger les salles")

    def _saved(self, saved, verb):
        self.success(f"Créneau « {saved.code} · {saved.when} » {verb}.")
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action="Impossible de charger les créneaux",
        )


# =============================================================================
# Rooms
# =============================================================================


class RoomsPage(CatalogPage):
    title = "Salles"
    description = "Salles de l'école. Une salle utilisée par le planning à venir ne peut pas être désactivée."
    columns = ["Code", "Nom", "Type", "Capacité", "Bancs", STATUS_COLUMN_TITLE]
    noun = "salle"

    def __init__(self, planning, references, runner, parent=None, **kwargs):
        self.planning, self.references = planning, references
        super().__init__(runner, parent, **kwargs)
        self.main_room_button.clicked.connect(self.main_room)

    def extra_actions(self):
        self.main_room_button = button("Salle principale d'une classe…")
        return [self.main_room_button]

    def fetch(self):
        return self.planning.rooms(search=self.search.text(), active=self.status.currentData())

    def cells(self, row):
        return [
            row.code,
            row.name,
            ROOM_TYPES.get(row.room_type, row.room_type),
            (str(row.capacity) if row.capacity else "—", row.capacity or 0),
            ("—" if row.bench_count is None else str(row.bench_count), row.bench_count or 0),
            "",
        ]

    def ask(self, kind, **context):
        if kind == "main_room":
            dialog = MainRoomDialog(context["classes"], context["rooms"], self)
        else:
            dialog = RoomDialog(self, context.get("room"))
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        values = self.ask("room")
        if values:
            self.call(
                lambda: self.planning.create_room(**values),
                lambda r: self._saved(r, "créée"),
                action="Impossible de créer la salle",
            )

    def edit(self):
        row = self.selected()
        if row is None:
            return
        values = self.ask("room", room=row)
        if values:
            values.pop("code")  # the code never changes (server rule code_immutable)
            self.call(
                lambda: self.planning.update_room(row.id, **values),
                lambda r: self._saved(r, "modifiée"),
                action="Impossible de modifier la salle",
            )

    def deactivate(self, row_id):
        return self.planning.deactivate(row_id)

    def reactivate(self, row_id):
        return self.planning.reactivate(row_id)

    def main_room(self):
        def open_form(lists):
            classes, rooms = lists
            values = self.ask("main_room", classes=classes, rooms=rooms)
            if values:
                self.call(
                    lambda: self.planning.set_main_room(values["class_id"], values["room_id"]),
                    lambda _: self.success("Salle principale enregistrée."),
                    action="Impossible de définir la salle principale",
                )

        self.call(
            lambda: (self.references.classes(), self.planning.rooms(active=True)),
            open_form,
            action="Impossible de charger les classes et les salles",
        )


# =============================================================================
# Availability requests
# =============================================================================


class RequestsPage(CatalogPage):
    title = "Disponibilités"
    description = "Demandes d'absence datées des enseignants : séances impactées et décision de l'administration."
    columns = ["Enseignant", "Date", "Horaire", "Motif", STATUS_COLUMN_TITLE]
    noun = "demande"
    search_placeholder = "Rechercher par enseignant ou motif…"
    status_filters = [(label, value) for value, label in REQUEST_STATUSES.items()]
    has_toggle = False

    def __init__(self, planning, teachers, runner, parent=None, **kwargs):
        self.planning, self.teachers = planning, teachers
        self.names = {}
        super().__init__(runner, parent, **kwargs)
        self.add_button.hide()
        self.edit_button.hide()
        self.impacted_button.clicked.connect(self.show_impacted)
        self.decide_button.clicked.connect(self.decide)

    def stretch_columns(self):
        return {0, 3}

    def extra_actions(self):
        self.impacted_button = button("Séances impactées")
        self.decide_button = button("Décider…", "primary")
        return [self.impacted_button, self.decide_button]

    def update_extra_actions(self, row):
        if hasattr(self, "decide_button"):
            self.impacted_button.setEnabled(row is not None)
            self.decide_button.setEnabled(row is not None and row.status in ("PENDING", "CHANGES_REQUESTED"))

    def status_cell(self, row):
        item = QTableWidgetItem(REQUEST_STATUSES.get(row.status, row.status))
        colour = {"PENDING": TOKENS.warning, "APPROVED": TOKENS.success}.get(row.status, TOKENS.text_secondary)
        item.setForeground(QBrush(QColor(colour)))
        return item

    def fetch(self):
        if not self.names:
            self.names = {t.id: f"{t.name} ({t.number})" for t in self.teachers.all(status=None)}
        rows = self.planning.requests(status=self.status.currentData())
        search = self.search.text().strip().lower()
        if search:
            rows = [r for r in rows if search in f"{self.names.get(r.teacher_id, '')} {r.reason}".lower()]
        return rows

    def cells(self, row):
        return [
            self.names.get(row.teacher_id, "?"),
            (f"{row.date:%d/%m/%Y}", row.date.isoformat() if row.date else ""),
            f"{row.start_time[:5]}–{row.end_time[:5]}",
            row.reason,
            "",
        ]

    def describe_row(self, row):
        return f"{self.names.get(row.teacher_id, '?')} · {row.code}"

    def ask(self, kind, **context):
        dialog = DecisionDialog(context["request"], context["teacher"], context["impacted"], self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def show_impacted(self):
        row = self.selected()
        if row is None:
            return

        def show(sessions):
            text = " ; ".join(f"{s.date:%d/%m} {s.hours} {s.code}" for s in sessions) or "aucune séance"
            self.banner.show_message("info", text, title=f"Séances impactées ({len(sessions)})")

        self.call(lambda: self.planning.impacted(row.id), show, action="Impossible de charger les séances impactées")

    def decide(self):
        row = self.selected()
        if row is None:
            return

        def open_form(impacted):
            values = self.ask("decide", request=row, teacher=self.names.get(row.teacher_id, "?"), impacted=impacted)
            if values:
                self.call(
                    lambda: self.planning.decide(row.id, values["decision"], values["comment"]),
                    lambda answer: self._decided(answer),
                    action="Impossible d'enregistrer la décision",
                )

        self.call(
            lambda: self.planning.impacted(row.id), open_form, action="Impossible de charger les séances impactées"
        )

    def _decided(self, answer):
        request, impacted = answer
        label = REQUEST_STATUSES.get(request.status, request.status).lower()
        extra = f" {len(impacted)} séance(s) à réorganiser." if impacted and request.status == "APPROVED" else ""
        self.success(f"Demande {label}.{extra}")
        self.reload()


# =============================================================================
# Breaks
# =============================================================================


class BreaksPage(CatalogPage):
    title = "Vacances et interruptions"
    description = "Périodes sans cours : la génération des séances les saute."
    columns = ["Nom", "Type", "Début", "Fin", STATUS_COLUMN_TITLE]
    noun = "interruption"
    search_placeholder = "Rechercher une période…"
    status_filters = [("Toutes", None)]
    has_toggle = False

    def __init__(self, planning, references, runner, parent=None, **kwargs):
        self.planning, self.references = planning, references
        super().__init__(runner, parent, **kwargs)
        self.status.hide()

    def status_cell(self, row):
        item = QTableWidgetItem("●  Bloque le planning" if row.affects_scheduling else "○  Informatif")
        item.setForeground(QBrush(QColor(TOKENS.text if row.affects_scheduling else TOKENS.text_secondary)))
        return item

    def fetch(self):
        rows = self.planning.breaks()
        search = self.search.text().strip().lower()
        return [r for r in rows if search in r.name.lower()] if search else rows

    def cells(self, row):
        return [
            row.name,
            BREAK_TYPES.get(row.break_type, row.break_type),
            (f"{row.start:%d/%m/%Y %H:%M}", row.start.isoformat()),
            (f"{row.end:%d/%m/%Y %H:%M}", row.end.isoformat()),
            "",
        ]

    def ask(self, years, school_break=None):
        dialog = BreakDialog(years, self, school_break)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        def open_form(years):
            values = self.ask(years)
            if values:
                self.call(
                    lambda: self.planning.create_break(**values),
                    lambda b: self._saved(b, "créée"),
                    action="Impossible de créer l'interruption",
                )

        self.call(lambda: self.references.years(open_only=True), open_form, action="Impossible de charger les années")

    def edit(self):
        row = self.selected()
        if row is None:
            return

        def open_form(years):
            values = self.ask(years, row)
            if values:
                values.pop("year_id")
                self.call(
                    lambda: self.planning.update_break(row.id, **values),
                    lambda b: self._saved(b, "modifiée"),
                    action="Impossible de modifier l'interruption",
                )

        self.call(lambda: self.references.years(), open_form, action="Impossible de charger les années")


# =============================================================================
# The page
# =============================================================================


class PlanningPage(Page):
    title = "Planning"

    def __init__(self, planning, references, teachers, subjects, courses, runner, parent=None, *, today=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.layout_.setContentsMargins(0, 8, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.week = WeekPage(planning, references, teachers, subjects, courses, runner, today=today, **kwargs)
        self.slots = SlotsPage(planning, references, teachers, courses, runner, **kwargs)
        self.rooms = RoomsPage(planning, references, runner, **kwargs)
        self.requests = RequestsPage(planning, teachers, runner, **kwargs)
        self.breaks = BreaksPage(planning, references, runner, **kwargs)
        for page, label in (
            (self.week, "Semaine"),
            (self.slots, "Créneaux"),
            (self.rooms, "Salles"),
            (self.requests, "Disponibilités"),
            (self.breaks, "Vacances"),
        ):
            self.tabs.addTab(page, label)
            page.session_expired.connect(self.session_expired.emit)
        self.layout_.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().activate())

    def activate(self):
        self.tabs.currentWidget().activate()

    def open_tab(self, name):
        page = getattr(self, name)
        self.tabs.setCurrentWidget(page)
        return page
