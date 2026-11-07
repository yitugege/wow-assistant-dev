"""原生主窗三栏静态布局。无信号连接、定时器、联网、文件修改或发键。

需要调用者先创建 QApplication；build_ui 不 show、不进入事件循环。
顶层使用原版 QWidget 直接承载外层布局，壳层行为另接。
"""
from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)


NATIVE_STYLESHEET = '\n* { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; }\n\nQWidget#Root {\n    background: qlineargradient(x1:0,y1:0,x2:0.7,y2:1,\n                stop:0 #141B2B, stop:0.55 #0E1421, stop:1 #0a0e17);\n    border: 1px solid #253048;\n    border-radius: 14px;\n}\nQWidget#Card {\n    background: #111724;\n    border: 1px solid #253048;\n    border-radius: 10px;\n}\nQLabel#Title {\n    color: #00e5ff;\n    font-size: 13px;\n    font-weight: 600;\n    letter-spacing: 1px;\n}\nQLabel#H1 {\n    color: #e6eeff;\n    font-size: 15px;\n    font-weight: 700;\n}\nQLabel { color: #e6eeff; font-size: 12px; }\nQLabel#Dim { color: #7c8ba8; }\n\nQPushButton {\n    background: #161d2d;\n    color: #e6eeff;\n    border: 1px solid #253048;\n    border-radius: 8px;\n    padding: 6px 14px;\n    font-size: 12px;\n}\nQPushButton:hover {\n    background: #1e273b;\n    border: 1px solid #00e5ff;\n    color: #00e5ff;\n}\nQPushButton:pressed { background: #111724; }\nQPushButton:disabled { color: #4a5670; border-color: #253048; background: #111724; }\nQPushButton#Primary {\n    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,\n                stop:0 #00e5ff, stop:1 #8b5cf6);\n    color: #04121A;\n    font-weight: 700;\n    border: none;\n}\nQPushButton#Primary:hover {\n    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,\n                stop:0 #7df9ff, stop:1 #00e5ff);\n}\nQPushButton#Primary:disabled { background: #253048; color: #4a5670; }\n\nQComboBox, QSpinBox, QLineEdit {\n    background: #111724;\n    color: #e6eeff;\n    border: 1px solid #253048;\n    border-radius: 8px;\n    padding: 5px 8px;\n    selection-background-color: #00e5ff;\n}\nQComboBox:hover, QSpinBox:hover { border: 1px solid #00e5ff; }\nQComboBox::drop-down { border: none; width: 18px; }\nQComboBox QAbstractItemView {\n    background: #161d2d;\n    color: #e6eeff;\n    border: 1px solid #253048;\n    selection-background-color: #1e273b;\n    outline: none;\n}\n\nQCheckBox { color: #e6eeff; spacing: 7px; font-size: 12px; }\nQCheckBox::indicator {\n    width: 15px; height: 15px;\n    border: 1px solid #253048; border-radius: 4px;\n    background: #111724;\n}\nQCheckBox::indicator:checked {\n    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,\n                stop:0 #00e5ff, stop:1 #8b5cf6);\n    border: 1px solid #00e5ff;\n}\n\n/* ---- 阈值滑条（一律水平）：细轨道 + 霓虹已选段 + 圆形旋钮 ----\n   滑条语义是「0 = 关闭」，已选段用霓虹渐变：值为 0 时渐变段宽度为 0，\n   整条轨道自动回落到深底色 —— 不用额外代码就与「关闭」态视觉一致。\n   ★ 旋钮刻意 **不加 border**：subcontrol 带边框时 Qt 会把 border-radius 按内容盒\n   钳制，半径拿不到半宽 → 渲染出来是个圆角方块（实测踩过）。改成\n   无边框 14x14 + radius 7px，半径正好等于半宽，才是真圆。\n   旋钮要溢出 8px 轨道，靠负 margin 撑出可绘制区（16-8 = 8px 居中）。\n   渐变只用 qlineargradient —— 本文件里已验证可用，语法写错会让整张样式表失效。 */\nQSlider { min-height: 20px; background: transparent; }\nQSlider::groove:horizontal {\n    height: 6px;\n    border: 1px solid #253048;\n    border-radius: 4px;\n    background: #0a0e17;\n}\nQSlider::sub-page:horizontal {\n    border-radius: 3px;\n    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,\n                stop:0 #00e5ff, stop:1 #8b5cf6);\n}\nQSlider::add-page:horizontal { background: transparent; }\nQSlider::handle:horizontal {\n    width: 14px;\n    height: 14px;\n    margin: -7px 0;\n    border: none;\n    border-radius: 7px;\n    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,\n                stop:0 #7df9ff, stop:0.45 #00e5ff, stop:1 #8b5cf6);\n}\nQSlider::handle:horizontal:hover {\n    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,\n                stop:0 #FFFFFF, stop:0.45 #7df9ff, stop:1 #00e5ff);\n}\nQSlider::handle:horizontal:pressed {\n    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,\n                stop:0 #00e5ff, stop:1 #8b5cf6);\n}\nQSlider::handle:horizontal:disabled { background: #253048; }\n\nQPlainTextEdit, QTextEdit {\n    background: #0a0e17;\n    color: #e6eeff;\n    border: 1px solid #253048;\n    border-radius: 8px;\n    font-family: "Cascadia Mono", "Consolas", monospace;\n    font-size: 11px;\n    selection-background-color: #1e273b;\n}\n\n/* 下载进度条（软件更新卡片用）。不写这条会掉回系统默认的白底粗条，\n   在暗色面板上非常突兀 —— 它是「界面里唯一一块亮白」那种突兀。 */\nQProgressBar {\n    background: #0a0e17;\n    border: 1px solid #253048;\n    border-radius: 5px;\n    text-align: center;\n    color: #e6eeff;\n}\nQProgressBar::chunk {\n    border-radius: 4px;\n    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,\n                stop:0 #00e5ff, stop:1 #8b5cf6);\n}\n\nQScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }\nQScrollBar::handle:vertical {\n    background: #253048; border-radius: 4px; min-height: 26px;\n}\nQScrollBar::handle:vertical:hover { background: #00e5ff; }\nQScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }\nQScrollBar::handle:horizontal {\n    background: #253048; border-radius: 4px; min-width: 26px;\n}\nQScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }\nQScrollBar::add-page, QScrollBar::sub-page { background: transparent; }\n\nQScrollArea { background: transparent; border: none; }\n/* 滚动区内容体：必须有**自己的不透明底色**。\n   否则 QAbstractScrollArea 的视口（系统白）会从卡片间隙、底部余量透出来，\n   看起来就是「背景没了 / 一片白」。给视口设调色板或样式表在这里都不生效（实测）。 */\nQWidget#ScrollBody {\n    background: #111724;\n    border: none;\n    border-radius: 12px;\n}\n/* ★ 视口（viewport）必须单独置透明。QAbstractScrollArea 默认给视口设 QPalette::Base\n   角色背景并开 autoFillBackground，只写 QScrollArea 规则没用 —— 卡片之间的间隙会\n   透出系统白底，看起来就像「面板出现白色边框」（实测踩过，用像素统计定位到的）。 */\nQScrollArea > QWidget#qt_scrollarea_viewport { background: transparent; }\nQToolTip {\n    background: #161d2d; color: #e6eeff; border: 1px solid #00e5ff;\n    border-radius: 6px; padding: 6px;\n}\n'  # PE RVA 0xd3e20；074fd0的13色替换。


