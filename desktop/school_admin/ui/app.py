"""Application controller: login -> shell -> logout / session expiry -> login."""

import sys

from PySide6.QtWidgets import QApplication

from ..api.client import ApiClient
from ..auth.device import device_info
from ..auth.session import AuthService
from ..auth.token_store import KeyringTokenStore
from ..config import load_config, save_preference
from ..realtime import RealtimeClient, socket_url
from ..services.accounts import AccountService
from ..services.catalog import CategoryService, SubjectService
from ..services.classes import ClassService, ReferenceService
from ..services.communication import CommunicationService
from ..services.courses import CourseService
from ..services.dashboard import DashboardService
from ..services.documents import DocumentService
from ..services.finance import FinanceService
from ..services.me import MeService
from ..services.parents import ParentAdminService
from ..services.payroll import PayrollService
from ..services.planning import PlanningService
from ..services.plans import PlanService
from ..services.structure import LevelService, YearService
from ..services.students import StudentService
from ..services.teachers import TeacherService
from .branding import SOFTWARE_NAME, software_icon
from .dialogs.account_dialog import AccountDialog
from .login_window import LoginWindow
from .main_window import MainWindow
from .pages.catalog_pages import CategoriesPage, SubjectsPage
from .pages.classes_page import ClassesPage
from .pages.communication_page import CommunicationPage
from .pages.courses_page import CoursesPage
from .pages.dashboard_page import DashboardPage
from .pages.documents_page import DocumentsPage
from .pages.finance_page import FinancePage
from .pages.parents_page import ParentsPage
from .pages.payroll_page import PayrollPage
from .pages.planning_page import PlanningPage
from .pages.structure_pages import LevelsPage, YearsPage
from .pages.students_page import StudentsPage
from .pages.teachers_page import TeachersPage
from .tasks import TaskRunner
from .theme import THEME_MODES, apply_theme, follow_system_scheme


