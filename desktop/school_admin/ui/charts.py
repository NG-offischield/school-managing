"""Dashboard charts drawn with QPainter in the theme colours (no extra
dependency, identical on every OS).

    LineChart   evolutions over time (attendance rate per day, pupils per month)
    BarChart    comparisons (pupils per level / per class)
    ChartCard   card around a chart: title, note, legend and the four states
                loading / data / no data / API error
    ActivityCard  recent administrative activity (list)

Charts show only the points they are given (models.ChartData, built from
the API by services/dashboard.py): nothing is interpolated or invented.
Hovering a point shows its full tooltip; every chart redraws to its size.
"""

import math
from html import escape

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .theme import TOKENS, TYPE
from .widgets import button, set_variant


def series_colours():
    """Read when painting: follows the active theme."""
    return (TOKENS.chart_1, TOKENS.chart_2, TOKENS.chart_3)


def nice_ceiling(value, ticks=4):
    """Axis maximum >= value whose `ticks` graduations are round whole
    numbers (step 1, 2, 2.5, 3, 4 or 5 × 10^n, at least 1): 38 -> 40 (0, 10 … 40)."""
    raw = max(value, 0) / ticks
    if raw <= 1:
        return ticks
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(s * magnitude for s in (1, 2, 2.5, 3, 4, 5, 10) if raw <= s * magnitude)
    if step != int(step):  # 2.5 below 10 would give 7,5 graduations
        step = math.ceil(step)
    return step * ticks


def _format(value, unit=""):
    text = f"{value:.0f}" if abs(value - round(value)) < 1e-9 else f"{value:.1f}".replace(".", ",")
    return f"{text} {unit}".strip() if unit == "%" else text


class ChartBase(QWidget):
    """Axes, grid, x labels, hover. Subclasses draw the series."""

    TICKS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(190)
        self.data = None
        self.hover = None
        self.font_small = QFont(TYPE.family)
        self.font_small.setPointSizeF(TYPE.small)

    def sizeHint(self):
        return QSize(420, 230)

    def set_data(self, data):
        self.data = data
        self.hover = None
        values = [v for p in data.points for v in p.values]
        summary = ", ".join(f"{p.label} : {' / '.join(_format(v, data.unit) for v in p.values)}" for p in data.points)
        self.setAccessibleDescription(summary[:500])
        self.top = data.maximum or nice_ceiling(max(values, default=0))
        self.update()

    # --- geometry ---------------------------------------------------------------------
    def plot_rect(self):
        metrics = QFontMetrics(self.font_small)
        label_width = max(metrics.horizontalAdvance(_format(self.top, self.data.unit)), 24)
        return QRectF(label_width + 14, 10, self.width() - label_width - 26, self.height() - 10 - 30)

    def x_at(self, index, rect):
        count = len(self.data.points)
        if count == 1:
            return rect.center().x()
        return rect.left() + rect.width() * index / (count - 1)

    def y_at(self, value, rect):
        return rect.bottom() - rect.height() * (value / self.top if self.top else 0)

    def index_at(self, x, rect):
        count = len(self.data.points)
        if count == 0:
            return None
        if count == 1:
            return 0
        return min(count - 1, max(0, round((x - rect.left()) / rect.width() * (count - 1))))

    # --- painting ---------------------------------------------------------------------
    def paintEvent(self, _event):
        if not self.data or not self.data.points:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.plot_rect()
        painter.setFont(self.font_small)
        metrics = painter.fontMetrics()
        for tick in range(self.TICKS + 1):
            value = self.top * tick / self.TICKS
            y = self.y_at(value, rect)
            painter.setPen(QPen(QColor(TOKENS.chart_grid if tick else TOKENS.border), 1))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(QColor(TOKENS.text_secondary))
            label = _format(value, self.data.unit)
            painter.drawText(QRectF(0, y - 8, rect.left() - 8, 16), Qt.AlignRight | Qt.AlignVCenter, label)
        # x labels: as many as fit without overlapping
        widest = max(metrics.horizontalAdvance(p.label) for p in self.data.points) + 12
        step = max(1, math.ceil(len(self.data.points) * widest / max(rect.width(), 1)))
        painter.setPen(QColor(TOKENS.text_secondary))
        for index, point in enumerate(self.data.points):
            if index % step and index != self.hover:
                continue
            # centred under its point, but never cut by the edges of the chart
            x = min(max(self.x_center(index, rect), widest / 2), self.width() - widest / 2)
            painter.drawText(QRectF(x - widest / 2, rect.bottom() + 6, widest, 18), Qt.AlignHCenter, point.label)
        self.draw_series(painter, rect)
        painter.end()

    def x_center(self, index, rect):
        return self.x_at(index, rect)

    def draw_series(self, painter, rect):
        raise NotImplementedError

    # --- hover ---------------------------------------------------------------------------
    def mouseMoveEvent(self, event):
        if not self.data or not self.data.points:
            return
        rect = self.plot_rect()
        inside = rect.adjusted(-8, 0, 8, 0).contains(event.position())
        index = self.index_at(event.position().x(), rect) if inside else None
        if index != self.hover:
            self.hover = index
            self.update()
        if index is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(event.globalPosition().toPoint(), self.tooltip(index), self)

    def tooltip(self, index):
        point = self.data.points[index]
        if point.tooltip:
            return point.tooltip
        values = " · ".join(
            f"{name} : {_format(v, self.data.unit)}" for name, v in zip(self.data.series, point.values, strict=False)
        )
        return f"{point.label} — {values}"

    def leaveEvent(self, event):
        self.hover = None
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)


