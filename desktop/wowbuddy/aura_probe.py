"""施法回执、光环回查和按动作保存的压制账本。

来源：FUN_1400a2d70 内联回查、FUN_140089570 成功发送后的记账，
以及原版 --selftest 的 aura_probe.h 用例。不会实际发送任何按键。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import re
from typing import Mapping, Sequence

from .expressions import EvaluationContext, _trim

CHECK_DELAY_MS = 400
RETRY_HOLD_MS = 1000
IMMUNE_FAILURES = 2
LOCAL_GCD_MS = 1500


class Receipt(IntEnum):
    INVALID = 0
    NOT_FIRED = 1
    FIRED_SAME = 2
    FIRED_OTHER = 3


class ProbeResult(IntEnum):
    NOT_DUE = 0
    CASTING = 1
    APPLIED = 2
    MISSED = 3
    IMMUNE = 4


def _integer(text: str) -> int:
    # 原Qt十进制转换；Unicode trimmed由明确执行该步骤的调用方负责。
    text = text.split("\0", 1)[0].strip(" \t\n\r\v\f")
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        return -1
    digits = text.lstrip("+-").lstrip("0") or "0"
    if len(digits) > 19:
        return -1
    value = int(digits) * (-1 if text.startswith("-") else 1)
    return value if -(2**63) <= value < 2**63 else -1


def field_integer(fields: Mapping[str, str], name: str) -> int:
    """FUN_14008af70：trim 后取普通空格首段、十进制 int64；未知返回 -1。"""
    text = fields.get(name)
    if text is None:
        return -1
    if not isinstance(text, str):
        raise TypeError("回执字段须为原生值文本")
    text = _trim(text)
    if not text or text.startswith("—"):
        return -1
    return _integer(text.split(" ", 1)[0])


def spell_id_from_action(action: str) -> int:
    """当前原生调用方接受 2..0xFFFFFE；保留可选下划线后缀。"""
    if not action.startswith("spell_"):
        return -1
    value = _integer(action[6:].split("_", 1)[0])
    return value if 2 <= value <= 0xFFFFFE else -1


def classify_receipt(action: str, sent_generation: int, current_generation: int,
                     current_spell_id: int) -> Receipt:
    if sent_generation < 1 or current_generation < 1:
        return Receipt.INVALID
    # 依照主程序内联顺序：代次未变时尚未进入动作 ID 判断。
    if sent_generation == current_generation:
        return Receipt.NOT_FIRED
    spell_id = spell_id_from_action(action)
    if spell_id == -1:
        return Receipt.INVALID
    return Receipt.FIRED_SAME if current_spell_id == spell_id else Receipt.FIRED_OTHER


def probe(*, expect_off: Sequence[str], fields: Mapping[str, str], now_ms: int,
          check_at_ms: int, casting: bool, failures: int = 0,
          receipt: Receipt = Receipt.INVALID) -> ProbeResult:
    """纯回查判据；读不到光环被原版当作 APPLIED，不推断为真实施法成功。"""
    if not expect_off:
        return ProbeResult.APPLIED
    if now_ms < check_at_ms:
        return ProbeResult.NOT_DUE
    if casting:
        return ProbeResult.CASTING
    context = EvaluationContext(fields)
    if any(context.flag(key) != 0 for key in expect_off):
        return ProbeResult.APPLIED
    if receipt == Receipt.FIRED_SAME or failures + 1 >= IMMUNE_FAILURES:
        return ProbeResult.IMMUNE
    return ProbeResult.MISSED


@dataclass(frozen=True)
class ProbeEvent:
    action: str
    result: ProbeResult
    receipt: Receipt
    old_suppression_until_ms: int
    suppression_until_ms: int
    failures: int


@dataclass
class AuraProbeLedger:
    """对应主窗口 d8/e8/f0/f8/100/108 六个按动作索引的容器。

    仅实现已查证的成功发送记账和回查更新；新目标/专精清账由外层调度调用。
    内部顺序不是 Qt QHash 的迭代顺序，事件集合不得当作原版日志排列承诺。
    """
    suppression_until: dict[str, int] = field(default_factory=dict)
    check_at: dict[str, int] = field(default_factory=dict)
    expect_off: dict[str, tuple[str, ...]] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    original_hold_ms: dict[str, int] = field(default_factory=dict)
    sent_generation: dict[str, int] = field(default_factory=dict)

    def record_send(self, action: str, *, success: bool, now_ms: int, hold_ms: int,
                    expect_off: Sequence[str], fields: Mapping[str, str]) -> None:
        if not success or hold_ms <= 0:
            return
        self.suppression_until[action] = now_ms + hold_ms
        if expect_off:
            self.expect_off[action] = tuple(expect_off)
            self.check_at[action] = now_ms + CHECK_DELAY_MS
            self.original_hold_ms[action] = hold_ms
            self.sent_generation[action] = field_integer(fields, "player_succeeded_generation")

    def check(self, fields: Mapping[str, str], *, now_ms: int, casting: bool) -> list[ProbeEvent]:
        generation = field_integer(fields, "player_succeeded_generation")
        spell_id = field_integer(fields, "player_succeeded_spell_id")
        events = []
        for action, due in list(self.check_at.items()):
            receipt = classify_receipt(action, self.sent_generation.get(action, -1), generation, spell_id)
            result = probe(expect_off=self.expect_off.get(action, ()), fields=fields,
                           now_ms=now_ms, check_at_ms=due, casting=casting,
                           failures=self.failures.get(action, 0), receipt=receipt)
            previous = self.suppression_until.get(action, 0)
            if result == ProbeResult.CASTING:
                self.check_at[action] = now_ms + CHECK_DELAY_MS
            elif result == ProbeResult.APPLIED:
                self.failures.pop(action, None)
            elif result == ProbeResult.MISSED:
                self.failures[action] = self.failures.get(action, 0) + 1
                if now_ms + RETRY_HOLD_MS < previous:
                    self.suppression_until[action] = now_ms + RETRY_HOLD_MS
            elif result == ProbeResult.IMMUNE:
                self.failures[action] = self.failures.get(action, 0) + 1
                restored = now_ms + self.original_hold_ms.get(action, 0)
                if previous < restored:
                    self.suppression_until[action] = restored
            if result not in (ProbeResult.NOT_DUE, ProbeResult.CASTING):
                self.check_at.pop(action, None)
                self.expect_off.pop(action, None)
                self.sent_generation.pop(action, None)
            events.append(ProbeEvent(action, result, receipt, previous,
                                    self.suppression_until.get(action, 0), self.failures.get(action, 0)))
        return events

    def clear(self):
        for mapping in (self.suppression_until, self.check_at, self.expect_off, self.failures,
                        self.original_hold_ms, self.sent_generation):
            mapping.clear()
