"""发送前焦点去重与本地 GCD 闸门；纯判断，不调用 Windows 输入。

依据 FUN_140089570:140-221、FUN_1400a2d70:363-378/1669-1724，
以及原版 --selftest 的 focus_dedup.h / off_gcd.h 实际输出。
"""
from dataclasses import dataclass

from .aura_probe import _integer

FOCUS_KEEP_MS = 3000
PRE_KEY_DELAY_MS = 40


def focus_index(action: str) -> int:
    if action == "focus_player":
        return 0
    if action.startswith("focus_party"):
        value = _integer(action[len("focus_party"):])
        if 1 <= value <= 4:
            return value
    return -1


def should_skip_focus(action: str, *, last_action: str, last_switch_ms: int, now_ms: int,
                      focus_known: bool, observed_index: int) -> bool:
    index = focus_index(action)
    if focus_known and index >= 0:
        return index == observed_index
    elapsed = now_ms - last_switch_ms
    return bool(last_action) and last_action == action and 0 <= elapsed < FOCUS_KEEP_MS


@dataclass
class FocusMemory:
    last_action: str = ""
    last_switch_ms: int = 0
    skipped_count: int = 0

    def should_skip(self, action: str, *, now_ms: int, focus_known: bool, observed_index: int) -> bool:
        return should_skip_focus(action, last_action=self.last_action,
                                 last_switch_ms=self.last_switch_ms, now_ms=now_ms,
                                 focus_known=focus_known, observed_index=observed_index)

    def record(self, action: str, *, now_ms: int, skipped: bool, sent: bool) -> int:
        """返回原版前置键后需要等待的毫秒数；失败仍由调用方继续主动作。"""
        if not skipped and not sent:
            self.last_action = ""
            return 0
        if skipped:
            self.skipped_count += 1
        self.last_action = action
        self.last_switch_ms = now_ms
        return 0 if skipped else PRE_KEY_DELAY_MS


def local_gcd_allows(action: str, *, off_gcd: bool) -> bool:
    if action == "auto_target":
        return True
    if action in ("start_attack", "pet_attack"):
        return False
    return off_gcd


def invalidate_local_gcd(*, active: bool, plugin_gcd: int, casting: bool) -> bool:
    """只在调用方确认换目标后使用；未知插件 GCD=-1 不足以清账。"""
    return active and plugin_gcd == 0 and not casting
