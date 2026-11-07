"""0ac0d0/0af270/0ae610/0afdf0 NeonSplash加载态；本地授权不访问网络。"""
from __future__ import annotations

import math
from PySide6.QtCore import Qt, QPointF, QRectF, Property, Signal, QPropertyAnimation, QTimer
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen, QBrush,
                          QLinearGradient, QRadialGradient)
from PySide6.QtWidgets import QWidget, QPushButton

from .startup_stages import LOCAL_AUTHORIZATION


DECORATIVE_STAGES = ("加载契约", "初始化界面", "抓屏自检", "决策引擎", "就绪")
CYAN = QColor("#00e5ff")
PURPLE = QColor("#8b5cf6")
BORDER = QColor("#253048")
MUTED = QColor("#4a5670")
TEXT = QColor("#e6eeff")
TRANSPARENT = QColor(0, 0, 0, 0)


def _alpha(color, alpha):
    value = QColor(color)
    value.setAlpha(alpha)
    return value


def _gradient(start, end, stops):
    gradient = QLinearGradient(start, end)
    for position, color in stops: gradient.setColorAt(position, color)
    return gradient


def _glow(painter, center, radius, color):
    gradient = QRadialGradient(center, radius)
    gradient.setColorAt(0, color)
    gradient.setColorAt(1, TRANSPARENT)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawEllipse(center, radius, radius)


