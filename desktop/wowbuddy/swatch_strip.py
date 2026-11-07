"""0b0c80–0b1fd0：原生隐藏色块条的绘制、命中和悬停提示。"""
from dataclasses import dataclass
from PySide6.QtCore import Qt, QEvent, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush, QFont, QFontMetrics
from PySide6.QtWidgets import QWidget, QSizePolicy, QToolTip
from .window_shell import round_global_coordinate
from .expressions import _trim


@dataclass(frozen=True)
class SwatchItem:
    rgb: tuple[int, int, int] | None
    label: str
    value: str
    number: int = 0


def frame_color_hash(colors, *, native_argb=False):
    """全体原采样值哈希；readable缺失行的原生零值须保留。"""
    value = 0x14650fb0739d0383
    for color in colors:
        packed = int(color) if native_argb else int(color) | 0xff000000
        value = ((value ^ packed) * 0x100000001b3) & 0xffffffffffffffff
    return value


def unknown_value(value):
    text = _trim(value)
    if text.endswith("无"):
        text = ""
    return not text or text == "—" or text.startswith("UNKNOWN")


class SwatchStrip(QWidget):
    cell_size, gap, padding = 10, 3, 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = ()
        self.hovered = -1
        self.row_count = 1
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MouseTracking, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(14)
        self.setToolTip("")

    def columns(self, width=None):
        width = self.width() if width is None else width
        return max(1, (width - 2 * self.padding + self.gap) // (self.cell_size + self.gap))

    def _resize_height(self):
        columns = self.columns(max(self.width(), self.sizeHint().width()))
        self.row_count = max(1, (len(self.items) + columns - 1) // columns)
        height = (self.cell_size + self.gap) * self.row_count - self.gap + self.padding * 2
        if self.height() != height:
            self.setFixedHeight(height)

    def set_items(self, items):
        self.items = tuple(items)
        self.hovered = -1
        self._resize_height()
        self.update()

    def hit_index(self, x, y):
        if x < self.padding or y < self.padding:
            return -1
        step = self.cell_size + self.gap
        column = (x - self.padding) // step
        if column >= self.columns():
            return -1
        index = ((y - self.padding) // step) * self.columns() + column
        return index if index < len(self.items) else -1

    def tooltip_text(self, index):
        item = self.items[index]
        return f"#{item.number if item.number > 0 else index + 1}  {item.label or '(通用)'} = {item.value or '—'}"

    def event(self, event):
        kind = event.type()
        if kind == QEvent.Type.ToolTip:
            index = self.hit_index(event.pos().x(), event.pos().y())
            if index < 0:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPos(), self.tooltip_text(index), self)
            return True
        if kind == QEvent.Type.HoverMove:
            point = event.position()
            index = self.hit_index(round_global_coordinate(point.x()), round_global_coordinate(point.y()))
            if index != self.hovered:
                self.hovered = index
                self.update()
            return True
        if kind == QEvent.Type.Leave:
            self.hovered = -1
            self.update()
        return super().event(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_height()

    def paintEvent(self, event):
        # 0x1400b1390：暗色且未知使用虚线占位，暗色有效值使用实线深底。
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            font = QFont(self.font())
            font.setPointSizeF(8.0 if not self.items else 7.0)
            painter.setFont(font)
            if not self.items:
                painter.setPen(QColor("#4a5670"))
                painter.drawText(self.rect().adjusted(self.padding + 2, 0, 0, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    "暂无字段色块（未选窗口或未开始监控）")
                return
            step, columns = self.cell_size + self.gap, self.columns()
            for index, item in enumerate(self.items):
                color = QColor(*item.rgb) if item.rgb is not None else QColor()
                rect = QRectF((index % columns) * step + self.padding,
                    (index // columns) * step + self.padding, self.cell_size, self.cell_size)
                path = QPainterPath()
                path.addRoundedRect(rect, 2.0, 2.0)
                dark = color.red() + color.green() + color.blue() < 12
                if dark and unknown_value(item.value):
                    fill, border, style = QColor("#1e273b"), QColor("#4a5670"), Qt.PenStyle.DotLine
                else:
                    fill = QColor("#0c111b") if dark else color
                    border = QColor("#00e5ff" if index == self.hovered else "#253048")
                    style = Qt.PenStyle.SolidLine
                painter.fillPath(path, QBrush(fill))
                painter.setPen(QPen(QBrush(border), 1.0, style,
                    Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.BevelJoin))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
            if 0 <= self.hovered < len(self.items):
                item = self.items[self.hovered]
                number = item.number if item.number > 0 else self.hovered + 1
                text = f"#{number} {item.label} = {item.value or '—'}"
                width = QFontMetrics(self.font()).horizontalAdvance(text) + 10
                rect = QRectF(self.rect().right() - width, self.rect().bottom() - 14, width, 13)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#1e273b"))
                painter.drawRoundedRect(rect, 3.0, 3.0)
                painter.setPen(QColor("#00e5ff"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        finally:
            painter.end()
