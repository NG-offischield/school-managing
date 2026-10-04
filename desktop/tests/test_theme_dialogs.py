"""Readability guard-rails: theme contrast (WCAG 2.1), effective colours of
the dialogs once styled, button states, keyboard, screen sizes.

These tests fail if a future change brings back dark-on-dark text (the bug
seen on Windows dark mode), an unreadable placeholder or a primary button
that looks like the secondary one."""

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLabel, QLineEdit, QPushButton

from school_admin.models import Category, Identity, Subject
from school_admin.ui.dialogs.category_dialog import CategoryDialog
from school_admin.ui.dialogs.subject_dialog import CHOOSE_CATEGORY, SubjectDialog
from school_admin.ui.main_window import MainWindow
from school_admin.ui.tasks import ImmediateRunner
from school_admin.ui.theme import TOKENS, build_stylesheet, contrast_ratio
from school_admin.ui.widgets import ConfirmDialog

CATEGORIES = [Category("c1", "SCI", "Scientifique", "", True), Category("c2", "LIT", "Littéraire", "", True)]


def color(widget, role):
    widget.ensurePolished()
    return widget.palette().color(role).name()


def shown(dialog):
    dialog.resize(dialog.sizeHint())
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    return dialog


# =============================================================================
# Theme
# =============================================================================


@pytest.mark.parametrize(
    ("foreground", "background", "minimum"),
    [
        ("text", "panel", 4.5),
        ("text", "background", 4.5),
        ("text_secondary", "panel", 4.5),
        ("text_secondary", "background", 4.5),
        ("placeholder", "field", 4.5),
        ("text_disabled", "disabled_fill", 4.5),
        ("text_disabled", "field_disabled", 4.5),
        ("on_primary", "primary", 4.5),
        ("on_primary", "primary_hover", 4.5),
        ("on_primary", "primary_pressed", 4.5),
        ("on_primary", "danger", 4.5),
        ("danger", "panel", 4.5),
        ("error", "error_bg", 4.5),
        ("success", "success_bg", 4.5),
        ("warning", "warning_bg", 4.5),
        ("info", "info_bg", 4.5),
        ("text", "primary_soft", 4.5),
        ("text", "row_alt", 4.5),
        ("sidebar_text", "sidebar", 4.5),
        ("sidebar_muted", "sidebar", 4.5),
        ("sidebar_text", "sidebar_hover", 4.5),
        ("field_border", "field", 3.0),
        ("field_border", "background", 3.0),
        ("focus", "field", 3.0),
    ],
)
def test_token_contrast_meets_wcag(foreground, background, minimum):
    ratio = contrast_ratio(getattr(TOKENS, foreground), getattr(TOKENS, background))
    assert ratio >= minimum, f"{foreground} on {background}: {ratio:.2f}"


def test_theme_ignores_the_system_dark_mode(qapp):
    assert qapp.property("theme_base_style") == "QFusionStyle"  # wrapped by QStyleSheetStyle
    palette = qapp.palette()
    assert palette.color(QPalette.Window).name() == TOKENS.background.lower()
    assert palette.color(QPalette.WindowText).name() == TOKENS.text.lower()
    assert palette.color(QPalette.Base).name() == TOKENS.field.lower()
    assert palette.color(QPalette.PlaceholderText).name() == TOKENS.placeholder.lower()
    sheet = build_stylesheet()
    assert "QDialog, QMessageBox" in sheet and "QComboBox QAbstractItemView" in sheet  # popups themed too


# =============================================================================
# Dialogs
# =============================================================================


