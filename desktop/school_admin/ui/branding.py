"""Branding of the SOFTWARE (School Managing) — the only place that knows its
logo files. Screens never load a logo themselves: they ask this module.

Two identities, never mixed (ADR 0021):
- School Managing (this module): login screen, sidebar, window icon, « À
  propos », future .exe / installer. Files in ui/assets/brand/ (see the
  README there); the official logo (concept 5) is dropped there ONCE.
- The SCHOOL (logo, colours, name in SchoolBranding on the server): official
  documents (report cards, cards, receipts, payslips…) — rendered by the
  backend, never with the software's logo.

Until the official files are in place, a neutral text mark « School
Managing » is shown: no logo is invented.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QLabel

from ..i18n import tr

SOFTWARE_NAME = "School Managing"
SOFTWARE_TAGLINE = "Administration de l'école"
BRAND_DIR = Path(__file__).resolve().parent / "assets" / "brand"

# kind -> candidate files (first found wins; SVG first: sharp at any size)
FILES = {
    "horizontal": ("logo-horizontal.svg", "logo-horizontal.png"),
    "compact": ("logo-compact.svg", "logo-compact.png"),
    "monochrome": ("logo-monochrome.svg", "logo-monochrome.png"),
    "icon": ("app-icon.ico", "app-icon.png", "app-icon.svg"),
}


def brand_file(kind):
    """Path of the official file for `kind`, or None when not provided yet."""
    for name in FILES[kind]:
        path = BRAND_DIR / name
        if path.is_file():
            return path
    return None


def software_pixmap(kind="horizontal", height=40):
    path = brand_file(kind)
    if path is None:
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return pixmap.scaledToHeight(height, Qt.SmoothTransformation)


def software_icon():
    """Window / taskbar icon (empty QIcon when the official icon is missing)."""
    path = brand_file("icon") or brand_file("compact")
    return QIcon(str(path)) if path is not None else QIcon()


def brand_mark(kind="horizontal", height=40, *, object_name="softwareBrand"):
    """Logo of School Managing as a label: the official image when present,
    otherwise the neutral text mark. Always named `softwareBrand` so screens
    and tests find it the same way."""
    label = QLabel(objectName=object_name)
    label.setAccessibleName(f"Logo {tr(SOFTWARE_NAME)}")
    label.setProperty("software_brand", True)
    pixmap = software_pixmap(kind, height)
    if pixmap is not None:
        label.setPixmap(pixmap)
        label.setProperty("brand_source", "file")
    else:
        label.setText(tr(SOFTWARE_NAME))
        label.setProperty("brand_source", "text")
    label.setToolTip(tr(SOFTWARE_NAME))
    return label