class LineChart(ChartBase):
    def draw_series(self, painter, rect):
        points = self.data.points
        for serie in range(len(self.data.series)):
            colours = series_colours()
            colour = QColor(colours[serie % len(colours)])
            path = QPainterPath()
            coords = [QPointF(self.x_at(i, rect), self.y_at(p.values[serie], rect)) for i, p in enumerate(points)]
            path.moveTo(coords[0])
            for coord in coords[1:]:
                path.lineTo(coord)
            if serie == 0 and len(coords) > 1:  # soft area under the main series
                area = QPainterPath(path)
                area.lineTo(coords[-1].x(), rect.bottom())
                area.lineTo(coords[0].x(), rect.bottom())
                area.closeSubpath()
                soft = QColor(TOKENS.chart_soft)
                soft.setAlpha(90)
                painter.fillPath(area, soft)
            painter.setPen(QPen(colour, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
            painter.setBrush(QColor(TOKENS.card))
            for index, coord in enumerate(coords):
                radius = 4.5 if index == self.hover else (3 if len(coords) <= 31 else 0)
                if radius:
                    painter.setPen(QPen(colour, 2))
                    painter.drawEllipse(coord, radius, radius)
        if self.hover is not None:
            x = self.x_at(self.hover, rect)
            painter.setPen(QPen(QColor(TOKENS.field_border), 1, Qt.DashLine))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))


class BarChart(ChartBase):
    """One series of bars; the hovered bar is darker, values above the bars
    when there is room."""

    def slot(self, rect):
        return rect.width() / max(len(self.data.points), 1)

    def x_center(self, index, rect):
        return rect.left() + self.slot(rect) * (index + 0.5)

    def index_at(self, x, rect):
        count = len(self.data.points)
        if count == 0 or x < rect.left() or x > rect.right():
            return None
        return min(count - 1, int((x - rect.left()) / self.slot(rect)))

    def draw_series(self, painter, rect):
        slot = self.slot(rect)
        width = max(4.0, min(46.0, slot * 0.62))
        metrics = painter.fontMetrics()
        for index, point in enumerate(self.data.points):
            value = point.values[0]
            x = self.x_center(index, rect)
            top = self.y_at(value, rect)
            bar = QRectF(x - width / 2, top, width, rect.bottom() - top)
            colour = QColor(TOKENS.primary_hover if index == self.hover else TOKENS.chart_1)
            painter.setPen(Qt.NoPen)
            painter.setBrush(colour)
            painter.drawRoundedRect(bar.adjusted(0, 0, 0, 2), 3, 3) if bar.height() > 3 else painter.drawRect(bar)
            label = _format(value, self.data.unit)
            if metrics.horizontalAdvance(label) <= slot - 2:
                painter.setPen(QColor(TOKENS.text))
                painter.drawText(QRectF(x - slot / 2, top - 18, slot, 16), Qt.AlignHCenter | Qt.AlignBottom, label)


# =============================================================================
# Cards
# =============================================================================


def legend_html(series):
    return "&nbsp;&nbsp;&nbsp;".join(
        f"<span style='color:{series_colours()[i % 3]}'>■</span>&nbsp;{name}" for i, name in enumerate(series)
    )


