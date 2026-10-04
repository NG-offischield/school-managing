"""Teacher dialogs (ADR 0019), all built on FormDialog (scrollable form,
fixed buttons, fits 1280×720):

    TeacherDialog         add / edit: IDENTITÉ, PROFIL PROFESSIONNEL, INFORMATIONS
    QualificationsDialog  the teacher's subjects: list (valider / retirer),
                          verdict of the compatibility engine for a subject,
                          add, override; applicable rules and overrides
    ReasonDialog          motif (retrait d'une matière, dérogation)
    TeacherRecordDialog   the record (identity, profile, subjects, planning,
                          remuneration, account); its buttons start actions

Compatibility is NEVER computed here: QualificationsDialog asks the server
(GET /teachers/{id}/compatibility/) and displays its verdict and reason.
"""

from datetime import datetime, time

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QWidget

from ...models import COMPATIBILITY_RESULTS, EMPLOYMENT_STATUSES, PROFESSIONAL_STATUSES
from ..feedback import describe
from ..widgets import Banner, FormDialog, button, date_field, set_variant

CHOOSE_CATEGORY = "Choisir une catégorie…"
CHOOSE_SUBJECT = "Choisir une matière…"
ALL_LEVELS = "Tous les niveaux"
NO_DATE = "jj/mm/aaaa"
EARLIEST = QDate(1950, 1, 1)
STATUS_COLOURS = {"COMPATIBLE": "success", "OVERRIDDEN": "info", "REQUIRES_REVIEW": "warning", "INCOMPATIBLE": "error"}


def verdict_text(verdict):
    """Plain French explanation of the SERVER's verdict (display only)."""
    rule, override = verdict.rule or {}, verdict.override or {}
    level = f" en {verdict.level_label}" if verdict.level_label else ""
    rule_scope = f" ({rule['level']['code']})" if rule.get("level") else " (tous niveaux)"
    reasons = {
        "primary_subject": "C'est la matière principale de l'enseignant.",
        "same_category": "La matière appartient à la catégorie pédagogique de l'enseignant.",
        "no_rule": "Aucune règle ne couvre cette matière : l'administration doit valider la qualification.",
        "rule_compatible": f"Règle de compatibilité de la catégorie {rule.get('category', '')}{rule_scope} : autorisé.",
        "rule_review": f"Règle de la catégorie {rule.get('category', '')}{rule_scope} : validation par "
        "l'administration exigée.",
        "rule_incompatible": f"Règle de la catégorie {rule.get('category', '')}{rule_scope} : matière interdite "
        "à ce profil. Une dérogation motivée est possible.",
        "override": f"Dérogation accordée par {override.get('approved_by', '?')} : « {override.get('reason', '')} »"
        + (f", jusqu'au {override['expires_at'][:10]}" if override.get("expires_at") else "")
        + ".",
    }
    return f"{verdict.subject_label}{level} — {verdict.result_label}. {reasons.get(verdict.reason, '')}".strip()


def _subject_label(subject):
    return f"{subject.code} — {subject.name}" + (
        f" ({subject.category_label.split(' — ')[0]})" if subject.category_label else ""
    )


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


# =============================================================================
# Add / edit
# =============================================================================


