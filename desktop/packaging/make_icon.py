"""Icon of the Windows executable and installer: the ISBREE monogram, as on the
four Android apps (same paths as web/isbree-public/src/components/logo.tsx and
mobile/tools/launcher_icons.mjs), ring in the ink colour of the administration.

    .venv\\Scripts\\python packaging\\make_icon.py      (from desktop/; offline, Qt only)

Writes packaging/build/app-icon.ico (generated, not versioned). Used ONLY for the
.exe and the installer: inside the program, the software keeps its neutral text
mark until its official logo is provided (ui/branding.py, ADR 0021).
"""

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

BOOK = "M12 49.5c6.8-2.6 13.5-2.4 20 1.3 6.5-3.7 13.2-3.9 20-1.3V56c-6.8-2.6-13.5-2.4-20 1.3-6.5-3.7-13.2-3.9-20-1.3z"
SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="18 18 72 72">
  <rect x="18" y="18" width="72" height="72" rx="16" fill="#faf6ee"/>
  <circle cx="54" cy="54" r="30" fill="none" stroke="#10294a" stroke-width="3.5"/>
  <g transform="translate(54 54.5) scale(0.62) translate(-32 -32)">
    <path d="M6 60V30C6 15.6 17.6 4 32 4s26 11.6 26 26v30z" fill="#10294a"/>
    <path d="M11 60V30.5C11 18.9 20.4 9.5 32 9.5S53 18.9 53 30.5V60" fill="none" stroke="#d9a441" stroke-width="1.6"/>
    <circle cx="32" cy="29" r="10" fill="#d9a441"/>
    <path d="M32 47V24" stroke="#faf6ee" stroke-width="3.2" stroke-linecap="round"/>
    <path d="M32 33c-1-6.2-5.4-9.6-11.4-9.4.4 6.1 4.8 9.7 11.4 9.4z" fill="#3f8a63"/>
    <path d="M32 28.5c1-5.4 4.9-8.4 10.2-8.2-.4 5.4-4.3 8.5-10.2 8.2z" fill="#3f8a63"/>
    <path d="{BOOK}" fill="#faf6ee"/>
    <path d="M32 50.8v6.5" stroke="#10294a" stroke-width="1.2"/>
  </g>
</svg>"""

OUT = Path(__file__).resolve().parent / "build" / "app-icon.ico"


def main():
    _app = QGuiApplication(sys.argv[:1])  # noqa: F841 - Qt image plugins need an application
    renderer = QSvgRenderer(QByteArray(SVG.encode()))
    image = QImage(256, 256, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(OUT), "ICO"):
        raise SystemExit(f"Could not write {OUT}")
    print(OUT)


if __name__ == "__main__":
    main()
