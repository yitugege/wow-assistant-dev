"""有效图像帧到方案/阈值/调度的控制器，不创建UI、计时器或系统后端。

settings 读写由上层显式承接。坏帧已确认身份的重建与候选计算分开。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .candidates import infer_role
from .expressions import EvaluationContext
from .display_schema import LayoutFrame, blank_schema
from .pipeline import DecisionPipeline, Frame, PreparedFrame
from .pixel_geometry import RGBImage
from .rotation_selection import (HubState, ApplyResult, initial_selection,
    restore_for_spec, rebuild_selection, apply_selection, refresh_library)
from .scheduler import Scheduler, TickResult
from .thresholds import (SliderGroup, visible_thresholds, group_sliders,
    migrate_settings, initialize_sliders, set_slider, promote_profile)


@dataclass(frozen=True)
class SettingsChange:
    selection: Mapping[str, str]
    switches: Mapping[str, int]
    removed_switches: tuple[str, ...] = ()


class FrameController:
    def __init__(self, pipeline: DecisionPipeline, hub: HubState, *,
                 selection_settings: Mapping[str, str] | None = None,
                 switch_settings: Mapping[str, int] | None = None,
                 persist: Callable[[SettingsChange], None] | None = None,
                 load_switches: Callable[[Mapping[str, int]], Mapping[str, int]] | None = None,
                 on_message: Callable[[str], None] | None = None,
                 load_spec_selection: Callable[[str], str] | None = None,
                 on_spec_change: Callable[[str, str], None] | None = None):
        self.pipeline, self.hub = pipeline, hub
        self.selection_settings = dict(selection_settings or {})
        self.switch_settings = dict(switch_settings or {})
        self.selection = initial_selection(self.selection_settings)
        self.persist, self.on_spec_change = persist, on_spec_change
        self.load_switches = load_switches
        self.on_message = on_message
        self.load_spec_selection = load_spec_selection
        self.spec_id = ""
        self.fields: dict[str, str] = {}
        self.last_frame: Frame | None = None
        self.display_frame: Frame | LayoutFrame | None = None
        self.display_revision = 0
        self.spec_pending_key = ""
        self.selection_status = ""
        self.groups: tuple[SliderGroup, ...] = ()
        self.slider_values: tuple[int, ...] = ()
        self.events: list[tuple[str, str]] = []

    def role_group(self) -> str:
        role = infer_role(self.pipeline.engine.roles.get(self.spec_id, {}), EvaluationContext(self.fields))
        return role.group if role.status == 2 else ""

    def _save(self, selection=None, switches=None, removed=()):
        if self.persist is not None and (selection or switches or removed):
            self.persist(SettingsChange(dict(selection or {}), dict(switches or {}), tuple(removed)))

    def _apply(self, result: ApplyResult):
        self.selection, self.selection_settings = result.state, result.settings
        self._save(selection=result.writes)
        self.events.append(("selection", result.effect))
        # 080F60在刷新阈值之前记录应用/实际清除事件；空选无规则不重复提示。
        if self.on_message is not None:
            if result.effect == "applied":
                profile = self.selection.active_profile
                self.on_message(f"循环方案：套用「{profile.name}」（{profile.spec_name}，{len(profile.rules)} 条规则，来源：循环库）")
            elif result.effect == "cleared":
                self.on_message("循环方案：未选择 —— 不自动发键")
        if result.refresh_thresholds:
            # 080F60→08DCB0→09AA10：应用方案时重新合并持久化开关，
            # 不是所有布局刷新都重读，也不能清除仅在内存中的键。
            if self.load_switches is not None:
                self.switch_settings = dict(self.load_switches(self.switch_settings))
            self.refresh_thresholds()

    def refresh_thresholds(self):
        if not self.spec_id:
            self.groups, self.slider_values = (), ()
            return
        # 原版098ea0在完整采样之前已调用09aa10；只需要已确认身份和规则元数据。
        # 不把 layout_only 改成 ok，也不借上帧读数制造一个成功帧。
        thresholds = self.pipeline.builtin_thresholds.get(self.spec_id, ())
        profile = self.selection.profile_for_spec(self.spec_id)
        if profile is not None:
            promoted = promote_profile(self.pipeline.rules, profile)
            if promoted.rules:
                thresholds = promoted.thresholds
        visible = visible_thresholds(thresholds, self.role_group())
        migration = migrate_settings(visible, self.switch_settings)
        self.switch_settings = migration.values
        self.groups = group_sliders(visible)
        initialized = initialize_sliders(self.groups, self.switch_settings)
        self.switch_settings, self.slider_values = initialized.values, initialized.slider_values
        self._save(switches=migration.writes | initialized.writes, removed=migration.removed)

    def select(self, key: str):
        """对应用户选择事件；不因列表有选项自动选择第一项。"""
        self._apply(apply_selection(self.hub, self.selection, self.selection_settings, current_key=key))

    def update_hub(self, hub: HubState):
        changed = hub.changed_pending
        self.hub, result = refresh_library(hub, self.selection, self.selection_settings,
                                          self.spec_id, self.role_group())
        if changed:
            self._report_pending_selection(result.state)
            # 09DD90：按原库顺序列出所有职业方案，再应用当前选择。
            if self.on_message is not None:
                for profile in self.hub.profiles:
                    self.on_message(f"循环库：{profile.spec_name} · {profile.name}（{len(profile.rules)} 条规则，作者 {profile.author or '匿名'}）")
        self._apply(result)

    def change_slider(self, index: int, value: int):
        group = self.groups[index]
        if not 0 <= value <= group.representative.maximum:
            raise ValueError("滑条值超出当前控件范围")
        updated = set_slider(group, value, self.switch_settings)
        self.switch_settings = updated.values
        self.slider_values = tuple(value if i == index else current
                                   for i, current in enumerate(self.slider_values))
        self._save(switches=updated.writes)

    def _rebuild(self):
        self.selection = rebuild_selection(self.hub, self.selection, self.spec_id, self.role_group())
        self._report_pending_selection(self.selection)
        self._apply(apply_selection(self.hub, self.selection, self.selection_settings))

    def _report_pending_selection(self, selection):
        if selection.rebuilt:
            spec, group = selection.spec_id, selection.sub_key
            title = self.pipeline.engine.specs.get(spec, {}).get("title") or spec
            label = f"{title} · {group}" if group else title
            count, total = len(selection.options), len(self.hub.profiles)
            if not spec:
                self.selection_status = f"循环库共 {total} 套 —— 进入角色后按专精显示"
            elif not count:
                self.selection_status = f"{label}暂无循环库方案（库中共 {total} 套）——可到循环库页面自己传一套"
            elif not group:
                self.selection_status = f"{title}：天赋还没读到，先列出全部 {count} 套（库中共 {total} 套）"
            else:
                self.selection_status = f"{label}：{count} 套可选（库中共 {total} 套）"
        # 0999F0：确实重建、findData失败、没有可选项且pending非空时才提示。
        # spec为空但已有列表的早返回不提示；库内容未变化也不重建/重复提示。
        if (self.on_message is not None and selection.rebuilt and not selection.options
                and not selection.current_key and selection.pending_key):
            self.on_message("循环方案：暂时认不出专精，先留着上一套方案，认出后自动恢复")

    def _change_spec(self, frame: Frame, spec_id: str, *, restore: bool):
        previous, self.spec_id = self.spec_id, spec_id
        self.fields = {}
        self.last_frame = None
        self.display_frame = blank_schema(self.pipeline, frame, spec_id)
        self.display_revision += 1
        self.refresh_thresholds()
        if self.on_spec_change is not None:
            self.on_spec_change(previous, spec_id)
        if restore:
            if self.load_spec_selection is not None:
                self.selection_settings[f"hub/by-spec/{spec_id}"] = self.load_spec_selection(spec_id)
            self.selection = restore_for_spec(self.selection, spec_id, self.selection_settings)
            self._rebuild()
        self.spec_pending_key = self.selection.pending_key
        # unknown legacy 不重建循环下拉框、不写入空选择；098be0只重建通用字段。
        self.events.append(("spec", spec_id))

    def _observe_invalid_identity(self, frame: Frame):
        if frame.protocol == "old" and frame.status == "unknown_spec":
            if self.spec_id:
                self._change_spec(frame, "", restore=False)
            return
        if frame.status != "out_of_bounds" or not frame.spec_id or frame.spec_id == self.spec_id:
            return
        definitions = self.pipeline.old.specs if frame.protocol == "old" else self.pipeline.readable.specs
        if frame.spec_id in definitions:
            self._change_spec(frame, frame.spec_id, restore=True)

    def prepare(self, image: RGBImage) -> PreparedFrame:
        frame, old_attempt = self.pipeline.decode(image)
        if not frame.ok:
            self._observe_invalid_identity(frame)
            return self.pipeline.prepare_frame(frame, old_attempt=old_attempt)
        if frame.spec_id != self.spec_id:
            # 098ea0先清字段表，再按专精恢复方案；这一刻天赋分组尚为空。
            self._change_spec(frame, frame.spec_id, restore=True)
        elif (not self.pipeline.legacy_descriptor_cache and self.display_frame is not None
              and self.display_frame.protocol != frame.protocol):
            # 用户选择修复协议切换：解码表和显示缓存必须一起换代。
            # 同专精不重新恢复方案或调用专精变化回调，旧行为对比模式保留。
            self.display_frame = blank_schema(self.pipeline, frame, self.spec_id)
            self.display_revision += 1
        self.last_frame = frame
        self.display_frame = frame
        self.fields = dict(frame.values)
        if frame.protocol == "old":
            # 092c90:1182：天赋暂未知保留原过滤；非空变化才重建。
            group = self.role_group()
            if ((group and group != self.selection.sub_key)
                    or self.spec_id != self.selection.spec_id):
                previous_group = self.selection.sub_key
                self._rebuild()
                self.refresh_thresholds()
                if group != previous_group:
                    self.events.append(("talent", group))
        # readable路径没有同样的每帧分组重建分支。
        return self.pipeline.prepare_frame(frame, old_attempt=old_attempt,
            selected_profile=self.selection.profile_for_spec(frame.spec_id), settings=self.switch_settings)

    def tick(self, image: RGBImage, scheduler: Scheduler, *, hwnd: int, send_interval_ms: int) -> TickResult:
        if scheduler.pipeline is not self.pipeline:
            raise ValueError("控制器和调度器必须使用同一个候选引擎实例")
        return scheduler.process(self.prepare(image), hwnd=hwnd, send_interval_ms=send_interval_ms)