@dataclass(frozen=True)
class UiWidgets:
    root: QWidget
    title_bar: QWidget
    title_label: QLabel
    website_button: QPushButton
    minimize_button: QPushButton
    close_button: QPushButton
    left_scroll: QScrollArea
    center_panel: QWidget
    right_panel: QWidget
    cards: dict[str, QWidget]
    window_combo: QComboBox
    refresh_button: QPushButton
    monitor_button: QPushButton
    calibration_label: QLabel
    addon_version_label: QLabel
    addon_path: QLineEdit
    addon_detect_button: QPushButton
    addon_browse_button: QPushButton
    addon_install_button: QPushButton
    addon_clean_button: QPushButton
    addon_status: QLabel
    update_status: QLabel
    update_progress: QProgressBar
    update_check_button: QPushButton
    update_apply_button: QPushButton
    auto_update_check: QCheckBox
    send_interval_spin: QSpinBox
    poll_interval_spin: QSpinBox
    rotation_combo: QComboBox
    hub_pull_button: QPushButton
    hub_online_button: QPushButton
    hub_status: QLabel
    sent_label: QLabel
    fps_label: QLabel
    elapsed_label: QLabel
    available_count: QLabel
    available_details: QLabel
    spec_label: QLabel
    field_count_label: QLabel
    show_all_check: QCheckBox
    threshold_grid: QGridLayout
    threshold_hint: QLabel
    threshold_host: QWidget
    field_grid: QGridLayout
    field_scroll: QScrollArea
    field_canvas: QWidget
    suggestions: QPlainTextEdit
    log_view: QPlainTextEdit
    clear_log_button: QPushButton
    status_bar: QWidget
    status_label: QLabel       # +1a8：监控/扫描状态；初始“未开始”。
    send_status_label: QLabel  # +1b0：输入发送状态；初始“发键：未开始”。
    frame_status_label: QLabel # +1c0：帧/运行诊断；初始“—”。

    @property
    def monitor_interval(self) -> QSpinBox:
        return self.send_interval_spin

    @property
    def repeat_interval(self) -> QSpinBox:
        return self.poll_interval_spin


