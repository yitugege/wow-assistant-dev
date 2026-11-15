"""0929d0：在主窗边距内绘制原生顶部渐变线。"""
from PySide6.QtCore import Qt, QLineF, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QBrush, QPen, QPainter


def paint_top_accent(painter, window_rect):
    rect = window_rect.adjusted(18, 18, -18, -18)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    gradient = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.topRight()))
    gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
    gradient.setColorAt(0.4, QColor("#00e5ff"))
    gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.setPen(QPen(QBrush(gradient), 1.6, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.BevelJoin))
    painter.drawLine(QLineF(rect.left() + 12, rect.top() + 1,
                           rect.right() - 12, rect.top() + 1))