class AppController:
    def __init__(self, api, auth, runner, config, *, page_options=None, realtime_factory=None):
        # realtime_factory(api, url) -> RealtimeClient; None = no live connection (tests).
        self.realtime_factory = realtime_factory
        self.realtime = None
        self.api, self.auth, self.runner, self.config = api, auth, runner, config
        self.page_options = page_options or {}  # test hooks (dialogs, confirmation)
        self.config_directory = None  # desktop.json location (None = the user's; tests: a temp dir)
        self.categories = CategoryService(api)
        self.subjects = SubjectService(api)
        self.dashboard = DashboardService(api)
        self.classes = ClassService(api)
        self.references = ReferenceService(api)
        self.years = YearService(api)
        self.levels = LevelService(api)
        self.students = StudentService(api)
        self.teachers = TeacherService(api)
        self.courses = CourseService(api)
        self.planning = PlanningService(api)
        self.finance = FinanceService(api)
        self.payroll = PayrollService(api)
        self.communication = CommunicationService(api)
        self.accounts = AccountService(api)
        self.parents = ParentAdminService(api)
        self.documents = DocumentService(api)
        self.plans = PlanService(api)
        self.me = MeService(api)
        self.login_window = LoginWindow(auth, runner, config)
        self.login_window.logged_in.connect(self.show_shell)
        self.main_window = None

    def page_factories(self):
        options = self.page_options
        return {
            "dashboard": lambda: DashboardPage(self.dashboard, self.runner),
            "years": lambda: YearsPage(self.years, self.runner, **options.get("years", {})),
            "levels": lambda: LevelsPage(self.levels, self.runner, **options.get("levels", {})),
            "categories": lambda: CategoriesPage(self.categories, self.runner, **options.get("categories", {})),
            "subjects": lambda: SubjectsPage(
                self.subjects, self.categories, self.runner, **options.get("subjects", {})
            ),
            "classes": lambda: ClassesPage(self.classes, self.references, self.runner, **options.get("classes", {})),
            "students": lambda: StudentsPage(
                self.students, self.references, self.runner, **options.get("students", {})
            ),
            "parents": lambda: ParentsPage(self.parents, self.runner, **options.get("parents", {})),
            "teachers": lambda: TeachersPage(
                self.teachers,
                self.categories,
                self.subjects,
                self.references,
                self.runner,
                payroll=self.payroll,
                accounts=self.accounts,
                **options.get("teachers", {}),
            ),
            "planning": lambda: PlanningPage(
                self.planning,
                self.references,
                self.teachers,
                self.subjects,
                self.courses,
                self.runner,
                **options.get("planning", {}),
            ),
            "finance": lambda: FinancePage(self.finance, self.runner, **options.get("finance", {})),
            "payroll": lambda: PayrollPage(
                self.payroll,
                self.finance,
                self.references,
                self.teachers,
                self.runner,
                **options.get("payroll", {}),
            ),
            "communication": lambda: CommunicationPage(
                self.communication,
                self.references,
                self.runner,
                realtime=self.realtime,
                **options.get("communication", {}),
            ),
            "documents": lambda: DocumentsPage(
                self.documents,
                self.finance,
                self.payroll,
                self.references,
                self.teachers,
                self.runner,
                plans=self.plans,
                **options.get("documents", {}),
            ),
            "courses": lambda: CoursesPage(
                self.courses, self.subjects, self.references, self.runner, **options.get("courses", {})
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
        if self.realtime is not None:
            self.realtime.stop()
            self.realtime.deleteLater()
            self.realtime = None
        if self.main_window is not None:
            self.main_window.close()
            self.main_window.deleteLater()
            self.main_window = None
        self.login_window.reset(message)
        self.login_window.show()

    def show_shell(self, identity):
        self.login_window.hide()
        if self.realtime_factory is not None:  # the existing ws/v1/realtime/ endpoint
            self.realtime = self.realtime_factory(self.api, socket_url(self.config.api_url))
            self.realtime.session_expired.connect(lambda: self.show_login("Votre session a expiré : reconnectez-vous."))
            self.realtime.start()
        self.main_window = MainWindow(identity, self.page_factories(), self.runner)
        self.main_window.logout_requested.connect(self.logout)
        self.main_window.account_requested.connect(self.open_account)
        self.main_window.session_expired.connect(lambda: self.show_login("Votre session a expiré : reconnectez-vous."))
        self.main_window.show()

    def account_dialog(self):
        dialog = AccountDialog(
            self.me, self.runner, self.main_window, theme_mode=self.theme_mode(), on_theme=self.set_theme
        )
        dialog.signed_out.connect(self.logout)  # every device disconnected: this one too
        dialog.session_expired.connect(lambda: self.show_login("Votre session a expiré : reconnectez-vous."))
        return dialog

    def theme_mode(self):
        app = QApplication.instance()
        return (app.property("theme_mode") if app else None) or self.config.theme

    def set_theme(self, mode):
        """Applied at once (open windows re-themed) and kept in desktop.json."""
        if mode not in THEME_MODES:
            return False
        apply_theme(QApplication.instance(), mode)
        return save_preference("theme", mode, self.config_directory)

    def open_account(self):
        self.account_dialog().exec()

    def logout(self):
        self.runner.run(
            self.auth.logout,
            lambda _: self.show_login("Vous êtes déconnecté."),
            lambda _exc: self.show_login("Vous êtes déconnecté."),
        )


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(SOFTWARE_NAME)
    app.setWindowIcon(software_icon())
    config = load_config()
    apply_theme(app, config.theme)  # Système (default) / Clair / Sombre, desktop.json
    follow_system_scheme(app)
    api = ApiClient(config.api_url, timeout=config.timeout, language=config.language)
    auth = AuthService(api, device_info(), persistent_store=KeyringTokenStore(config.api_url))
    controller = AppController(
        api, auth, TaskRunner(), config, realtime_factory=lambda client, url: RealtimeClient(client, url)
    )
    controller.start()
    code = app.exec()
    api.close()
    return code