class TeacherDialog(FormDialog):
    def __init__(self, categories, subjects, parent=None, teacher=None):
        editing = teacher is not None
        super().__init__(
            "Modifier l'enseignant" if editing else "Nouvel enseignant",
            "Fiche de l'enseignant. Le compte de connexion est créé sans mot de passe : "
            "son activation se fait séparément."
            if not editing
            else "Fiche de l'enseignant. Les matières se gèrent dans « Qualifications ».",
            parent,
            width=600,
        )
        self.add_section("Identité")
        self.last_name = self.add_field(
            "last_name", "Nom", QLineEdit(placeholderText="Ex. MBARGA", maxLength=120), required=True, width="medium"
        )
        self.first_name = self.add_field(
            "first_name",
            "Prénom(s)",
            QLineEdit(placeholderText="Ex. Jean", maxLength=120),
            required=True,
            width="medium",
            beside=True,
        )
        self.email = self.add_field(
            "email",
            "E-mail",
            QLineEdit(placeholderText="Ex. j.mbarga@ecole.cm", maxLength=254),
            required=True,
            width="medium",
            help_text="Identifiant de connexion du compte.",
        )
        self.phone = self.add_field(
            "phone", "Téléphone", QLineEdit(placeholderText="Facultatif", maxLength=40), width="short", beside=True
        )

        self.add_section("Profil professionnel")
        self.employee_number = self.add_field(
            "employee_number",
            "Matricule",
            QLineEdit(placeholderText="Ex. ENS-001", maxLength=50),
            required=True,
            width="short",
            help_text="Unique dans l'école.",
        )
        hired = date_field()
        hired.setMinimumDate(EARLIEST)
        hired.setSpecialValueText(NO_DATE)  # EARLIEST = not given
        hired.setDate(EARLIEST)
        hired.calendarWidget().setCurrentPage(QDate.currentDate().year(), QDate.currentDate().month())
        self.hire_date = self.add_field("hire_date", "Date d'embauche", hired, width="short", beside=True)
        category = QComboBox()
        category.addItem(CHOOSE_CATEGORY, None)
        for item in categories:
            category.addItem(f"{item.code} — {item.name}", item.id)
        self.category = self.add_field("category", "Catégorie pédagogique", category, required=True, width="medium")
        subject = QComboBox()
        subject.addItem(CHOOSE_SUBJECT, None)
        for item in subjects:
            subject.addItem(_subject_label(item), item.id)
        self.primary_subject = self.add_field(
            "primary_subject",
            "Matière principale",
            subject,
            required=True,
            width="medium",
            beside=True,
            help_text="Jugée par les règles de compatibilité du serveur.",
        )
        self.professional_status = self.employment_status = None
        if editing:
            professional = QComboBox()
            for value, label in PROFESSIONAL_STATUSES.items():
                professional.addItem(label, value)
            self.professional_status = self.add_field(
                "professional_status", "Statut professionnel", professional, width="medium"
            )
            employment = QComboBox()
            for value, label in EMPLOYMENT_STATUSES.items():
                employment.addItem(label, value)
            self.employment_status = self.add_field(
                "employment_status", "Statut d'emploi", employment, width="medium", beside=True
            )
        address = QPlainTextEdit(placeholderText="Facultatif")
        address.setFixedHeight(56)
        address.setTabChangesFocus(True)
        self.address = self.add_field("address", "Adresse", address)

        self.add_section("Informations complémentaires")
        summary = QPlainTextEdit(placeholderText="Diplômes, spécialités… (facultatif)")
        summary.setFixedHeight(56)
        summary.setTabChangesFocus(True)
        self.qualification_summary = self.add_field("qualification_summary", "Résumé des qualifications", summary)
        bio = QPlainTextEdit(placeholderText="Facultatif")
        bio.setFixedHeight(56)
        bio.setTabChangesFocus(True)
        self.bio = self.add_field("bio", "Présentation", bio)

        if editing:
            self.last_name.setText(teacher.last_name)
            self.first_name.setText(teacher.first_name)
            self.email.setText(teacher.email)
            self.phone.setText(teacher.phone)
            self.employee_number.setText(teacher.number)
            if teacher.hire_date:
                self.hire_date.setDate(QDate(teacher.hire_date.year, teacher.hire_date.month, teacher.hire_date.day))
            self._select(self.category, teacher.category_id, f"{teacher.category_label} (inactive)")
            self._select(
                self.primary_subject, teacher.primary_subject_id, f"{teacher.primary_subject_label} (inactive)"
            )
            self.professional_status.setCurrentIndex(
                max(0, self.professional_status.findData(teacher.professional_status))
            )
            self.employment_status.setCurrentIndex(max(0, self.employment_status.findData(teacher.employment_status)))
            self.address.setPlainText(teacher.address)
            self.qualification_summary.setPlainText(teacher.qualification_summary)
            self.bio.setPlainText(teacher.bio)
        for signal in (
            self.last_name.textChanged,
            self.first_name.textChanged,
            self.email.textChanged,
            self.employee_number.textChanged,
            self.category.currentIndexChanged,
            self.primary_subject.currentIndexChanged,
        ):
            signal.connect(self.refresh_state)
        self.finish()
        self.last_name.setFocus()

    @staticmethod
    def _select(combo, value, missing_label):
        index = combo.findData(value)
        if index < 0 and value:
            combo.addItem(missing_label, value)
            index = combo.count() - 1
        combo.setCurrentIndex(max(0, index))

    def missing_fields(self):
        missing = [
            label
            for widget, label in (
                (self.last_name, "Nom"),
                (self.first_name, "Prénom(s)"),
                (self.email, "E-mail"),
                (self.employee_number, "Matricule"),
            )
            if not widget.text().strip()
        ]
        if self.email.text().strip() and "@" not in self.email.text():
            missing.append("une adresse e-mail valide")
        if not self.category.currentData():
            missing.append("Catégorie pédagogique")
        if not self.primary_subject.currentData():
            missing.append("Matière principale")
        return missing

    def values(self):
        hired = self.hire_date.date()
        values = {
            "last_name": self.last_name.text().strip(),
            "first_name": self.first_name.text().strip(),
            "email": self.email.text().strip(),
            "phone": self.phone.text().strip(),
            "employee_number": self.employee_number.text().strip(),
            "hire_date": None if hired == EARLIEST else hired.toPython(),
            "category_id": self.category.currentData(),
            "primary_subject_id": self.primary_subject.currentData(),
            "address": self.address.toPlainText().strip(),
            "qualification_summary": self.qualification_summary.toPlainText().strip(),
            "bio": self.bio.toPlainText().strip(),
        }
        if self.professional_status is not None:
            values["professional_status"] = self.professional_status.currentData()
            values["employment_status"] = self.employment_status.currentData()
        return values


