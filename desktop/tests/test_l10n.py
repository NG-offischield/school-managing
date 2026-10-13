"""Français / English on the admin desktop: the catalog covers every French text
of the code, each module (and each of its tabs) shows no French text once in
English, the switch rebuilds the windows on the same module without leaving the
old ones behind, and the choice is kept in desktop.json, sent to the server
(Accept-Language) and independent of the theme."""

import json
import re

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QTableWidget,
    QTabWidget,
)

from school_admin import i18n
from school_admin.config import load_config, save_preference
from school_admin.i18n import Labels, Texts, Tr, tr
from school_admin.i18n_en import ENGLISH
from school_admin.ui.main_window import MainWindow
from school_admin.ui.navigation import NAVIGATION

from .l10n_keys import french_keys
from .test_communication_documents import controller, open_module  # noqa: F401 (fixture)

FIELD = re.compile(r"(?<!\{)\{(\d+)[^{}]*\}")
FRENCH_WORDS = re.compile(
    r"\b(le|la|les|des|du|une|aucun|aucune|vos|votre|vous|nous|pour|avec|dans|est|sont|cette|ces|et|ou|pas|sur"
    r"|par|au|aux|d'|l'|qu'|n'|s')\b|[àâçéèêëîïôûùüÿœ]",
    re.IGNORECASE,
)
# Business data of the fake backend (names of people, school, subjects, typed
# messages, server-written notifications): shown as they are, never translated.
DATA = re.compile(
    r"Lycée|Collège|École|Mathématiques|Français|Sciences physiques|Éducation|Histoire|Réunion|Bénédicte|"
    r"Hélène|Gaëlle|Élodie|Désiré|Thérèse|Clément|Frédéric|Mélanie|Noël|Rentrée|rentrée|Sécurité|Côté|Bâtiment|"
    r"Rez-de-chaussée|Étage|Salle|Cantine|Scolarité|Inscription|Trimestre|trimestre|Février|Décembre|Août|"
    r"Sixième|Cinquième|Laboratoire|Carte d'élève|"
    # a message the fake server writes in French (the real one answers in Accept-Language)
    r"Aucune politique de présence\."
)


@pytest.fixture(autouse=True)
def french_again():
    i18n.set_language("fr")
    i18n.missing.clear()
    yield
    i18n.set_language("fr")


def test_catalog_covers_every_french_text_of_the_code():
    keys = french_keys()
    assert len(keys) > 1500  # not vacuous
    missing = sorted(k for k in keys if k not in ENGLISH)
    assert not missing, f"{len(missing)} texts without English: {missing[:20]}"
    for french, english in ENGLISH.items():
        assert english.strip(), french
        # English may drop a French agreement ({0} = « e », « s »…), never invent a value
        assert set(FIELD.findall(english)) <= set(FIELD.findall(french)), french
    assert not sorted(set(ENGLISH) - keys), "catalog entries no code uses any more"


def test_translation_rules():
    assert tr("Ajouter") == "Ajouter"  # French by default
    i18n.set_language("en")
    assert tr("Ajouter") == "Add"
    assert tr("Add") == "Add"  # idempotent
    assert tr("Impossible de charger les {0}", "rooms") == "Could not load the rooms"
    assert tr("Semaine du {0:%d/%m} au {1:%d/%m/%Y}", *_days()) == "Week of 07/09 to 13/09/2026"
    assert tr("Texte inconnu du catalogue") == "Texte inconnu du catalogue"  # fallback: French, never blank
    assert i18n.missing == {"Texte inconnu du catalogue"}
    i18n.set_language("de")  # unknown code: French
    assert i18n.language() == "fr"


def _days():
    from datetime import date

    return date(2026, 9, 7), date(2026, 9, 13)


def test_labels_texts_and_class_attributes_follow_the_language():
    statuses = Labels({"ACTIVE": "Actif", "CLOSED": "Clôturée"})
    columns = Texts(["Code", "Nom", "Statut"])

    class Page:
        title = Tr("Salles")

    assert statuses["ACTIVE"] == "Actif" and list(columns) == ["Code", "Nom", "Statut"] and Page.title == "Salles"
    i18n.set_language("en")
    assert statuses["ACTIVE"] == "Active" and statuses.get("CLOSED") == "Closed"
    assert statuses.get("UNKNOWN", "UNKNOWN") == "UNKNOWN"  # a code is never translated
    assert statuses.french("CLOSED") == "Clôturée"
    assert list(columns) == ["Code", "Name", "Status"] and Page.title == "Rooms"


