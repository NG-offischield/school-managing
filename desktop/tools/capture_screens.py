"""Developer tool: render the real screens against a running backend and save
PNG captures (visual review of contrast and layout, e.g. after a theme change).

    set SCHOOL_ADMIN_E2E_URL=http://127.0.0.1:8000/api/v1/
    set SCHOOL_ADMIN_E2E_USER=admin
    set SCHOOL_ADMIN_E2E_PASSWORD=...          (environment only, never committed)
    python tools/capture_screens.py OUTPUT_DIR [WIDTHxHEIGHT ...]

Creates one category and one subject (random codes) on the target backend.
"""

import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from school_admin.api import ApiClient  # noqa: E402
from school_admin.auth.device import device_info  # noqa: E402
from school_admin.auth.session import AuthService  # noqa: E402
from school_admin.auth.token_store import MemoryTokenStore  # noqa: E402
from school_admin.config import AppConfig  # noqa: E402
from school_admin.ui.app import AppController  # noqa: E402
from school_admin.ui.dialogs.category_dialog import CategoryDialog  # noqa: E402
from school_admin.ui.dialogs.subject_dialog import SubjectDialog  # noqa: E402
from school_admin.ui.tasks import ImmediateRunner  # noqa: E402
from school_admin.ui.theme import ensure_app  # noqa: E402
from school_admin.ui.widgets import ConfirmDialog  # noqa: E402


def save(widget, path):
    widget.show()
    QTest.qWaitForWindowExposed(widget)
    QTest.qWait(50)
    widget.grab().save(str(path))
    print("saved", path)


def main(out, sizes):
    url, user, password = (
        os.environ[k] for k in ("SCHOOL_ADMIN_E2E_URL", "SCHOOL_ADMIN_E2E_USER", "SCHOOL_ADMIN_E2E_PASSWORD")
    )
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ensure_app()
    api = ApiClient(url)
    controller = AppController(
        api,
        AuthService(api, device_info(), persistent_store=MemoryTokenStore()),
        ImmediateRunner(),
        AppConfig(api_url=url),
    )
    login = controller.login_window
    login.resize(1366, 768)
    save(login, out / "01-login.png")
    login.identifier.setText(user)
    login.password.setText(password)
    login.attempt()
    shell = controller.main_window
    if shell is None:
        raise SystemExit(f"login failed: {login.banner.plain_text()}")
    suffix = uuid.uuid4().hex[:4].upper()
    for size in sizes:
        width, height = (int(v) for v in size.split("x"))
        shell.resize(QSize(width, height))
        shell.open("dashboard")
        save(shell, out / f"02-dashboard-{size}.png")
        categories = shell.open("categories")
        categories.open_dialog = lambda category=None: {
            "code": f"UI{suffix}",
            "name": f"Catégorie {suffix}",
            "description": "Créée par capture_screens",
        }
        if size == sizes[0]:
            categories.add()
        save(shell, out / f"03-categories-{size}.png")
        subjects = shell.open("subjects")
        save(shell, out / f"05-subjects-{size}.png")
    active = controller.categories.list(active=True)
    empty = SubjectDialog(active)
    save(empty, out / "04-subject-dialog-empty.png")
    filled = SubjectDialog(active)
    filled.code.setText(f"M{suffix}")
    filled.name.setText("Mathématiques appliquées")
    filled.category.setCurrentIndex(1)
    save(filled, out / "04-subject-dialog-filled.png")
    save(CategoryDialog(), out / "04-category-dialog.png")
    save(
        ConfirmDialog(
            "Désactiver la matière ?",
            "« MATH — Mathématiques » ne sera plus proposée dans les nouvelles saisies. Son historique est conservé.",
            confirm_text="Désactiver",
            danger=True,
        ),
        out / "06-confirm.png",
    )
    subjects.open_dialog = lambda cats, subject=None: {
        "code": f"M{suffix}",
        "name": "Mathématiques appliquées",
        "category_id": cats[0].id,
        "subject_type": "THEORETICAL",
        "public_visible": False,
    }
    subjects.add()
    shell.resize(QSize(1366, 768))
    save(shell, out / "07-subject-created.png")
    controller.auth.logout()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or ["1366x768", "1920x1080"])
