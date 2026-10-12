"""« Mon compte » of the connected administrator (header button): read-only
identity, editable fields decided by the server, photo, password, devices.
Widget tests against the fake backend (tests/fake_me.py), not E2E."""

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

from .test_communication_documents import controller, open_module  # noqa: F401 (fixture)


def png():
    image = QImage(200, 200, QImage.Format_RGB32)
    image.fill(Qt.darkCyan)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def account(ctrl, **hooks):
    open_module(ctrl, "dashboard")
    dialog = ctrl.account_dialog()
    for name, value in hooks.items():
        setattr(dialog, name, value)
    return dialog


def test_header_button_and_read_only_identity(controller, backend):  # noqa: F811
    shell, _ = open_module(controller, "dashboard")
    assert shell.account_button.text() == "Mon compte" and shell.account_button.isEnabled()
    dialog = controller.account_dialog()
    assert dialog.name_label.text() == "Ada Admin" and dialog.email_label.text() == "admin@school.local"
    assert "École Test" in dialog.role_label.text()
    assert set(dialog.inputs) == {"phone", "address"}  # what the server declares editable, nothing more
    assert isinstance(dialog.inputs["address"], QPlainTextEdit) and isinstance(dialog.inputs["phone"], QLineEdit)
    assert not any(isinstance(w, QLineEdit) and w.text() == "admin@school.local" for w in dialog.inputs.values())
    dialog.close()


def test_only_changed_fields_are_sent_and_errors_explained(controller, backend):  # noqa: F811
    dialog = account(controller)
    dialog.save_details()
    assert "Aucune modification" in dialog.banner.plain_text() and backend.me_patches == []
    dialog.inputs["phone"].setText("699 00 11 22")
    dialog.save_details()
    assert backend.me_patches == [{"phone": "699 00 11 22"}]
    assert dialog.banner.plain_text() == "Coordonnées enregistrées."
    dialog.inputs["phone"].setText("abc")
    dialog.save_details()
    assert "Numéro de téléphone invalide." in dialog.banner.plain_text()
    assert backend.me_values["phone"] == "699 00 11 22"
    dialog.close()


def test_photo_refused_then_set_then_removed(controller, backend, tmp_path):  # noqa: F811
    fake = tmp_path / "secret" / "photo.png"
    fake.parent.mkdir()
    fake.write_bytes(b"MZ\x90 not an image")
    dialog = account(controller, choose_photo=lambda parent: str(fake))
    assert not dialog.remove_photo_button.isEnabled()
    dialog.change_photo()
    assert "Ce fichier n'est pas une image lisible." in dialog.banner.plain_text() and backend.me_photo is None
    fake.write_bytes(png())
    dialog.change_photo()
    assert backend.me_photo == fake.read_bytes() and dialog.banner.plain_text() == "Photo mise à jour."
    assert not dialog.photo.pixmap().isNull() and dialog.remove_photo_button.isEnabled()
    dialog.remove_photo()
    assert backend.me_photo is None and dialog.photo.pixmap().isNull() and dialog.photo.text() == "AA"
    dialog.close()


def test_password_change_checks_confirmation_and_current(controller, backend):  # noqa: F811
    dialog = account(controller)
    dialog.current_password.setText("faux")
    dialog.new_password.setText("Nouveau-Mot-2026!")
    dialog.confirm_password.setText("autre")
    dialog.change_password()
    assert "confirmation ne correspond pas" in dialog.banner.plain_text()
    dialog.confirm_password.setText("Nouveau-Mot-2026!")
    dialog.change_password()
    assert "Current password is incorrect." in dialog.banner.plain_text() and backend.me_password == "Ancien-Mot-2026!"
    dialog.current_password.setText("Ancien-Mot-2026!")
    dialog.change_password()
    assert backend.me_password == "Nouveau-Mot-2026!" and dialog.current_password.text() == ""
    assert dialog.table.rowCount() == 1  # the other devices were disconnected
    dialog.close()


def test_devices_this_one_protected_others_revocable_revoke_all_logs_out(controller, backend):  # noqa: F811
    dialog = account(controller, confirm=lambda *a, **k: True)
    assert dialog.table.rowCount() == 2 and dialog.table.item(0, 2).text() == "Ce poste"
    dialog.table.selectRow(0)
    assert not dialog.revoke_button.isEnabled()  # this computer: use « Se déconnecter »
    dialog.table.selectRow(1)
    assert dialog.revoke_button.isEnabled()
    dialog.revoke_selected()
    assert [s["id"] for s in backend.me_sessions] == ["s-this"] and "Pixel 7a" in dialog.banner.plain_text()
    dialog.revoke_all()
    assert backend.me_revoked_all == 1
    assert controller.main_window is None  # logged out locally too: back to the login window
    assert controller.login_window.banner.plain_text() == "Vous êtes déconnecté."


def test_dialog_fits_small_screens(controller, backend):  # noqa: F811
    for size in (QSize(1366, 768), QSize(1280, 720), QSize(1024, 768), QSize(800, 480)):
        dialog = account(controller)
        dialog.fit_to(size)
        assert dialog.width() <= size.width() and dialog.height() <= size.height()
        assert dialog.save_button.isVisibleTo(dialog)  # « Fermer » always reachable (the form scrolls)
        dialog.close()
