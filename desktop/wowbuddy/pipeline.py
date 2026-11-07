"""图像→双协议→阈值字段→候选的无副作用运行链。

保留主窗身份与字段描述状态；窗口捕获、方案选择持久化、发送调度由上层负责。
原生 readable 资源只加载 name→key，不替换基础动作或规则。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping

from .candidates import Candidate, CandidateEngine
from .expressions import _int, _string
from .old_protocol import OldDecoder, OldFrame
from .pixel_geometry import RGBImage
from .readable_protocol import ReadableDecoder, ReadableFrame
from .thresholds import Threshold, apply_thresholds, promote_builtin_rotations, promote_profile
from .dev_protocol import DEV_VERSION, normalize_availability


Frame = OldFrame | ReadableFrame


def readable_key_maps(document: Mapping) -> dict[str, dict[str, str]]:
    """0446a0：只接受非空字符串 name/key；同名最后一次有效值覆盖。"""
    specs = document.get("specs", {})
    result = {}
    for spec_id, spec in specs.items() if isinstance(specs, dict) else ():
        actions = spec.get("actions", []) if isinstance(spec, dict) else []
        keys = {}
        for action in actions if isinstance(actions, list) else []:
            if not isinstance(action, dict):
                continue
            name, key = _string(action.get("name")), _string(action.get("key"))
            if name and key:
                keys[name] = key
        if keys:
            result[spec_id] = keys
    return result


@dataclass(frozen=True)
class Decision:
    frame: Frame
    fields: Mapping[str, str]
    candidates: tuple[Candidate, ...]
    thresholds: tuple[Threshold, ...] = ()
    # 保留旧条失败原因，供上层解释为何走 readable；不复用失败帧字段。
    old_attempt: OldFrame | None = None


@dataclass(frozen=True)
class PreparedFrame:
    frame: Frame
    fields: Mapping[str, str]
    thresholds: tuple[Threshold, ...] = ()
    selected_rules: list | None = None
    key_overrides: Mapping[str, str] | None = None
    old_attempt: OldFrame | None = None


class DecisionPipeline:
    def __init__(self, old_contract: Mapping, readable_contract: Mapping,
                 rules: Mapping, readable_rules: Mapping, *, legacy_descriptor_cache=False):
        # 固定一次资源加载快照；调用者改原 dict 不会偷偷改变运行中的表。
        self.rules = deepcopy(rules)
        self.old = OldDecoder(deepcopy(old_contract), additional_versions=(DEV_VERSION,))
        self.readable = ReadableDecoder(deepcopy(old_contract), deepcopy(readable_contract))
        # 原主窗098BE0在首帧前建立空身份通用表；None仅用于触发首次构建。
        self._descriptor_identity = None
        # 独立版修复：协议也参与缓存身份。旧行为仅供离线对比，不由GUI启用。
        self.legacy_descriptor_cache = legacy_descriptor_cache
        self._descriptor_protocol = None
        self._retained_descriptors: tuple[Mapping, ...] = ()
        self._old_descriptors("")
        self.readable_keys = readable_key_maps(readable_rules)
        compiled = deepcopy(self.rules)
        self.builtin_thresholds = {}
        for spec_id, spec in compiled.get("specs", {}).items():
            promotions = promote_builtin_rotations(self.rules, spec_id)
            spec["rotations"] = {group: item.json_rules() for group, item in promotions.items()}
            self.builtin_thresholds[spec_id] = tuple(
                threshold for item in promotions.values() for threshold in item.thresholds)
        self.engine = CandidateEngine(compiled)

    def evaluate(self, image: RGBImage, *, selected_profile: Mapping | None = None,
                 settings: Mapping[str, int] | None = None) -> Decision:
        return self.generate(self.prepare(image, selected_profile=selected_profile, settings=settings))

    def prepare(self, image: RGBImage, *, selected_profile: Mapping | None = None,
                settings: Mapping[str, int] | None = None) -> PreparedFrame:
        """selected_profile 是上层已为当前专精选择的循环库对象。

        settings 是去掉 switch/ 前缀后的整数配置；UI 迁移/夹紧单独执行。
        无图/失败帧返回空候选，不保留上帧动作。
        """
        frame, attempt = self.decode(image)
        return self.prepare_frame(frame, old_attempt=attempt, selected_profile=selected_profile, settings=settings)

    def decode(self, image: RGBImage) -> tuple[Frame, OldFrame | None]:
        """先取专精，再允许上层恢复方案；同一张图像无需重复解码。"""
        old_frame = self.old.decode(image, descriptor_resolver=self._old_descriptors)
        if old_frame.fallback_readable:
            return normalize_availability(self.readable.decode(image, descriptor_resolver=self._readable_descriptors)), old_frame
        return normalize_availability(old_frame), None

    def rebuild_old_descriptors(self, spec_id: str) -> tuple[Mapping, ...]:
        """08CFE0→098BE0：显式布局回调即使身份相同也重建旧契约表。"""
        return self._old_descriptors(spec_id, force=True)

    def _old_descriptors(self, spec_id: str, *, force: bool = False) -> tuple[Mapping, ...]:
        # 093A48：未知身份仅在先前身份非空时触发公共字段重建。
        if force or spec_id != self._descriptor_identity or (not self.legacy_descriptor_cache and self._descriptor_protocol != 'old'):
            common_count = len(self.old.contract.get("commonFields", []))
            class_only = self.old.contract.get("classOnlyFields", {})
            numeric_spec = int(spec_id) if spec_id else 0
            self._retained_descriptors = tuple(
                dict(field, applicable=(field["id"] not in class_only
                                       or numeric_spec in class_only[field["id"]]),
                     is_common=index < common_count)
                for index, field in enumerate(self.old.field_definitions(spec_id)))
            self._descriptor_identity = spec_id
            self._descriptor_protocol = 'old'
        return self._retained_descriptors

    def _readable_descriptors(self, spec_id: str) -> tuple[Mapping, ...]:
        # 095410：未知身份已提前返回；只有身份改变才重建，协议不参与比较。
        if spec_id != self._descriptor_identity or (not self.legacy_descriptor_cache and self._descriptor_protocol != 'readable'):
            self._retained_descriptors = tuple(
                {"id": key, "label": key, "type": kind, "applicable": True,
                 "is_common": False, "note": ""}
                for key, kind, _ in self.readable.field_definitions(spec_id))
            self._descriptor_identity = spec_id
            self._descriptor_protocol = 'readable'
        return self._retained_descriptors

    def prepare_frame(self, frame: Frame, *, old_attempt: OldFrame | None = None,
                      selected_profile: Mapping | None = None,
                      settings: Mapping[str, int] | None = None) -> PreparedFrame:
        attempt = old_attempt
        if not frame.ok:
            return PreparedFrame(frame, {}, old_attempt=attempt)
        thresholds = self.builtin_thresholds.get(frame.spec_id, ())
        selected_rules = None
        if selected_profile is not None:
            if str(_int(selected_profile.get("specId"))) != frame.spec_id:
                raise ValueError("上层必须传入当前专精的已选方案，不能跨专精套用")
            promotion = promote_profile(self.rules, selected_profile)
            selected_rules = promotion.json_rules()
            # 原引擎空外部规则仍回退到内置；相应保留内置阈值。
            if promotion.rules:
                thresholds = promotion.thresholds
        fields = apply_thresholds(thresholds, settings or {}, frame.values)
        keys = self.readable_keys.get(frame.spec_id) if frame.protocol == "readable" else None
        return PreparedFrame(frame, fields, thresholds, selected_rules, keys, attempt)

    def generate(self, prepared: PreparedFrame, *, engine_fields: Mapping[str, str] | None = None) -> Decision:
        """调度器在这里注入圣印回执覆盖；原字段仍保留用于光环回查。"""
        candidates = ()
        if prepared.frame.ok:
            candidates = tuple(self.engine.generate(
                prepared.frame.spec_id, prepared.fields if engine_fields is None else engine_fields,
                selected_rules=prepared.selected_rules, key_overrides=prepared.key_overrides,
                allow_unknown_availability=prepared.frame.allow_unknown_availability))
        return Decision(prepared.frame, prepared.fields, candidates, prepared.thresholds, prepared.old_attempt)
