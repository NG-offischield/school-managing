"""Diagnostic log of the desktop client.

An installed, windowed client has no console: an unexpected error would vanish.
It is written to a per-user log file instead (%LOCALAPPDATA% on Windows), kept
small (3 files of 1 MB), and the user sees a readable message.

Never in the log: passwords, tokens, request bodies. Only the program version,
the server it talks to (scheme and host), and the traceback of an unexpected
error (which holds code locations, not credentials).
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

from .config import APP_DIR_NAME

LOG_NAME = "desktop.log"
logger = logging.getLogger("school_admin")


def log_dir():
    """Per-user, never synchronised between machines (LOCALAPPDATA, not APPDATA)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / APP_DIR_NAME / "logs"


def setup_logging(directory=None):
    """File log of the client; returns its path (None if it cannot be written:
    the client then runs without a log rather than not at all)."""
    path = Path(directory or log_dir()) / LOG_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return path


def server_label(api_url):
    """Scheme and host only: the log never needs more of the configured URL."""
    parsed = urlparse(api_url)
    return f"{parsed.scheme}://{parsed.hostname or '?'}" + (f":{parsed.port}" if parsed.port else "")


def install_excepthook(show_message=None):
    """An unexpected error is logged with its traceback, and the user is told
    (show_message) instead of the window silently closing."""

    def hook(kind, value, tb):
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, tb)
            return
        logger.error("Erreur inattendue", exc_info=(kind, value, tb))
        if show_message is not None:
            try:
                show_message()
            except Exception:  # noqa: BLE001, S110 - the report itself must never crash the client
                pass

    sys.excepthook = hook
    return hook
