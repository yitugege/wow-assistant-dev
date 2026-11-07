"""FUN_140047c50 的纯候选生成层；不包含发键账本或窗口捕获。

解析 actions/rotations 与已选择循环，保留三态字段和原生职责/总开关/
读条/GCD 闸门。输入 selected_rules 应当已经经过 UI 阈值转换。
原生证据与运行自测对照见 evidence/候选引擎.md。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Mapping, Sequence

from .auto_target import parse_auto_target
from .expressions import EvaluationContext, UnsupportedSemantics, _double, _int, _string, _trim, evaluate


# 原始 PE RVA 0xd2900..0xd295b 的 23 个 int32。
OFF_GCD_SPELL_IDS = frozenset((
    100, 2139, 2565, 2687, 2973, 3045, 5217, 5229, 5277, 10060, 11129,
    12042, 12043, 12292, 12975, 14177, 14751, 16188, 17116, 19263, 20216,
    20271, 417141,
))
OFF_GCD_ACTIONS = frozenset(("start_attack", "pet_attack", "auto_target"))


def _object(value: object) -> Mapping:
    return value if isinstance(value, dict) else {}


def _array(value: object) -> list:
    return value if isinstance(value, list) else []


def _decimal_int(text: str) -> int | None:
    # 原QString::toInt(base10)：NUL终止，ASCII空白；不额外trim Unicode。
    text = text.split('\0', 1)[0].strip(' \t\n\r\v\f')
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        return None
    digits = text.lstrip('+-').lstrip('0') or '0'
    if len(digits) > 10:
        return None
    number = int(digits) * (-1 if text.startswith('-') else 1)
    return number if -(2**31) <= number < 2**31 else None


@dataclass(frozen=True)
class Action:
    name: str
    key: str = ""
    label: str = ""
    spell_id: int = -1

    @classmethod
    def from_json(cls, value: object) -> "Action":
        obj = _object(value)
        return cls(_string(obj.get("name")), _string(obj.get("key")),
                   _string(obj.get("label")), _int(obj.get("spellId"), -1))


@dataclass(frozen=True)
class Rule:
    action: str
    when: object
    reason: str = ""
    tag: str = ""
    hold_ms: int = 0
    pre: str = ""
    off_gcd: bool = False


def parse_rules(values: object) -> tuple[Rule, ...]:
    """FUN_14004fb00：忽略空 action 或缺失 when；null when 保留。"""
    result = []
    for value in _array(values):
        obj = _object(value)
        action = _string(obj.get("action"))
        if not action or "when" not in obj:
            continue
        result.append(Rule(action, obj["when"], _string(obj.get("reason")),
                           _string(obj.get("tag")), _int(obj.get("holdMs")),
                           _string(obj.get("pre")), obj.get("offGcd") is True))
    return tuple(result)


@dataclass(frozen=True)
class Candidate:
    action: str = ""       # 原生 +0x00
    key: str = ""          # +0x18
    label: str = ""        # +0x30
    reason: str = ""       # +0x48
    tag: str = ""          # +0x60
    hold_ms: int = 0        # +0x78；压制期，并非 keydown 持续时间
    priority: int = 0       # +0x7c
    stop: bool = False     # +0x80
    gcd_blocked: bool = False  # +0x81；原生对留下的 offGcd 也设置此标记
    off_gcd: bool = False   # +0x82
    pre_key: str = ""      # +0x88
    pre_action: str = ""   # +0xa0
    expect_off: tuple[str, ...] = ()  # +0xb8 的 QStringList


@dataclass(frozen=True)
class RoleState:
    status: int = 0  # 0 读不到；1 三系最高点数为 0；2 已识别主系
    group: str = ""
    points: tuple[int, int, int] | None = None


def collect_expect_off(expression: object) -> tuple[str, ...]:
    """FUN_14003bf80：仅从 and 内显式 false flag 收集，跳过 or/not。"""
    output = []

    def visit(expr: object) -> None:
        if not isinstance(expr, list) or not expr or not isinstance(expr[0], str):
            return
        if expr[0] == "and":
            for child in expr[1:]:
                visit(child)
        elif expr[0] == "flag" and len(expr) >= 3 and expr[2] is False:
            field = _string(expr[1])
            if field and not field.startswith("sw_") and field not in output:
                output.append(field)

    visit(expression)
    return tuple(output)


def focus_unit(action: str) -> str | None:
    """FUN_14003f990；沿用 QString::toInt，允许 +1、01 等整数写法。"""
    if action == "focus_player":
        return "player"
    if action.startswith("focus_party"):
        index = _decimal_int(action[len("focus_party"):])
        if index is not None and 1 <= index <= 4:
            return f"party{index}"
    return None


def infer_role(role_config: Mapping, context: EvaluationContext) -> RoleState:
    """FUN_14004ab60：三系点数，平点时选最先达到最大值的系。"""
    token = _string(role_config.get("token"))
    field = token + "_talents" if token else ""
    value = context.raw(field) if field else None
    if value is None:
        return RoleState()
    value = _trim(value)
    if not value or value.upper() == "UNKNOWN":
        return RoleState()
    parts = value.split("/")
    if len(parts) != 3:
        return RoleState()
    points = tuple(_decimal_int(part) for part in parts)
    if any(point is None for point in points):
        return RoleState()
    if max(points) == 0:
        return RoleState(1, points=points)
    best = points.index(max(points))
    groups = [_string(value) for value in _array(role_config.get("groups"))]
    group = groups[best] if len(groups) == 3 else f"第{best + 1}系"
    return RoleState(2, group, points)


def _is_healer(role: RoleState, role_config: Mapping) -> bool:
    roles = _object(role_config.get("roles"))
    return role.status == 2 and any(_string(roles.get(group)) == "HEALER" for group in role.group.split("/"))


def _reorder_focus_health(candidates: list[Candidate], context: EvaluationContext, no_value: int) -> None:
    # 原生分组键 action + U+001F + tag，保留其潜在字符串碰撞行为。
    groups: dict[str, list[int]] = {}
    for index, candidate in enumerate(candidates):
        if candidate.pre_action:
            groups.setdefault(candidate.action + "\x1f" + candidate.tag, []).append(index)
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        health_values = []
        for index in indexes:
            unit = focus_unit(candidates[index].pre_action)
            if unit is None:
                break
            health = context.number("health_" + unit)
            if health is None:
                health = context.number(unit + "_health_pct")
            if health is None or not 0 <= health < no_value:
                break
            health_values.append(health)
        if len(health_values) != len(indexes):
            continue  # 原生任何一条不满足就保留整组原序。
        priorities = [candidates[index].priority for index in indexes]
        ordered = [candidates[indexes[offset]] for offset in sorted(range(len(indexes)), key=health_values.__getitem__)]
        for index, priority, candidate in zip(indexes, priorities, ordered):
            candidates[index] = replace(candidate, priority=priority)


class CandidateEngine:
    """原生规则数据的纯内存载入与候选生成。

    selected_rules 为当前专精已经选中的外部循环；空数组与原生一样不构成
    有效覆盖。key_overrides 是上层启用后的当前专精映射，空键可禁用动作。
    allow_unknown_availability 是 engine+0x30 的显式状态，未提供时保留
    expressions 模块的 UnsupportedSemantics，而不猜测运行时设置。
    """

    def __init__(self, rules_document: Mapping):
        self.document = rules_document
        self.specs = _object(rules_document.get("specs"))
        self.roles = _object(rules_document.get("roles"))
        sentinel = _object(rules_document.get("sentinel"))
        self.sentinel = sentinel
        self.cd_ready_epsilon = _double(sentinel.get("cdReadyEps"), 0.05)
        no_value = _double(sentinel.get("noValue"), 16777215.0)
        # 原0424CA的CVTTSD2SI在默认MXCSR下，对越界有限double返回INT64_MIN。
        self.no_value = int(no_value) if -(2**63) <= no_value < 2**63 else -(2**63)
        self.last_auto_packet = None  # 原生+0x130诊断快照；提前返回不重置。

    def generate(self, spec_id: str | int, fields: Mapping[str, str], *,
                 selected_rules: list | None = None,
                 key_overrides: Mapping[str, str] | None = None,
                 allow_unknown_availability: bool | None = None) -> list[Candidate]:
        spec_key = str(spec_id)
        if spec_key not in self.specs:
            return []
        spec = _object(self.specs[spec_key])
        actions = {}
        for value in _array(spec.get("actions")):
            action = Action.from_json(value)
            actions[action.name] = action  # QHash::insert，重名后者覆盖。
        context = EvaluationContext(fields,
            tuple(_int(value) for value in _array(spec.get("actionAvailSpellIDs"))),
            self.cd_ready_epsilon, allow_unknown_availability)
        role_config = _object(self.roles.get(spec_key))
        role = infer_role(role_config, context)
        healer = _is_healer(role, role_config)
        master = context.flag(_string(self.sentinel.get("masterSwitchField")))
        if master == 0:
            combat = context.number(_string(self.sentinel.get("combatTimeField")))
            if not healer or (combat is not None and combat > 0):
                return [Candidate(label=_string(self.sentinel.get("stopLabel")),
                    reason=_string(self.sentinel.get("stopReason")),
                    tag=_string(self.sentinel.get("stopTag")), priority=1_000_000, stop=True)]

        external_rules = parse_rules(selected_rules)
        builtin = _object(spec.get("rotations"))
        has_rotation = bool(builtin) or bool(external_rules)
        roles = _object(role_config.get("roles"))
        group_names = [_string(value) for value in _array(role_config.get("groups"))]
        if not has_rotation and role_config and role.status != 2:
            # 此处原生没有过滤空 role 值；规则选择中的同类回退有过滤。
            if len({_string(roles.get(group)) for group in group_names}) > 1:
                return [Candidate(label="职责未读到", reason="天赋读数不足以判定职责，已停发（不猜方向）",
                    tag=_string(self.sentinel.get("stopTag")), priority=1_000_000, stop=True)]

        candidates = []
        ttd = context.number("ttd")
        packet = parse_auto_target(ttd) if ttd is not None else None
        self.last_auto_packet = packet
        if packet is not None and packet.state == 1:
            candidates.append(Candidate(action="auto_target", key=packet.key, label="自动选目标",
                reason=f"无目标／目标已死 → 按 {packet.key} 换目标（键#{packet.key_index} 回执{packet.ack}）",
                tag="选目标", hold_ms=400, priority=9000, off_gcd=True))

        if external_rules:
            rules = external_rules
        elif "" in builtin:
            rules = parse_rules(builtin[""])
        elif role.status == 2:
            rules = ()
            for group in role.group.split("/"):
                if group in builtin:
                    rules = parse_rules(builtin[group])
                    break
        elif role.status != 0 and len({_string(roles.get(group)) for group in group_names if _string(roles.get(group))}) == 1:
            rules = parse_rules(builtin.get(group_names[0] if group_names else ""))
        else:
            rules = ()

        def key_for(action: Action) -> str:
            if key_overrides is not None and action.name in key_overrides:
                value = key_overrides[action.name]
                if not isinstance(value, str):
                    raise UnsupportedSemantics("启用的按键覆盖值必须是原生 QString 文本")
                return value
            return action.key

        for index, rule in enumerate(rules):
            action = actions.get(rule.action)
            if action is None or not key_for(action) or not evaluate(rule.when, context):
                continue
            pre = actions.get(rule.pre) if rule.pre else None
            candidates.append(Candidate(action=rule.action, key=key_for(action),
                label=action.label or action.name, reason=rule.reason, tag=rule.tag,
                hold_ms=rule.hold_ms, priority=1000 - 5 * index,
                off_gcd=rule.off_gcd or action.spell_id in OFF_GCD_SPELL_IDS or action.name in OFF_GCD_ACTIONS,
                pre_key=key_for(pre) if pre is not None else "", pre_action=rule.pre,
                expect_off=collect_expect_off(rule.when) if rule.hold_ms > 0 else ()))

        _reorder_focus_health(candidates, context, self.no_value)
        if not candidates and not has_rotation and not healer:
            for value in _array(spec.get("genericFill")):
                action = actions.get(_string(value))
                # 原生通用填充使用基础键，不走覆盖，也不自动设置 offGcd。
                if action is not None and action.key and context.availability(action.spell_id) == 1:
                    label = action.label or action.name
                    candidates.append(Candidate(action=action.name, key=action.key, label=label,
                        reason=f"{label} 就绪（通用填充）", tag="填充", hold_ms=1500, priority=150))
                    break

        casting = context.raw("player_casting") or ""
        if casting.startswith(("读条中", "引导")):
            return []
        if context.flag("gcd") == 1:
            candidates = [replace(candidate, priority=candidate.priority - 50, gcd_blocked=True)
                          for candidate in candidates if candidate.off_gcd]
        # 原生最终只按 priority 降序排序。本生成器的优先值无重复；不依赖
        # std::sort 对等值项的未规定顺序。
        return sorted(candidates, key=lambda candidate: candidate.priority, reverse=True)