def test_subject_dialog_is_readable(qapp):
    dialog = shown(SubjectDialog(CATEGORIES))
    background = color(dialog, QPalette.Window)
    assert contrast_ratio(background, "#FFFFFF") < 1.1  # light dialog
    labels = [label for label in dialog.findChildren(QLabel) if label.isVisible()]
    assert labels
    for label in labels:
        assert label.text().strip(), "empty label"
        ratio = contrast_ratio(color(label, QPalette.WindowText), background)
        assert ratio >= 4.5, f"{label.text()!r}: {ratio:.2f}"
    for field in dialog.findChildren(QLineEdit) + dialog.findChildren(QComboBox):
        assert contrast_ratio(color(field, QPalette.Text), color(field, QPalette.Base)) >= 4.5
    dialog.close()


def test_subject_dialog_structure_order_and_buttons(qapp):
    dialog = shown(SubjectDialog(CATEGORIES))
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    order = [texts.index(t) for t in ("Nouvelle matière", "Code *", "Nom *", "Catégorie *", "Type", "Options")]
    assert order == sorted(order)  # title, then Code, Nom, Catégorie, Type, options
    assert dialog.category.currentText() == CHOOSE_CATEGORY and not dialog.category.isEditable()
    assert dialog.findChildren(QCheckBox)[0].text() == "Visible sur le site public de l'école"
    buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
    assert set(buttons) == {"Annuler", "Enregistrer"}
    assert buttons["Enregistrer"].property("variant") == "primary"
    assert buttons["Annuler"].property("variant") == "secondary"
    # Visual weight: the main action is filled, the secondary one is not.
    assert buttons["Annuler"].x() < buttons["Enregistrer"].x()
    assert color(buttons["Annuler"], QPalette.Button) != color(buttons["Enregistrer"], QPalette.Button)
    dialog.close()


def test_save_state_follows_the_required_fields(qapp):
    dialog = shown(SubjectDialog(CATEGORIES))
    assert not dialog.save_enabled
    assert dialog.status.text() == "Pour enregistrer, complétez : Code, Nom, Catégorie."
    assert dialog.save_button.toolTip() == dialog.status.text()  # the reason is visible and in the tooltip
    disabled = dialog.save_button
    assert contrast_ratio(color(disabled, QPalette.ButtonText), color(disabled, QPalette.Button)) >= 4.5
    QTest.keyClicks(dialog.code, "MATH")
    QTest.keyClicks(dialog.name, "Maths")  # ASCII: QTest cannot type accents headless
    assert not dialog.save_enabled and dialog.status.text() == "Pour enregistrer, complétez : Catégorie."
    dialog.category.setCurrentIndex(2)  # selection change
    assert dialog.save_enabled and dialog.status.text() == ""
    assert dialog.values() == {
        "code": "MATH",
        "name": "Maths",
        "category_id": "c2",
        "subject_type": "THEORETICAL",
        "public_visible": False,
    }
    primary = dialog.save_button
    assert contrast_ratio(color(primary, QPalette.ButtonText), color(primary, QPalette.Button)) >= 4.5
    dialog.category.setCurrentIndex(0)  # back to "Choisir une catégorie…"
    assert not dialog.save_enabled
    dialog.close()


def test_keyboard_escape_closes_enter_saves_only_when_valid(qapp):
    dialog = shown(SubjectDialog(CATEGORIES))
    QTest.keyClick(dialog, Qt.Key_Return)
    assert dialog.result() != QDialog.Accepted and dialog.isVisible()  # invalid: Enter does nothing
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert not dialog.isVisible() and dialog.result() == QDialog.Rejected
    dialog = shown(CategoryDialog())
    assert dialog.focusWidget() is dialog.code
    QTest.keyClicks(dialog.code, "SCI")
    QTest.keyClick(dialog.code, Qt.Key_Tab)
    assert dialog.focusWidget() is dialog.name  # logical tab order
    QTest.keyClicks(dialog.name, "Scientifique")
    QTest.keyClick(dialog.name, Qt.Key_Return)
    assert dialog.result() == QDialog.Accepted