def test_language_is_a_local_preference_validated_and_kept(tmp_path):
    (tmp_path / "desktop.json").write_text(json.dumps({"api_url": "http://serveur.test:8000/api/v1/"}), "utf-8")
    assert load_config(env={}, directory=tmp_path).language == "fr"  # default
    assert save_preference("language", "en", directory=tmp_path)
    assert save_preference("theme", "dark", directory=tmp_path)
    config = load_config(env={}, directory=tmp_path)
    assert (config.language, config.theme, config.api_url) == ("en", "dark", "http://serveur.test:8000/api/v1/")
    (tmp_path / "desktop.json").write_text(json.dumps({"language": "klingon"}), "utf-8")
    assert load_config(env={}, directory=tmp_path).language == "fr"


def _visible_texts(widget):
    """Interface texts (labels, buttons, tabs, headers, fields, lists) and table
    cells (data, checked against the catalog only)."""
    texts, cells = [], []
    for w in [widget, *widget.findChildren(QLabel)]:
        if isinstance(w, QLabel) and w.isVisibleTo(widget) and w.text().strip():
            texts.append(re.sub(r"<[^>]+>", " ", w.text()))
    for b in widget.findChildren(QAbstractButton):
        if b.isVisibleTo(widget):
            texts += [b.text(), b.toolTip()]
    for tabs in widget.findChildren(QTabWidget):
        texts += [tabs.tabText(i) for i in range(tabs.count())]
    for line in widget.findChildren(QLineEdit):
        texts.append(line.placeholderText())
    for combo in widget.findChildren(QComboBox):
        texts += [combo.itemText(i) for i in range(combo.count())] + [combo.toolTip()]
    for table in widget.findChildren(QTableWidget):
        for c in range(table.columnCount()):
            header = table.horizontalHeaderItem(c)
            texts.append(header.text() if header else "")
        for r in range(min(table.rowCount(), 30)):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item is not None:
                    cells += [item.text(), item.toolTip()]
    for lst in widget.findChildren(QListWidget):
        texts += [lst.item(i).text() for i in range(lst.count())]
    return [t for t in texts if t and t.strip()], [c for c in cells if c and c.strip()]


def _untranslated(texts, cells):
    french = {k for k, v in ENGLISH.items() if k != v}
    left = [t for t in texts + cells if t in french and not DATA.fullmatch(t)]  # a catalog text left in French
    left += [t for t in texts if FRENCH_WORDS.search(DATA.sub("", t))]
    return sorted(set(left))


def test_every_module_and_tab_shows_no_french_text_in_english(controller, backend, tmp_path):  # noqa: F811
    controller.config_directory = tmp_path
    open_module(controller, "dashboard")
    controller.set_language("en")
    shell = controller.main_window
    assert shell.windowTitle() and not FRENCH_WORDS.search(DATA.sub("", shell.windowTitle()))
    problems = {}
    walked = 0
    for entry in [e for e in NAVIGATION if e.available]:
        page = shell.open(entry.key)
        tab_widgets = page.findChildren(QTabWidget)
        for tabs in tab_widgets or [None]:
            for index in range(tabs.count()) if tabs else [None]:
                if tabs is not None:
                    tabs.setCurrentIndex(index)
                walked += 1
                left = _untranslated(*_visible_texts(page))
                if left:
                    problems.setdefault(entry.key, set()).update(left)
    nav, _ = _visible_texts(shell.nav)
    left = _untranslated(nav, [])
    if left:
        problems["navigation"] = set(left)
    assert walked >= 20  # every module, every tab
    assert not problems, "\n".join(f"{k}: {sorted(v)}" for k, v in problems.items())
    left = sorted(t for t in i18n.missing if not DATA.fullmatch(t))  # server-written texts fall back as they are
    assert not left, left


