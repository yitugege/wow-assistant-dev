"""原生技能阈值提升、合并、settings 迁移及逐帧 sw_ 字段合成。

纯数据算法；不读取注册表、不构建窗口、不发送按键。证据见技能阈值.md。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import re
from typing import Mapping, Sequence

from .candidates import Action, Rule, parse_rules
from .expressions import EvaluationContext, UnsupportedSemantics, _double, _int, _string


@dataclass(frozen=True)
class SwitchField:
    field: str
    label: str
    unit: str = ""
    maximum: int = 100


@dataclass(frozen=True)
class Threshold:
    key: str
    label: str
    field_label: str
    group: str
    kind: str
    field: str
    direction: str
    unit: str
    reason: str
    maximum: int
    step: int
    default: int
    skills: tuple[str, ...]
    tag: str
    action: str

    @property
    def legacy_key(self) -> str:
        return f"sw_{self.field}_{'b' if self.direction == 'below' else 'a'}{self.default}"


@dataclass(frozen=True)
class Promotion:
    rules: tuple[Rule, ...]
    thresholds: tuple[Threshold, ...]

    def json_rules(self) -> list[dict]:
        """适配 CandidateEngine.generate(selected_rules=...) 的 JSON 输入。"""
        return [{"action": rule.action, "when": deepcopy(rule.when), "reason": rule.reason,
                 "tag": rule.tag, "holdMs": rule.hold_ms, "pre": rule.pre, "offGcd": rule.off_gcd}
                for rule in self.rules]


@dataclass(frozen=True)
class SliderGroup:
    """09aa10 的一个滑条；保留原阈值顺序和首条代表值。"""
    identity: str
    thresholds: tuple[Threshold, ...]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.thresholds)

    @property
    def representative(self) -> Threshold:
        return self.thresholds[0]


@dataclass(frozen=True)
class SettingsResult:
    values: dict[str, int]
    writes: dict[str, int]
    removed: tuple[str, ...] = ()
    slider_values: tuple[int, ...] = ()


def parse_switch_fields(document: Mapping) -> dict[str, SwitchField]:
    result = {}
    values = document.get("switchFields", [])
    for obj in values if isinstance(values, list) else []:
        if not isinstance(obj, dict):
            continue
        field = _string(obj.get("field"))
        if field:
            result[field] = SwitchField(field, _string(obj.get("label")) or field,
                                       _string(obj.get("unit")), _int(obj.get("max"), 100))
    return result


def action_labels(actions: object) -> dict[str, str]:
    """047740 的 label-or-name 映射；重复 name 后者覆盖前者。"""
    result = {}
    for obj in actions if isinstance(actions, list) else []:
        action = Action.from_json(obj)
        result[action.name] = action.label or action.name
    return result


def threshold_key(action: str, field: str, direction: str, default: int) -> str:
    """04a530：先同时替换三个文本，再用整数arg替换最低编号占位符。"""
    text = f"sw_{action or '-'}~{field}_{'b' if direction == 'below' else 'a'}%4"
    # 原包整数arg只认一至两位ASCII编号；%L使用当前Qt区域格式。
    pattern = r'%(L?)([0-9]{1,2})'
    matches = tuple(re.finditer(pattern, text))
    lowest = min(int(match.group(2)) for match in matches)
    def substitute(match):
        if int(match.group(2)) != lowest:
            return match.group(0)
        if match.group(1):
            from PySide6.QtCore import QLocale
            return QLocale().toString(default)
        return str(default)
    return re.sub(pattern, substitute, text)


def promote_rules(rules: Sequence[Rule], fields: Mapping[str, SwitchField],
                  labels: Mapping[str, str], group: str = "") -> Promotion:
    """041a80/040940；只提升匹配元数据且为正整数的三项比较。"""
    thresholds: list[Threshold] = []
    indices: dict[str, int] = {}

    def rewrite(value: object, rule: Rule, skill: str) -> object:
        if isinstance(value, list):
            if (len(value) == 3 and type(value[0]) is str and type(value[1]) is str
                    and type(value[2]) in (int, float)
                    and value[0] in ("num_below", "num_at_least") and value[1] in fields):
                meta = fields[value[1]]
                number = _double(value[2])
                if number.is_integer() and 0 < number <= meta.maximum:
                    default = int(number)
                    direction = "below" if value[0] == "num_below" else "at_least"
                    key = threshold_key(rule.action, meta.field, direction, default)
                    if key in indices:
                        index = indices[key]
                        old = thresholds[index]
                        skills = old.skills + ((skill,) if skill and skill not in old.skills else ())
                        thresholds[index] = replace(old, skills=skills, reason=old.reason or rule.reason,
                                                    tag=old.tag or rule.tag)
                    else:
                        indices[key] = len(thresholds)
                        sign = "<" if direction == "below" else "≥"
                        thresholds.append(Threshold(key, f"{meta.label} {sign} {default}{meta.unit}",
                            meta.label, group, "pct" if meta.unit == "%" else "num", meta.field,
                            direction, meta.unit, rule.reason, meta.maximum, 1, default,
                            (skill,) if skill else (), rule.tag, rule.action))
                    return ["flag", key, True]
            return [rewrite(item, rule, skill) for item in value]
        if isinstance(value, dict):
            # QJsonObject 的 QString 键顺序按 UTF-16 代码单元排序。
            return {key: rewrite(value[key], rule, skill)
                    for key in sorted(value, key=lambda k: k.encode("utf-16be", "surrogatepass"))}
        return deepcopy(value)

    rewritten = []
    for rule in rules:
        label = labels.get(rule.action, "")
        delimiter = label.find(" · ")
        skill = label[:delimiter] if delimiter > 0 else label
        rewritten.append(replace(rule, when=rewrite(rule.when, rule, skill)))
    return Promotion(tuple(rewritten), tuple(thresholds))


def promote_profile(document: Mapping, profile: Mapping) -> Promotion:
    """循环库外部方案入口；同原生使用空 group，不使用 profile.subKey。"""
    specs = document.get("specs", {})
    spec = specs.get(str(_int(profile.get("specId"))), {})
    return promote_rules(parse_rules(profile.get("rules")), parse_switch_fields(document),
                         action_labels(spec.get("actions", [])))


def promote_builtin_rotations(document: Mapping, spec_id: str | int) -> dict[str, Promotion]:
    """041e00:1029；每个内置 rotation 独立提升/去重，group 为其键。"""
    spec = document.get("specs", {}).get(str(spec_id), {})
    rotations = spec.get("rotations", {})
    if not isinstance(rotations, dict):
        return {}
    fields, labels = parse_switch_fields(document), action_labels(spec.get("actions", []))
    return {key: promote_rules(parse_rules(rotations[key]), fields, labels, key)
            for key in sorted(rotations, key=lambda k: k.encode("utf-16be", "surrogatepass"))}


def visible_thresholds(thresholds: Sequence[Threshold], selected_group: str) -> tuple[Threshold, ...]:
    """09aa10:280；group 为空、选择为空或两者相同时显示。"""
    return tuple(item for item in thresholds
                 if not item.group or not selected_group or item.group == selected_group)


def group_sliders(thresholds: Sequence[Threshold]) -> tuple[SliderGroup, ...]:
    groups: dict[str, list[Threshold]] = {}
    for item in thresholds:
        identity = "\x1f".join(("/".join(item.skills) or item.key,
                                item.direction, str(item.default), str(item.maximum)))
        groups.setdefault(identity, []).append(item)
    return tuple(SliderGroup(key, tuple(items)) for key, items in groups.items())


def _settings(values: Mapping[str, int]) -> dict[str, int]:
    for key, value in values.items():
        if type(value) is not int or not -(2**31) <= value < 2**31:
            raise UnsupportedSemantics(f"settings {key!r} 必须已完成 QVariant::toInt 转换")
    return dict(values)


def migrate_settings(thresholds: Sequence[Threshold], settings: Mapping[str, int]) -> SettingsResult:
    """08f020；先复制全部新 key，最后删除旧 key，新 key 已有值优先。"""
    values, writes, removed = _settings(settings), {}, []
    for item in thresholds:
        legacy = item.legacy_key
        if legacy != item.key and legacy in values:
            if item.key not in values:
                values[item.key] = writes[item.key] = values[legacy]
            if legacy not in removed:
                removed.append(legacy)
    for key in removed:
        del values[key]
    return SettingsResult(values, writes, tuple(removed))


def initialize_sliders(groups: Sequence[SliderGroup], settings: Mapping[str, int]) -> SettingsResult:
    """09aa10:1211-1252；首个已保存 key 决定组值，负值退回默认。

    仅当某成员的已有值/默认值不等于最终值时，将整组写入 settings。
    """
    values, writes, selected = _settings(settings), {}, []
    for group in groups:
        first = group.representative
        value = first.default
        for key in group.keys:
            if key in values:
                value = values[key] if values[key] >= 0 else first.default
                break
        value = max(0, min(first.maximum, value))
        selected.append(value)
        if any(values.get(key, first.default) != value for key in group.keys):
            for key in group.keys:
                values[key] = writes[key] = value
    return SettingsResult(values, writes, slider_values=tuple(selected))


def set_slider(group: SliderGroup, value: int, settings: Mapping[str, int]) -> SettingsResult:
    """0a19e0 的已接受 valueChanged(int)；调用者负责 UI 范围约束。"""
    values = _settings(settings)
    _settings({"value": value})
    writes = dict.fromkeys(group.keys, value)
    values.update(writes)
    return SettingsResult(values, writes)


def apply_thresholds(thresholds: Sequence[Threshold], settings: Mapping[str, int],
                     fields: Mapping[str, str]) -> dict[str, str]:
    """03afc0 每帧处理；未知数值移除已有 sw_，不会保留上一帧的 ON。"""
    overrides, result = _settings(settings), dict(fields)
    context = EvaluationContext(result)
    for item in thresholds:
        value = overrides.get(item.key, item.default)
        if value < 1:
            result[item.key] = "OFF"
        elif not item.field:
            result[item.key] = "ON"
        else:
            number = context.number(item.field)
            if number is None:
                result.pop(item.key, None)
            else:
                enabled = number >= value if item.direction == "at_least" else number < value
                result[item.key] = "ON" if enabled else "OFF"
    return result


def value_label(threshold: Threshold, value: int) -> str:
    return "关闭" if value < 1 else f"{'≥' if threshold.direction == 'at_least' else '<'} {value}{threshold.unit}"
