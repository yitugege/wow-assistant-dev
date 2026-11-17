"""MCP 与助手之间的文件信箱（docs/design/20261115-assistant-mcp.md）。

MCP 服务把请求写到 数据目录/control/inbox/<编号>.json，助手每秒取走、在主线程执行，
结果写到 control/outbox/<编号>.json。不开网络端口；只认白名单动作，过期请求丢弃。
本模块不导入 Qt，MCP 服务与助手共用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import time
import uuid

CONTROL_ACTIONS = frozenset({'stop_monitoring', 'stop_unattended', 'export_diagnostics'})
ASSIST_ACTIONS = frozenset({'capture_frame', 'mark'})
EXPIRE_SECONDS = 30.0

ACTION_LABELS = {'stop_monitoring': '停止监控', 'stop_unattended': '关闭无人托管',
                 'export_diagnostics': '导出诊断', 'capture_frame': '保存当前帧', 'mark': '打标记'}


@dataclass(frozen=True)
class Request:
    id: str
    action: str
    args: dict = field(default_factory=dict)


def _box(data_dir, name) -> Path:
    return Path(data_dir) / 'control' / name


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), 'utf-8')
    os.replace(temporary, path)


def submit(data_dir, action: str, args: dict | None = None, *, now: float | None = None) -> str:
    now = time.time() if now is None else now
    request_id = f'{int(now * 1000)}-{uuid.uuid4().hex[:8]}'
    _write(_box(data_dir, 'inbox') / f'{request_id}.json',
           dict(id=request_id, action=action, args=dict(args or {}), created_at=now))
    return request_id


def _answer(data_dir, request_id, status, ok, message, **extra) -> None:
    _write(_box(data_dir, 'outbox') / f'{request_id}.json',
           dict(id=request_id, status=status, ok=ok, message=message, **extra))


def reply(data_dir, request_id: str, ok: bool, message: str, **extra) -> None:
    _answer(data_dir, request_id, 'done', bool(ok), message, **extra)


def take(data_dir, *, now: float, allow_control: bool) -> list[Request]:
    """取走全部请求：返回可执行的请求（按提交顺序）；过期、未知、未允许的直接写结果。"""
    inbox = _box(data_dir, 'inbox')
    if not inbox.is_dir():
        return []
    accepted = []
    for path in sorted(inbox.glob('*.json')):
        try:
            data = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            data = None
        try:
            path.unlink()
        except OSError:
            continue
        if not isinstance(data, dict) or not isinstance(data.get('id'), str) or data['id'] != path.stem:
            continue
        request_id, action = data['id'], data.get('action')
        created = data.get('created_at')
        args = data.get('args') if isinstance(data.get('args'), dict) else {}
        if not isinstance(created, (int, float)) or now - created > EXPIRE_SECONDS:
            _answer(data_dir, request_id, 'expired', False, '请求已过期，未执行。')
        elif action not in CONTROL_ACTIONS | ASSIST_ACTIONS:
            _answer(data_dir, request_id, 'rejected', False, f'不支持的动作：{action}')
        elif action in CONTROL_ACTIONS and not allow_control:
            _answer(data_dir, request_id, 'not_allowed', False, '助手未允许 MCP 控制（界面上的“允许 MCP 控制”未勾选）。')
        else:
            accepted.append(Request(request_id, action, args))
    return accepted


def read_reply(data_dir, request_id: str) -> dict | None:
    """读取并删除结果；尚无结果时返回 None。"""
    path = _box(data_dir, 'outbox') / f'{request_id}.json'
    try:
        data = json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        return None
    try:
        path.unlink()
    except OSError:
        pass
    return data
