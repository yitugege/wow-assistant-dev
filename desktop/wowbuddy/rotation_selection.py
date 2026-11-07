"""循环库载入与方案选择状态机；不访问网络、注册表或 Qt 控件。

恢复 04e250/04f960/0999f0/080f60，证据及边界见 evidence/循环选择.md。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Mapping

from .candidates import Rule, parse_rules, _decimal_int
from .expressions import UnsupportedSemantics, _int, _string


def _rules_json(rules: tuple[Rule, ...]) -> list[dict]:
    return [{"action": r.action, "when": deepcopy(r.when), "reason": r.reason,
             "tag": r.tag, "holdMs": r.hold_ms, "pre": r.pre, "offGcd": r.off_gcd} for r in rules]


@dataclass(frozen=True)
class Profile:
    id: int
    spec_id: int
    spec_name: str
    sub_key: str
    name: str
    summary: str
    author: str
    game_version: str
    updated_at: str
    rules: tuple[Rule, ...]

    @property
    def key(self) -> str:
        return f"{self.spec_id}|{self.sub_key}|{self.name}"

    @property
    def display_name(self) -> str:
        text = self.name
        if self.sub_key and self.sub_key not in self.name:
            text += f"（{self.sub_key}）"
        text += f"  · {len(self.rules)} 条"
        if self.author:
            text += f"  by {self.author}"
        return text

    @property
    def engine_name(self) -> str:
        return f"{self.spec_name} · {self.name}"

    def to_json(self) -> dict:
        """适配 DecisionPipeline.evaluate(selected_profile=...)。"""
        return {"id": self.id, "specId": self.spec_id, "specName": self.spec_name,
                "subKey": self.sub_key, "profileName": self.name, "summary": self.summary,
                "author": self.author, "gameVersion": self.game_version,
                "updatedAt": self.updated_at, "rules": _rules_json(self.rules)}


def _content(value: object) -> object:
    """用于变化检测的类型敏感 JSON 值；不冒充 Qt 的字节摘要。"""
    if isinstance(value, dict):
        return ("object", tuple((k, _content(v)) for k, v in sorted(value.items())))
    if isinstance(value, list):
        return ("array", tuple(_content(v) for v in value))
    if type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            raise UnsupportedSemantics("循环快照包含非有限数字")
        return ("number", value)
    return (type(value).__name__, value)


def _snapshot_digest(rotations: list) -> str:
    from PySide6.QtCore import QJsonDocument
    _content(rotations)  # 保留显式Mapping入口的非有限数字拒绝。
    encoded = json.dumps(rotations, ensure_ascii=True, allow_nan=False).encode('utf-8')
    document = QJsonDocument.fromJson(encoded)
    return hashlib.md5(bytes(document.toJson(QJsonDocument.Compact))).hexdigest()


@dataclass(frozen=True)
class HubState:
    profiles: tuple[Profile, ...] = ()
    generated_at: str = ""
    valid: bool = False
    from_cache: bool = False
    changed_pending: bool = False
    # 原生只对 rotations 数组的 Qt JSON 序列化做 hash(algorithm=1)。
    # 原数组Compact序列化的MD5十六进制串。
    content_identity: object = None
    error: str = ""


@dataclass(frozen=True)
class LoadResult:
    state: HubState
    accepted: bool


def load_snapshot(payload: str | bytes | Mapping, previous: HubState | None = None,
                  *, from_cache: bool = True) -> LoadResult:
    """纯内存载入；缓存缺失/不可读由调用者处理，空缓存保留所有旧状态。"""
    old = previous or HubState()
    if isinstance(payload, (str, bytes)):
        if from_cache and not payload.strip():
            return LoadResult(old, False)
        from PySide6.QtCore import QJsonDocument, QJsonParseError
        raw_payload = payload.encode("utf-8", errors="surrogatepass") if isinstance(payload, str) else payload
        error = QJsonParseError()
        document = QJsonDocument.fromJson(raw_payload, error)
        if error.error != QJsonParseError.NoError or not document.isObject():
            return LoadResult(replace(old, valid=False, error="invalid_json"), False)
        # PySide toVariant会丢失孤立UTF-16代理字符；Qt序列化以转义保留。
        obj = json.loads(bytes(document.toJson(QJsonDocument.Compact)))
    else:
        obj = payload
    if not isinstance(obj, dict):
        return LoadResult(replace(old, valid=False, error="invalid_json"), False)
    if _string(obj.get("format")) != "wowbuddy-rotation-hub":
        return LoadResult(replace(old, valid=False, error="wrong_format"), False)
    raw = obj.get("rotations", [])
    raw = raw if isinstance(raw, list) else []
    identity = _snapshot_digest(raw)
    profiles = []
    for entry in raw:
        entry = entry if isinstance(entry, dict) else {}
        spec_id, name = _int(entry.get("specId")), _string(entry.get("profileName"))
        if spec_id > 0 and name:
            profiles.append(Profile(_int(entry.get("id")), spec_id, _string(entry.get("specName")),
                _string(entry.get("subKey")), name, _string(entry.get("summary")),
                _string(entry.get("author")), _string(entry.get("gameVersion")),
                _string(entry.get("updatedAt")), parse_rules(entry.get("rules"))))
    generated = obj.get("generatedAt")
    generated = generated if isinstance(generated, str) else "未知时间"
    return LoadResult(HubState(tuple(profiles), generated, True, from_cache,
                              old.changed_pending or identity != old.content_identity, identity), True)


def consume_update(hub: HubState) -> tuple[bool, HubState]:
    """050840 的一次性 changed 标志；无变化不会清除已待处理的变化。"""
    return hub.changed_pending, replace(hub, changed_pending=False)


@dataclass(frozen=True)
class SelectionState:
    # options 不含固定第 0 项“未选择（不自动发键）”。
    options: tuple[Profile, ...] = ()
    current_key: str = ""
    pending_key: str = ""
    preserve_active: bool = False       # UI +0x208：暂时无匹配项/缺少 spec。
    enabled: bool = False
    spec_id: str = ""
    sub_key: str = ""
    active_profile: Profile | None = None
    rebuilt: bool = False

    @property
    def has_external_rules(self) -> bool:
        return self.active_profile is not None and bool(self.active_profile.rules)

    def profile_for_spec(self, spec_id: str | int) -> dict | None:
        """保留的外部方案只传给相同 spec；空规则允许下游原生回退。"""
        item = self.active_profile
        return item.to_json() if item is not None and str(item.spec_id) == str(spec_id) else None


@dataclass(frozen=True)
class ApplyResult:
    state: SelectionState
    settings: dict[str, str]
    writes: dict[str, str]
    effect: str                     # applied / cleared / preserved / not_found / malformed
    refresh_thresholds: bool


def _settings(settings: Mapping[str, str]) -> dict[str, str]:
    if any(not isinstance(value, str) for value in settings.values()):
        raise UnsupportedSemantics("选择 settings 必须已完成 QVariant::toString 转换")
    return dict(settings)


def initial_selection(settings: Mapping[str, str]) -> SelectionState:
    return SelectionState(pending_key=_settings(settings).get("hub/selection", ""))


def restore_for_spec(state: SelectionState, spec_id: str | int,
                     settings: Mapping[str, str]) -> SelectionState:
    """092c90/095410：只有非空 by-spec 值覆盖 pending；不擅自清 current。"""
    saved = _settings(settings).get(f"hub/by-spec/{spec_id}", "")
    return replace(state, pending_key=saved or state.pending_key)


def rebuild_selection(hub: HubState, state: SelectionState, spec_id: str | int,
                      sub_key: str = "") -> SelectionState:
    """0999f0：原数组顺序、精确 spec、slash 拆分匹配，不自动选第一套。"""
    spec = str(spec_id)
    if not spec and state.options:
        return replace(state, spec_id=spec, sub_key=sub_key, preserve_active=True, rebuilt=False)
    options = tuple(p for p in hub.profiles if spec and str(p.spec_id) == spec
                    and (not sub_key or not p.sub_key or sub_key in p.sub_key.split("/")))
    desired = state.current_key or state.pending_key
    found = next((p for p in options if p.key == desired), None) if desired else None
    # 无 desired 时原 findData 不执行，index=0，因此会清 pending。
    missing = bool(desired) and found is None
    pending = state.pending_key if missing and not options else ""
    return replace(state, options=options, current_key=found.key if found else "",
                   pending_key=pending, preserve_active=not options, enabled=bool(options),
                   spec_id=spec, sub_key=sub_key, rebuilt=True)


def _selection_parts(key: str) -> tuple[int, str, str] | None:
    pieces = key.split("|")
    if len(pieces) < 3:
        return None
    # QString::toInt(base=10, ok=nullptr)：失败返回 0。
    value = _decimal_int(pieces[0]) or 0
    return value, pieces[1], "|".join(pieces[2:])


def apply_selection(hub: HubState, state: SelectionState,
                    settings: Mapping[str, str], *, current_key: str | None = None) -> ApplyResult:
    """080f60：保存条件与应用条件分别建模；找不到 key 不清旧方案。"""
    values = _settings(settings)
    if current_key is not None:
        state = replace(state, current_key=current_key)
    key, writes = state.current_key, {}
    if not state.preserve_active and (key or not state.has_external_rules):
        writes["hub/selection"] = key
        if state.spec_id and key:
            writes[f"hub/by-spec/{state.spec_id}"] = key
    values.update(writes)
    if key:
        parts = _selection_parts(key)
        if parts is None:
            return ApplyResult(state, values, writes, "malformed", False)
        found = next((p for p in hub.profiles if (p.spec_id, p.sub_key, p.name) == parts), None)
        if found is None:
            return ApplyResult(state, values, writes, "not_found", False)
        return ApplyResult(replace(state, active_profile=found), values, writes, "applied", True)
    if not state.preserve_active:
        # 原生仅在外部规则 count!=0 时清除 spec/name/规则/阈值。
        cleared = state.has_external_rules
        return ApplyResult(replace(state, active_profile=None) if cleared else state,
                           values, writes, "cleared" if cleared else "preserved", True)
    return ApplyResult(state, values, writes, "preserved", not state.has_external_rules)


def refresh_library(hub: HubState, state: SelectionState, settings: Mapping[str, str],
                    spec_id: str | int, sub_key: str = "") -> tuple[HubState, ApplyResult]:
    """09dd90：消费变化标志后才重建并应用；不变时仅刷新状态显示。"""
    changed, hub = consume_update(hub)
    if not changed:
        return hub, ApplyResult(state, _settings(settings), {}, "preserved", False)
    state = rebuild_selection(hub, state, spec_id, sub_key)
    return hub, apply_selection(hub, state, settings)
