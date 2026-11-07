"""原生候选、可用技能和日志呈现；无 Qt、时钟、发键或文件副作用。

0a2d70 的候选控件原本是纯文本。candidate_html 仅是转义后的 UI 适配。
诊断节流状态由调用者持有，时间和原始 fields 均须显式传入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import html
import re
from typing import Mapping, Sequence

from .candidates import Action, Candidate
from .aura_probe import ProbeEvent, ProbeResult, Receipt
from .dispatch import DispatchResult
from .expressions import UnsupportedSemantics, _int, _trim


READY_COLOR = "#22e58b"
UNAVAILABLE_COLOR = "#4a5670"
DIAGNOSTIC_KEYS = (
    "master_switch", "gcd", "player_casting", "target_valid", "player_valid",
    "action_avail", "distance", "combat_time", "active_enemies", "target_health_pct",
)


def _arg(template: str, *values: object) -> str:
    """QString::arg 的最低编号替换；多参数一次替换，不重扫插入字符串。"""
    pattern = r"%([1-9][0-9]?)"
    indices = sorted({int(m.group(1)) for m in re.finditer(pattern, template)})
    replacements = dict(zip(indices, map(str, values)))
    return re.sub(pattern, lambda m: replacements.get(int(m.group(1)), m.group(0)), template)


def _pad(text: str, width: int) -> str:
    # QString::size 计 UTF-16 单元；CJK 不是按终端显示列宽计算。
    length = len(text.encode("utf-16-le", "surrogatepass")) // 2
    return text + " " * max(0, width - length)


def _one_decimal(value: float) -> str:
    return str(Decimal.from_float(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def hold_text(hold_ms: int) -> str:
    """08c0a0：零/负值隐藏；整秒无小数，非整秒固定一位。"""
    if hold_ms <= 0:
        return ""
    if hold_ms < 1000:
        return f"  压制{hold_ms}ms"
    seconds = str(hold_ms // 1000) if hold_ms % 1000 == 0 else _one_decimal(hold_ms / 1000)
    return f"  压制{seconds}s"


def candidate_text(candidates: Sequence[Candidate], *, now_ms: int = 0,
                   suppression_until: Mapping[str, int] | None = None) -> str:
    lines = []
    deadlines = suppression_until or {}
    for candidate in candidates[:8]:
        if candidate.stop:
            lines.append(_arg("  ⛔ %1：%2", candidate.label, candidate.reason))
            continue
        deadline = deadlines.get(candidate.action, 0)
        suffix = (f"  压制 {_one_decimal((deadline - now_ms) / 1000)}s"
                  if now_ms < deadline else hold_text(candidate.hold_ms))
        line = _arg("  [%1] %2  %3  %4%5", candidate.priority)
        line = _arg(line, _pad(candidate.key, 10))
        line = _arg(line, _pad(candidate.label, 14))
        lines.append(_arg(line, candidate.reason, suffix))
    return "\n".join(lines) if lines else "  （本帧无建议）"


def candidate_html(candidates: Sequence[Candidate], **kwargs) -> str:
    """非原生包装层：保持原版空格及换行，禁止把候选文案当 HTML。"""
    return "<pre>" + html.escape(candidate_text(candidates, **kwargs)) + "</pre>"


def _mask(fields: Mapping[str, str]) -> int | None:
    raw = fields.get("action_avail", "")
    if not isinstance(raw, str):
        raise TypeError("decoded fields must contain strings")
    token = _trim(_trim(raw).split(" ", 1)[0])
    if not re.fullmatch(r"[+-]?[0-9]+", token):
        return None
    value = int(token)
    return value if -(2**63) <= value < 2**63 else None


@dataclass(frozen=True)
class AvailabilityDisplay:
    summary: str
    detail_html: str
    ready: tuple[str, ...]
    unavailable: tuple[str, ...]
    valid: bool
    total: int

    @property
    def ready_count(self) -> int:
        return len(self.ready)


def availability(spec: Mapping | None, fields: Mapping[str, str]) -> AvailabilityDisplay:
    has_spec = spec is not None
    spec = spec or {}
    raw_ids = spec.get("actionAvailSpellIDs", [])
    ids = tuple(_int(value) for value in raw_ids) if isinstance(raw_ids, list) else ()
    labels = {}
    actions = spec.get("actions", [])
    for item in actions if isinstance(actions, list) else ():
        action = Action.from_json(item)
        if action.spell_id > 0:
            labels[action.spell_id] = action.label or action.name
    mask = _mask(fields) if has_spec else None
    ready, unavailable = [], []
    if mask is not None:
        for bit, spell in enumerate(ids, 1):
            target = ready if (mask >> (bit & 63)) & 1 else unavailable
            target.append(labels.get(spell, str(spell)))
    parts = []
    # 原生 QLabel 的字符串未转义；保留原生格式，调用者应仅传已信任方案。
    if ready:
        parts.append(f"<span style='color:{READY_COLOR}'>✔ {' '.join(ready)}</span>")
    if unavailable:
        parts.append(f"<span style='color:{UNAVAILABLE_COLOR}'>✘ {' '.join(unavailable)}</span>")
    total = len(ids)
    summary = f"{len(ready)} / {total}" if total else "— / —"
    detail = ("<br>".join(parts) or "（本专精没有登记动作）") if total else "开启监控后显示"
    return AvailabilityDisplay(summary, detail, tuple(ready), tuple(unavailable), mask is not None, total)


@dataclass(frozen=True)
class SendDisplay:
    status: str | None
    log: str | None


def send_display(candidate: Candidate, result: DispatchResult, *, prefix: str = "自动",
                 focus_known: bool = False) -> SendDisplay:
    """089570：每次实际主键尝试都记日志；成功仅代表通道投递结果。"""
    if result.status == "no_sender":
        return SendDisplay(None, None)  # 原版直接返回，保留旧状态。
    if result.status == "no_key":
        return SendDisplay("发送被拒绝：建议没有可用按键", None)
    if result.status not in ("sent", "failed"):
        raise UnsupportedSemantics(f"unsupported dispatch status: {result.status}")
    status = _arg("%1 %2 → %3（%4）", "✓" if result.success else "✗",
                  candidate.label, candidate.key, result.channel_status)
    pre = ""
    if candidate.pre_key:
        if result.pre_skipped:
            pre_result = "已就位(读数)" if focus_known else "已就位(保鲜)"
        elif result.pre_success is not None:
            pre_result = "✓" if result.pre_success else "✗"
        else:
            raise UnsupportedSemantics("pre-key result is missing")
        pre = _arg("  先行=%1(%2) %3", candidate.pre_action, candidate.pre_key, pre_result)
    tag = _arg(" 标签=%1", candidate.tag) if candidate.tag else ""
    path = _arg("  路径=%1", result.channel_path)
    log = _arg("%1发送 %2 键=%3%4 结果=%5 %6%7%8", prefix, candidate.label, candidate.key,
               tag, "成功" if result.success else "失败", result.channel_status, path, pre)
    return SendDisplay(status, log)


def success_count_text(count: int) -> str:
    return f"发键：累计 {count} 条"


def statistics_text(frames: int, changes: int, elapsed_ms: int) -> str:
    """092c90/095410：成功抓屏帧数、字段展示文本变更次数、均值 fps。"""
    seconds = max(elapsed_ms / 1000, 0.1)
    # 状态行的秒数是 f/0 舍入；右侧独立秒数徽标才是 int 截断。
    elapsed = Decimal.from_float(seconds).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{frames} 帧 / {changes} 变更   {_one_decimal(frames / seconds)} fps   {elapsed} 秒"


@dataclass(frozen=True)
class FrameDisplay:
    status: str
    diagnostic_reason: str | None = None


def frame_status(status: str, candidates: Sequence[Candidate] = (), *, send_interval_ms: int = 100,
                 local_gcd_active: bool = False, plugin_gcd: int = -1) -> FrameDisplay:
    """仅映射 0a2d70 已确定的调度终态；发送终态使用 send_display。"""
    if status == "stopped":
        reason = candidates[0].reason if candidates else "空哨兵"
        return FrameDisplay(f"已停发：{reason}", f"停发哨兵 → {reason}")
    if status == "no_candidates":
        return FrameDisplay("无建议", "本帧没有任何规则命中")
    if status == "interval":
        return FrameDisplay(f"节流中（{send_interval_ms}ms）")
    if status == "suppressed":
        return FrameDisplay("高优先级动作均在压制期", "所有建议都在压制期内")
    if status == "gcd_blocked":
        source = ("本地账本+插件读数都判在冷却" if plugin_gcd == 1 else "只有本地账本在挡·插件读数空闲") if local_gcd_active else "插件读到 GCD·本地账本已过期"
        return FrameDisplay("GCD 中（本地记 1500ms），只放行不吃 GCD 的动作",
                            f"GCD 中（{source}），可插的动作都在压制期内")
    raise UnsupportedSemantics(f"unrecovered frame display status: {status}")


def diagnostic_text(reason: str, spec_id: str, fields: Mapping[str, str], *,
                    spec: Mapping | None = None, talent_key: str = "") -> str:
    """08de90；talent_key 由 04b0b0 的职业前缀 + '_talents' 调用方提供。"""
    keys = (*DIAGNOSTIC_KEYS, talent_key) if talent_key else DIAGNOSTIC_KEYS
    pairs = [f"{key}={fields.get(key, '') or '(缺)'}" for key in keys]
    display = availability(spec, fields)
    if spec is not None and display.valid:
        pairs.append(f"可用技能={display.ready_count}/{display.total}")
    return f"⛔ 未发键：{reason}｜专精={spec_id}｜{' '.join(pairs)}"


@dataclass
class DiagnosticThrottle:
    last_reason: str = ""
    last_ms: int = 0

    def emit(self, reason: str, spec_id: str, fields: Mapping[str, str], *, now_ms: int,
             spec: Mapping | None = None, talent_key: str = "") -> str | None:
        if reason == self.last_reason and now_ms - self.last_ms < 5000:
            return None
        self.last_reason, self.last_ms = reason, now_ms
        return diagnostic_text(reason, spec_id, fields, spec=spec, talent_key=talent_key)


def timestamped(message: str, when: datetime) -> str:
    """080d60 使用本地时间；时区由调用者 datetime 决定，不另读系统时钟。"""
    return f"[{when:%H:%M:%S}.{when.microsecond // 1000:03d}] {message}"


def _arg_chain(template: str, *values: object) -> str:
    """逐次 QString::arg；原生这些日志会重新扫描前次插入的占位符。"""
    for value in values:
        template = _arg(template, value)
    return template


def capture_backend_text(backend_name: str) -> str:
    """092c90:230；仅非空抓屏计数变为 1 时调用，坏标记也会记录。"""
    return _arg("抓屏后端：%1", backend_name)


def legacy_spec_text(field_count: int, *, restored_selection_nonempty: bool = False) -> str:
    # 原生只检查 +0x1f0 非空；不证明该循环确实成功恢复。
    suffix = "（已恢复该专精上次的循环）" if restored_selection_nonempty else ""
    return _arg_chain("检测到专精 → 重建字段表（%1 格）%2", field_count, suffix)


def readable_spec_text(spec_name: str, field_count: int, presence_count: int) -> str:
    """095410:608；spec_name 须传内部 spec_id，非中文显示名。

    身份切换后、完整采样越界检查前调用。
    """
    return _arg_chain("readable 条 → %1（%2 字段 + %3 presence）",
                      spec_name, field_count, presence_count)


def talent_group_text(group: str) -> str:
    """仅旧条 092c90:1213 的实际分组变化分支；重建不一定有此日志。"""
    return _arg("检测到专精变化 → 循环方案与开关只列「%1」", group or "全部（天赋未读到）")


def field_change_text(slot_index: int, label: str, value_text: str,
                      rgb: tuple[int, int, int]) -> str:
    """旧条槽位从零传入；value_text 是已合成的「值 说明」，而非仅数值。"""
    red, green, blue = rgb
    return _arg_chain("#%1 %2：%3  (rgb=%4,%5,%6)",
                      slot_index + 1, label, value_text, red, green, blue)


@dataclass
class FieldChangeThrottle:
    """092c90 的 +0xa8 哈希；调用者仅在旧条展示文本变化时调用。

    使用会话 QElapsedTimer 的秒数，按字段 key 独立限流。098ea0 重建字段
    清的是 +0xa0 解码表，不清本哈希；停止/开始也不清，重启 elapsed 后
    可延迟后续日志。clear 仅供显式新建窗口/测试重置，不接专精或监控事件。
    """
    last_seconds: dict[str, float] = field(default_factory=dict)

    def emit(self, key: str, slot_index: int, label: str, value_text: str,
             rgb: tuple[int, int, int], *, elapsed_ms: int) -> str | None:
        seconds = elapsed_ms / 1000.0
        # 092c90:845–846 的 double 位模式 c1cdcd6500000000 = -1e9。
        if seconds - self.last_seconds.get(key, -1_000_000_000.0) < 2.0:
            return None
        self.last_seconds[key] = seconds
        return field_change_text(slot_index, label, value_text, rgb)

    def clear(self) -> None:
        self.last_seconds.clear()


@dataclass
class NoFiducialThrottle:
    """092c90 的独立 no-fiducial 键；与未发键原因去重完全分离。"""
    last_ms: int = 0

    def emit(self, *, now_ms: int) -> str | None:
        if now_ms - self.last_ms < 5000:
            return None
        self.last_ms = now_ms
        return "⛔ 未找到插件色块（未进入角色 / 插件未启用 / 像素条被隐藏）"


def scheduler_event_text(name: str, value: int = 0, *, gate: int | None = None) -> str | None:
    """0a2d70 已发生的事件→日志，不推导事件、不改变调度状态。

    new_target_gcd_clear 的 value 必须为清零前剩余毫秒，不是布尔值。
    auto_target_clear 须提供当前包 gate；协议就绪日志使用两个固定常量。
    事件原生顺序：新目标 GCD 作废→非零清账→圣印→自动目标→光环回查。
    """
    if name == "new_target_gcd_clear":
        return _arg("新目标：游戏读数说 GCD 空闲 → 作废本地 GCD 账本（还剩 %1ms），首个技能不必干等", value)
    if name == "new_target_clear":
        return (_arg("检测到新目标 → 清除 %1 条旧压制期，首个技能可立即施放", value)
                if value != 0 else None)
    if name == "auto_target_clear":
        if gate is None:
            raise UnsupportedSemantics("auto_target_clear requires the observed packet gate")
        return _arg_chain("自动选目标已换到新目标（gate 1→%1）→ 清除 %2 条压制期，首个技能可立即施放", gate, value)
    if name == "auto_protocol_found":
        return "自动选目标通道就绪：插件在回传包（基址 13631488，键表 81 项）"
    if name == "auto_protocol_lost":
        return "自动选目标包读不到了（ttd 格无值）→ 换目标功能暂停；请确认插件设置里开了「自动选目标」"
    if name == "seal_consumed":
        return "⚡ 审判成功 → 圣印被消耗（时间式推定），下一 GCD 自动补印"
    raise UnsupportedSemantics(f"unrecovered scheduler event: {name}")


def probe_event_text(event: ProbeEvent, *, now_ms: int) -> str | None:
    """仅压制截止时间实际缩短/延长时记录；回查完成本身不保证有日志。

    now_ms 必须是该批回查的时刻（TickResult.display_now_ms），不可重新读钟。
    数字均为 QString::arg 的 f/1；提示中的成功、免疫是原文推断。
    """
    before, after = event.old_suppression_until_ms, event.suppression_until_ms
    if event.result == ProbeResult.MISSED and after < before:
        reason = ("施法代次没跳（这一下根本没成功，被打断或够不着）"
                  if event.receipt == Receipt.NOT_FIRED else "光环没出现（施法被打断？）")
        return _arg_chain("⚠ %1 按出去了但" + reason + "→ 压制期从 %2s 缩到 %3s，重试",
                          event.action, _one_decimal((before - now_ms) / 1000), "1.0")
    if event.result == ProbeResult.IMMUNE and before < after:
        hold = _one_decimal((after - now_ms) / 1000)
        if event.receipt == Receipt.FIRED_SAME:
            return _arg_chain("⛔ %1 技能确实出手了（施法代次已跳、成功ID 对得上）但光环始终没出现 → 这个目标对它免疫，压制期恢复成 %2s，不再试第二次",
                              event.action, hold)
        return _arg_chain("⛔ %1 连着 %2 次按出去光环都没出现 → 这个目标免疫/抵抗（或打不到），压制期恢复成 %3s，不再连按",
                          event.action, event.failures, hold)
    return None
