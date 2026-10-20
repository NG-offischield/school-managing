"""Diagnostic log of the installed client (school_admin/diagnostics.py): an
unexpected error is recorded and reported instead of vanishing; the log names
the server by scheme and host only."""

import sys

from school_admin import diagnostics


def test_log_file_and_server_label(tmp_path):
    path = diagnostics.setup_logging(tmp_path)
    assert path == tmp_path / diagnostics.LOG_NAME
    diagnostics.logger.info("Démarrage %s", diagnostics.server_label("https://isbree-api.onrender.com/api/v1/?x=1"))
    for handler in diagnostics.logger.handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "Démarrage https://isbree-api.onrender.com" in text
    assert "/api/v1" not in text and "x=1" not in text
    assert diagnostics.server_label("http://127.0.0.1:8000/api/v1/") == "http://127.0.0.1:8000"


def test_unexpected_error_is_logged_and_reported(tmp_path, monkeypatch):
    path = diagnostics.setup_logging(tmp_path)
    shown = []
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # restored after the test
    hook = diagnostics.install_excepthook(lambda: shown.append(True))
    try:
        raise RuntimeError("panne simulée")
    except RuntimeError:
        hook(*sys.exc_info())
    for handler in diagnostics.logger.handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "Erreur inattendue" in text and "RuntimeError: panne simulée" in text
    assert shown == [True]


def test_an_unwritable_log_never_stops_the_client(tmp_path):
    blocker = tmp_path / "fichier"
    blocker.write_text("x")
    assert diagnostics.setup_logging(blocker / "logs") is None  # a file where the folder should be
