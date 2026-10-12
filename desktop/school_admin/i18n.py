"""Français / English for the admin desktop.

The FRENCH text is the key: tr("Se déconnecter"). French is the default
language and the explicit fallback; English comes from one central catalog
(i18n_en.ENGLISH). Placeholders are positional, str.format style:
tr("Plan « {0} » retiré", title), tr("Le {0:%d/%m/%Y}", day).

Only the INTERFACE is translated: names, school names, messages typed by
people, amounts and dates exchanged with the server are never touched.
Tables of labels defined once at import (statuses, roles…) are Labels: their
values are translated when READ, so they follow a language switch.

The choice is a local preference of this computer (desktop.json « language »),
independent of the account, the server and the theme; requests send it as
Accept-Language so the server's own messages come in the same language.
"""

LANGUAGES = {"fr": "Français", "en": "English"}  # each name in its own language

_state = {"language": "fr"}
_english = {}
_english_texts = set()
missing = set()  # keys asked in English without a translation (tests fail on them)


def _catalog():
    if not _english:
        from .i18n_en import ENGLISH

        _english.update(ENGLISH)
        _english_texts.update(ENGLISH.values())
    return _english


def language():
    return _state["language"]


def set_language(code):
    _state["language"] = code if code in LANGUAGES else "fr"


def is_english():
    return _state["language"] == "en"


def translate(french):
    if _state["language"] == "fr" or not french:
        return french
    catalog = _catalog()
    if french in catalog:
        return catalog[french]
    if french in _english_texts:
        return french  # already translated: tr() is idempotent
    missing.add(french)
    return french  # fallback, never a blank


def tr(french, *args):
    """The interface text for `french` in the current language, {0}, {1}…
    filled with `args` (names, numbers, dates: never translated themselves)."""
    text = translate(french)
    return text.format(*args) if args else text


def looks_like_text(value):
    """An interface text (« Statut : tous », « Ajouter »), not a code (ACTIVE,
    pageTitle, admin/plans/…): only texts go through the catalog."""
    if not isinstance(value, str) or not value.strip():
        return False
    if value.isupper() or "/" in value and " " not in value:
        return False
    return value[:1].isupper() or " " in value or any(c in value for c in "éèàêâçîôûùëïüœÉÈÀ")


def deep(value):
    """`value` with its interface texts translated (lists, tuples, dicts)."""
    if isinstance(value, str):
        return translate(value) if looks_like_text(value) else value
    if isinstance(value, tuple):
        return tuple(deep(v) for v in value)
    if isinstance(value, list):
        return [deep(v) for v in value]
    if isinstance(value, dict):
        return {k: deep(v) for k, v in value.items()}
    return value


class Tr:
    """Class attribute read in the current language (page title, columns,
    filters…): `title = Tr("Plans")`, `columns = Tr(["Titre", "Statut"])`."""

    def __init__(self, french):
        self.french = french

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner=None):
        return deep(self.french)


class Lazy:
    """Class attribute BUILT at each read from translated tables, so it follows a
    language switch: `status_filters = Lazy(lambda: ALL + [(l, c) for c, l in X.items()])`."""

    def __init__(self, build):
        self.build = build

    def __get__(self, instance, owner=None):
        return deep(self.build())


class Texts(list):
    """Module-level list of interface texts, read in the current language."""

    def __iter__(self):
        return iter(deep(list(super().__iter__())))

    def __getitem__(self, index):
        return deep(super().__getitem__(index))


class Labels(dict):
    """{code: French label} read in the current language (statuses, roles…).
    Defined once at import, translated at each read."""

    def __getitem__(self, key):
        return deep(super().__getitem__(key))

    def get(self, key, default=None):
        if key in self:
            return deep(super().get(key))
        # a French default is translated too; a code (ACTIVE…) is returned as is
        return deep(default)

    def values(self):
        return [deep(v) for v in super().values()]

    def items(self):
        return [(k, deep(v)) for k, v in super().items()]

    def french(self, key):
        return super().__getitem__(key)
