"""09aa10/09e140 的动态阈值控件；规则、合并和配置语义由 thresholds/controller 提供。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Sequence

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QGridLayout, QLabel, QSlider, QWidget

from .thresholds import SliderGroup, value_label


UNKNOWN_SPEC_HINT = "未识别专精：识别到职业后，这里按「一个技能一条滑条」列出该专精的触发线"
NO_PROFILE_HINT = "尚未选择循环：软件不自带循环，未选择时不会自动发键。请在上方「循环方案」里选一套循环库方案（没有就点「拉取」）。"
ACTIVE_VALUE_STYLE = "color:#22e58b;font-weight:600;"
OFF_VALUE_STYLE = "color:#4a5670;"


def field_subject(field: str) -> str:
    """0a1e10：大小写敏感子串检查，party > pet > target > 自己。"""
    if "party" in field:
        return "队友"
    if "pet" in field:
        return "宠物"
    return "目标" if "target" in field else "自己"


def _unique(items):
    return tuple(dict.fromkeys(items))


def hint_text(groups: Sequence[SliderGroup], *, spec_id: str,
              library_profile_name: str | None = None) -> str:
    if not spec_id:
        return UNKNOWN_SPEC_HINT
    source = f"循环库方案「{library_profile_name}」" if library_profile_name is not None else "未选择循环"
    count = sum(len(group.thresholds) for group in groups)
    if not count:
        return (source + "：这套循环没有技能触发阈值。循环库里的方案带阈值时会自动在这里列出滑条。"
                if library_profile_name is not None else NO_PROFILE_HINT)
    return (f"{source}：{len(groups)} 条技能触发线（{count} 条血线条件并合而来）。"
            "每个技能一条 —— 调到「血/资源到多少才放它」，拖到 0 = 不发这个技能")


@dataclass(frozen=True)
class ThresholdPresentation:
    label: str
    tooltip: str
    subjects: tuple[str, ...]
    fields: tuple[str, ...]


def presentations(groups: Sequence[SliderGroup]) -> tuple[ThresholdPresentation, ...]:
    """只生成展示文字，不再次分组、排序、提升规则或迁移settings。"""
    if any(not group.thresholds for group in groups):
        raise ValueError("滑条组不能为空")
    names = tuple("/".join(group.representative.skills) for group in groups)
    subjects = tuple(_unique(field_subject(t.field) for t in group.thresholds) for group in groups)
    signatures = tuple("/".join(values) for values in subjects)
    counts = Counter(names)
    distinct = {name: _unique(signatures[i] for i, other in enumerate(names) if name == other)
                for name in names}
    output = []
    for index, group in enumerate(groups):
        first, name = group.representative, names[index]
        if not name:
            label = (first.field_label or first.label) + "（未查到技能）"
        elif counts[name] > 1:
            suffix = signatures[index] if len(distinct[name]) > 1 else first.field_label or first.label
            label = name + " · " + suffix
        else:
            label = name
        fields = _unique(t.field for t in group.thresholds)
        reason = "规则原话：" + first.reason if first.reason else "规则里没有写说明"
        tooltip = (f"技能：{name or '（未查到，只看条件）'}\n{reason}\n规则原条件：{first.label}"
                   + ("\n类别：" + first.tag if first.tag else "")
                   + "\n看的是：" + "、".join(subjects[index])
                   + (f"（一条滑条同时管这 {len(group.keys)} 项血线条件）" if len(group.keys) > 1 else "")
                   + "\n字段：" + ", ".join(fields) + "\n拖到 0 = 不发这个技能")
        output.append(ThresholdPresentation(label, tooltip, subjects[index], fields))
    return tuple(output)


@dataclass(frozen=True)
class ThresholdRow:
    group: SliderGroup
    description: ThresholdPresentation
    label: QLabel
    slider: QSlider
    value_label: QLabel


class ThresholdPanel:
    """绑定现有 ui.threshold_grid/hint/host；不拥有规则或持久化存储。

    on_change(index,value) 应接 controller.change_slider。构建/同步不会发此回调。
    render 接受 controller 已归一化的 slider_values，不重复初始化或持久化。
    """
    def __init__(self, grid: QGridLayout, hint: QLabel, host: QWidget, *,
                 on_change: Callable[[int, int], None]):
        if grid.parentWidget() is not host:
            raise ValueError("grid 必须属于指定 threshold_host")
        self.grid, self.hint, self.host, self.on_change = grid, hint, host, on_change
        self.rows: tuple[ThresholdRow, ...] = ()
        self._groups: tuple[SliderGroup, ...] | None = None
        self._generation = 0
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        grid.setColumnMinimumWidth(0, 100)
        grid.setColumnMinimumWidth(2, 56)
        grid.setColumnStretch(3, 1)

    def clear(self):
        self._generation += 1
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
            if item.layout() is not None:
                # 原版只有直接控件；不静默吞掉宿主额外嵌套布局。
                raise ValueError("阈值 grid 含未确认的嵌套布局")
        self.rows, self._groups = (), None

    def render(self, groups: Sequence[SliderGroup], values: Sequence[int], *,
               spec_id: str, library_profile_name: str | None = None):
        groups, values = tuple(groups), tuple(values)
        if len(groups) != len(values) or any(not group.thresholds for group in groups):
            raise ValueError("滑条组和归一化值数量不匹配，或含空组")
        if any(type(value) is not int or not 0 <= value <= group.representative.maximum
               for group, value in zip(groups, values)):
            raise ValueError("滑条值必须由 thresholds.initialize_sliders 归一化")
        self.hint.setText(hint_text(groups, spec_id=spec_id, library_profile_name=library_profile_name))
        self.hint.show()  # 原版即使有阈值也展示说明与计数。
        self.host.setVisible(bool(groups))
        if groups != self._groups:
            descriptions = presentations(groups)
            self.clear()
            self._groups = groups
            generation = self._generation
            rows = []
            for index, (group, value, description) in enumerate(zip(groups, values, descriptions)):
                threshold = group.representative
                label = QLabel(description.label)
                label.setToolTip(description.tooltip)
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(0, threshold.maximum)
                slider.setSingleStep(max(1, threshold.step))
                slider.setPageStep(max(1, threshold.maximum // 10))
                slider.setValue(value)
                slider.setFixedWidth(180)
                slider.setToolTip(description.tooltip)
                slider.setTickPosition(QSlider.TickPosition.NoTicks)
                output = QLabel()
                output.setMinimumWidth(56)
                output.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row = ThresholdRow(group, description, label, slider, output)
                for column, widget in enumerate((label, slider, output)):
                    self.grid.addWidget(widget, index, column)
                slider.valueChanged.connect(lambda amount, i=index, g=generation: self._changed(g, i, amount))
                rows.append(row)
            self.rows = tuple(rows)
        for row, value in zip(self.rows, values):
            with QSignalBlocker(row.slider):
                row.slider.setValue(value)
            self._refresh_value(row)
        return self.rows

    def render_controller(self, controller):
        """FrameController 的薄适配；仅实际注入同专精且非空规则时称循环库方案。"""
        profile = controller.selection.active_profile
        active = profile is not None and str(profile.spec_id) == str(controller.spec_id) and bool(profile.rules)
        return self.render(controller.groups, controller.slider_values, spec_id=controller.spec_id,
                           library_profile_name=profile.engine_name if active else None)

    def _changed(self, generation, index, value):
        if generation != self._generation:
            return  # 原deleteLater前可能仍有排队信号，不映射到新组。
        self.on_change(index, value)
        if generation == self._generation:
            for row in self.rows:
                self._refresh_value(row)

    @staticmethod
    def _refresh_value(row):
        value = row.slider.value()
        row.value_label.setText(value_label(row.group.representative, value))
        row.value_label.setStyleSheet(OFF_VALUE_STYLE if value < 1 else ACTIVE_VALUE_STYLE)
