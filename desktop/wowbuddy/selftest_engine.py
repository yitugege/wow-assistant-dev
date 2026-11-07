"""原生自测的规则快照和分段阈值处理；不使用GUI逐帧pipeline。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping, Literal

from .candidates import CandidateEngine
from .expressions import _int
from .thresholds import Threshold, promote_builtin_rotations, promote_profile, apply_thresholds


SelftestSection = Literal["initial", "direct", "focus"]


@dataclass(frozen=True)
class PreparedSelftestFrame:
    fields: dict[str, str]
    selected_rules: list[dict] | None
    thresholds: tuple[Threshold, ...]
    external_active: bool


class NativeSelftestEngine:
    """输入native_assets规范化后的、尚未提升的rules.document。

    source_document保留未改写规则；document是041e00已提升快照。
    初始14帧和直接047c50调用不补sw；焦点helper使用空settings补默认sw。
    不缓存跨分段外部方案：宿主显式提供当前profile，避免假定恢复时机。
    """
    def __init__(self, rules: Mapping):
        self.source_document = deepcopy(rules)
        self.document = deepcopy(rules)
        self.promotions = {}
        self.builtin_thresholds = {}
        for spec_id, spec in self.document.get("specs", {}).items():
            groups = promote_builtin_rotations(self.source_document, spec_id)
            self.promotions[spec_id] = groups
            spec["rotations"] = {group: promotion.json_rules() for group, promotion in groups.items()}
            # 03f780逐组追加；不同组同名key不能跨组去重。
            self.builtin_thresholds[spec_id] = tuple(
                item for promotion in groups.values() for item in promotion.thresholds)
        self.engine = CandidateEngine(self.document)

    def prepare(self, spec_id: str | int, fields: Mapping[str, str], *,
                section: SelftestSection, profile: Mapping | None = None) -> PreparedSelftestFrame:
        if section not in ("initial", "direct", "focus"):
            raise ValueError(f"未恢复的自测分段: {section}")
        if section == "initial" and profile is not None:
            raise ValueError("初始14帧在安装外部循环前执行，不能传profile")
        spec_id = str(spec_id)
        thresholds = self.builtin_thresholds.get(spec_id, ())
        selected = None
        active = False
        if profile is not None:
            if str(_int(profile.get("specId"))) != spec_id:
                raise ValueError("显式profile必须属于本次自测专精")
            promotion = promote_profile(self.source_document, profile)
            selected = promotion.json_rules()
            active = bool(promotion.rules)
            # 03a4a0按外部rules非空选外部thresholds，不按thresholds非空。
            if active:
                thresholds = promotion.thresholds
        prepared = (apply_thresholds(thresholds, {}, fields) if section == "focus" else dict(fields))
        return PreparedSelftestFrame(prepared, selected, thresholds, active)

    def generate(self, spec_id: str | int, fields: Mapping[str, str], *,
                 section: SelftestSection, profile: Mapping | None = None,
                 allow_unknown_availability: bool | None = None):
        frame = self.prepare(spec_id, fields, section=section, profile=profile)
        return self.engine.generate(spec_id, frame.fields, selected_rules=frame.selected_rules,
                                   allow_unknown_availability=allow_unknown_availability)