# =============================================================================
# Reason (withdraw a subject, override)
# =============================================================================


class ReasonDialog(FormDialog):
    def __init__(self, title, instruction, parent=None, *, save_text="Confirmer", with_expiry=False, danger=False):
        super().__init__(title, instruction, parent, save_text=save_text, width=520)
        reason = QPlainTextEdit(placeholderText="Motif (obligatoire)")
        reason.setFixedHeight(72)
        reason.setTabChangesFocus(True)
        self.reason = self.add_field("reason", "Motif", reason, required=True)
        self.expires = self.expiry = None
        if with_expiry:
            self.expires = self.add_field("expires", "Durée", QCheckBox("Limiter la dérogation dans le temps"))
            self.expiry = self.add_field("expiry", "Jusqu'au", date_field(), width="short")
            self.expiry.setMinimumDate(QDate.currentDate().addDays(1))
            self.expiry.setDate(QDate.currentDate().addMonths(12))
            self.expiry.setEnabled(False)
            self.expires.toggled.connect(self.expiry.setEnabled)
        if danger:
            set_variant(self.save_button, "danger-solid")
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()
        self.reason.setFocus()

    def missing_fields(self):
        return [] if self.reason.toPlainText().strip() else ["Motif"]

    def values(self):
        expires_at = None
        if self.expires is not None and self.expires.isChecked():
            expires_at = datetime.combine(self.expiry.date().toPython(), time(23, 59)).astimezone()
        return {"reason": self.reason.toPlainText().strip(), "expires_at": expires_at}


def ask_reason(parent, title, instruction, **options):
    dialog = ReasonDialog(title, instruction, parent, **options)
    return dialog.values() if dialog.exec() == ReasonDialog.DialogCode.Accepted else None


# =============================================================================
# Qualifications
# =============================================================================


