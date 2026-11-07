"""恢复自 FUN_14003dc90 的规则表达式；不负责发键或候选调度。

输入字段保持原程序 QHash<QString, QString> 的文本表示，不转换为 Python
truthiness。来源及未恢复边界见 evidence/规则语义.md。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Mapping, Sequence
import unicodedata


class UnsupportedSemantics(RuntimeError):
    """缺少原程序上下文，或输入落入尚未验证的转换边界。"""


OPERATORS = frozenset({
    "and", "or", "not", "always", "flag", "avail", "ready",
    "num_at_least", "num_below", "enemies_at_least", "injured_at_least",
    "interruptible",
})
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")


def _space(char: str) -> bool:
    return char in "\t\n\v\f\r\x85" or unicodedata.category(char) in {"Zs", "Zl", "Zp"}


def _trim(value: str) -> str:
    start, end = 0, len(value)
    while start < end and _space(value[start]):
        start += 1
    while end > start and _space(value[end - 1]):
        end -= 1
    return value[start:end]


def _string(value: object) -> str:
    # QJsonValue::toString() 对非字符串返回空 QString。
    return value if isinstance(value, str) else ""


def _double(value: object, default: float = 0.0) -> float:
    # bool 在 Python 中是 int 子类，在 QJsonValue 中是另一种类型。
    if type(value) not in (int, float):
        return default
    try:
        result = float(value)
    except OverflowError as exc:
        raise UnsupportedSemantics("数字超出 JSON double 范围") from exc
    if not math.isfinite(result):
        raise UnsupportedSemantics("非有限 JSON 数字不在已恢复输入范围内")
    return result


def _int(value: object, default: int = 0) -> int:
    number = _double(value, float(default))
    if not number.is_integer() or not -(2**31) <= number < 2**31:
        return default
    return int(number)


@dataclass(frozen=True)
class EvaluationContext:
    fields: Mapping[str, str]
    action_avail_spell_ids: Sequence[int] = ()
    cd_ready_epsilon: float = 0.05
    # 原生 context+0x20 来自 engine+0x30；调用方必须明确提供状态。
    # None 不是 false：它代表该上下文尚未恢复。
    allow_unknown_availability: bool | None = None

    def raw(self, key: str) -> str | None:
        if key not in self.fields:
            return None
        value = self.fields[key]
        if not isinstance(value, str):
            raise UnsupportedSemantics(f"字段 {key!r} 必须使用原生文本表示")
        return value

    def flag(self, key: str) -> int:
        """返回 1/0/-1，分别为 ON/OFF/未知；未知绝不能当成 OFF。"""
        value = self.raw(key)
        if value is None:
            return -1
        first = _trim(value).split(" ", 1)[0].upper()
        return {"ON": 1, "OFF": 0}.get(first, -1)

    def number(self, key: str) -> float | None:
        value = self.raw(key)
        if value is None:
            return None
        value = _trim(value)
        if not value or value.startswith("\u2014"):
            return None
        token = _trim(value.split(" ", 1)[0])
        if token.lower() in {"nan", "inf", "+inf", "-inf"}:
            return float(token)
        if not _DECIMAL.fullmatch(token):
            return None
        result = float(token)
        if not math.isfinite(result):
            # 原附带Qt toDouble返回inf但ok=false；044fd0不写输出并返回失败。
            return None
        if result == 0 and any(c in "123456789" for c in token.split("e")[0].split("E")[0]):
            # 下溢为零同样ok=false；仍可表示的非正规数保留。
            return None
        return result

    def availability(self, spell_id: int) -> int:
        value = self.raw("action_avail")
        try:
            index = self.action_avail_spell_ids.index(spell_id)
        except ValueError:
            index = -1
        if value is not None and index >= 0:
            # 03b800只在section之前Unicode trimmed；原Qt转换在NUL
            # 终止且只裁剪ASCII空白。失败后才进入ready字段回退。
            token = _trim(value).split(" ", 1)[0].split("\0", 1)[0].strip(" \t\n\r\v\f")
            if _INTEGER.fullmatch(token):
                # Qt允许任意前导零；先约束有效十进制长度，避免Python长整数限制异常。
                negative = token.startswith("-")
                digits = token.lstrip("+-").lstrip("0") or "0"
                bits = (-1 if negative else 1) * int(digits) if len(digits) <= 19 else None
                if bits is not None and -(2**63) <= bits < 2**63:
                    # 原生 x64 sar 的移位量取低 6 位，技能第 0 项使用 bit 1。
                    return (bits >> ((index + 1) & 63)) & 1
        result = self.flag(f"ready_{spell_id}")
        if result < 0:
            result = self.flag(f"spell_{spell_id}_ready")
        if result < 0:
            if self.allow_unknown_availability is None:
                raise UnsupportedSemantics("缺少 engine+0x30 的未知可用性策略")
            return 1 if self.allow_unknown_availability else -1
        return result


def evaluate(expression: object, context: EvaluationContext) -> bool:
    """按原生行为计算布尔结果；尚未确定的上下文明确抛出异常。

    原生已确认的非法表达式/未知操作符返回 false；这与未实现的语义不同。
    and/or 短路，not 只使用第一个操作数，多余参数按原生行为忽略。
    """
    if not isinstance(expression, list) or not expression or not isinstance(expression[0], str):
        return False
    op, args = expression[0], expression[1:]
    if op == "and":
        return all(evaluate(arg, context) for arg in args)
    if op == "or":
        return any(evaluate(arg, context) for arg in args)
    if op == "not":
        return bool(args) and not evaluate(args[0], context)
    if op == "always":
        return True
    if op == "flag":
        return len(args) >= 2 and context.flag(_string(args[0])) == (1 if args[1] is True else 0)
    if op == "avail":
        return bool(args) and context.availability(_int(args[0])) == 1
    if op == "ready":
        if not args:
            return False
        value = context.number(_string(args[0]))
        return value is not None and value <= context.cd_ready_epsilon
    if op in {"num_at_least", "num_below"}:
        if len(args) < 2:
            return False
        value = context.number(_string(args[0]))
        if value is None:
            return False
        limit = _double(args[1])
        return value >= limit if op == "num_at_least" else value < limit
    if op == "enemies_at_least":
        if not args:
            return False
        value = context.number("active_enemies")
        # 原cvttsd2si r12d在默认屏蔽异常下，对NaN/Inf/截断后越界返回INT_MIN。
        count = 0 if value is None else (int(value) if math.isfinite(value) else -(2**31))
        if not -(2**31) <= count < 2**31:
            count = -(2**31)
        return count >= _int(args[0])
    if op == "injured_at_least":
        if len(args) < 2:
            return False
        threshold, minimum = _double(args[0]), _int(args[1])
        if minimum <= 0:
            return True
        count = 0
        for unit in ("player", "party1", "party2", "party3", "party4"):
            if unit != "player" and context.flag(f"friendly_{unit}") != 1:
                continue
            value = context.number(f"health_{unit}")
            if value is None:
                value = context.number(f"{unit}_health_pct")
            if value is not None and 0 <= value < threshold:
                count += 1
        return count >= minimum
    if op == "interruptible":
        value = context.raw(_string(args[0]) if args else "") or ""
        if len(value.encode('utf-16-le', 'surrogatepass')) != 14 or not value.startswith("#"):
            return False
        # 原版按UTF-16计长；toUInt在NUL终止，只允许ASCII空白、+及0x。
        token = value[1:].split('\0', 1)[0].strip(' \t\n\r\v\f')
        if token.startswith("+"):
            token = token[1:]
        if not re.fullmatch(r"(?:0[xX])?[0-9A-Fa-f]+", token):
            return False
        return int(token, 16) & 0xFFFFFF00 == 0xFF00
    return False