def test_switch_rebuilds_on_the_same_module_and_keeps_the_choice(controller, backend, tmp_path, api):  # noqa: F811
    controller.config_directory = tmp_path
    old, _ = open_module(controller, "classes")
    old.show()
    assert old.nav.currentItem().text() == "Classes"
    before = {w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()}
    assert controller.set_language("en")
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    new = controller.main_window
    assert new is not old and new.current_key == "classes" and new.isVisible()
    after = {w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()}
    assert after == (before - {old}) | {new}  # the old window is closed, no duplicate
    assert not shiboken6.isValid(old)  # and deleted: nothing left behind
    labels = [new.nav.item(i).text() for i in range(new.nav.count())]
    assert "Students" in labels and "Teachers" in labels and "Élèves" not in labels
    assert api._http.headers["Accept-Language"] == "en"
    assert load_config(env={}, directory=tmp_path).language == "en"
    assert controller.set_language("fr")
    assert "Élèves" in [controller.main_window.nav.item(i).text() for i in range(controller.main_window.nav.count())]
    assert api._http.headers["Accept-Language"] == "fr"
    assert not controller.set_language("de")  # refused, nothing changes
    assert i18n.language() == "fr"
    controller.main_window.close()


def test_login_window_follows_the_language(controller, tmp_path):  # noqa: F811
    controller.config_directory = tmp_path
    controller.login_window.show()
    controller.set_language("en")
    window = controller.login_window
    assert window.isVisible()
    texts, _ = _visible_texts(window)
    assert not _untranslated(texts, []), _untranslated(texts, [])


def test_account_dialog_offers_the_language(controller, backend, tmp_path):  # noqa: F811
    controller.config_directory = tmp_path
    open_module(controller, "dashboard")
    dialog = controller.account_dialog()
    assert [dialog.language.itemText(i) for i in range(dialog.language.count())] == ["Français", "English"]
    assert dialog.language.currentData() == "fr" and dialog.language.isEnabled()
    reopened = []
    controller.open_account = lambda: reopened.append(i18n.language())
    dialog.language.setCurrentIndex(dialog.language.findData("en"))
    QCoreApplication.processEvents()
    assert i18n.language() == "en" and reopened == ["en"]  # « Mon compte » reopens in English
    assert load_config(env={}, directory=tmp_path).language == "en"
    english = controller.account_dialog()
    texts, _ = _visible_texts(english)
    assert "Language" in " ".join(texts)
    assert not _untranslated(texts, []), _untranslated(texts, [])
    english.close()
    dialog.close()


def test_list_messages_are_grammatical_in_english(controller, backend, tmp_path):  # noqa: F811
    controller.config_directory = tmp_path
    open_module(controller, "categories")
    controller.set_language("en")
    page = controller.main_window.open("categories")
    page.search.setText("zzz-nothing")
    page.reload()
    assert page.empty.text() == "No category matches these criteria."
    assert page.a == "a" and page.the == "the " and page.plural == "categories"


def test_realtime_connection_announces_the_language(qapp):
    """The server renders system notifications in the connection's language."""
    from school_admin.realtime import RealtimeClient

    from .test_communication_documents import FakeSocket, StubApi

    class LanguageSocket(FakeSocket):
        def open(self, request):
            super().open(request)
            self.headers[b"Accept-Language"] = bytes(request.rawHeader("Accept-Language"))

    sockets = []
    rt = RealtimeClient(
        StubApi(), "ws://h/ws/v1/realtime/", socket_factory=lambda: sockets.append(LanguageSocket()) or sockets[-1]
    )
    rt.start()
    i18n.set_language("en")
    rt.start()
    assert [s.headers[b"Accept-Language"] for s in sockets] == [b"fr", b"en"]
    rt.stop()


def test_switch_reconnects_a_live_connection_only(controller, tmp_path):  # noqa: F811
    controller.config_directory = tmp_path
    starts = []

    class Live:
        state = "online"

        def start(self):
            starts.append(i18n.language())

    controller.realtime = Live()
    controller.set_language("en")
    assert starts == ["en"]  # reconnected, announcing English
    controller.realtime.state = "stopped"  # logged out: stays closed
    controller.set_language("fr")
    assert starts == ["en"]
    controller.realtime = None
