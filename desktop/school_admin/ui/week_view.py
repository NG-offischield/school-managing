"""Week view of the planning: days in columns, hours in rows, one block per
TeachingSession returned by the API (nothing is computed: positions only
come from the sessions' own start / end, in the school's local time).

Status is visible at a glance (colour + text):
    planifiée   blue          remplacée  amber (« Remplaçant : … »)
    déplacée    light blue    annulée    grey, struck through
Click selects a session (signal `selected`), double-click opens it
(`activated`); the tooltip gives every detail. Overlapping sessions of the
same day (no filter) share the column in lanes.
"""

from datetime import timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..models import WEEKDAY_NAMES
from .theme import TOKENS, TYPE

HOUR_HEIGHT = 48
HEADER_HEIGHT = 40
GUTTER = 52
STYLES = {  # (background, border, text)
    "SCHEDULED": (TOKENS.primary_soft, TOKENS.primary, TOKENS.text),
    "SUBSTITUTED": (TOKENS.warning_bg, TOKENS.warning, TOKENS.text),
    "MOVED": (TOKENS.info_bg, TOKENS.info, TOKENS.text),
    "CANCELLED": (TOKENS.field_disabled, TOKENS.field_border, TOKENS.text_secondary),
    "COMPLETED": (TOKENS.success_bg, TOKENS.success, TOKENS.text),
}
LEGEND = [
    ("Planifiée", "SCHEDULED"),
    ("Remplacée", "SUBSTITUTED"),
    ("Déplacée", "MOVED"),
    ("Réalisée", "COMPLETED"),
    ("Annulée", "CANCELLED"),
]


def style_key(session):
    if session.status in ("CANCELLED", "COMPLETED"):
        return session.status
    if session.is_substituted:
        return "SUBSTITUTED"
    if session.is_moved:
        return "MOVED"
    return "SCHEDULED"


def session_tooltip(session):
    lines = [
        f"{session.subject_code} — {session.subject_name}",
        f"Classe : {session.class_name}",
        f"{session.date:%d/%m/%Y} · {session.hours}" if session.date else session.hours,
        f"Salle : {session.room_code or '—'}",
        f"Enseignant : {session.teacher_name}",
    ]
    if session.is_substituted:
        lines.append(f"Enseignant prévu : {session.planned_teacher_name}")
    lines.append(f"Statut : {session.status_label}")
    return "\n".join(lines)


