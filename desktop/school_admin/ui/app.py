"""Application controller: login -> shell -> logout / session expiry -> login."""

import sys

from PySide6.QtWidgets import QApplication

from ..api.client import ApiClient
from ..auth.device import device_info
from ..auth.session import AuthService
from ..auth.token_store import KeyringTokenStore
from ..config import load_config
from ..services.catalog import CategoryService, SubjectService
from ..services.dashboard import DashboardService
from .login_window import LoginWindow
from .main_window import MainWindow
from .pages.catalog_pages import CategoriesPage, SubjectsPage
from .pages.dashboard_page import DashboardPage
from .tasks import TaskRunner
from .theme import apply_theme


class AppController:
    def __init__(self, api, auth, runner, config, *, page_options=None):
        self.api, self.auth, self.runner, self.config = api, auth, runner, config
        self.page_options = page_options or {}  # test hooks (dialogs, confirmation)
        self.categories = CategoryService(api)
        self.subjects = SubjectService(api)
        self.dashboard = DashboardService(api)
        self.login_window = LoginWindow(auth, runner, config)
        self.login_window.logged_in.connect(self.show_shell)
        self.main_window = None

    def page_factories(self):
        options = self.page_options
        return {
            "dashboard": lambda: DashboardPage(self.dashboard, self.runner),
            "categories": lambda: CategoriesPage(self.categories, self.runner, **options.get("categories", {})),
            "subjects": lambda: SubjectsPage(
                self.subjects, self.categories, self.runner, **options.get("subjects", {})
            ),
        }

    def start(self):
        """Resume a remembered session if any, otherwise show the login."""
        self.runner.run(
            self.auth.restore,
            lambda identity: self.show_shell(identity) if identity else self.show_login(),
            lambda _exc: self.show_login(),
        )

    def show_login(self, message=None):
        if self.main_window is not None:
            self.main_window.close()
            self.main_window.deleteLater()
            self.main_window = None
        self.login_window.reset(message)
        self.login_window.show()

    def show_shell(self, identity):
        self.login_window.hide()
        self.main_window = MainWindow(identity, self.page_factories(), self.runner)
        self.main_window.logout_requested.connect(self.logout)
        self.main_window.session_expired.connect(lambda: self.show_login("Votre session a expiré : reconnectez-vous."))
        self.main_window.show()

    def logout(self):
        self.runner.run(
            self.auth.logout,
            lambda _: self.show_login("Vous êtes déconnecté."),
            lambda _exc: self.show_login("Vous êtes déconnecté."),
        )


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Administration scolaire")
    apply_theme(app)
    config = load_config()
    api = ApiClient(config.api_url, timeout=config.timeout, language=config.language)
    auth = AuthService(api, device_info(), persistent_store=KeyringTokenStore(config.api_url))
    controller = AppController(api, auth, TaskRunner(), config)
    controller.start()
    code = app.exec()
    api.close()
    return code
