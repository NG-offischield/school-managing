"""Student dialogs (ADR 0018), all built on FormDialog (scrollable form,
fixed buttons, fits 1280×720):

    StudentDialog       add / edit: IDENTITÉ, PHOTO, INFORMATIONS
                        COMPLÉMENTAIRES, INSCRIPTION (optional, add only)
    EnrollDialog        enroll an existing student: année → niveau → classe
    ChangeClassDialog   another class of the SAME year (niveau → classe)
    StudentRecordDialog the record: identity, schooling, history; its
                        buttons tell the page which action to start

Years, levels and classes come from the API (never typed); the class list
follows the chosen year and level. The server re-checks everything (same
school, same year, open year, full class…).
"""

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QImage, QIntValidator, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QWidget,
)

from ...i18n import Labels, tr
from ...models import SEXES, STUDENT_STATUSES
from ...services.students import PHOTO_MAX_BYTES, PHOTO_TYPES
from ..widgets import FormDialog, button, date_field

CHOOSE_SEX = "Choisir…"
CHOOSE_YEAR = "Choisir une année scolaire…"
CHOOSE_LEVEL = "Choisir un niveau…"
CHOOSE_CLASS = "Choisir une classe…"
NO_DATE = "jj/mm/aaaa"
PHOTO_SIZE = (96, 120)
EARLIEST = QDate(1900, 1, 1)

HISTORY_LABELS = Labels(
    {
        "STUDENT_CREATED": "Fiche créée",
        "STUDENT_UPDATED": "Fiche modifiée",
        "STUDENT_ARCHIVED": "Élève archivé",
        "STUDENT_REACTIVATED": "Élève réactivé",
        "STUDENT_ENROLLED": "Inscription",
        "STUDENT_CLASS_CHANGED": "Changement de classe",
        "STUDENT_WITHDRAWN": "Retrait de la classe",
        "STUDENT_PHOTO_SET": "Photo ajoutée",
        "STUDENT_PHOTO_REMOVED": "Photo retirée",
    }
)


def _qdate(value):
    return QDate(value.year, value.month, value.day)


def _day(value):
    return f"{value:%d/%m/%Y}" if value else "—"