class ChartCard(QFrame):
    """Card: title (+ optional switch), note, legend, then one of: loading,
    chart, no data, error. `views` = [(label, chart)] when the card can show
    several charts (e.g. « Par niveau » / « Par classe »)."""

    LOADING = "Chargement…"

    def __init__(self, title, views, parent=None):
        super().__init__(parent, objectName="card")
        self.setMinimumHeight(300)
        self.views = views
        self.data = [None] * len(views)
        self.current = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(4)
        head = QHBoxLayout()
        self.title = QLabel(title, objectName="chartTitle")
        head.addWidget(self.title, 1)
        self.switch = []
        if len(views) > 1:
            group = QButtonGroup(self)
            for index, (label, _chart) in enumerate(views):
                choice = button(label, "primary" if index == 0 else "secondary")
                choice.setCheckable(True)
                choice.setChecked(index == 0)
                choice.setMinimumHeight(28)
                choice.setAccessibleName(f"{title} : {label}")
                group.addButton(choice, index)
                head.addWidget(choice)
                self.switch.append(choice)
            group.idClicked.connect(self.show_view)
        layout.addLayout(head)
        self.note = QLabel("", objectName="help")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.legend = QLabel("", objectName="legend")
        self.legend.setTextFormat(Qt.RichText)
        layout.addWidget(self.legend)
        self.stack = QStackedWidget()
        self.state = QLabel(self.LOADING, objectName="chartState", alignment=Qt.AlignCenter)
        self.state.setWordWrap(True)
        self.stack.addWidget(self.state)
        for _label, chart in views:
            chart.setAccessibleName(title)
            self.stack.addWidget(chart)
        layout.addWidget(self.stack, 1)

    @property
    def chart(self):
        return self.views[self.current][1]

    @property
    def status(self):
        """'loading' | 'data' | 'empty' | 'error' (tests, accessibility)."""
        return self.property("status") or "loading"

    def _set_status(self, status, text=""):
        self.setProperty("status", status)
        self.state.setObjectName("chartError" if status == "error" else "chartState")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.state.setText(text)
        self.setAccessibleDescription(text or self.title.text())

    def set_loading(self):
        self._set_status("loading", self.LOADING)
        self.legend.setText("")
        self.stack.setCurrentWidget(self.state)

    def set_data(self, *datas):
        self.data = list(datas)
        self.show_view(self.current)

    def show_view(self, index):
        self.current = index
        for i, choice in enumerate(self.switch):
            set_variant(choice, "primary" if i == index else "secondary")
            choice.setChecked(i == index)
        data = self.data[index]
        if data is None:
            return self.set_loading()
        self.note.setText(data.note)
        self.note.setVisible(bool(data.note))
        if data.error:
            self._set_status("error", f"Indisponible — {data.error}")
            self.legend.setText("")
            self.stack.setCurrentWidget(self.state)
        elif not data.points:
            self._set_status("empty", data.empty_text)
            self.legend.setText("")
            self.stack.setCurrentWidget(self.state)
        else:
            self._set_status("data")
            self.legend.setText(legend_html(data.series) if len(data.series) > 1 or data.unit else "")
            self.chart.set_data(data)
            self.stack.setCurrentWidget(self.chart)
        return None


class ActivityCard(QFrame):
    """Recent administrative actions: what, on what, who, when."""

    def __init__(self, title="Activité récente", parent=None):
        super().__init__(parent, objectName="card")
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)
        self.title = QLabel(title, objectName="chartTitle")
        layout.addWidget(self.title)
        note = QLabel("Dernières opérations d'administration de l'école.", objectName="help")
        layout.addWidget(note)
        self.state = QLabel(ChartCard.LOADING, objectName="chartState", alignment=Qt.AlignCenter)
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        layout.addLayout(self.list)
        layout.addStretch()
        self.rows = []
        self.status = "loading"

    def _clear(self):
        for row in self.rows:
            self.list.removeWidget(row)
            row.deleteLater()
        self.rows = []

    def set_loading(self):
        self._clear()
        self.status = "loading"
        self.state.setObjectName("chartState")
        self.state.setText(ChartCard.LOADING)
        self.state.show()

    def set_error(self, text):
        self._clear()
        self.status = "error"
        self.state.setObjectName("chartError")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.state.setText(f"Indisponible — {text}")
        self.state.show()

    def set_items(self, items):
        """items: [(title, detail, when)]"""
        self._clear()
        if not items:
            self.status = "empty"
            self.state.setObjectName("chartState")
            self.state.setText("Aucune opération enregistrée pour le moment.")
            self.state.show()
            return
        self.status = "data"
        self.state.hide()
        for title, detail, when in items:
            row = QWidget()
            line = QVBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(0)
            head = QLabel(f"<b>{escape(title)}</b>" + (f" · {escape(detail)}" if detail else ""))
            head.setTextFormat(Qt.RichText)
            head.setWordWrap(True)
            line.addWidget(head)
            line.addWidget(QLabel(when, objectName="activityTime"))
            self.list.addWidget(row)
            self.rows.append(row)