class NeonSplash(QWidget):
    """只绘制已核实加载态；不创建原卡密输入/联网面板。

    cancelled仅发信号，由StartupStages.cancel_from_splash执行退出。
    accept_local_authorization记录显式差异，清授权绘制标志、显示加载进度。
    record可接日志；未注入时仍保留audit_events，不冒充已写磁盘日志。
    """
    cancelled = Signal()

    def __init__(self, parent=None, *, version="1.0.38", website="https://wowbuddy.cn",
                 record=None, start_animations=True):
        super().__init__(parent, Qt.WindowType(0x4080F))
        self.setFixedSize(760, 452)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("WOW战斗助手")
        self.setStyleSheet("background: transparent;")
        self.version = str(version)
        self.website = str(website)
        self.progress = 0.0
        self.status_text = ""
        self.active_stage = -1
        self._sweep = 0.0
        self.phase = 0.0
        self.awaiting_authorization = True
        self.audit_events = []
        self._record = record
        self._drag_offset = QPointF()
        self.close_button = QPushButton("✕", self)
        self.close_button.setObjectName("CornerClose")
        self.close_button.setFixedSize(36, 27)
        self.close_button.move(710, 10)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:6px;padding:0;"
            "color:#7c8ba8;font-size:13px;}QPushButton:hover{background:#1e273b;color:#ff4d4d;}")
        self.close_button.clicked.connect(self.cancelled)
        self.sweep_animation = QPropertyAnimation(self, b"sweep", self)
        self.sweep_animation.setStartValue(0.0)
        self.sweep_animation.setEndValue(360.0)
        self.sweep_animation.setDuration(2600)
        self.sweep_animation.setLoopCount(-1)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(33)
        self.pulse_timer.timeout.connect(self.advance_pulse)
        if start_animations:
            self.sweep_animation.start()
            self.pulse_timer.start()

    def _get_sweep(self): return self._sweep

    def _set_sweep(self, value):
        self._sweep = float(value)
        self.update()

    sweep = Property(float, _get_sweep, _set_sweep)

    def stop_animations(self):
        self.sweep_animation.stop()
        self.pulse_timer.stop()

    def advance_pulse(self):
        # 0ad8c0: +0.045，严格大于2π才减一次，不做任意取模。
        self.phase += 0.045
        if self.phase > 2 * math.pi: self.phase -= 2 * math.pi
        self.update()

    def set_progress(self, value, text=""):
        value = float(value)
        # 按0acb20比较顺序处理NaN，与Python min/max默认行为不同。
        value = value if value <= 1.0 else 1.0
        self.progress = 0.0 if value <= 0.0 else value
        if text: self.status_text = str(text)
        self.active_stage = min(int(len(DECORATIVE_STAGES) * self.progress), len(DECORATIVE_STAGES) - 1)
        self.update()

    def accept_local_authorization(self):
        if not self.awaiting_authorization: return
        self.awaiting_authorization = False
        self.audit_events.append(LOCAL_AUTHORIZATION)
        if self._record is not None: self._record(LOCAL_AUTHORIZATION)
        # 状态文字沿用0ad770；差异已经单独记录，不伪造服务器响应。
        self.status_text = "验证通过，开始启动"
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition() - QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            from .window_shell import round_global_coordinate
            position = event.globalPosition() - self._drag_offset
            self.move(round_global_coordinate(position.x()), round_global_coordinate(position.y()))
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
            outer = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
            outline = QPainterPath()
            outline.addRoundedRect(outer, 18, 18)
            background = _gradient(outer.topLeft(), outer.bottomLeft(),
                ((0, QColor("#141b2b")), (0.55, QColor("#0e1421")), (1, QColor("#0a0e17"))))
            painter.fillPath(outline, QBrush(background))
            painter.save()
            painter.setClipPath(outline)
            top = _gradient(outer.topLeft(), outer.topRight(), ((0, TRANSPARENT), (0.35, CYAN), (1, TRANSPARENT)))
            painter.setPen(QPen(QBrush(top), 1.6))
            painter.drawLine(QPointF(outer.left()+8, outer.top()+1), QPointF(outer.right()-8, outer.top()+1))
            painter.setPen(QPen(QColor(26, 35, 54, 120), 1))
            x = outer.left()
            while x < outer.right():
                painter.drawLine(QPointF(x, outer.top()), QPointF(x, outer.bottom()))
                x += 26
            y = outer.top()
            while y < outer.bottom():
                painter.drawLine(QPointF(outer.left(), y), QPointF(outer.right(), y))
                y += 26
            corner = QRadialGradient(QPointF(outer.right()-40, outer.bottom()+30), 240)
            corner.setColorAt(0, _alpha(PURPLE, 70))
            corner.setColorAt(1, TRANSPARENT)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(corner))
            painter.drawRect(outer)
            painter.restore()
            painter.setPen(QPen(BORDER, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(outer, 18, 18)
            content = outer.adjusted(34, 40, -34, -26)
            self._paint_header(painter, content)
            if not self.awaiting_authorization: self._paint_progress(painter, content)
            font = QFont(self.font())
            font.setPointSizeF(9)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            footer = _gradient(QPointF(outer.left()+34, 0), QPointF(outer.left()+300, 0), ((0, CYAN), (1, PURPLE)))
            painter.setPen(QPen(QBrush(footer), 1))
            painter.drawText(QRectF(outer.left()+34, outer.bottom()-34, 420, 20), 0x81, "官网  " + self.website)
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(MUTED)
            painter.drawText(QRectF(outer.right()-260, outer.bottom()-34, 226, 20), 0x82, "v" + self.version)
        finally:
            painter.end()

    def _paint_header(self, painter, area):
        center = QPointF(area.left()+96, area.center().y()-26)
        for i in range(7, 0, -1):
            radius = (i*0.3+1) * (math.sin(self.phase)*0.06+1) * 46
            _glow(painter, center, radius, _alpha(CYAN, int((1-i*0.125)*0.85*0.3*255)))
        painter.setPen(QPen(BORDER, 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, 58, 58)
        for i in range(3):
            radius = 58 - i*3
            ring = QRectF(center.x()-radius, center.y()-radius, radius*2, radius*2)
            arc = QPainterPath()
            arc.arcMoveTo(ring, self._sweep+i*14)
            arc.arcTo(ring, self._sweep+i*14, 92)
            painter.setPen(QPen(_alpha(CYAN, 255-i*70), 3-i*0.6, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.BevelJoin))
            painter.drawPath(arc)
        for row in range(3):
            for column in range(3):
                active = (row in (0, 1) and column == 1) or (row == 2 and column == 2)
                if active:
                    mix = (row+column)*0.25
                    brightness = math.sin((row+column)*0.6+self.phase)*0.25+0.75
                    channels = [int((b*mix+a*(1-mix))) for a, b in zip(CYAN.getRgb()[:3], PURPLE.getRgb()[:3])]
                    painter.setBrush(QColor(*(int(channel*brightness) for channel in channels)))
                    painter.setPen(Qt.PenStyle.NoPen)
                else:
                    painter.setBrush(QColor("#1b2438"))
                    painter.setPen(QPen(BORDER, 1))
                painter.drawRoundedRect(QRectF(center.x()-21+column*16, center.y()-21+row*16, 14, 14), 3.5, 3.5)
        left = area.left()+186
        font = QFont(self.font())
        font.setPointSizeF(23)
        font.setWeight(QFont.Weight.Black)
        painter.setFont(font)
        title = _gradient(QPointF(left, 0), QPointF(left+330, 0),
                          ((0, QColor("#e8fbff")), (0.6, CYAN), (1, PURPLE)))
        painter.setPen(QPen(QBrush(title), 1))
        painter.drawText(QRectF(left, area.top()+74, 420, 44), 0x81, self.windowTitle())
        painter.setFont(QFont("Cascadia Mono", 9))
        painter.setPen(CYAN)
        painter.drawText(QRectF(left, area.top()+126, 500, 20), 0x81, "▸ " + (self.status_text or "准备中…"))

    def _paint_progress(self, painter, area):
        bar = QRectF(area.left()+186, area.top()+186, area.width()-232, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b2438"))
        painter.drawRoundedRect(bar, 3, 3)
        if self.progress > 0.001:
            fill = QRectF(bar)
            fill.setWidth(bar.width()*self.progress)
            painter.setBrush(QBrush(_gradient(fill.topLeft(), fill.topRight(), ((0, CYAN), (1, PURPLE)))))
            painter.drawRoundedRect(fill, 3, 3)
            _glow(painter, QPointF(fill.right(), fill.center().y()), 14, QColor(207, 250, 255, 210))
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(TEXT)
        painter.drawText(QRectF(bar.right()-60, bar.top()-26, 60, 20), 0x82, f"{int(self.progress*100)}%")
        font.setPointSizeF(8.5)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        step = bar.width()/len(DECORATIVE_STAGES)
        y = bar.bottom()+30
        for index, label in enumerate(DECORATIVE_STAGES):
            color = QColor("#22e58b") if index < self.active_stage else (CYAN if index == self.active_stage else MUTED)
            center = QPointF(bar.left()+index*step+6, y)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            radius = 4 if index == self.active_stage else 3
            painter.drawEllipse(center, radius, radius)
            if index == self.active_stage: _glow(painter, center, 13, _alpha(color, 150))
            painter.setPen(color)
            painter.drawText(QRectF(center.x()+10, y-9, step-16, 18), 0x81, label)
