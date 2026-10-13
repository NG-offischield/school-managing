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

from ...i18n import tr
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
    rule_scope = f" ({rule['level']['code']})" if rule.get("level") else tr(" (tous niveaux)")
    reasons = {
        "primary_subject": tr("C'est la matière principale de l'enseignant."),
        "same_category": tr("La matière appartient à la catégorie pédagogique de l'enseignant."),
        "no_rule": tr("Aucune règle ne couvre cette matière : l'administration doit valider la qualification."),
        "rule_compatible": tr(
            "Règle de compatibilité de la catégorie {0}{1} : autorisé.", rule.get("category", ""), rule_scope
        ),
        "rule_review": tr(
            "Règle de la catégorie {0}{1} : validation par l'administration exigée.",
            rule.get("category", ""),
            rule_scope,
        ),
        "rule_incompatible": tr(
            "Règle de la catégorie {0}{1} : matière interdite à ce profil. Une dérogation motivée est possible.",
            rule.get("category", ""),
            rule_scope,
        ),
        "override": tr(
            "Dérogation accordée par {0} : « {1} »", override.get("approved_by", "?"), override.get("reason", "")
        )
        + (tr(", jusqu'au {0}", override["expires_at"][:10]) if override.get("expires_at") else "")
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
            tr("Modifier l'enseignant") if editing else tr("Nouvel enseignant"),
            tr(
                "Fiche de l'enseignant. Le compte de connexion est créé sans mot de passe : son activation se fait "
                "séparément."
            )
            if not editing
            else tr("Fiche de l'enseignant. Les matières se gèrent dans « Qualifications »."),
            parent,
            width=600,
        )
        self.add_section(tr("Identité"))
        self.last_name = self.add_field(
            "last_name",
            tr("Nom"),
            QLineEdit(placeholderText=tr("Ex. MBARGA"), maxLength=120),
            required=True,
            width="medium",
        )
        self.first_name = self.add_field(
            "first_name",
            tr("Prénom(s)"),
            QLineEdit(placeholderText=tr("Ex. Jean"), maxLength=120),
            required=True,
            width="medium",
            beside=True,
        )
        self.email = self.add_field(
            "email",
            "E-mail",
            QLineEdit(placeholderText=tr("Ex. j.mbarga@ecole.cm"), maxLength=254),
            required=True,
            width="medium",
            help_text=tr("Identifiant de connexion du compte."),
        )
        self.phone = self.add_field(
            "phone",
            tr("Téléphone"),
            QLineEdit(placeholderText=tr("Facultatif"), maxLength=40),
            width="short",
            beside=True,
        )

        self.add_section(tr("Profil professionnel"))
        self.employee_number = self.add_field(
            "employee_number",
            tr("Matricule"),
            QLineEdit(placeholderText=tr("Ex. ENS-001"), maxLength=50),
            required=True,
            width="short",
            help_text=tr("Unique dans l'école."),
        )
        hired = date_field()
        hired.setMinimumDate(EARLIEST)
        hired.setSpecialValueText(NO_DATE)  # EARLIEST = not given
        hired.setDate(EARLIEST)
        hired.calendarWidget().setCurrentPage(QDate.currentDate().year(), QDate.currentDate().month())
        self.hire_date = self.add_field("hire_date", tr("Date d'embauche"), hired, width="short", beside=True)
        category = QComboBox()
        category.addItem(tr(CHOOSE_CATEGORY), None)
        for item in categories:
            category.addItem(f"{item.code} — {item.name}", item.id)
        self.category = self.add_field("category", tr("Catégorie pédagogique"), category, required=True, width="medium")
        subject = QComboBox()
        subject.addItem(tr(CHOOSE_SUBJECT), None)
        for item in subjects:
            subject.addItem(_subject_label(item), item.id)
        self.primary_subject = self.add_field(
            "primary_subject",
            tr("Matière principale"),
            subject,
            required=True,
            width="medium",
            beside=True,
            help_text=tr("Jugée par les règles de compatibilité du serveur."),
        )
        self.professional_status = self.employment_status = None
        if editing:
            professional = QComboBox()
            for value, label in PROFESSIONAL_STATUSES.items():
                professional.addItem(label, value)
            self.professional_status = self.add_field(
                "professional_status", tr("Statut professionnel"), professional, width="medium"
            )
            employment = QComboBox()
            for value, label in EMPLOYMENT_STATUSES.items():
                employment.addItem(label, value)
            self.employment_status = self.add_field(
                "employment_status", tr("Statut d'emploi"), employment, width="medium", beside=True
            )
        address = QPlainTextEdit(placeholderText=tr("Facultatif"))
        address.setFixedHeight(56)
        address.setTabChangesFocus(True)
        self.address = self.add_field("address", tr("Adresse"), address)

        self.add_section(tr("Informations complémentaires"))
        summary = QPlainTextEdit(placeholderText=tr("Diplômes, spécialités… (facultatif)"))
        summary.setFixedHeight(56)
        summary.setTabChangesFocus(True)
        self.qualification_summary = self.add_field("qualification_summary", tr("Résumé des qualifications"), summary)
        bio = QPlainTextEdit(placeholderText=tr("Facultatif"))
        bio.setFixedHeight(56)
        bio.setTabChangesFocus(True)
        self.bio = self.add_field("bio", tr("Présentation"), bio)

        if editing:
            self.last_name.setText(teacher.last_name)
            self.first_name.setText(teacher.first_name)
            self.email.setText(teacher.email)
            self.phone.setText(teacher.phone)
            self.employee_number.setText(teacher.number)
            if teacher.hire_date:
                self.hire_date.setDate(QDate(teacher.hire_date.year, teacher.hire_date.month, teacher.hire_date.day))
            self._select(self.category, teacher.category_id, tr("{0} (inactive)", teacher.category_label))
            self._select(
                self.primary_subject, teacher.primary_subject_id, tr("{0} (inactive)", teacher.primary_subject_label)
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
                (self.last_name, tr("Nom")),
                (self.first_name, tr("Prénom(s)")),
                (self.email, "E-mail"),
                (self.employee_number, tr("Matricule")),
            )
            if not widget.text().strip()
        ]
        if self.email.text().strip() and "@" not in self.email.text():
            missing.append(tr("une adresse e-mail valide"))
        if not self.category.currentData():
            missing.append(tr("Catégorie pédagogique"))
        if not self.primary_subject.currentData():
            missing.append(tr("Matière principale"))
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
    def __init__(
        self, title, instruction, parent=None, *, save_text=None, with_expiry=False, danger=False, optional=False
    ):
        save_text = tr("Confirmer") if save_text is None else save_text  # read now: follows the language
        super().__init__(title, instruction, parent, save_text=save_text, width=520)
        self.optional = optional  # a comment rather than a mandatory reason
        reason = QPlainTextEdit(
            placeholderText=tr("Commentaire (facultatif)") if optional else tr("Motif (obligatoire)")
        )
        reason.setFixedHeight(72)
        reason.setTabChangesFocus(True)
        self.reason = self.add_field(
            "reason", tr("Commentaire") if optional else tr("Motif"), reason, required=not optional
        )
        self.expires = self.expiry = None
        if with_expiry:
            self.expires = self.add_field("expires", tr("Durée"), QCheckBox(tr("Limiter la dérogation dans le temps")))
            self.expiry = self.add_field("expiry", tr("Jusqu'au"), date_field(), width="short")
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
        return [] if self.optional or self.reason.toPlainText().strip() else [tr("Motif")]

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
            tr("Qualifications — {0}", teacher.name),
            tr(
                "Matières que l'enseignant peut enseigner. La compatibilité est calculée par le serveur ; "
                "l'administration valide, retire ou accorde une dérogation motivée."
            ),
            parent,
            save_text=tr("Fermer"),
            width=640,
        )
        self.teacher, self.service, self.runner, self.ask = teacher, service, runner, ask
        self.subjects, self.changed, self.expired, self.verdict = subjects, False, False, None
        self.cancel_button.hide()
        self.banner = Banner(self)
        self.body.addWidget(self.banner)

        self.add_section(tr("Matières de l'enseignant"))
        self.list_holder = QWidget()
        self.list_layout = QGridLayout(self.list_holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setHorizontalSpacing(10)
        self.list_layout.setVerticalSpacing(6)
        self.body.addWidget(self.list_holder)
        self.subject_rows = {}

        self.add_section(
            tr("Ajouter une matière"), tr("Vérifiez d'abord la compatibilité : le verdict vient du serveur.")
        )
        subject = QComboBox()
        subject.addItem(tr(CHOOSE_SUBJECT), None)
        for item in subjects:
            subject.addItem(_subject_label(item), item.id)
        self.subject = self.add_field("subject", tr("Matière"), subject, width="medium")
        level = QComboBox()
        level.addItem(tr(ALL_LEVELS), None)
        for item in levels:
            level.addItem(item.label, item.id)
        self.level = self.add_field("level", tr("Niveau (facultatif)"), level, width="short", beside=True)
        self.verdict_label = QLabel("", objectName="banner")
        self.verdict_label.setWordWrap(True)
        self.verdict_label.hide()
        self.body.addWidget(self.verdict_label)
        actions = QWidget()
        line = QHBoxLayout(actions)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        self.check_button = button(tr("Vérifier la compatibilité"))
        self.add_button = button(tr("Ajouter la matière"), "primary")
        self.override_button = button(tr("Accorder une dérogation…"))
        for widget in (self.check_button, self.add_button, self.override_button):
            line.addWidget(widget)
        line.addStretch()
        self.body.addWidget(actions)

        self.add_section(tr("Règles et dérogations"))
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
            tr("Impossible de charger les qualifications"),
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
            primary = tr(" · principale") if q.subject_id == self.teacher.primary_subject_id else ""
            text = QLabel(
                tr(
                    "<b>{0}</b>{1}<br><span>{2} · {3}</span>",
                    q.label,
                    primary,
                    q.status_label,
                    COMPATIBILITY_RESULTS.get(q.current, q.current),
                ),
                objectName="fieldValue",
            )
            text.setTextFormat(Qt.RichText)
            text.setWordWrap(True)
            verify = button(tr("Valider"))
            verify.setEnabled(q.status in ("DECLARED", "PENDING"))
            verify.setToolTip(
                tr("Confirmer la qualification") if verify.isEnabled() else tr("Déjà validée ou retirée.")
            )
            withdraw = button(tr("Retirer"), "danger")
            withdraw.setEnabled(q.status != "REJECTED" and not primary)
            withdraw.setToolTip(
                tr("La matière principale ne se retire pas.")
                if primary
                else tr("Retirer cette matière (motif demandé)")
            )
            verify.clicked.connect(lambda _=False, q=q: self.verify(q))
            withdraw.clicked.connect(lambda _=False, q=q: self.withdraw(q))
            self.list_layout.addWidget(text, index, 0)
            self.list_layout.addWidget(verify, index, 1, Qt.AlignTop)
            self.list_layout.addWidget(withdraw, index, 2, Qt.AlignTop)
            self.subject_rows[q.subject_code] = (text, verify, withdraw)
        self.list_layout.setColumnStretch(0, 1)
        if not qualifications:
            self.list_layout.addWidget(QLabel(tr("Aucune matière."), objectName="help"), 0, 0)
        lines = [
            tr("Règle : {0}{1} — ", r["subject"]["code"], " (" + r["level"]["code"] + ")" if r.get("level") else "")
            + (
                tr("validation exigée")
                if r["requires_admin_review"]
                else (tr("autorisé") if r["compatible"] else "interdit")
            )
            for r in rules
        ]
        lines += [
            tr("Dérogation : {0} — « {1} » ({2})", o["subject"]["code"], o["reason"], o["approved_by"])
            + ("" if o["active"] else tr(" — expirée"))
            for o in overrides
        ]
        self.rules_label.setText(
            "\n".join(lines)
            or tr(
                "Aucune règle pour cette catégorie : même catégorie ou matière principale = compatible ; sinon "
                "validation par l'administration."
            )
        )

    def _selection_changed(self, _index=None):
        chosen = bool(self.subject.currentData())
        self.verdict = None
        self.verdict_label.hide()
        self.check_button.setEnabled(chosen)
        self.add_button.setEnabled(chosen)
        self.override_button.setEnabled(False)
        self.override_button.setToolTip(tr("Vérifiez d'abord la compatibilité."))

    def check(self):
        subject, level = self.subject.currentData(), self.level.currentData()
        if not subject:
            return
        self.call(
            lambda: self.service.compatibility(self.teacher.id, subject, level),
            self._show_verdict,
            tr("Impossible de vérifier la compatibilité"),
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
            tr("Dérogation motivée et tracée (administrateurs).") if needs else tr("Aucune dérogation nécessaire.")
        )

    def add(self):
        subject, level = self.subject.currentData(), self.level.currentData()
        self.call(
            lambda: self.service.add_qualification(self.teacher.id, subject, level),
            self._added,
            tr("Impossible d'ajouter la matière"),
        )

    def _added(self, qualification):
        self.changed = True
        self.banner.show_message(
            "success", tr("{0} ajoutée : {1}.", qualification.label, qualification.status_label.lower()), autohide=True
        )
        self.reload()

    def verify(self, qualification):
        self.call(
            lambda: self.service.verify(qualification.id),
            lambda q: self._done(tr("{0} validée.", q.label)),
            tr("Impossible de valider la matière"),
        )

    def withdraw(self, qualification):
        values = self.ask(
            self,
            tr("Retirer la matière ?"),
            tr(
                "{0} ne pourra plus être confiée à cet enseignant. L'historique est conservé ; le serveur refuse le "
                "retrait si un cours actif l'utilise.",
                qualification.label,
            ),
            save_text=tr("Retirer"),
            danger=True,
        )
        if values:
            self.call(
                lambda: self.service.reject(qualification.id, values["reason"]),
                lambda q: self._done(tr("{0} retirée.", q.label)),
                tr("Impossible de retirer la matière"),
            )

    def grant_override(self):
        if self.verdict is None:
            return
        subject, level = self.subject.currentData(), self.level.currentData()
        values = self.ask(
            self,
            tr("Accorder une dérogation ?"),
            tr(
                "{0} : le serveur a répondu « {1} ». La dérogation est tracée (auteur, motif, date, portée).",
                self.verdict.subject_label,
                self.verdict.result_label,
            ),
            save_text=tr("Accorder la dérogation"),
            with_expiry=True,
        )
        if values:
            self.call(
                lambda: self.service.grant_override(
                    self.teacher.id, subject, values["reason"], level_id=level, expires_at=values["expires_at"]
                ),
                lambda _: (self._done(tr("Dérogation accordée.")), self.check()),
                tr("Impossible d'accorder la dérogation"),
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

    def __init__(self, teacher, qualifications, rates, parent=None, *, with_remuneration=False, account=None):
        super().__init__(tr("Fiche de l'enseignant — {0}", teacher.name), "", parent, save_text=tr("Fermer"), width=640)
        self.action = None
        self.cancel_button.hide()

        self.add_section(tr("Identité"))
        self.body.addWidget(
            _grid(
                [
                    (tr("Nom"), teacher.last_name),
                    (tr("Prénom(s)"), teacher.first_name),
                    ("E-mail", teacher.email or "—"),
                    (tr("Téléphone"), teacher.phone or "—"),
                    (tr("Adresse"), teacher.address or "—"),
                ]
            )
        )
        self.add_section(tr("Profil professionnel"))
        self.body.addWidget(
            _grid(
                [
                    (tr("Matricule"), teacher.number),
                    (tr("Fonction"), tr("Enseignant")),
                    (tr("Statut"), teacher.status_label),
                    (tr("Statut professionnel"), PROFESSIONAL_STATUSES.get(teacher.professional_status, "—")),
                    (tr("Statut d'emploi"), EMPLOYMENT_STATUSES.get(teacher.employment_status, "—")),
                    (tr("Date d'embauche"), f"{teacher.hire_date:%d/%m/%Y}" if teacher.hire_date else "—"),
                    (tr("Catégorie pédagogique"), teacher.category_label or "—"),
                    (tr("Matière principale"), teacher.primary_subject_label or "—"),
                ]
            )
        )
        self.edit_button = self._action(tr("Modifier la fiche…"), "edit")
        self.body.addWidget(self.edit_button, 0, Qt.AlignLeft)

        self.add_section("Qualifications")
        live = [q for q in qualifications if q.status != "REJECTED"]
        self.body.addWidget(
            _grid([(q.label, f"{q.status_label} · {COMPATIBILITY_RESULTS.get(q.current, q.current)}") for q in live])
            if live
            else QLabel(tr("Aucune matière."), objectName="help")
        )
        self.qualifications_button = self._action(tr("Gérer les qualifications…"), "qualifications")
        self.body.addWidget(self.qualifications_button, 0, Qt.AlignLeft)

        self.add_section(tr("Planning"))
        self.body.addWidget(
            _grid(
                [
                    (
                        tr("Cours actifs"),
                        "—" if teacher.active_course_count is None else str(teacher.active_course_count),
                    ),
                    (
                        tr("Séances à venir"),
                        "—" if teacher.upcoming_session_count is None else str(teacher.upcoming_session_count),
                    ),
                    (
                        tr("Emploi du temps"),
                        tr("PDF disponible dans le module Documents (emploi du temps de l'enseignant)."),
                    ),
                ]
            )
        )
        self.add_section(tr("Rémunération"), tr("Lecture seule : la paie se gère dans son module."))
        current = [r for r in rates if r.get("active")]
        self.body.addWidget(
            _grid(
                [
                    (
                        tr("Taux de vacation"),
                        tr(
                            "{0} {1} / {2} min depuis le {3}",
                            r["vacation_rate"],
                            r.get("currency", ""),
                            r.get("vacation_minutes", 60),
                            r["effective_from"],
                        ),
                    )
                    for r in current
                ]
            )
            if current
            else QLabel(tr("Aucun taux de vacation défini."), objectName="help")
        )
        self.remuneration_button = None
        if with_remuneration:
            self.remuneration_button = self._action(tr("Rémunération et paies…"), "remuneration")
            self.body.addWidget(self.remuneration_button, 0, Qt.AlignLeft)
        self._account_section(teacher, account)
        self.finish(required_note=False)
        self.save_button.setFocus()

    def _account_section(self, teacher, account):
        """Account lifecycle (ADR 0024): state and the actions the state allows.
        The activation code is never shown here (only once, when generated)."""
        self.add_section(tr("Compte"), tr("Identifiant de connexion et activation par l'enseignant lui-même."))
        self.account_buttons = {}
        if account is None:
            self.body.addWidget(QLabel(tr("État du compte indisponible."), objectName="help"))
            return
        explanations = {
            "ACTIVE": tr("L'enseignant a défini son mot de passe : il peut se connecter."),
            "PENDING_ACTIVATION": tr("Un code d'activation a été remis ; il n'a pas encore été utilisé."),
            "NOT_ACTIVATED": tr("Aucun mot de passe : générez un code d'activation et remettez-le à l'enseignant."),
            "DISABLED": tr("Compte suspendu : connexion impossible, sessions fermées."),
        }
        rows = [
            (tr("État"), account.state_label),
            (tr("Identifiant"), account.login or "—"),
            (tr("Détail"), explanations.get(account.state, "")),
        ]
        if account.pending_expires_at:
            rows.append((tr("Code valable jusqu'au"), f"{account.pending_expires_at:%d/%m/%Y %H:%M}"))
        if account.activated_at:
            rows.append((tr("Activé le"), f"{account.activated_at:%d/%m/%Y %H:%M}"))
        if account.last_login:
            rows.append((tr("Dernière connexion"), f"{account.last_login:%d/%m/%Y %H:%M}"))
        self.body.addWidget(_grid(rows))
        actions = {
            "NOT_ACTIVATED": [("issue_code", tr("Générer un code d'activation…"))],
            "PENDING_ACTIVATION": [
                ("issue_code", tr("Générer un nouveau code…")),
                ("revoke_code", tr("Révoquer le code")),
            ],
            "ACTIVE": [],
            "DISABLED": [("enable_account", tr("Réactiver le compte"))],
        }.get(account.state, [])
        if account.state != "DISABLED":
            actions.append(("disable_account", tr("Suspendre le compte…")))
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        for name, text in actions:
            widget = self._action(text, name)
            if name == "disable_account":
                set_variant(widget, "danger")
            self.account_buttons[name] = widget
            line.addWidget(widget)
        line.addStretch()
        self.body.addWidget(row)

    def _action(self, text, action):
        widget = button(text)
        widget.clicked.connect(lambda: self._start(action))
        return widget

    def _start(self, action):
        self.action = action
        self.accept()


class ActivationCodeDialog(FormDialog):
    """Shows a new activation code ONCE. It is not stored by the desktop and
    cannot be displayed again (only regenerated)."""

    def __init__(self, teacher_name, issued, parent=None):
        super().__init__(
            tr("Code d'activation"),
            tr("À remettre en main propre à {0}. Il ne sera plus affiché.", teacher_name),
            parent,
            save_text=tr("J'ai noté le code"),
            width=520,
        )
        self.cancel_button.hide()
        self.code = QLabel(issued.code, objectName="activationCode")
        self.code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.code.setAlignment(Qt.AlignCenter)
        font = self.code.font()
        font.setFamily(tr("Consolas"))
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        self.code.setFont(font)
        self.body.addWidget(self.code)
        self.copy_button = button(tr("Copier"))
        self.copy_button.clicked.connect(self._copy)
        self.body.addWidget(self.copy_button, 0, Qt.AlignCenter)
        expires = f"{issued.expires_at:%d/%m/%Y à %H:%M}" if issued.expires_at else "—"
        steps = QLabel(
            tr(
                "Valable une seule fois, jusqu'au {0}.\nL'enseignant l'utilise pour choisir lui-même son premier mot "
                "de passe, puis se connecte avec l'identifiant « {1} ».\nSi le code est perdu ou divulgué : "
                "générez-en un nouveau (l'ancien est révoqué).",
                expires,
                issued.account.login,
            ),
            objectName="help",
        )
        steps.setWordWrap(True)
        self.body.addWidget(steps)
        self.finish(required_note=False)

    def _copy(self):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.code.text())
        self.copy_button.setText(tr("Copié"))