def test_edit_dialogs_keep_the_code_and_explain_it(qapp):
    category = CategoryDialog(category=Category("c1", "SCI", "Scientifique", "Maths", True))
    assert category.windowTitle() == "Modifier la catégorie" and category.code.isReadOnly()
    assert category.save_enabled and "ne peut plus être modifié" in " ".join(
        label.text() for label in category.findChildren(QLabel)
    )
    subject = Subject("s1", "MATH", "Maths", "old", "OLD — Ancienne", "PRACTICAL", True, True)
    dialog = SubjectDialog(CATEGORIES, subject=subject)
    assert dialog.category.currentText() == "OLD — Ancienne (inactive)" and dialog.save_enabled
    assert dialog.subject_type.currentData() == "PRACTICAL" and dialog.public_visible.isChecked()


def test_confirmation_dialog_is_explicit(qapp):
    dialog = shown(
        ConfirmDialog("Désactiver la matière ?", "Texte explicatif.", confirm_text="Désactiver", danger=True)
    )
    buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
    assert set(buttons) == {"Annuler", "Désactiver"}
    assert buttons["Désactiver"].property("variant") == "danger-solid"
    assert buttons["Annuler"].isDefault()  # Enter keeps the safe choice
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert dialog.result() == QDialog.Rejected


# =============================================================================
# Screen sizes
# =============================================================================


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1920, 1080)])
def test_dialogs_fit_the_screen_without_cutting(qapp, size):
    for dialog in (SubjectDialog(CATEGORIES), CategoryDialog()):
        hint = dialog.sizeHint()
        assert hint.width() <= size.width() - 100 and hint.height() <= size.height() - 100
        shown(dialog)
        for widget in dialog.findChildren(QLabel) + dialog.findChildren(QPushButton):
            if widget.isVisible():
                geometry = widget.geometry()
                assert dialog.rect().contains(geometry), f"{widget.text()!r} cut"
                assert widget.width() >= widget.minimumSizeHint().width() or isinstance(widget, QLabel)
        dialog.close()


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1920, 1080), QSize(1100, 640)])
def test_shell_keeps_room_for_content(qapp, size):
    identity = Identity("u1", "admin", "Ada Admin", "TEST01", "École Test", ("SUPER_ADMIN",))
    window = MainWindow(identity, {}, ImmediateRunner())
    window.resize(size)
    window.show()
    QTest.qWaitForWindowExposed(window)
    sidebar = window.findChild(type(window.centralWidget()), None)
    assert window.nav.width() <= 256
    assert window.stack.width() >= size.width() - 260 - 10  # the sidebar never crushes the content
    assert window.logout_button.isVisible() and window.rect().contains(
        window.logout_button.mapTo(window, window.logout_button.rect().bottomRight())
    )
    assert sidebar is not None
    window.close()


def test_sidebar_coming_soon_entries_are_secondary_but_readable(qapp):
    identity = Identity("u1", "admin", "Ada Admin", "TEST01", "École Test", ("SUPER_ADMIN",))
    window = MainWindow(identity, {}, ImmediateRunner())
    items = {window.nav.item(i).text(): window.nav.item(i) for i in range(window.nav.count())}
    soon = items["Communication   ·  Bientôt"].foreground().color().name()
    section = items["GESTION ACADÉMIQUE"].foreground().color().name()
    assert soon == section == TOKENS.sidebar_muted.lower()
    assert contrast_ratio(soon, TOKENS.sidebar) >= 4.5  # secondary, still readable
    assert "color" not in build_stylesheet().split("#sidebar QListWidget::item {")[1].split("}")[0]
    window.close()


def test_dashboard_explains_known_rules(qapp):
    from school_admin.api.errors import ValidationFailed
    from school_admin.messages import explain

    error = ValidationFailed("Cette opération enfreint une règle métier.", details={"rule": "no_current_year"})
    assert explain(error) == "Aucune année scolaire courante n'est définie."
    assert explain(ValidationFailed("Message serveur.")) == "Message serveur."
