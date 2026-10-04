"""Course dialogs (ADR 0020), built on FormDialog (scrollable, fixed buttons).

    CourseDialog        add: Année → Classe → Matière → Enseignant ; edit: the
                        class, subject and year are fixed (server rule),
                        teacher / coefficient / hours / scale editable
    CourseRecordDialog  the record; « Modifier » closes it with action "edit"

The teacher list is the SERVER's list of eligible teachers for the chosen
class and subject (GET /courses/eligible-teachers/): `find_teachers(class_id,
subject_id, done)` asks it (off the UI thread, through the page). Teachers
the server excluded are listed with its reason; nothing is judged here.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QLineEdit, QWidget

from ..widgets import FormDialog, button

CHOOSE_YEAR = "Choisir une année scolaire…"
CHOOSE_CLASS = "Choisir une classe…"
CHOOSE_SUBJECT = "Choisir une matière…"
CHOOSE_TEACHER = "Choisir un enseignant…"
DEFAULT_SCALE = "Barème de la matière ou de l'école"
EXCLUSION_REASONS = {
    "teacher_inactive": "inactif",
    "teacher_not_qualified": "matière non validée",
    "incompatible_subject": "incompatible à ce niveau",
    "teacher_other_school": "autre école",
}


def _number_field(placeholder):
    field = QLineEdit(placeholderText=placeholder, maxLength=6)
    validator = QDoubleValidator(0.0, 999.99, 2, field)
    validator.setNotation(QDoubleValidator.StandardNotation)
    field.setValidator(validator)
    return field


class CourseDialog(FormDialog):
    def __init__(self, references, find_teachers, parent=None, course=None):
        years, classes, subjects, scales = references
        editing = course is not None
        super().__init__(
            "Modifier le cours" if editing else "Nouveau cours",
            "Un cours = une matière, un enseignant, une classe, pour l'année de la classe. "
            "Seuls les enseignants autorisés par le serveur sont proposés.",
            parent,
            width=600,
        )
        self.find_teachers = find_teachers
        self.classes = classes
        self.course = course
        self.excluded = []

        self.add_section("Classe et matière")
        year = QComboBox()
        year.addItem(CHOOSE_YEAR, None)
        for item in years:
            year.addItem(item.short_label, item.id)
        self.year = self.add_field("academic_year", "Année scolaire", year, required=True, width="medium")
        self.school_class = self.add_field(
            "school_class", "Classe", QComboBox(), required=True, width="medium", beside=True
        )
        subject = QComboBox()
        subject.addItem(CHOOSE_SUBJECT, None)
        for item in subjects:
            subject.addItem(f"{item.code} — {item.name}", item.id)
        self.subject = self.add_field("subject", "Matière", subject, required=True, width="medium")

        self.add_section("Enseignant", "Liste calculée par le serveur : actif, matière validée, compatible au niveau.")
        self.teacher = self.add_field("teacher", "Enseignant", QComboBox(), required=True, width="medium")
        self.teacher_hint = QLabel("", objectName="help")
        self.teacher_hint.setWordWrap(True)
        self.body.addWidget(self.teacher_hint)

        self.add_section("Évaluation")
        self.coefficient = self.add_field(
            "coefficient", "Coefficient", _number_field("Ex. 4"), width="short", help_text="Défaut : 1."
        )
        self.weekly_hours = self.add_field(
            "weekly_hours", "Heures / semaine", _number_field("Ex. 5"), width="short", beside=True
        )
        scale = QComboBox()
        scale.addItem(DEFAULT_SCALE, None)
        for item in scales:
            scale.addItem(f"{item['code']} — {item['label']}", item["id"])
        self.scale = self.add_field("scale", "Barème", scale, width="medium")

        if editing:
            if self.year.findData(course.year_id) < 0:  # e.g. a closed year: shown, not offered
                self.year.addItem(course.year_name, course.year_id)
            self.year.setCurrentIndex(self.year.findData(course.year_id))
            self._fill_classes()
            if self.school_class.findData(course.class_id) < 0:
                self.school_class.addItem(course.class_name, course.class_id)
            self.school_class.setCurrentIndex(self.school_class.findData(course.class_id))
            if self.subject.findData(course.subject_id) < 0:
                self.subject.addItem(course.subject_label, course.subject_id)
            self.subject.setCurrentIndex(self.subject.findData(course.subject_id))
            for combo in (self.year, self.school_class, self.subject):
                combo.setEnabled(False)  # a course's identity never changes
            self.coefficient.setText(course.coefficient)
            self.weekly_hours.setText(course.weekly_hours)
            self.scale.setCurrentIndex(max(0, self.scale.findData(course.scale_id)))
        else:
            self.year.setCurrentIndex(1 if years else 0)  # the current year comes first
            self._fill_classes()
        self.year.currentIndexChanged.connect(self._year_changed)
        self.school_class.currentIndexChanged.connect(self._reload_teachers)
        self.subject.currentIndexChanged.connect(self._reload_teachers)
        self.teacher.currentIndexChanged.connect(self.refresh_state)
        self.finish()
        self._reload_teachers()

    # --- cascade ----------------------------------------------------------------------
    def _fill_classes(self):
        year = self.year.currentData()
        self.school_class.blockSignals(True)
        self.school_class.clear()
        self.school_class.addItem(CHOOSE_CLASS, None)
        for item in self.classes:
            if item.year_id == year:
                self.school_class.addItem(item.name, item.id)
        self.school_class.blockSignals(False)

    def _year_changed(self, _index=None):
        self._fill_classes()
        self._reload_teachers()

    def _reload_teachers(self, _index=None):
        class_id, subject_id = self.school_class.currentData(), self.subject.currentData()
        self.teacher.clear()
        self.teacher.addItem(CHOOSE_TEACHER, None)
        self.teacher.setEnabled(False)
        if not (class_id and subject_id):
            self.teacher_hint.setText("Choisissez d'abord la classe et la matière.")
            self.refresh_state()
            return
        self.teacher_hint.setText("Recherche des enseignants autorisés…")
        self.find_teachers(class_id, subject_id, self.show_teachers)

    def show_teachers(self, result):
        eligible, excluded = result
        self.excluded = excluded
        self.teacher.blockSignals(True)
        self.teacher.clear()
        self.teacher.addItem(CHOOSE_TEACHER, None)
        for item in eligible:
            self.teacher.addItem(item.label, item.id)
        if self.course is not None:
            self.teacher.setCurrentIndex(max(0, self.teacher.findData(self.course.teacher_id)))
        self.teacher.blockSignals(False)
        self.teacher.setEnabled(bool(eligible))
        lines = [f"{len(eligible)} enseignant(s) autorisé(s) pour cette classe et cette matière."]
        if not eligible:
            lines = ["Aucun enseignant autorisé : ajoutez ou validez la qualification dans « Enseignants »."]
        if excluded:
            lines.append(
                "Non proposés : "
                + " ; ".join(f"{t.name} ({EXCLUSION_REASONS.get(t.reason, t.reason)})" for t in excluded)
                + "."
            )
        self.teacher_hint.setText("\n".join(lines))
        self.refresh_state()

    # --- state ----------------------------------------------------------------------------
    def missing_fields(self):
        if not hasattr(self, "teacher"):
            return []
        missing = []
        if not self.year.currentData():
            missing.append("Année scolaire")
        if not self.school_class.currentData():
            missing.append("Classe")
        if not self.subject.currentData():
            missing.append("Matière")
        if not self.teacher.currentData():
            missing.append("Enseignant")
        return missing

    def values(self):
        values = {
            "teacher_id": self.teacher.currentData(),
            "coefficient": self.coefficient.text().strip() or None,
            "weekly_hours": self.weekly_hours.text().strip() or None,
            "scale_id": self.scale.currentData(),
        }
        if self.course is None:
            values["class_id"] = self.school_class.currentData()
            values["subject_id"] = self.subject.currentData()
        return values


def _grid(pairs):
    widget = QWidget()
    grid = QGridLayout(widget)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(6)
    for index, (label, value) in enumerate(pairs):
        caption = QLabel(label, objectName="fieldLabel")
        text = QLabel(str(value), objectName="fieldValue")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(caption, index, 0, Qt.AlignTop)
        grid.addWidget(text, index, 1)
    grid.setColumnStretch(1, 1)
    return widget


class CourseRecordDialog(FormDialog):
    def __init__(self, course, parent=None):
        super().__init__(
            f"Fiche du cours — {course.subject_code} · {course.class_name}", "", parent, save_text="Fermer"
        )
        self.action = None
        self.cancel_button.hide()
        self.add_section("Cours")
        self.body.addWidget(
            _grid(
                [
                    ("Matière", course.subject_label),
                    ("Classe", course.class_name),
                    ("Niveau", course.level_code or "—"),
                    ("Année scolaire", course.year_name),
                    ("Statut", "Actif" if course.active else "Inactif"),
                ]
            )
        )
        self.add_section("Enseignant")
        self.body.addWidget(_grid([("Enseignant", f"{course.teacher_name} ({course.teacher_number})")]))
        self.add_section("Évaluation")
        self.body.addWidget(
            _grid(
                [
                    ("Coefficient", course.coefficient),
                    ("Heures / semaine", course.weekly_hours),
                    ("Barème", course.scale_label or DEFAULT_SCALE),
                ]
            )
        )
        self.add_section("Planning", "Le planning se gère dans son module ; il utilise ce cours tel quel.")
        self.body.addWidget(
            _grid(
                [
                    ("Créneaux en cours", "—" if course.published_slot_count is None else course.published_slot_count),
                    (
                        "Séances à venir",
                        "—" if course.upcoming_session_count is None else course.upcoming_session_count,
                    ),
                ]
            )
        )
        self.edit_button = button("Modifier le cours…")
        self.edit_button.clicked.connect(self._edit)
        self.body.addWidget(self.edit_button, 0, Qt.AlignLeft)
        self.finish(required_note=False)
        self.save_button.setFocus()

    def _edit(self):
        self.action = "edit"
        self.accept()
