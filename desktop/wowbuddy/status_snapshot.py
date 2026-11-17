"""助手实时状态快照（docs/design/20261115-assistant-mcp.md）。

开发版窗口每秒把状态汇总成字典写到 数据目录/status.json，供 MCP 服务读取。
本模块不导入 Qt；只描述已有对象，不参与决策。
"""
from __future__ import annotations

import dataclasses
from enum import Enum
import json
import os
from pathlib import Path

STATUS_FILE = 'status.json'
SCHEMA = 1

_CHARACTER_FIELDS = ('life', 'outdoors', 'faction', 'level', 'map_id', 'zone', 'x', 'y', 'elevation')


def write_json_atomic(path, data) -> None:
    """先写同目录临时文件再替换，读者不会看到半份内容。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), 'utf-8')
    os.replace(temporary, path)


def _is_name_field(key: str) -> bool:
    lowered = key.lower()
    return 'name' in lowered or 'guid' in lowered


def describe_candidate(candidate) -> dict | None:
    if candidate is None:
        return None
    return dict(label=candidate.label, key=candidate.key, action=candidate.action, reason=candidate.reason,
                tag=candidate.tag, stop=bool(candidate.stop))


def describe_decision(decision, selected) -> dict | None:
    """最近一帧决策的解释：帧状态、选中与全部候选、拦截标记、生效阈值、解码字段（去掉名字类字段）。"""
    if decision is None:
        return None
    frame = decision.frame
    thresholds = []
    for threshold in getattr(decision, 'thresholds', ()) or ():
        thresholds.append({key: value for key, value in vars(threshold).items()
                           if isinstance(value, (str, int, float, bool)) or value is None}
                          if hasattr(threshold, '__dict__') else str(threshold))
    return dict(
        frame=dict(ok=bool(frame.ok), status=frame.status, protocol=getattr(frame, 'protocol', None),
                   spec_id=getattr(frame, 'spec_id', None)),
        selected=describe_candidate(selected),
        candidates=[describe_candidate(item) for item in getattr(decision, 'candidates', ())],
        attack_blocked_by_range=bool(getattr(decision, 'attack_blocked_by_range', False)),
        attack_blocked_by_sight=bool(getattr(decision, 'attack_blocked_by_sight', False)),
        target_rejection=getattr(decision, 'target_rejection', None),
        recovery_ready=bool(getattr(decision, 'recovery_ready', False)),
        thresholds=thresholds,
        fields={key: value for key, value in dict(getattr(decision, 'fields', None) or {}).items()
                if not _is_name_field(key)},
    )


def _bind_decoders():
    """加载时绑定原解码函数：测试对 character_state.decode_* 的打桩不影响快照，快照也不消耗打桩的返回序列。"""
    from wowbuddy.engine import character_state as state
    return dict(session=state.decode_character_session, character=state.decode_character_state,
                navigation=state.decode_navigation_state, death=state.decode_death_state,
                quest_pin=state.decode_quest_turn_in_pin, quest_dialog=state.decode_quest_dialog,
                mob=state.decode_mob_state, vendor=state.decode_vendor_state, taxi=state.decode_taxi_state,
                target_rejection=state.decode_target_rejection, cast_feedback=state.decode_cast_feedback,
                level_progress=state.decode_level_progress)


_DECODERS = _bind_decoders()


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if dataclasses.is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in dataclasses.fields(value)
                if not _is_name_field(item.name)}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items() if not _is_name_field(str(key))}
    if isinstance(value, Enum):
        return value.value
    return str(value)


def describe_packets(image, frame) -> dict | None:
    """用最近一帧解插件发送的签名包；帧无效时返回 None，单个包解不出时为 None。"""
    if image is None or frame is None or not getattr(frame, 'ok', False):
        return None
    packets = {}
    for name, decode in _DECODERS.items():
        try:
            if name == 'session':
                value = decode(image, frame)
            elif name == 'level_progress':
                value = decode(image, frame, packets.get('session'))
            else:
                value = decode(image, frame)
        except Exception as error:
            value = {'error': f'{type(error).__name__}: {error}'}
        packets[name] = _plain(value)
    return packets


def describe_character(character, *, at: float) -> dict | None:
    """角色状态（不含名字）；at 为该读数的时间戳（秒），角色读数只在脱战时更新。"""
    if character is None:
        return None
    data = {name: getattr(character, name, None) for name in _CHARACTER_FIELDS}
    data['at'] = at
    return data


def describe_patrol(route, index) -> dict | None:
    if route is None:
        return None
    count = len(route.points)
    index = index or 0
    return dict(map_id=route.map_id, recorded=bool(getattr(route, 'recorded', False)),
                stops=count, index=index, stop=f'{min(index, count - 1) + 1 if count else 0}/{count}',
                path_points=len(getattr(route, 'path', ()) or route.points),
                points=[list(point) for point in route.points])


def build_status(*, now, version, running, monitoring, hwnd, status_text, unattended, phase, patrol,
                 character, life, decision, log_tail, steering, last_mark, control_allowed, packets=None, input_block=None, ghost=None,
                 walk_grid=None, patrol_scan=None) -> dict:
    return dict(schema=SCHEMA, updated_at=now, version=version, running=running, monitoring=monitoring,
                hwnd=hwnd, status_text=status_text, unattended=dict(enabled=bool(unattended), phase=phase),
                patrol=patrol, character=character, life=life, decision=decision, log_tail=list(log_tail),
                steering=steering, last_mark=last_mark, control_allowed=bool(control_allowed), packets=packets,
                input_block=input_block, ghost=ghost, walk_grid=walk_grid,
                patrol_scan=patrol_scan)


def stopped_status(*, now, version) -> dict:
    return dict(schema=SCHEMA, updated_at=now, version=version, running=False, monitoring=False)
