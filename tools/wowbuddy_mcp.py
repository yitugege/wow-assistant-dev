"""助手 MCP 服务（docs/design/20261115-assistant-mcp.md）。

stdio 方式运行，由 Claude Code 按项目 .mcp.json 启动：
    .venv/Scripts/python.exe tools/wowbuddy_mcp.py --data-dir .local

读：status.json（助手每秒写）、logs/monitor_*.log、addon-install.log、diagnostics/*.zip。
写：只往 control/inbox 投请求（停止监控、关闭无人托管、导出诊断、保存当前帧、打标记），
由助手在主线程执行；不开网络端口，不发键，不改设置。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))

from wowbuddy import control_mailbox as mailbox  # noqa: E402
from wowbuddy.status_snapshot import STATUS_FILE  # noqa: E402

STALE_SECONDS = 5.0
REPLY_TIMEOUT = 5.0
_STAMP = re.compile(r'^\[(\d\d:\d\d:\d\d(?:\.\d+)?)\]')
_NOISE = re.compile(r'^\[[\d:.]+\] #\d+ |\(rgb=\d+,\d+,\d+\)')
_STUCK = re.compile(r'受阻|卡住|卡在|停滞|无法到达|无法前进')
_STEERING = re.compile(r'^\[([\d:.]+)\] 转向统计 · 第 (\d+)/(\d+) 段：用时 ([\d.]+) 秒，最大偏离 ([\d.]+) 码，'
                       r'平均偏离 ([\d.]+) 码，原地转向 (\d+) 次，转向修正 (\d+) 次，受阻 (\d+) 次')
EVENTS = ('phase_change', 'death', 'stuck', 'monitor_stopped', 'log')
_MAX_MEMBER_BYTES = 256 * 1024


class AssistantTools:
    def __init__(self, data_dir, *, clock=time.time, sleep=time.sleep):
        self.root = Path(data_dir).resolve()
        self.clock, self.sleep = clock, sleep

    # ---- 状态 ----
    def _read_status(self):
        try:
            return json.loads((self.root / STATUS_FILE).read_text('utf-8'))
        except (OSError, ValueError):
            return None

    def get_status(self) -> dict:
        status = self._read_status()
        if status is None:
            return dict(available=False, message='没有 status.json：助手未运行，或版本尚不支持状态快照。')
        age = self.clock() - float(status.get('updated_at') or 0)
        stale = bool(status.get('running')) and age > STALE_SECONDS
        return dict(status, available=True, age_s=round(age, 1), stale=stale or not status.get('running'))

    def get_patrol(self) -> dict:
        status = self._read_status() or {}
        return status.get('patrol') or dict(message='当前没有启用循环打怪路线。')

    def explain_decision(self) -> dict:
        status = self.get_status()
        if not status.get('available'):
            return status
        return dict(decision=status.get('decision'), age_s=status['age_s'], stale=status['stale'])

    # ---- 日志 ----
    def _logs(self):
        folder = self.root / 'logs'
        if not folder.is_dir():
            return []
        return sorted(folder.glob('monitor_*.log'), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)

    def list_logs(self) -> list:
        return [dict(name=path.name, size=path.stat().st_size,
                     modified=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(path.stat().st_mtime)))
                for path in self._logs()]

    @staticmethod
    def _lines(path):
        try:
            return path.read_text('utf-8', errors='replace').splitlines()
        except OSError:
            return []

    def tail_log(self, lines: int = 200, contains: str | None = None, skip_noise: bool = True) -> dict:
        logs = self._logs()
        if not logs:
            return dict(file=None, lines=[])
        selected = self._lines(logs[0])
        if skip_noise:
            selected = [line for line in selected if not _NOISE.search(line)]
            collapsed = []
            for line in selected:
                if collapsed and collapsed[-1][15:] == line[15:]:
                    continue
                collapsed.append(line)
            selected = collapsed
        if contains:
            selected = [line for line in selected if contains in line]
        return dict(file=logs[0].name, lines=selected[-max(1, int(lines)):])

    def search_log(self, pattern: str, since: str | None = None, limit: int = 200, files: int = 3) -> dict:
        expression = re.compile(pattern)
        found = []
        for path in reversed(self._logs()[:max(1, files)]):
            for line in self._lines(path):
                stamp = _STAMP.match(line)
                if since and (not stamp or stamp.group(1) < since):
                    continue
                if expression.search(line):
                    found.append(line if path == self._logs()[0] else f'{path.name}: {line}')
        return dict(lines=found[-max(1, int(limit)):], total=len(found))

    def get_steering_stats(self, limit: int = 50) -> list:
        stats = []
        for line in self.tail_log(lines=100000, skip_noise=False)['lines']:
            match = _STEERING.match(line)
            if match:
                stamp, index, count, seconds, worst, mean, turns, pulses, stalls = match.groups()
                stats.append(dict(time=stamp, segment=int(index), count=int(count), seconds=float(seconds),
                                  max_deviation=float(worst), mean_deviation=float(mean), stop_turns=int(turns),
                                  steer_pulses=int(pulses), stalls=int(stalls)))
        return stats[-max(1, int(limit)):]

    def get_addon_install_log(self, lines: int = 50) -> list:
        return self._lines(self.root / 'addon-install.log')[-max(1, int(lines)):]

    # ---- 诊断包 ----
    def list_diagnostics(self) -> list:
        folder = self.root / 'diagnostics'
        if not folder.is_dir():
            return []
        return [dict(name=path.name, size=path.stat().st_size)
                for path in sorted(folder.glob('*.zip'), key=lambda path: path.stat().st_mtime, reverse=True)]

    def _diagnostic(self, name: str) -> Path:
        if (not name or PureWindowsPath(name).name != name or PurePosixPath(name).name != name
                or name in ('.', '..') or not name.endswith('.zip')):
            raise ValueError('只能读取 diagnostics 目录下的诊断包文件名。')
        path = (self.root / 'diagnostics' / name).resolve()
        if path.parent != (self.root / 'diagnostics').resolve() or not path.is_file():
            raise ValueError(f'没有这个诊断包：{name}')
        return path

    def read_diagnostics(self, name: str, member: str | None = None) -> dict:
        with zipfile.ZipFile(self._diagnostic(name)) as archive:
            members = archive.namelist()
            member = member or ('manifest.json' if 'manifest.json' in members else None)
            content = None
            if member is not None:
                if member not in members:
                    raise ValueError(f'诊断包中没有：{member}')
                raw = archive.read(member)[:_MAX_MEMBER_BYTES]
                content = raw.decode('utf-8', errors='replace')
        return dict(members=members, member=member, content=content)

    # ---- 等事件 ----
    def wait_for(self, event: str, timeout_s: float = 60, pattern: str | None = None) -> dict:
        if event not in EVENTS:
            raise ValueError(f'事件只能是：{"、".join(EVENTS)}')
        if event == 'log' and not pattern:
            raise ValueError('event=log 需要 pattern。')
        expression = re.compile(pattern) if event == 'log' else _STUCK
        timeout_s = max(1.0, min(600.0, float(timeout_s)))
        start = self.get_status()
        phase = (start.get('unattended') or {}).get('phase')
        logs = self._logs()
        log, offset = (logs[0], logs[0].stat().st_size) if logs else (None, 0)
        deadline = self.clock() + timeout_s
        while True:
            self.sleep(1.0)
            status = self.get_status()
            hit, lines = None, []
            if event in ('stuck', 'log'):
                logs = self._logs()
                if logs and logs[0] != log:
                    log, offset = logs[0], 0
                if log is not None:
                    with log.open('rb') as handle:
                        handle.seek(offset)
                        fresh = handle.read()
                    complete = fresh.rfind(b'\n') + 1
                    offset += complete
                    lines = [line for line in fresh[:complete].decode('utf-8', errors='replace').splitlines()
                             if expression.search(line)]
                    hit = bool(lines)
            elif event == 'phase_change':
                hit = (status.get('unattended') or {}).get('phase') != phase
            elif event == 'death':
                hit = status.get('life') in ('dead', 'ghost')
            elif event == 'monitor_stopped':
                hit = not status.get('available') or status.get('stale') or not status.get('monitoring')
            if hit:
                return dict(happened=True, event=event, status=status, lines=lines,
                            recent=self.tail_log(lines=30)['lines'])
            if self.clock() >= deadline:
                return dict(happened=False, event=event, status=status, recent=self.tail_log(lines=30)['lines'])

    # ---- 请求（经信箱由助手执行）----
    def request(self, action: str, **args) -> dict:
        status = self.get_status()
        if not status.get('available') or not status.get('running') or status.get('stale'):
            return dict(status='not_running', ok=False, message='助手未运行或状态已过期，请求未发送。')
        if action in mailbox.CONTROL_ACTIONS and not status.get('control_allowed'):
            return dict(status='not_allowed', ok=False,
                        message='助手未允许 MCP 控制：请在助手日志卡片下勾选“允许 MCP 控制”。')
        request_id = mailbox.submit(self.root, action, args, now=self.clock())
        deadline = self.clock() + REPLY_TIMEOUT
        while self.clock() < deadline:
            self.sleep(0.2)
            reply = mailbox.read_reply(self.root, request_id)
            if reply is not None:
                return reply
        return dict(status='no_response', ok=False, id=request_id, message='助手 5 秒内未响应。')


def build_server(tools: AssistantTools):
    from mcp.server.mcpserver import MCPServer

    server = MCPServer('wowbuddy', instructions=(
        'WoW 助手（WowBuddyDev）的日志与实时状态。只读为主；停止监控、关闭无人托管、导出诊断需用户在助手上'
        '勾选“允许 MCP 控制”。不提供开始监控、发键或改设置。日志可能含本机路径。'))

    @server.tool(description='助手实时状态：监控、无人托管阶段、循环路线进度、角色坐标、最近决策与日志。stale=true 表示助手未运行或卡住。')
    def get_status() -> dict:
        return tools.get_status()

    @server.tool(description='最新监控日志末尾若干行；contains 按关键字过滤；skip_noise 去掉逐帧字段读数并合并重复行。')
    def tail_log(lines: int = 200, contains: str | None = None, skip_noise: bool = True) -> dict:
        return tools.tail_log(lines, contains, skip_noise)

    @server.tool(description='在最近几个监控日志中按正则查找；since 为 "HH:MM:SS"，只看该时间之后的行。')
    def search_log(pattern: str, since: str | None = None, limit: int = 200, files: int = 3) -> dict:
        return tools.search_log(pattern, since, limit, files)

    @server.tool(description='列出监控日志文件（新到旧）。')
    def list_logs() -> list:
        return tools.list_logs()

    @server.tool(description='当前循环打怪路线：停留点、是否录制、当前进度。')
    def get_patrol() -> dict:
        return tools.get_patrol()

    @server.tool(description='最新日志中的“转向统计”逐段结果：用时、最大/平均偏离、原地转向、转向修正、受阻次数。')
    def get_steering_stats(limit: int = 50) -> list:
        return tools.get_steering_stats(limit)

    @server.tool(description='插件安装记录 addon-install.log 末尾。')
    def get_addon_install_log(lines: int = 50) -> list:
        return tools.get_addon_install_log(lines)

    @server.tool(description='列出已导出的诊断包（新到旧）。')
    def list_diagnostics() -> list:
        return tools.list_diagnostics()

    @server.tool(description='读取诊断包：返回成员列表与指定成员的文本（默认 manifest.json）。')
    def read_diagnostics(name: str, member: str | None = None) -> dict:
        return tools.read_diagnostics(name, member)

    @server.tool(description='解释最近一帧决策：选中候选、全部候选及停发原因、距离/视线/目标拒绝拦截、生效阈值、解码字段。')
    def explain_decision() -> dict:
        return tools.explain_decision()

    @server.tool(description='等待事件后返回当时状态与日志：phase_change、death、stuck、monitor_stopped、log（需 pattern）。timeout_s 最长 600。')
    def wait_for(event: str, timeout_s: float = 60, pattern: str | None = None) -> dict:
        return tools.wait_for(event, timeout_s, pattern)

    @server.tool(description='让助手保存当前帧：只裁像素条区域，存到 数据目录/frames（PNG + 解码字段 JSON），用于写复现测试。')
    def capture_frame(note: str = '') -> dict:
        return tools.request('capture_frame', note=note)

    @server.tool(description='在助手运行日志中插入一行带时间的标记，便于事后对照。')
    def mark(text: str) -> dict:
        return tools.request('mark', text=text)

    @server.tool(description='停止监控（等同点“停止”，会松开移动键）。需助手允许 MCP 控制。')
    def stop_monitoring() -> dict:
        return tools.request('stop_monitoring')

    @server.tool(description='关闭无人托管，常规监控继续。需助手允许 MCP 控制。')
    def stop_unattended() -> dict:
        return tools.request('stop_unattended')

    @server.tool(description='导出诊断包到 数据目录/diagnostics（不弹出目录），返回包路径。需助手允许 MCP 控制。')
    def export_diagnostics() -> dict:
        return tools.request('export_diagnostics')

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--data-dir', default=str(ROOT / '.local'))
    options = parser.parse_args(argv)
    data_dir = Path(options.data_dir)
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    build_server(AssistantTools(data_dir)).run('stdio')


if __name__ == '__main__':
    main()