class WeekView(QWidget):
    selected = Signal(object)  # Session or None
    activated = Signal(object)  # Session

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Planning de la semaine")
        self.monday = None
        self.sessions = []
        self.current = None
        self.first_hour, self.last_hour = 7, 18
        self.days = 6
        self.blocks = []  # (rect, session)
        self.font_small = QFont(TYPE.family)
        self.font_small.setPointSizeF(TYPE.small)

    def set_week(self, monday, sessions):
        self.monday, self.sessions = monday, list(sessions)
        hours = [(s.start.hour, s.end.hour + (1 if s.end.minute else 0)) for s in self.sessions if s.start and s.end]
        self.first_hour = min([7, *(h[0] for h in hours)])
        self.last_hour = max([18, *(h[1] for h in hours)])
        self.days = 7 if any(s.date and s.date.isoweekday() == 7 for s in self.sessions) else 6
        if self.current is not None and self.current.id not in {s.id for s in self.sessions}:
            self.current = None
        self.setMinimumHeight(self.sizeHint().height())
        self.setAccessibleDescription(f"{len(self.sessions)} séance(s) cette semaine")
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QSize(640, HEADER_HEIGHT + (self.last_hour - self.first_hour) * HOUR_HEIGHT + 2)

    def minimumSizeHint(self):
        return QSize(460, 300)

    # --- geometry --------------------------------------------------------------------
    def column_width(self):
        return (self.width() - GUTTER - 1) / self.days

    def y_of(self, moment):
        hours = moment.hour + moment.minute / 60 - self.first_hour
        return HEADER_HEIGHT + hours * HOUR_HEIGHT

    def _layout_blocks(self):
        """Rectangles of the sessions; overlapping ones share the day in lanes."""
        self.blocks = []
        width = self.column_width()
        by_day = {}
        for session in self.sessions:
            if session.date and session.start and session.end:
                by_day.setdefault(session.date, []).append(session)
        for day, items in by_day.items():
            column = day.isoweekday() - 1
            if column >= self.days:
                continue
            items.sort(key=lambda s: (s.start, s.end))
            lanes = []  # end time of the last block of each lane
            placed = []
            for session in items:
                lane = next((i for i, end in enumerate(lanes) if end <= session.start), None)
                if lane is None:
                    lanes.append(session.end)
                    lane = len(lanes) - 1
                else:
                    lanes[lane] = session.end
                placed.append((session, lane))
            count = max(1, len(lanes))
            for session, lane in placed:
                left = GUTTER + column * width + 2 + lane * (width - 4) / count
                rect = QRectF(left, self.y_of(session.start) + 1, (width - 4) / count - 2, 0)
                rect.setBottom(self.y_of(session.end) - 1)
                self.blocks.append((rect, session))

    # --- painting ---------------------------------------------------------------------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(TOKENS.card))
        painter.setFont(self.font_small)
        width = self.column_width()
        # header: days
        for index in range(self.days):
            x = GUTTER + index * width
            label = WEEKDAY_NAMES[index + 1]
            if self.monday is not None:
                label += f" {self.monday + timedelta(days=index):%d/%m}"
            painter.setPen(QColor(TOKENS.text))
            painter.drawText(QRectF(x, 0, width, HEADER_HEIGHT), Qt.AlignCenter, label)
            painter.setPen(QPen(QColor(TOKENS.chart_grid), 1))
            painter.drawLine(QPointF(x, HEADER_HEIGHT), QPointF(x, self.height()))
        # hours
        for hour in range(self.first_hour, self.last_hour + 1):
            y = HEADER_HEIGHT + (hour - self.first_hour) * HOUR_HEIGHT
            painter.setPen(QPen(QColor(TOKENS.chart_grid if hour > self.first_hour else TOKENS.border), 1))
            painter.drawLine(QPointF(GUTTER, y), QPointF(self.width(), y))
            painter.setPen(QColor(TOKENS.text_secondary))
            painter.drawText(QRectF(0, y - 8, GUTTER - 8, 16), Qt.AlignRight | Qt.AlignVCenter, f"{hour:02d}:00")
        # sessions
        self._layout_blocks()
        metrics = QFontMetrics(self.font_small)
        for rect, session in self.blocks:
            background, border, text = STYLES[style_key(session)]
            selected = self.current is not None and session.id == self.current.id
            painter.setPen(QPen(QColor(TOKENS.focus if selected else border), 2.5 if selected else 1))
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(rect, 4, 4)
            font = QFont(self.font_small)
            font.setStrikeOut(session.status == "CANCELLED")
            painter.setFont(font)
            painter.setPen(QColor(text))
            inner = rect.adjusted(5, 3, -4, -2)
            lines = [f"{session.subject_code} · {session.class_name}", f"{session.hours} · {session.room_code or '—'}"]
            if session.is_substituted:
                lines.append(f"Remplaçant : {session.teacher_name}")
            else:
                lines.append(session.teacher_name)
            y = inner.top()
            for line in lines:
                if y + metrics.height() > inner.bottom() + 1:
                    break
                painter.drawText(
                    QRectF(inner.left(), y, inner.width(), metrics.height()),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    metrics.elidedText(line, Qt.ElideRight, int(inner.width())),
                )
                y += metrics.height()
        painter.end()

    # --- interaction -------------------------------------------------------------------
    def session_at(self, point):
        for rect, session in reversed(self.blocks):
            if rect.contains(point):
                return session
        return None

    def select(self, session):
        self.current = session
        self.update()
        self.selected.emit(session)

    def mousePressEvent(self, event):
        self.select(self.session_at(event.position()))

    def mouseDoubleClickEvent(self, event):
        session = self.session_at(event.position())
        if session is not None:
            self.select(session)
            self.activated.emit(session)

    def mouseMoveEvent(self, event):
        session = self.session_at(event.position())
        if session is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(event.globalPosition().toPoint(), session_tooltip(session), self)

    def keyPressEvent(self, event):
        """Left / right go through the week's sessions in time order; Enter opens."""
        ordered = sorted(self.sessions, key=lambda s: (s.start or s.date, s.class_name))
        if event.key() in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Left, Qt.Key_Up) and ordered:
            index = next((i for i, s in enumerate(ordered) if self.current and s.id == self.current.id), -1)
            step = 1 if event.key() in (Qt.Key_Right, Qt.Key_Down) else -1
            self.select(ordered[(index + step) % len(ordered)])
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.current is not None:
            self.activated.emit(self.current)
        else:
            super().keyPressEvent(event)