def photo_pixmap(content):
    """QPixmap scaled to the photo frame, or None if `content` is not an image."""
    image = QImage()
    if not content or not image.loadFromData(content):
        return None
    return QPixmap.fromImage(image).scaled(*PHOTO_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def photo_frame(content=None):
    frame = QLabel(tr("Pas de photo"), objectName="photoFrame", alignment=Qt.AlignCenter)
    frame.setFixedSize(*PHOTO_SIZE)
    frame.setWordWrap(True)
    pixmap = photo_pixmap(content)
    if pixmap is not None:
        frame.setPixmap(pixmap)
    frame.setAccessibleName(tr("Photo de l'élève"))
    return frame


class ClassPicker:
    """Année scolaire → Niveau → Classe, three lists of a FormDialog.

    `classes` = active classes of the school (any year); the class list shows
    those of the chosen year AND level. `fixed_year` locks the year (class
    change). Calls `on_change` when the selection changes."""

    def __init__(self, dialog, years, levels, classes, *, fixed_year=None, current=None, on_change=None):
        self.classes = classes
        self.on_change = on_change or (lambda: None)
        self.year = dialog.add_field("academic_year", tr("Année scolaire"), QComboBox(), required=True, width="medium")
        self.level = dialog.add_field("level", tr("Niveau"), QComboBox(), required=True, width="medium", beside=True)
        self.school_class = dialog.add_field("school_class", tr("Classe"), QComboBox(), required=True, width="medium")
        self.hint = QLabel("", objectName="help")
        self.hint.setWordWrap(True)
        dialog.body.addWidget(self.hint)
        if fixed_year is None:
            self.year.addItem(tr(CHOOSE_YEAR), None)
            for year in years:
                self.year.addItem(year.short_label, year.id)
            self.year.setCurrentIndex(1 if years else 0)  # the current year comes first
        else:
            self.year.addItem(fixed_year[1], fixed_year[0])
            self.year.setEnabled(False)  # a class change stays in the enrollment's year
        self.level.addItem(tr(CHOOSE_LEVEL), None)
        for level in levels:
            self.level.addItem(level.label, level.id)
        self.current = current  # class id to leave out (class change)
        self.year.currentIndexChanged.connect(self.reload)
        self.level.currentIndexChanged.connect(self.reload)
        self.school_class.currentIndexChanged.connect(lambda _: self.on_change())
        self.reload()

    def select_level(self, level_id):
        self.level.setCurrentIndex(max(0, self.level.findData(level_id)))

    def reload(self, _index=None):
        """Classes compatible with the chosen year and level (fresh API list)."""
        year, level = self.year.currentData(), self.level.currentData()
        chosen = self.school_class.currentData()
        self.school_class.blockSignals(True)
        self.school_class.clear()
        self.school_class.addItem(tr(CHOOSE_CLASS), None)
        matching = [
            c for c in self.classes if c.year_id == year and c.level_id == level and c.id != self.current and c.active
        ]
        for school_class in matching:
            places = tr(" · {0} places", school_class.capacity) if school_class.capacity else ""
            self.school_class.addItem(f"{school_class.name}{places}", school_class.id)
        self.school_class.setCurrentIndex(max(0, self.school_class.findData(chosen)))
        self.school_class.setEnabled(bool(matching))
        self.school_class.blockSignals(False)
        if not year:
            self.hint.setText(tr("Choisissez d'abord l'année scolaire."))
        elif not level:
            self.hint.setText(tr("Choisissez le niveau : seules ses classes de cette année sont proposées."))
        elif not matching:
            self.hint.setText(tr("Aucune classe active pour ce niveau dans cette année."))
        else:
            self.hint.setText(tr("{0} classe(s) de ce niveau pour cette année.", len(matching)))
        self.on_change()

    @property
    def class_id(self):
        return self.school_class.currentData()

    def year_of(self, years):
        return next((y for y in years if y.id == self.year.currentData()), None)


# =============================================================================
# Add / edit
# =============================================================================


class StudentDialog(FormDialog):
    def __init__(self, references=None, parent=None, student=None, *, photo=None, choose_file=None):
        editing = student is not None
        super().__init__(
            tr("Modifier la fiche de l'élève") if editing else tr("Nouvel élève"),
            tr("Fiche administrative de l'élève. La classe dépend de l'année : elle est gérée par l'inscription."),
            parent,
            width=600,
        )
        self.choose_file = choose_file or self._choose_file
        self.photo_change = None  # None | ("set", bytes, extension) | ("remove",)

        # --- IDENTITÉ ---
        self.add_section(tr("Identité"))
        self.student_number = self.add_field(
            "student_number",
            tr("Matricule"),
            QLineEdit(placeholderText=tr("Ex. MAT-2026-001"), maxLength=50),
            required=True,
            width="short",
            help_text=tr("Unique dans l'école."),
        )
        self.registration_number = self.add_field(
            "registration_number",
            tr("N° d'inscription"),
            QLineEdit(placeholderText=tr("Ex. INS-0001"), maxLength=50),
            required=True,
            width="short",
            beside=True,
            help_text=tr("Numéro administratif, unique."),
        )
        self.last_name = self.add_field(
            "last_name",
            tr("Nom"),
            QLineEdit(placeholderText=tr("Ex. NDIAYE"), maxLength=120),
            required=True,
            width="medium",
        )
        self.first_name = self.add_field(
            "first_name",
            tr("Prénom(s)"),
            QLineEdit(placeholderText=tr("Ex. Awa Marie"), maxLength=120),
            required=True,
            width="medium",
            beside=True,
        )
        sex = QComboBox()
        sex.addItem(tr(CHOOSE_SEX), None)
        for value, label in SEXES.items():
            sex.addItem(label, value)
        self.sex = self.add_field("sex", tr("Sexe"), sex, required=True, width="short")
        born = date_field()
        born.setMinimumDate(EARLIEST)
        born.setSpecialValueText(NO_DATE)  # EARLIEST = not chosen yet
        born.setMaximumDate(QDate.currentDate().addDays(-1))
        born.setDate(EARLIEST)
        born.calendarWidget().setCurrentPage(QDate.currentDate().year() - 10, 1)
        self.date_of_birth = self.add_field(
            "date_of_birth", tr("Date de naissance"), born, required=True, width="short", beside=True
        )
        self.birth_place = self.add_field(
            "birth_place",
            tr("Lieu de naissance"),
            QLineEdit(placeholderText=tr("Facultatif"), maxLength=160),
            width="medium",
        )

        # --- PHOTO ---
        self.add_section(tr("Photo"), tr("JPEG, PNG ou WebP, 3 Mo au plus. Utilisée par la carte d'élève."))
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(12)
        self.photo = photo_frame(photo)
        line.addWidget(self.photo)
        actions = QWidget()
        column = QGridLayout(actions)
        column.setContentsMargins(0, 0, 0, 0)
        self.photo_button = button(tr("Choisir une photo…"))
        self.remove_photo_button = button(tr("Retirer la photo"))
        self.photo_status = QLabel("", objectName="help")
        self.photo_status.setWordWrap(True)
        column.addWidget(self.photo_button, 0, 0, Qt.AlignLeft)
        column.addWidget(self.remove_photo_button, 1, 0, Qt.AlignLeft)
        column.addWidget(self.photo_status, 2, 0)
        line.addWidget(actions, 1, Qt.AlignTop)
        self.body.addWidget(row)
        self.photo_button.clicked.connect(self.pick_photo)
        self.remove_photo_button.clicked.connect(self.drop_photo)
        self.remove_photo_button.setEnabled(bool(photo))

        # --- INFORMATIONS COMPLÉMENTAIRES (champs existants du modèle) ---
        self.add_section(tr("Informations complémentaires"))
        address = QPlainTextEdit(placeholderText=tr("Facultatif"))
        address.setFixedHeight(64)
        address.setTabChangesFocus(True)
        self.address = self.add_field("address", tr("Adresse"), address)
        height = QLineEdit(placeholderText=tr("Ex. 145"), maxLength=3)
        height.setValidator(QIntValidator(30, 250, height))
        self.height_cm = self.add_field("height_cm", tr("Taille (cm)"), height, width="short")

        # --- INSCRIPTION (création seulement) ---
        self.picker = None
        if not editing and references is not None:
            years, levels, classes = references
            self.add_section(tr("Inscription"), tr("Facultatif : l'élève peut aussi être inscrit plus tard."))
            self.enroll = self.add_field("enroll", tr("Inscription"), QCheckBox(tr("Inscrire l'élève maintenant")))
            self.picker = ClassPicker(self, years, levels, classes, on_change=self.refresh_state)
            self.enroll.toggled.connect(self._toggle_enrollment)
            self._toggle_enrollment(False)

        if editing:
            self.student_number.setText(student.student_number)
            self.registration_number.setText(student.registration_number)
            self.last_name.setText(student.last_name)
            self.first_name.setText(student.first_name)
            self.sex.setCurrentIndex(max(0, self.sex.findData(student.sex)))
            if student.date_of_birth:
                self.date_of_birth.setDate(_qdate(student.date_of_birth))
            self.birth_place.setText(student.birth_place)
            self.address.setPlainText(student.address)
            self.height_cm.setText(str(student.height_cm) if student.height_cm else "")
        for signal in (
            self.student_number.textChanged,
            self.registration_number.textChanged,
            self.last_name.textChanged,
            self.first_name.textChanged,
            self.sex.currentIndexChanged,
            self.date_of_birth.dateChanged,
        ):
            signal.connect(self.refresh_state)
        self.finish()
        (self.last_name if editing else self.student_number).setFocus()

    # --- photo -----------------------------------------------------------------------
    @staticmethod
    def _choose_file(parent):
        path, _ = QFileDialog.getOpenFileName(
            parent, tr("Choisir une photo"), "", tr("Images (*.jpg *.jpeg *.png *.webp)")
        )
        return path

    def pick_photo(self):
        path = self.choose_file(self)
        if not path:
            return
        extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        try:
            with open(path, "rb") as handle:  # read locally; only the bytes are sent
                content = handle.read(PHOTO_MAX_BYTES + 1)
        except OSError:
            self.photo_status.setText(tr("Impossible de lire ce fichier."))
            return
        if extension not in PHOTO_TYPES:
            self.photo_status.setText(tr("Format non accepté : JPEG, PNG ou WebP."))
            return
        if len(content) > PHOTO_MAX_BYTES:
            self.photo_status.setText(tr("Photo trop lourde : 3 Mo au plus."))
            return
        pixmap = photo_pixmap(content)
        if pixmap is None:
            self.photo_status.setText(tr("Ce fichier n'est pas une image lisible."))
            return
        self.photo.setPixmap(pixmap)
        self.photo_change = ("set", content, extension)
        self.photo_status.setText(tr("Nouvelle photo : elle sera envoyée à l'enregistrement."))
        self.remove_photo_button.setEnabled(True)

    def drop_photo(self):
        self.photo.clear()
        self.photo.setText(tr("Pas de photo"))
        self.photo_change = ("remove",)
        self.photo_status.setText(tr("La photo sera retirée à l'enregistrement."))
        self.remove_photo_button.setEnabled(False)

    # --- state --------------------------------------------------------------------------
    def _toggle_enrollment(self, checked):
        for combo in (self.picker.year, self.picker.level):
            combo.setEnabled(checked)
        self.picker.school_class.setEnabled(checked and self.picker.school_class.count() > 1)
        self.refresh_state()

    def missing_fields(self):
        missing = []
        for widget, label in (
            (self.student_number, tr("Matricule")),
            (self.registration_number, tr("N° d'inscription")),
            (self.last_name, tr("Nom")),
            (self.first_name, tr("Prénom(s)")),
        ):
            if not widget.text().strip():
                missing.append(label)
        if not self.sex.currentData():
            missing.append(tr("Sexe"))
        if self.date_of_birth.date() == EARLIEST:
            missing.append(tr("Date de naissance"))
        if self.picker is not None and self.enroll.isChecked() and not self.picker.class_id:
            missing.append(tr("Classe"))
        return missing

    def values(self):
        born = self.date_of_birth.date()
        values = {
            "student_number": self.student_number.text().strip(),
            "registration_number": self.registration_number.text().strip(),
            "last_name": self.last_name.text().strip(),
            "first_name": self.first_name.text().strip(),
            "sex": self.sex.currentData(),
            "date_of_birth": None if born == EARLIEST else born.toPython(),
            "birth_place": self.birth_place.text().strip(),
            "address": self.address.toPlainText().strip(),
            "height_cm": int(self.height_cm.text()) if self.height_cm.text().strip() else None,
        }
        if self.picker is not None and self.enroll.isChecked():
            values["class_id"] = self.picker.class_id
        return values


# =============================================================================
# Enrollment
# =============================================================================


class EnrollDialog(FormDialog):
    def __init__(self, references, parent=None, student=None):
        years, levels, classes = references
        super().__init__(
            tr("Inscrire l'élève"),
            tr("{0} ({1}) : une seule classe par année scolaire.", student.name, student.student_number),
            parent,
            save_text=tr("Inscrire"),
        )
        self.years = years
        self._year_shown = None
        self.picker = ClassPicker(self, years, levels, classes, on_change=self._follow_year)
        self.enrollment_date = self.add_field(
            "enrollment_date",
            tr("Date d'inscription"),
            date_field(),
            width="short",
            help_text=tr("Comprise dans l'année scolaire choisie."),
        )
        self._follow_year()
        self.finish()

    def _follow_year(self):
        if not hasattr(self, "enrollment_date"):
            return
        year = self.picker.year_of(self.years)
        if year is not None and year.id != self._year_shown and year.start_date and year.end_date:
            self._year_shown = year.id  # only when the YEAR changes: a chosen date is kept
            self.enrollment_date.setDateRange(_qdate(year.start_date), _qdate(year.end_date))
            today = date.today()
            self.enrollment_date.setDate(_qdate(min(max(today, year.start_date), year.end_date)))
        self.refresh_state()

    def missing_fields(self):
        picker = getattr(self, "picker", None)
        return [] if picker is not None and picker.class_id else [tr("Classe")]

    def values(self):
        return {"class_id": self.picker.class_id, "enrollment_date": self.enrollment_date.date().toPython()}


class ChangeClassDialog(FormDialog):
    def __init__(self, references, parent=None, enrollment=None):
        _years, levels, classes = references
        super().__init__(
            tr("Changer de classe"),
            tr(
                "Classe actuelle : {0} ({1}). La nouvelle classe est de la même année ; notes et présences déjà "
                "saisies restent dans l'historique.",
                enrollment.class_name,
                enrollment.year_name,
            ),
            parent,
            save_text=tr("Changer de classe"),
        )
        self.picker = ClassPicker(
            self,
            [],
            levels,
            classes,
            fixed_year=(enrollment.year_id, enrollment.year_name),
            current=enrollment.class_id,
            on_change=self.refresh_state,
        )
        self.picker.select_level(enrollment.level_id)
        self.finish()

    def missing_fields(self):
        picker = getattr(self, "picker", None)
        return [] if picker is not None and picker.class_id else [tr("Nouvelle classe")]

    def values(self):
        return {"class_id": self.picker.class_id}


# =============================================================================
# Record
# =============================================================================


class StudentRecordDialog(FormDialog):
    """Read-only record. Its buttons close it with `action` set to "edit",
    "enroll", "change_class" or "withdraw"; the page then runs the action."""

    def __init__(self, student, enrollments, history, photo=None, parent=None):
        super().__init__(tr("Fiche de l'élève — {0}", student.name), "", parent, save_text=tr("Fermer"), width=640)
        self.student = student
        self.action = None
        self.cancel_button.hide()
        active = next((e for e in enrollments if e.active), None)

        self.add_section(tr("Identité"))
        identity = QWidget()
        row = QHBoxLayout(identity)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        row.addWidget(photo_frame(photo), 0, Qt.AlignTop)
        row.addWidget(
            self._grid(
                [
                    (tr("Matricule"), student.student_number),
                    (tr("N° d'inscription"), student.registration_number),
                    (tr("Nom"), student.last_name),
                    (tr("Prénom(s)"), student.first_name),
                    (tr("Sexe"), student.sex_label),
                    (tr("Date de naissance"), _day(student.date_of_birth)),
                    (tr("Lieu de naissance"), student.birth_place or "—"),
                    (tr("Statut"), STUDENT_STATUSES.get(student.status, student.status)),
                ]
            ),
            1,
        )
        self.body.addWidget(identity)
        self.edit_button = self._action_button(tr("Modifier la fiche…"), "edit", student.status != "ARCHIVED")
        self.body.addWidget(self.edit_button, 0, Qt.AlignLeft)

        self.add_section(tr("Scolarité"))
        if active is not None:
            self.body.addWidget(
                self._grid(
                    [
                        (tr("Année scolaire"), active.year_name),
                        (tr("Niveau"), f"{active.level_name} ({active.level_code})" if active.level_code else "—"),
                        (tr("Classe"), active.class_name),
                        (tr("Inscription"), tr("{0} depuis le {1}", active.status_label, _day(active.enrollment_date))),
                    ]
                )
            )
        else:
            note = QLabel(tr("Aucune inscription en cours."), objectName="help")
            self.body.addWidget(note)
        buttons = QWidget()
        line = QHBoxLayout(buttons)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        can_enroll = student.status == "ACTIVE"
        self.enroll_button = self._action_button(tr("Inscrire…"), "enroll", can_enroll and active is None)
        self.change_button = self._action_button(tr("Changer de classe…"), "change_class", active is not None)
        self.withdraw_button = self._action_button(
            tr("Retirer de la classe…"), "withdraw", active is not None, "danger"
        )
        for widget in (self.enroll_button, self.change_button, self.withdraw_button):
            line.addWidget(widget)
        line.addStretch()
        self.body.addWidget(buttons)

        self.add_section(tr("Informations complémentaires"))
        self.body.addWidget(
            self._grid(
                [
                    (tr("Adresse"), student.address or "—"),
                    (tr("Taille"), f"{student.height_cm} cm" if student.height_cm else "—"),
                ]
            )
        )

        self.add_section(tr("Historique des inscriptions"))
        if enrollments:
            self.body.addWidget(
                self._grid(
                    [
                        (
                            e.year_name,
                            f"{e.class_name} · {e.status_label}"
                            + (tr(" (jusqu'au {0})", _day(e.end_date)) if e.end_date else ""),
                        )
                        for e in enrollments
                    ]
                )
            )
        else:
            self.body.addWidget(QLabel(tr("Aucune inscription."), objectName="help"))

        self.add_section(tr("Changements"))
        if history:
            lines = []
            for entry in history[:20]:
                when = f"{entry.at.astimezone():%d/%m/%Y %H:%M}" if entry.at else ""
                label = HISTORY_LABELS.get(entry.action, entry.action)
                detail = f" — {entry.summary}" if entry.summary else ""
                author = f" · {entry.actor}" if entry.actor else ""
                lines.append((when, f"{label}{detail}{author}"))
            self.body.addWidget(self._grid(lines))
        else:
            self.body.addWidget(QLabel(tr("Aucun changement enregistré."), objectName="help"))
        self.finish(required_note=False)
        self.save_button.setFocus()

    def _action_button(self, text, action, enabled, variant="secondary"):
        widget = button(text, variant)
        widget.setEnabled(enabled)
        widget.clicked.connect(lambda: self._start(action))
        return widget

    def _start(self, action):
        self.action = action
        self.accept()

    @staticmethod
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
