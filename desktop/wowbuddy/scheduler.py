"""0a2d70 的行为调度核心：换目标、圣印回执、回查及单次发送。

UI富文本、可用技能统计和诊断日志渲染另行实现。此模块不创建输入后端。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from .aura_probe import ProbeEvent, _integer, field_integer
from .candidates import Candidate, Rule, collect_expect_off, parse_rules
from .dispatch import ActionDispatcher, DispatchResult, DispatchState
from .expressions import EvaluationContext, _trim
from .pipeline import Decision, DecisionPipeline, PreparedFrame
from .pixel_geometry import RGBImage
from .send_gates import invalidate_local_gcd, local_gcd_allows


SEAL_FIELDS = ("seal_fury", "seal_righteousness", "seal_command")
SEAL_IDS = {
    **dict.fromkeys((0x4eba, 0x4f3f, 0x4f40, 0x4f41, 0x4f42, 0x4f43, 0x4f44, 0x4f45, 0x525c), "seal_righteousness"),
    **dict.fromkeys((0x4f97, 0x51b3, 0x51b6, 0x51b7, 0x51b8), "seal_command"),
    **dict.fromkeys((0x4ec3, 0x4fc3, 0x4fc5, 0x4fc6, 0x4fc7, 0x1403a1, 0x1403a8), "seal_fury"),
}


def self_buff_actions(rules: Sequence[Rule]) -> frozenset[str]:
    """039fc0：只保留增益、正压制、含显式false光环且无_target后缀的动作。"""
    result = set()
    for rule in rules:
        expected = collect_expect_off(rule.when)
        if rule.tag == "增益" and rule.hold_ms > 0 and expected and not any(key.endswith("_target") for key in expected):
            result.add(rule.action)
    return frozenset(result)


def retain_self_buffs(state: DispatchState, keep: frozenset[str]) -> int:
    removed = len(set(state.auras.suppression_until) - keep)
    for name in ("suppression_until", "check_at", "expect_off", "failures", "original_hold_ms", "sent_generation"):
        mapping = getattr(state.auras, name)
        for key in set(mapping) - keep:
            del mapping[key]
    state.last_sent_ms = 0
    return removed


def is_casting(fields: Mapping[str, str]) -> bool:
    return fields.get("player_casting", "").startswith(("读条中", "引导"))


@dataclass
class SealMemory:
    generation: int = -1
    seal: str = ""
    until_ms: int = 0
    judgement_ms: int = 0

    def observe(self, fields: Mapping[str, str], now_ms: int) -> dict[str, str]:
        generation = field_integer(fields, "player_succeeded_generation")
        spell = field_integer(fields, "player_succeeded_spell_id")
        if generation > 0:
            if self.generation > 0 and generation != self.generation and 2 <= spell <= 0xFFFFFE:
                if spell == 20271:
                    self.seal, self.until_ms, self.judgement_ms = "", 0, now_ms
                elif spell in SEAL_IDS:
                    self.seal, self.until_ms, self.judgement_ms = SEAL_IDS[spell], now_ms + 30000, 0
            self.generation = generation
        result = dict(fields)
        if fields.get("player_in_combat", "").upper() == "ON":
            if self.seal and now_ms < self.until_ms:
                result.update({key: "ON" if key == self.seal else "OFF" for key in SEAL_FIELDS})
            elif self.judgement_ms > 0 and now_ms - self.judgement_ms < 30000:
                result.update(dict.fromkeys(SEAL_FIELDS, "OFF"))
        return result


@dataclass
class SchedulerState:
    target_valid: int = -1
    auto_waiting: bool = False
    auto_protocol_active: bool = False
    focus_known: bool = False
    observed_focus: int = -1
    seals: SealMemory = field(default_factory=SealMemory)


@dataclass(frozen=True)
class TickResult:
    status: str
    decision: Decision
    selected: Candidate | None = None
    dispatch: DispatchResult | None = None
    probes: tuple[ProbeEvent, ...] = ()
    events: tuple[tuple[str, int], ...] = ()
    display_now_ms: int = 0
    display_suppression_until: Mapping[str, int] = field(default_factory=dict)
    local_gcd_active: bool = False
    auto_gate: int | None = None


class Scheduler:
    def __init__(self, pipeline: DecisionPipeline, dispatcher: ActionDispatcher,
                 clock_ms: Callable[[], int], state: SchedulerState | None = None):
        self.pipeline, self.dispatcher, self.clock_ms = pipeline, dispatcher, clock_ms
        self.state = state if state is not None else SchedulerState()

    def preserved_actions(self, prepared: PreparedFrame) -> frozenset[str]:
        rules = parse_rules(prepared.selected_rules)
        if not rules:
            spec = self.pipeline.engine.specs.get(prepared.frame.spec_id, {})
            rules = tuple(rule for group in spec.get("rotations", {}).values() for rule in parse_rules(group))
        return self_buff_actions(rules)

    def tick(self, image: RGBImage, *, hwnd: int, send_interval_ms: int,
             selected_profile: Mapping | None = None, settings: Mapping[str, int] | None = None) -> TickResult:
        prepared = self.pipeline.prepare(image, selected_profile=selected_profile, settings=settings)
        if not prepared.frame.ok:
            return TickResult("invalid_frame", self.pipeline.generate(prepared))
        return self.process(prepared, hwnd=hwnd, send_interval_ms=send_interval_ms)

    def process(self, prepared: PreparedFrame, *, hwnd: int, send_interval_ms: int,
                on_event=None, on_probe=None) -> TickResult:
        if not prepared.frame.ok:
            return TickResult("invalid_frame", self.pipeline.generate(prepared))
        fields = prepared.fields
        state, dispatch_state = self.state, self.dispatcher.state
        events = []
        def event(name, value=0, *, gate=None):
            events.append((name, value))
            if on_event is not None:
                on_event(name, value, gate=gate)
        keep = self.preserved_actions(prepared)
        target = fields.get("target_valid", "").upper()
        if target == "ON":
            if state.target_valid != 1:
                cleared = retain_self_buffs(dispatch_state, keep)
                now = self.clock_ms()
                if invalidate_local_gcd(active=now < dispatch_state.local_gcd_until_ms,
                                        plugin_gcd=EvaluationContext(fields).flag("gcd"), casting=is_casting(fields)):
                    remaining_ms = dispatch_state.local_gcd_until_ms - now
                    dispatch_state.local_gcd_until_ms = 0
                    event("new_target_gcd_clear", remaining_ms)
                event("new_target_clear", cleared)
            state.target_valid = 1
        elif target == "OFF":
            state.target_valid = 0
        # 未知值既不当作OFF，也不改前次有效目标状态。
        if fields.get("player_valid", "").upper() == "OFF":
            dispatch_state.focus.last_action = ""
            dispatch_state.focus.last_switch_ms = 0
        focus = _integer(_trim(fields.get("focus_index", "")))
        state.focus_known = 0 <= focus <= 5
        state.observed_focus = focus if state.focus_known else -1
        generation = field_integer(fields, "player_succeeded_generation")
        seal_now = self.clock_ms()
        consumed = (state.seals.generation > 0 and generation > 0
                    and generation != state.seals.generation
                    and field_integer(fields, "player_succeeded_spell_id") == 20271
                    and bool(state.seals.seal) and seal_now < state.seals.until_ms)
        engine_fields = state.seals.observe(fields, seal_now)
        if consumed:
            event("seal_consumed")
        decision = self.pipeline.generate(prepared, engine_fields=engine_fields)
        packet = self.pipeline.engine.last_auto_packet
        if packet is None:
            if state.auto_protocol_active:
                event("auto_protocol_lost")
            state.auto_protocol_active = False
            # 原版未在包丢失时清auto_waiting；后续有效包仍可能触发清账。
        else:
            if state.auto_waiting and packet.state != 1:
                event("auto_target_clear", retain_self_buffs(dispatch_state, keep), gate=packet.state)
            state.auto_waiting = packet.state == 1
            if not state.auto_protocol_active:
                event("auto_protocol_found", packet.key_index)
            state.auto_protocol_active = True
        now = self.clock_ms()
        probes = tuple(dispatch_state.auras.check(fields, now_ms=now, casting=is_casting(fields)))
        if on_probe is not None:
            for probe_event in probes:
                on_probe(probe_event, now_ms=now)
        candidates = decision.candidates
        display_deadlines = dict(dispatch_state.auras.suppression_until)
        display_gcd_active = now < dispatch_state.local_gcd_until_ms
        def result(status, selected=None, sent=None):
            return TickResult(status, decision, selected, sent, probes, tuple(events), now, display_deadlines,
                              display_gcd_active, packet.state if packet is not None else None)
        # 原版只在前8条展示循环里累计停发标记；实际候选引擎哨兵独占列表。
        if any(candidate.stop for candidate in candidates[:8]):
            return result("stopped")
        if not candidates:
            return result("no_candidates")
        if now - dispatch_state.last_sent_ms < send_interval_ms:
            return result("interval")
        gcd = now < dispatch_state.local_gcd_until_ms or EvaluationContext(fields).flag("gcd") == 1
        for candidate in candidates:
            if candidate.stop or (gcd and not local_gcd_allows(candidate.action, off_gcd=candidate.off_gcd)):
                continue
            if dispatch_state.auras.suppression_until.get(candidate.action, 0) > now:
                continue
            sent = self.dispatcher.dispatch(candidate, hwnd=hwnd, fields=fields,
                                            focus_known=state.focus_known, observed_focus=state.observed_focus)
            # 每帧只尝试第一个可发项；失败也不会继续尝试较低优先项。
            return result("sent" if sent.success else "send_failed", candidate, sent)
        return result("gcd_blocked" if gcd else "suppressed")
