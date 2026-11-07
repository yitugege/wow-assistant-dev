"""029da0/041e00/02b710/0446a0 的有状态资源适配；不执行原程序。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Callable

from .expressions import _double, _int, _string
from .pipeline import readable_key_maps
from .startup_stages import LoadOutcome


def _object(value):
    return value if isinstance(value, dict) else {}


def _array(value):
    return value if isinstance(value, list) else []


def _items(value):
    # QJsonObject 的 QString 排序是 UTF-16 code unit 顺序。
    obj = _object(value)
    return ((key, obj[key]) for key in sorted(obj, key=lambda s: s.encode("utf-16-be", "surrogatepass")))


def _int64(value, default=0):
    number = _double(value, float(default))
    # 原加载点 02a1bd/02ac32/02b9de/0424ca 均为 CVTTSD2SI rax,xmm0。
    # 保持进程默认屏蔽浮点异常时，有限越界返回 integer-indefinite，而非饱和或抛错。
    # _double 仍拒绝非有限注入值；Qt JSON 解析器不接受这种数值。
    if not -(2**63) <= number < 2**63:
        return -(2**63)
    return int(number)


def _fields(value, forced_type=""):
    result = []
    for entry in _array(value):
        entry = _object(entry)
        identifier = _string(entry.get("id"))
        result.append({"id": identifier, "label": _string(entry.get("label")) or identifier,
                       "type": forced_type or _string(entry.get("type")) or "number",
                       "note": _string(entry.get("note"))})
    return result


def normalize_contract(raw: dict) -> dict:
    """保留所有原始元数据，覆盖已确认由原加载器消费的字段。"""
    result = deepcopy(raw)
    constants = _object(raw.get("constants"))
    result["constants"] = {**constants, **{
        name: _int(constants.get(name), default) for name, default in (
            ("noValue", 0xFFFFFF), ("cdUnavailable", 601), ("identityHeroShift", 4096),
            ("fiducialX", 4), ("fiducialY", 128), ("cellSize", 4), ("commonCount", 29))}}
    result["constants"]["expectedVersion"] = _int64(constants.get("expectedVersion"))
    result["commonFields"] = _fields(raw.get("commonFields"))
    for name in ("classNames", "sentinel601"):
        result[name] = {k: _string(v) for k, v in _items(raw.get(name))}
    result["talentGroups"] = {k: [_string(x) for x in _array(v)]
                              for k, v in _items(raw.get("talentGroups"))}
    result["classOnlyFields"] = {k: [_int64(x) for x in _array(v)]
                                 for k, v in _items(raw.get("classOnlyFields"))}
    result["specs"] = {}
    for key, value in _items(raw.get("specs")):
        spec = _object(value)
        result["specs"][key] = {**spec, "title": _string(spec.get("title")),
            "fields": _fields(spec.get("fields")),
            "presenceFields": _fields(spec.get("presenceFields"), "presence")}
    return result


def normalize_rules(raw: dict) -> dict:
    result = deepcopy(raw)
    sentinel = _object(raw.get("sentinel"))
    result["sentinel"] = {**sentinel, **{name: _string(sentinel.get(name)) for name in
        ("stopTag", "stopLabel", "stopReason", "masterSwitchField", "combatTimeField")},
        "cdReadyEps": _double(sentinel.get("cdReadyEps"), 0.05),
        "noValue": _int64(sentinel.get("noValue"), 0xFFFFFF)}
    switches = {}
    for value in _array(raw.get("switchFields")):
        value = _object(value)
        name = _string(value.get("field"))
        if name:
            switches[name] = {**value, "field": name,
                "label": _string(value.get("label")) or name,
                "unit": _string(value.get("unit")), "max": _int(value.get("max"), 100)}
    # 原存入QHash；保留末值，不声称该列表顺序就是原QHash遍历顺序。
    result["switchFields"] = list(switches.values())
    result["roles"] = {}
    for key, value in _items(raw.get("roles")):
        value = _object(value)
        result["roles"][key] = {**value, "token": _string(value.get("token")),
            "class": _string(value.get("class")),
            "groups": [_string(x) for x in _array(value.get("groups"))],
            "roles": {k: _string(v) for k, v in _items(value.get("roles"))}}
    result["specs"] = {}
    for key, value in _items(raw.get("specs")):
        spec = _object(value)
        actions = []
        for value in _array(spec.get("actions")):
            action = _object(value)
            actions.append({**action, **{k: _string(action.get(k)) for k in ("name", "key", "label")},
                            "spellId": _int(action.get("spellId"), -1)})
        rotations = {}
        for group, value in _items(spec.get("rotations")):
            entries = []
            for value in _array(value):
                rule = _object(value)
                entries.append({**rule, **{k: _string(rule.get(k)) for k in ("action", "reason", "tag", "pre")},
                    "holdMs": _int(rule.get("holdMs")), "offGcd": rule.get("offGcd") is True})
            rotations[group] = entries
        result["specs"][key] = {**spec, "title": _string(spec.get("title")),
            "actionAvailSpellIDs": [_int(x) for x in _array(spec.get("actionAvailSpellIDs"))],
            "actions": actions, "rotations": rotations,
            "genericFill": [_string(x) for x in _array(spec.get("genericFill"))]}
    return result


@dataclass(frozen=True)
class JsonRead:
    """document为QJsonDocument.object()结果；失败kind仅open或parse。"""
    document: dict | None = None
    failure: str = ""
    error: str = ""


def read_qt_json(path: str | Path) -> JsonRead:
    from PySide6.QtCore import QFile, QIODevice, QJsonDocument, QJsonParseError
    file = QFile(str(path))
    if not file.open(QIODevice.OpenModeFlag.ReadOnly):
        return JsonRead(failure="open", error=file.errorString())
    try:
        data = file.readAll()
    finally:
        file.close()
    error = QJsonParseError()
    document = QJsonDocument.fromJson(data, error)
    if error.error != QJsonParseError.ParseError.NoError:
        return JsonRead(failure="parse", error=error.errorString())
    # 原加载器没有isObject判断；JSON数组转换为空对象，进入内容判据。
    # PySide object()/toVariant 会丢失孤立 UTF-16 代理字符；Qt Compact
    # 序列化将这些代码单元转义，保留原字段键、标签和动作名称。
    return JsonRead(json.loads(bytes(document.toJson(QJsonDocument.Compact)))
                    if document.isObject() else {})


@dataclass
class NativeAssetState:
    document: dict = field(default_factory=dict)
    raw_document: dict = field(default_factory=dict)
    valid: bool = False


class NativeAssetStore:
    """构造无IO。四个load可直接注入ResourceStageLoader。

    每次LoadOutcome.value是状态的独立快照；accepted是本次返回值，
    valid是原单例持久标志，两者在readable行表失败时可能不同。
    """
    def __init__(self, *, read_json: Callable[[str | Path], JsonRead] = read_qt_json):
        self.read_json = read_json
        self.contract = NativeAssetState(normalize_contract({}))
        self.rules = NativeAssetState(normalize_rules({}))
        # 029d30 返回 DAT_14010f040；PE 的 +0x48 初始 qword 为 0x00a30d41。
        # 02b710 仅在 JSON 解析成功后覆盖（包括成功解析空对象时写0）。
        self.readable_contract = NativeAssetState({"header": {"addonVersionCode": 10685761}, "specs": {}})
        self.readable_rules = NativeAssetState({"specs": {}})
        self.contract_error = ""
        self.rules_error = ""

    def _read(self, path, *, state, family, open_prefix, parse_prefix):
        result = self.read_json(path)
        if result.failure:
            if result.failure not in ("open", "parse"):
                raise ValueError("资源读取器未知失败类型")
            message = open_prefix + str(path) if result.failure == "open" else parse_prefix + result.error
            setattr(self, family + "_error", message)
            return None, self._outcome(False, family, state)
        if not isinstance(result.document, dict):
            raise TypeError("读取器必须返回QJsonDocument.object()字典")
        return result.document, None

    def _outcome(self, accepted, family, state):
        return LoadOutcome(accepted, getattr(self, family + "_error"), deepcopy(state))

    def load_contract(self, path) -> LoadOutcome:
        state = self.contract
        raw, failure = self._read(path, state=state, family="contract",
            open_prefix="打不开契约文件: ", parse_prefix="契约 JSON 解析失败: ")
        if failure is not None: return failure
        state.document = normalize_contract(raw)
        state.raw_document = deepcopy(raw)
        state.valid = bool(state.document["commonFields"] and state.document["specs"])
        if not state.valid: self.contract_error = "契约内容为空"
        return self._outcome(state.valid, "contract", state)

    def load_rules(self, path) -> LoadOutcome:
        state = self.rules
        raw, failure = self._read(path, state=state, family="rules",
            open_prefix="打不开规则文件: ", parse_prefix="规则 JSON 解析失败: ")
        if failure is not None: return failure
        state.document = normalize_rules(raw)
        state.raw_document = deepcopy(raw)
        state.valid = bool(state.document["specs"])
        if not state.valid: self.rules_error = "规则内容为空"
        return self._outcome(state.valid, "rules", state)

    def load_readable_contract(self, path) -> LoadOutcome:
        state = self.readable_contract
        raw, failure = self._read(path, state=state, family="contract",
            open_prefix="打不开 readable 契约: ", parse_prefix="readable 契约解析失败: ")
        if failure is not None: return failure
        header = _object(raw.get("header"))
        state.document = {**deepcopy(raw), "header": {**header,
            "addonVersionCode": _int64(header.get("addonVersionCode"))}, "specs": {}}
        state.raw_document = deepcopy(raw)
        for key, value in _items(raw.get("specs")):
            spec = _object(value)
            keys = [_string(x) for x in _array(spec.get("classicKeys"))]
            rows = [_int(x) for x in _array(spec.get("classicRows"))]
            selected = {_int(x) for x in _array(spec.get("presenceRows"))}
            presence = []
            for value in _array(spec.get("presenceFields")):
                value = _object(value)
                row = _int(value.get("row"), -1)
                if row in selected:
                    presence.append({**value, "row": row, "key": _string(value.get("key"))})
            if len(keys) != len(rows):
                self.contract_error = f"readable 契约 {key} 行表不一致"
                return self._outcome(False, "contract", state)
            state.document["specs"][key] = {**spec, "moduleName": _string(spec.get("moduleName")),
                "classicKeys": keys, "classicRows": rows, "height": _int(spec.get("height")),
                "presenceRows": sorted(selected), "presenceFields": presence}
        state.valid = bool(state.document["specs"])
        return self._outcome(state.valid, "contract", state)

    def load_readable_rules(self, path) -> LoadOutcome:
        state = self.readable_rules
        raw, failure = self._read(path, state=state, family="rules",
            open_prefix="打不开 readable 键表: ", parse_prefix="readable 键表解析失败: ")
        if failure is not None: return failure
        keys = readable_key_maps(raw)
        state.document = {**deepcopy(raw), "specs": {key: {"actions": [
            {"name": name, "key": binding} for name, binding in mapping.items()]}
            for key, mapping in keys.items()}}
        state.raw_document = deepcopy(raw)
        state.valid = bool(keys)
        return self._outcome(state.valid, "rules", state)

    def to_assets(self, directory: str | Path):
        """快照适配现有Assets；valid/错误须由宿主另行保留，不能视作全有效。"""
        from .assets import Assets
        return Assets(Path(directory), *(deepcopy(state.document) for state in
            (self.contract, self.readable_contract, self.rules, self.readable_rules)))