class QualificationsDialog(FormDialog):
    """Manage the subjects of one teacher. API calls run through the page's
    runner (off the UI thread); errors are shown in the dialog's banner.
    `ask` = ask_reason (overridable in tests)."""

    def __init__(self, teacher, service, runner, subjects, levels, parent=None, *, ask=ask_reason):
        super().__init__(
            f"Qualifications — {teacher.name}",
            "Matières que l'enseignant peut enseigner. La compatibilité est calculée par le serveur ; "
            "l'administration valide, retire ou accorde une dérogation motivée.",
            parent,
            save_text="Fermer",
            width=640,
        )
        self.teacher, self.service, self.runner, self.ask = teacher, service, runner, ask
        self.subjects, self.changed, self.expired, self.verdict = subjects, False, False, None
        self.cancel_button.hide()
        self.banner = Banner(self)
        self.body.addWidget(self.banner)

        self.add_section("Matières de l'enseignant")
        self.list_holder = QWidget()
        self.list_layout = QGridLayout(self.list_holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setHorizontalSpacing(10)
        self.list_layout.setVerticalSpacing(6)
        self.body.addWidget(self.list_holder)
        self.subject_rows = {}

        self.add_section("Ajouter une matière", "Vérifiez d'abord la compatibilité : le verdict vient du serveur.")
        subject = QComboBox()
        subject.addItem(CHOOSE_SUBJECT, None)
        for item in subjects:
            subject.addItem(_subject_label(item), item.id)
        self.subject = self.add_field("subject", "Matière", subject, width="medium")
        level = QComboBox()
        level.addItem(ALL_LEVELS, None)
        for item in levels:
            level.addItem(item.label, item.id)
        self.level = self.add_field("level", "Niveau (facultatif)", level, width="short", beside=True)
        self.verdict_label = QLabel("", objectName="banner")
        self.verdict_label.setWordWrap(True)
        self.verdict_label.hide()
        self.body.addWidget(self.verdict_label)
        actions = QWidget()
        line = QHBoxLayout(actions)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        self.check_button = button("Vérifier la compatibilité")
        self.add_button = button("Ajouter la matière", "primary")
        self.override_button = button("Accorder une dérogation…")
        for widget in (self.check_button, self.add_button, self.override_button):
            line.addWidget(widget)
        line.addStretch()
        self.body.addWidget(actions)

        self.add_section("Règles et dérogations")
        self.rules_label = QLabel("", objectName="help")
        self.rules_label.setWordWrap(True)
        self.body.addWidget(self.rules_label)

        self.subject.currentIndexChanged.connect(self._selection_changed)
        self.level.currentIndexChanged.connect(self._selection_changed)
        self.check_button.clicked.connect(self.check)
        self.add_button.clicked.connect(self.add)
        self.override_button.clicked.connect(self.grant_override)
        self.finish(required_note=False)
        self._selection_changed()
        self.reload()

    # --- calls ------------------------------------------------------------------------
    def call(self, fn, on_success, action):
        def failed(exc):
            feedback = describe(exc, action)
            if feedback.session_expired:
                self.expired = True
                self.reject()
                return
            self.banner.show_message(feedback.kind, feedback.text, title=feedback.title, detail=feedback.detail)

        self.runner.run(fn, on_success, failed)

    def reload(self):
        teacher_id = self.teacher.id
        self.call(
            lambda: (
                self.service.qualifications(teacher_id),
                self.service.rules(teacher_id),
                self.service.overrides(teacher_id),
            ),
            self._show,
            "Impossible de charger les qualifications",
        )

    def _show(self, loaded):
        qualifications, rules, overrides = loaded
        self.qualifications = qualifications
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.subject_rows = {}
        for index, q in enumerate(qualifications):
            primary = " · principale" if q.subject_id == self.teacher.primary_subject_id else ""
            text = QLabel(
                f"<b>{q.label}</b>{primary}<br><span>{q.status_label} · "
                f"{COMPATIBILITY_RESULTS.get(q.current, q.current)}</span>",
                objectName="fieldValue",
            )
            text.setTextFormat(Qt.RichText)
            text.setWordWrap(True)
            verify = button("Valider")
            verify.setEnabled(q.status in ("DECLARED", "PENDING"))
            verify.setToolTip("Confirmer la qualification" if verify.isEnabled() else "Déjà validée ou retirée.")
            withdraw = button("Retirer", "danger")
            withdraw.setEnabled(q.status != "REJECTED" and not primary)
            withdraw.setToolTip(
                "La matière principale ne se retire pas." if primary else "Retirer cette matière (motif demandé)"
            )
            verify.clicked.connect(lambda _=False, q=q: self.verify(q))
            withdraw.clicked.connect(lambda _=False, q=q: self.withdraw(q))
            self.list_layout.addWidget(text, index, 0)
            self.list_layout.addWidget(verify, index, 1, Qt.AlignTop)
            self.list_layout.addWidget(withdraw, index, 2, Qt.AlignTop)
            self.subject_rows[q.subject_code] = (text, verify, withdraw)
        self.list_layout.setColumnStretch(0, 1)
        if not qualifications:
            self.list_layout.addWidget(QLabel("Aucune matière.", objectName="help"), 0, 0)
        lines = [
            f"Règle : {r['subject']['code']}{' (' + r['level']['code'] + ')' if r.get('level') else ''} — "
            + ("validation exigée" if r["requires_admin_review"] else ("autorisé" if r["compatible"] else "interdit"))
            for r in rules
        ]
        lines += [
            f"Dérogation : {o['subject']['code']} — « {o['reason']} » ({o['approved_by']})"
            + ("" if o["active"] else " — expirée")
            for o in overrides
        ]
        self.rules_label.setText(
            "\n".join(lines)
            or "Aucune règle pour cette catégorie : même catégorie ou matière principale = compatible ; "
            "sinon validation par l'administration."
        )

    def _selection_changed(self, _index=None):
        chosen = bool(self.subject.currentData())
        self.verdict = None
        self.verdict_label.hide()
        self.check_button.setEnabled(chosen)
        self.add_button.setEnabled(chosen)
        self.override_button.setEnabled(False)
        self.override_button.setToolTip("Vérifiez d'abord la compatibilité.")

    def check(self):
        subject, level = self.subject.currentData(), self.level.currentData()
        if not subject:
            return
        self.call(
            lambda: self.service.compatibility(self.teacher.id, subject, level),
            self._show_verdict,
            "Impossible de vérifier la compatibilité",
        )

    def _show_verdict(self, verdict):
        self.verdict = verdict
        self.verdict_label.setProperty("kind", STATUS_COLOURS.get(verdict.result, "info"))
        self.verdict_label.style().unpolish(self.verdict_label)
        self.verdict_label.style().polish(self.verdict_label)
        self.verdict_label.setText(verdict_text(verdict))
        self.verdict_label.show()
        needs = verdict.result in ("INCOMPATIBLE", "REQUIRES_REVIEW")
        self.override_button.setEnabled(needs)
        self.override_button.setToolTip(
            "Dérogation motivée et tracée (administrateurs)." if needs else "Aucune dérogation nécessaire."
        )

    def add(self):
        subject, level = self.subject.currentData(), self.level.currentData()
        self.call(
            lambda: self.service.add_qualification(self.teacher.id, subject, level),
            self._added,
            "Impossible d'ajouter la matière",
        )

    def _added(self, qualification):
        self.changed = True
        self.banner.show_message(
            "success", f"{qualification.label} ajoutée : {qualification.status_label.lower()}.", autohide=True
        )
        self.reload()

    def verify(self, qualification):
        self.call(
            lambda: self.service.verify(qualification.id),
            lambda q: self._done(f"{q.label} validée."),
            "Impossible de valider la matière",
        )

    def withdraw(self, qualification):
        values = self.ask(
            self,
            "Retirer la matière ?",
            f"{qualification.label} ne pourra plus être confiée à cet enseignant. L'historique est conservé ; "
            "le serveur refuse le retrait si un cours actif l'utilise.",
            save_text="Retirer",
            danger=True,
        )
        if values:
            self.call(
                lambda: self.service.reject(qualification.id, values["reason"]),
                lambda q: self._done(f"{q.label} retirée."),
                "Impossible de retirer la matière",
            )

    def grant_override(self):
        if self.verdict is None:
            return
        subject, level = self.subject.currentData(), self.level.currentData()
        values = self.ask(
            self,
            "Accorder une dérogation ?",
            f"{self.verdict.subject_label} : le serveur a répondu « {self.verdict.result_label} ». La dérogation "
            "est tracée (auteur, motif, date, portée).",
            save_text="Accorder la dérogation",
            with_expiry=True,
        )
        if values:
            self.call(
                lambda: self.service.grant_override(
                    self.teacher.id, subject, values["reason"], level_id=level, expires_at=values["expires_at"]
                ),
                lambda _: (self._done("Dérogation accordée."), self.check()),
                "Impossible d'accorder la dérogation",
            )

    def _done(self, message):
        self.changed = True
        self.banner.show_message("success", message, autohide=True)
        self.reload()


# =============================================================================
# Record
# =============================================================================


class TeacherRecordDialog(FormDialog):
    """Read-only record; its buttons close it with `action` = "edit" or
    "qualifications" (the page then runs the action)."""

    def __init__(self, teacher, qualifications, rates, parent=None):
        super().__init__(f"Fiche de l'enseignant — {teacher.name}", "", parent, save_text="Fermer", width=640)
        self.action = None
        self.cancel_button.hide()

        self.add_section("Identité")
        self.body.addWidget(
            _grid(
                [
                    ("Nom", teacher.last_name),
                    ("Prénom(s)", teacher.first_name),
                    ("E-mail", teacher.email or "—"),
                    ("Téléphone", teacher.phone or "—"),
                    ("Adresse", teacher.address or "—"),
                ]
            )
        )
        self.add_section("Profil professionnel")
        self.body.addWidget(
            _grid(
                [
                    ("Matricule", teacher.number),
                    ("Fonction", "Enseignant"),
                    ("Statut", teacher.status_label),
                    ("Statut professionnel", PROFESSIONAL_STATUSES.get(teacher.professional_status, "—")),
                    ("Statut d'emploi", EMPLOYMENT_STATUSES.get(teacher.employment_status, "—")),
                    ("Date d'embauche", f"{teacher.hire_date:%d/%m/%Y}" if teacher.hire_date else "—"),
                    ("Catégorie pédagogique", teacher.category_label or "—"),
                    ("Matière principale", teacher.primary_subject_label or "—"),
                ]
            )
        )
        self.edit_button = self._action("Modifier la fiche…", "edit")
        self.body.addWidget(self.edit_button, 0, Qt.AlignLeft)

        self.add_section("Qualifications")
        live = [q for q in qualifications if q.status != "REJECTED"]
        self.body.addWidget(
            _grid([(q.label, f"{q.status_label} · {COMPATIBILITY_RESULTS.get(q.current, q.current)}") for q in live])
            if live
            else QLabel("Aucune matière.", objectName="help")
        )
        self.qualifications_button = self._action("Gérer les qualifications…", "qualifications")
        self.body.addWidget(self.qualifications_button, 0, Qt.AlignLeft)

        self.add_section("Planning")
        self.body.addWidget(
            _grid(
                [
                    ("Cours actifs", "—" if teacher.active_course_count is None else str(teacher.active_course_count)),
                    (
                        "Séances à venir",
                        "—" if teacher.upcoming_session_count is None else str(teacher.upcoming_session_count),
                    ),
                    ("Emploi du temps", "PDF disponible dans le module Documents (emploi du temps de l'enseignant)."),
                ]
            )
        )
        self.add_section("Rémunération", "Lecture seule : la paie se gère dans son module.")
        current = [r for r in rates if r.get("active")]
        self.body.addWidget(
            _grid(
                [
                    (
                        "Taux de vacation",
                        f"{r['vacation_rate']} {r.get('currency', '')} / {r.get('vacation_minutes', 60)} min "
                        f"depuis le {r['effective_from']}",
                    )
                    for r in current
                ]
            )
            if current
            else QLabel("Aucun taux de vacation défini.", objectName="help")
        )
        self.add_section("Compte")
        self.body.addWidget(
            QLabel(
                "Compte activé : l'enseignant peut se connecter."
                if teacher.account_activated
                else "Compte créé, non activé : aucun mot de passe n'est défini (activation séparée).",
                objectName="help",
            )
        )
        self.finish(required_note=False)
        self.save_button.setFocus()

    def _action(self, text, action):
        widget = button(text)
        widget.clicked.connect(lambda: self._start(action))
        return widget

    def _start(self, action):
        self.action = action
        self.accept()