def _label(text: str, *, name: str = '', wrap: bool = False) -> QLabel:
    result = QLabel(text)
    if name:
        result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


def _button(text: str, height: int = 0, name: str = '') -> QPushButton:
    result = QPushButton(text)
    if height:
        result.setMinimumHeight(height)
    if name:
        result.setObjectName(name)
    return result


def _column(parent: QWidget | None = None) -> tuple[QWidget, QVBoxLayout]:
    panel = QWidget(parent)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(13)
    return panel, layout


def _card(title: str, subtitle: str = '') -> tuple[QWidget, QVBoxLayout]:
    card = QWidget()
    card.setObjectName('Card')
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 13)
    layout.setSpacing(9)
    layout.addWidget(_label(title, name='Title'))
    if subtitle:
        layout.addWidget(_label(subtitle, name='Dim', wrap=True))
    return card, layout


def _transparent_viewport(scroll: QScrollArea) -> None:
    palette = scroll.viewport().palette()
    palette.setColor(QPalette.ColorRole.Base, Qt.GlobalColor.transparent)
    palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
    scroll.viewport().setPalette(palette)
    scroll.viewport().setAutoFillBackground(True)


def build_ui(window: QWidget, *, app_name: str = 'WOW战斗助手', version: str = '',
             website: str = 'wowbuddy.cn', auto_update: bool = True) -> UiWidgets:
    """创建原版控件并返回引用；业务连接/资源动态数据/壳层事件全部交调用方。"""
    if window.layout() is not None:
        raise ValueError('build_ui 需要尚无布局的 QWidget')
    window.setWindowTitle(app_name)
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.setMinimumSize(1160, 740)
    window.resize(1330, 830)
    window.setStyleSheet(NATIVE_STYLESHEET)
    outer = QVBoxLayout(window)
    outer.setContentsMargins(18, 18, 18, 18)
    root = QWidget()
    root.setObjectName('Root')
    root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    outer.addWidget(root)
    shadow = QGraphicsDropShadowEffect(root)
    shadow.setBlurRadius(44)
    shadow.setOffset(0, 10)
    shadow.setColor(QColor(0, 0, 0, 200))
    root.setGraphicsEffect(shadow)
    root_layout = QVBoxLayout(root)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    title_bar = QWidget()
    title_bar.setObjectName('TitleBar')
    title_bar.setFixedHeight(48)
    title_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    title_layout = QHBoxLayout(title_bar)
    title_layout.setContentsMargins(20, 0, 12, 0)
    title_layout.setSpacing(10)
    icon = _label('◈')
    icon.setStyleSheet('color:#00e5ff;font-size:15px;')
    title_layout.addWidget(icon)
    title_label = _label(app_name, name='H1')
    title_layout.addWidget(title_label)
    title_layout.addStretch(1)
    website_button = _button(f'官网 {website}')
    website_button.setFixedHeight(27)
    website_button.setCursor(Qt.CursorShape.PointingHandCursor)
    website_button.setToolTip(f'打开 https://{website}')
    website_button.setStyleSheet('QPushButton{background:transparent;border:1px solid #1e273b;'
        'border-radius:13px;color:#00e5ff;font-size:11px;padding:0 12px;}'
        'QPushButton:hover{background:#253048;border-color:#00e5ff;}')
    title_layout.addWidget(website_button)
    title_layout.addSpacing(4)
    minimize_button, close_button = _button('—'), _button('✕')
    for button, color in ((minimize_button, '#00e5ff'), (close_button, '#ff4d4d')):
        button.setFixedSize(36, 27)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet('QPushButton{background:transparent;border:none;border-radius:6px;'
            f'color:{color};font-size:13px;}}QPushButton:hover{{background:#1e273b;color:#7c8ba8;}}')
        title_layout.addWidget(button)
    root_layout.addWidget(title_bar)

    body = QWidget()
    body_layout = QHBoxLayout(body)
    body_layout.setContentsMargins(16, 4, 16, 8)
    body_layout.setSpacing(13)
    cards = {}
    left_body, left_layout = _column()
    left_body.setObjectName('ScrollBody')
    left_body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    target_card, target_layout = _card('目标窗口', '认进程名不认标题；只有装了插件的客户端才有数据。')
    cards['target'] = target_card
    window_combo = QComboBox()
    window_combo.setMinimumHeight(30)
    window_combo.setMinimumContentsLength(10)
    window_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    target_layout.addWidget(window_combo)
    row = QHBoxLayout()
    refresh_button = _button('刷新')
    monitor_button = _button('开始监控', 36, 'Primary')
    row.addWidget(refresh_button)
    row.addWidget(monitor_button, 1)
    target_layout.addLayout(row)
    calibration_label = _label('基准标记：未校准', name='Dim', wrap=True)
    addon_version_label = _label('插件版本：—', name='Dim', wrap=True)
    for label in (calibration_label, addon_version_label):
        label.setMinimumHeight(window.fontMetrics().height() * 2 + 4)
        target_layout.addWidget(label)
    send_interval_spin, poll_interval_spin = QSpinBox(), QSpinBox()
    for name, spin, lo, hi, step, value in (
        ('发送频率', send_interval_spin, 50, 5000, 50, 100),
        ('轮询间隔', poll_interval_spin, 20, 500, 10, 25)):
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setSuffix(' ms')
        row = QHBoxLayout()
        row.addWidget(_label(name))
        row.addWidget(spin, 1)
        target_layout.addLayout(row)
    send_interval_spin.setToolTip('两次发键之间的最小间隔')
    poll_interval_spin.setToolTip('越小反应越快、CPU 越高。\n一帧（抓屏+解码）约 25ms 打底，\n'
        '低于 25ms 不会更快，只会空转。\n实际每秒帧数 ≈ 1000 / 本值（定时器已用精确定时器）。')
    rotation_combo = QComboBox()
    rotation_combo.setMinimumContentsLength(6)
    rotation_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    rotation_combo.addItem('未选择（不自动发键）', '')
    rotation_combo.setToolTip('软件不自带循环：必须从下面选一套循环库方案才会发键。\n'
        '列表会自动保持最新（启动检查一次、之后每 30 分钟一次），\n'
        '没有合适的就点「拉取」立即刷新，或到循环库页面自己传一套。')
    hub_pull_button = _button('拉取', 29)
    hub_pull_button.setToolTip('立即联网检查循环库更新。\n平时不用点：启动时会自动检查一次，之后每 30 分钟自动检查，\n'
        '有更新会自动下载并生效（快照存到软件目录的 hub\\ 下，离线也能用）。')
    row = QHBoxLayout()
    row.addWidget(_label('循环方案'))
    row.addWidget(rotation_combo, 1)
    row.addWidget(hub_pull_button)
    hub_online_button = _button('GitHub刷新', 29)
    hub_online_button.setVisible(False)
    row.addWidget(hub_online_button)
    target_layout.addLayout(row)
    hub_status = _label('尚未拉取循环库', name='Dim', wrap=True)
    target_layout.addWidget(hub_status)
    target_layout.addWidget(_label('开启后自动发键 · 后台投递 · 读条期间停发', name='Dim', wrap=True))
    left_layout.addWidget(target_card)

    addon_card, layout = _card('插件安装', '软件自带插件包，装到游戏的 AddOns 目录。')
    cards['addon'] = addon_card
    addon_path = QLineEdit()
    addon_path.setMinimumHeight(30)
    addon_path.setPlaceholderText('游戏 AddOns 目录，例如 …\\World of Warcraft\\_classic_beta_\\Interface\\AddOns')
    addon_path.setToolTip('这是插件的最终安装位置。\n自动检测填不出来时，点「选择目录…」自己指到任意一层，软件会自己找 AddOns。')
    layout.addWidget(addon_path)
    addon_detect_button = _button('自动检测', 28, 'Dim')
    addon_browse_button = _button('选择目录…', 28, 'Dim')
    addon_detect_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    addon_detect_button.setToolTip('点一下自动检测；右键可以选择最近用过的目录')
    addon_browse_button.setToolTip('手动指定：游戏根目录 / 客户端目录 / Interface / AddOns 都行')
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(addon_detect_button)
    row.addWidget(addon_browse_button)
    layout.addLayout(row)
    addon_install_button = _button('安装插件到游戏', 30)
    addon_clean_button = _button('清理旧插件', 30, 'Dim')
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(addon_install_button, 1)
    row.addWidget(addon_clean_button)
    layout.addLayout(row)
    addon_status = _label('', name='Dim', wrap=True)
    addon_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    addon_status.setMinimumHeight(window.fontMetrics().height() * 2 + 4)
    layout.addWidget(addon_status)
    left_layout.addWidget(addon_card)

    update_card, layout = _card('软件更新', '启动时自动检查；发现新版本会下载并校验，通过才替换。')
    cards['update'] = update_card
    update_status = _label(f'当前 v{version}' if version else '', name='Dim', wrap=True)
    update_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    update_status.setMinimumHeight(window.fontMetrics().height() * 2 + 4)
    layout.addWidget(update_status)
    update_progress = QProgressBar()
    update_progress.setRange(0, 100)
    update_progress.setValue(0)
    update_progress.setTextVisible(False)
    update_progress.setFixedHeight(8)
    update_progress.hide()
    layout.addWidget(update_progress)
    update_check_button = _button('检查更新', 28, 'Dim')
    update_apply_button = _button('立即更新', 28, 'Primary')
    update_apply_button.hide()
    row = QHBoxLayout()
    row.addWidget(update_check_button)
    row.addWidget(update_apply_button, 1)
    layout.addLayout(row)
    auto_update_check = QCheckBox('启动时自动检查并更新')
    auto_update_check.setChecked(auto_update)
    auto_update_check.setToolTip('开启：启动时自动检查，发现新版本直接下载并升级（升级后会重启程序）。\n'
        '关闭：只提示有新版本，什么时候更新由你决定。')
    layout.addWidget(auto_update_check)
    left_layout.addWidget(update_card)

    stats_card, layout = _card('本局统计')
    cards['stats'] = stats_card
    row = QHBoxLayout()
    statistic_labels = []
    for name in ('已发送', '帧/秒', '运行秒'):
        tile = QWidget()
        tile.setObjectName('Card')
        tile.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tile.setMinimumHeight(58)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(6, 9, 6, 9)
        tile_layout.setSpacing(1)
        value = _label('—')
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value.setStyleSheet('color:#00e5ff;font-size:18px;font-weight:800;')
        tile_layout.addWidget(value)
        caption = _label(name, name='Dim')
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile_layout.addWidget(caption)
        row.addWidget(tile, 1)
        statistic_labels.append(value)
    sent_label, fps_label, elapsed_label = statistic_labels
    layout.addLayout(row)
    left_layout.addWidget(stats_card)
    available_card, layout = _card('可用技能', '插件上报每个动作此刻能否施放')
    cards['available'] = available_card
    available_count = _label('— / —')
    available_count.setStyleSheet('color:#00e5ff;font-size:24px;font-weight:800;')
    layout.addWidget(available_count)
    available_details = _label('开启监控后显示', name='Dim', wrap=True)
    available_details.setTextFormat(Qt.TextFormat.RichText)
    available_details.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    layout.addWidget(available_details, 1)
    left_layout.addWidget(available_card, 1)
    footer = _label(f'{website}   ·   v{version}', name='Dim')
    footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
    left_layout.addWidget(footer)
    left_scroll = QScrollArea()
    left_scroll.setFixedWidth(336)
    left_scroll.setWidgetResizable(True)
    left_scroll.setFrameShape(QFrame.Shape.NoFrame)
    left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    _transparent_viewport(left_scroll)
    left_scroll.setWidget(left_body)
    body_layout.addWidget(left_scroll)

    center_panel, center_layout = _column()
    fields_card, layout = _card('实时字段')
    cards['fields'] = fields_card
    row = QHBoxLayout()
    spec_label = _label('专精：未识别', name='H1')
    field_count_label = _label('字段：—', name='Dim')
    show_all_check = QCheckBox('显示全部')
    show_all_check.setToolTip('连本职业用不到的字段格一起显示')
    row.addWidget(spec_label)
    row.addStretch(1)
    row.addWidget(field_count_label)
    row.addWidget(show_all_check)
    layout.addLayout(row)
    center_layout.addWidget(fields_card)
    threshold_card, layout = _card('技能触发线 · 阈值')
    cards['thresholds'] = threshold_card
    from .swatch_strip import SwatchStrip
    field_canvas = SwatchStrip(threshold_card)
    field_canvas.hide()
    threshold_hint = _label('未识别专精：开关行等识别到职业后再列', name='Dim', wrap=True)
    layout.addWidget(threshold_hint)
    threshold_host = QWidget()
    threshold_grid = QGridLayout(threshold_host)
    threshold_grid.setContentsMargins(0, 0, 0, 0)
    threshold_grid.setHorizontalSpacing(10)
    threshold_grid.setVerticalSpacing(3)
    threshold_grid.setColumnStretch(3, 1)
    threshold_grid.setColumnMinimumWidth(0, 100)
    threshold_grid.setColumnMinimumWidth(2, 56)
    layout.addWidget(threshold_host)
    center_layout.addWidget(threshold_card)
    field_scroll = QScrollArea()
    field_scroll.setWidgetResizable(True)
    field_scroll.setFrameShape(QFrame.Shape.NoFrame)
    field_container = QWidget()
    field_container.setObjectName('Card')
    field_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    field_grid = QGridLayout(field_container)
    field_grid.setContentsMargins(10, 10, 10, 10)
    field_grid.setSpacing(4)
    _transparent_viewport(field_scroll)
    field_scroll.setWidget(field_container)
    field_scroll.setParent(center_panel)
    field_scroll.hide()  # 原函数明确hide且未加入中栏layout。
    center_layout.addStretch(1)
    body_layout.addWidget(center_panel, 1)

    right_panel, right_layout = _column()
    right_panel.setFixedWidth(344)
    suggestions_card, layout = _card('动作建议')
    cards['suggestions'] = suggestions_card
    suggestions = QPlainTextEdit()
    suggestions.setReadOnly(True)
    suggestions.setMinimumHeight(190)
    suggestions.setPlaceholderText('引擎逐帧给出候选动作…')
    layout.addWidget(suggestions)
    right_layout.addWidget(suggestions_card, 1)
    log_card, layout = _card('运行日志')
    cards['log'] = log_card
    log_view = QPlainTextEdit()
    log_view.setReadOnly(True)
    layout.addWidget(log_view)
    clear_log_button = _button('清空日志')
    layout.addWidget(clear_log_button)
    right_layout.addWidget(log_card, 1)
    body_layout.addWidget(right_panel)
    root_layout.addWidget(body, 1)

    status_bar = QWidget()
    status_bar.setFixedHeight(30)
    status_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    status_layout = QHBoxLayout(status_bar)
    status_layout.setContentsMargins(20, 0, 20, 0)
    status_layout.setSpacing(18)
    status_label = _label('未开始')
    send_status_label = _label('发键：未开始', name='Dim')
    frame_status_label = _label('—', name='Dim')
    status_layout.addWidget(status_label)
    status_layout.addStretch(1)
    status_layout.addWidget(send_status_label)
    status_layout.addWidget(frame_status_label)
    root_layout.addWidget(status_bar)
    values = locals()
    return UiWidgets(**{name: values[name] for name in UiWidgets.__dataclass_fields__})
