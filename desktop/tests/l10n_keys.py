"""The French keys of the desktop code (what i18n_en.ENGLISH must translate):

- tr("…") calls (first argument; implicit concatenation included);
- interface texts held by Tr(…), Labels({…}) and Texts([…]);
- module constants read through tr(NAME);
- the NAVIGATION entries (label, section, description);
- the nouns of the list pages (noun, plural_noun or noun + "s").

Shared by the l10n tests and by whoever completes the catalog."""

import ast
from pathlib import Path

from school_admin.i18n import looks_like_text

PACKAGE = Path(__file__).resolve().parent.parent / "school_admin"


def _texts(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and looks_like_text(n.value):
            yield n.value


def _call_name(node):
    if isinstance(node, ast.Call):
        return getattr(node.func, "id", None) or getattr(node.func, "attr", None)
    return None


def french_keys(package=PACKAGE):
    keys = set()
    constants = {}  # module constant name -> value
    read_through_tr = set()
    for path in sorted(Path(package).rglob("*.py")):
        if path.name.startswith("i18n"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name) and isinstance(node.value.value, str):
                        constants[target.id] = node.value.value
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "NAVIGATION" for t in node.targets):
                for call in ast.walk(node.value):
                    if _call_name(call) == "NavEntry":
                        args = [
                            a.value for a in call.args[1:] if isinstance(a, ast.Constant) and isinstance(a.value, str)
                        ]
                        keys.update(a for a in args if a)
        for node in ast.walk(tree):
            name = _call_name(node)
            if name == "tr" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    keys.add(first.value)
                elif isinstance(first, ast.Name):
                    read_through_tr.add(first.id)
            elif name in ("Tr", "Labels", "Texts") and node.args:
                keys.update(_texts(node.args[0]))
            if isinstance(node, ast.ClassDef):
                values = {}
                for item in node.body:
                    if isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and target.id in ("noun", "plural_noun"):
                                values[target.id] = item.value.value
                noun = values.get("noun")
                if noun:
                    keys.add(noun)
                    keys.add(values.get("plural_noun") or f"{noun}s")
    keys.update(constants[name] for name in read_through_tr if name in constants)
    return {k for k in keys if k and k.strip()}
