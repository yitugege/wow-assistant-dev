"""089570 的发送执行与记账核心；调度器决定何时调用此模块。

显式注入 KeySender；不创建后端、不选择窗口、不启动监控。通道返回成功
只表示输入投递成功，不表示游戏实际施法成功。UI 文案层另行重建。
"""
from dataclasses import dataclass, field
from typing import Mapping

from .aura_probe import AuraProbeLedger
from .candidates import Candidate
from .send_gates import FocusMemory, PRE_KEY_DELAY_MS
from .windows_keys import KeySender


@dataclass
class DispatchState:
    focus: FocusMemory = field(default_factory=FocusMemory)
    auras: AuraProbeLedger = field(default_factory=AuraProbeLedger)
    last_sent_ms: int = 0
    success_count: int = 0
    local_gcd_until_ms: int = 0


@dataclass(frozen=True)
class DispatchResult:
    status: str
    success: bool = False
    pre_skipped: bool = False
    pre_success: bool | None = None
    sent_at_ms: int | None = None
    channel_status: str = ""
    channel_path: str = ""


class ActionDispatcher:
    def __init__(self, sender: KeySender | None, state: DispatchState | None = None):
        self.sender = sender
        self.state = state if state is not None else DispatchState()

    def dispatch(self, candidate: Candidate, *, hwnd: int, fields: Mapping[str, str],
                 focus_known: bool = False, observed_focus: int = -1) -> DispatchResult:
        sender = self.sender
        if sender is None:
            return DispatchResult("no_sender")
        # 每次发送前原主窗强制这三项；不会使用临时激活通道。
        sender.hwnd = hwnd
        sender.force_background = True
        sender.allow_activation = False
        sender.interval_ms = 30
        if not candidate.key:
            return DispatchResult("no_key", channel_status="发送被拒绝：建议没有可用按键")
        skipped = False
        pre_success = None
        if candidate.pre_key:
            before_pre = sender.backend.now_ms()
            skipped = self.state.focus.should_skip(candidate.pre_action, now_ms=before_pre,
                                                    focus_known=focus_known, observed_index=observed_focus)
            if not skipped:
                pre_success = sender.send(candidate.pre_key, bypass_interval=True)
                if pre_success:
                    sender.backend.Sleep(PRE_KEY_DELAY_MS)
            self.state.focus.record(candidate.pre_action, now_ms=before_pre,
                                    skipped=skipped, sent=bool(pre_success))
        # 原版前置失败仍尝试主键；成功计数仅主键贡献。
        success = sender.send(candidate.key, bypass_interval=False)
        now_ms = sender.backend.now_ms()
        if success:
            self.state.last_sent_ms = now_ms
            self.state.success_count += 1
            self.state.auras.record_send(candidate.action, success=True, now_ms=now_ms,
                                         hold_ms=candidate.hold_ms, expect_off=candidate.expect_off,
                                         fields=fields)
            if not candidate.off_gcd:
                self.state.local_gcd_until_ms = now_ms + 1500
        return DispatchResult("sent" if success else "failed", success, skipped, pre_success,
                              now_ms, sender.status, sender.channel)
