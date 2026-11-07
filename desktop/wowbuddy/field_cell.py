"""04BC30/04BEE0/04CB00：旧字段格，真实 QWidget 自绘且无外部动作。"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import QWidget, QSizePolicy


def field_tooltip(number: int, label: str, key: str, field_type: str, note: str = "") -> str:
    """098EA0：原字段编号，不按过滤后的格子序号重编号。"""
    return f"#{number} {label}  ·  id={key}  ·  类型={field_type}\n{note or '专精字段'}"


def field_grid_columns(count: int, viewport_width: int, viewport_height: int) -> int:
    """098EA0：高度不足200时用600×620；保留原版减列循环方向。"""
    if viewport_height < 200:
        viewport_width, viewport_height = 600, 620
    columns = max(6, min(16, (viewport_width - 16) // 60))
    while columns > 6 and viewport_height < ((count + columns - 1) // columns) * 46 + 16:
        columns -= 1
    return columns


def value_text_color(text: str) -> str:
    """04BEE0：原字符串不trim；精确破折号优先，再正向，再负向。"""
    if text == "—":
        return "#4a5670"
    if text.startswith("ON") or "存在" in text or "生效" in text:
        return "#22e58b"
    if text.startswith("OFF") or "无" in text:
        return "#7c8ba8"
    return "#e6eeff"


def _color(value: QColor | tuple[int, int, int] | None) -> QColor:
    if isinstance(value, QColor):
        return QColor(value)
    return QColor(*value) if value is not None else QColor()


class FieldCell(QWidget):
    """number=字段原index+1；is_common=契约来源commonFields，并非applicable。

    构造默认黑色/“—”。set_value只更新RGB和文本，不覆盖元数据tooltip。
    可接受QColor以保留原生有效性/alpha比较；None表示无效QColor。
    """
    def __init__(self, number: int, label: str, is_common: bool, parent=None):
        super().__init__(parent)
        self.number = number
        self.label = label
        self.is_common = bool(is_common)
        self._color = QColor(0, 0, 0)
        self.value_text = "—"
        self.hovered = False
        self.setMinimumWidth(54)
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip(f"#{number} {label}")

    @property
    def color(self) -> QColor:
        return QColor(self._color)

    def set_value(self, rgb: QColor | tuple[int, int, int] | None, text: str) -> bool:
        color = _color(rgb)
        if self._color == color and self.value_text == text:
            return False
        self._color = color
        self.value_text = text
        self.update()
        return True

    def enterEvent(self, event):
        self.hovered = True
        self.update()

    def leaveEvent(self, event):
        self.hovered = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            outer = QPainterPath()
            outer.addRoundedRect(rect, 6.0, 6.0)
            painter.fillPath(outer, QBrush(QColor("#1e273b" if self.hovered else "#161d2d")))
            painter.setPen(QPen(QBrush(QColor("#00e5ff" if self.hovered else "#253048")),
                1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.BevelJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(outer)

            color_sum = self._color.red() + self._color.green() + self._color.blue()
            side = QPainterPath()
            side.addRoundedRect(QRectF(rect.left() + 1.0, rect.top() + 4.0,
                                      2.5, rect.height() - 8.0), 1.5, 1.5)
            painter.fillPath(side, QBrush(QColor("#2a344a") if color_sum < 24 else self._color))
            chip = QPainterPath()
            chip.addRoundedRect(QRectF(rect.right() - 12.0, rect.top() + 4.0, 8.0, 8.0), 3.0, 3.0)
            painter.fillPath(chip, QBrush(QColor("#0c111b") if color_sum < 12 else self._color))
            painter.setPen(QPen(QBrush(QColor("#253048")), 1.0, Qt.PenStyle.SolidLine,
                               Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.BevelJoin))
            painter.drawPath(chip)

            font = QFont(self.font())
            font.setPointSizeF(6.5)
            font.setWeight(QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor("#4a5670" if self.is_common else "#5c7ac8"))
            alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(QRectF(rect.left() + 7.0, rect.top() + 3.0, 26.0, 11.0),
                             alignment, f"#{self.number}")
            painter.setPen(QColor("#7c8ba8"))
            title = QFontMetrics(font).elidedText(self.label, Qt.TextElideMode.ElideRight,
                                                int(rect.width()) - 34)
            painter.drawText(QRectF(rect.left() + 28.0, rect.top() + 3.0,
                                    rect.width() - 34.0, 11.0), alignment, title)
            font.setPointSizeF(9.5)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(value_text_color(self.value_text)))
            value = QFontMetrics(font).elidedText(self.value_text, Qt.TextElideMode.ElideRight,
                                                int(rect.width()) - 14)
            painter.drawText(QRectF(rect.left() + 7.0, rect.top() + 15.0,
                                    rect.width() - 14.0, rect.height() - 19.0), alignment, value)
        finally:
            painter.end()
