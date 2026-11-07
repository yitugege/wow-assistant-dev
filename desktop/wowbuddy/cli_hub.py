"""060ab0 循环库命令报告；默认离线，仅 --hub-fetch 显式创建网络客户端。"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
from typing import Callable

from .hub_sync import HubSynchronizer, LocalFileBackend, cache_path
from .native_cli import NativeCliOptions
from .rotation_selection import HubState, consume_update


FETCH_TIMEOUT_MS = 20_000
REPORT_NAME = "_hub.txt"
HEADER = "== 循环库本地缓存 / 自动更新 =="


@dataclass(frozen=True)
class FetchWait:
    notifications: int
    timed_out: bool
    cleanup: Callable[[], None] | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class CliHubResult:
    exit_code: int
    report_path: Path
    report_text: str
    report_written: bool
    hub: HubState
    status: str
    fetch_wait: FetchWait | None = None
    report_error: str = ""


class CliHubSynchronizer(HubSynchronizer):
    """保留命令入口类型；错误文案现由共用同步器在通知之前生成。"""


def _describe(hub: HubState) -> list[str]:
    return [f"  · 套数 {len(hub.profiles)}", f"  · 快照 {hub.generated_at}",
            "  · 来源 " + ("本地缓存" if hub.from_cache else "在线")]


def run_hub_command(options: NativeCliOptions, *, synchronizer: HubSynchronizer,
                    exists: Callable[[str], bool], fetch,
                    write_report: Callable[[Path, bytes], bool]) -> CliHubResult:
    """注入式执行；fetch(sync, explicit_url, timeout_ms)->FetchWait。

    报告只记录原生实际字段。timeout和通知数量作为结果元数据，不增造报告行。
    清理在报告/最终状态快照之后，避免abort信号污染原生超时报告。
    """
    if options.command != "hub_selftest":
        raise ValueError("只接受已选中的 hub_selftest 命令")
    sync = synchronizer
    path = lambda: cache_path(sync.environment, sync.application_dir, sync.files)
    lines = [HEADER, "缓存路径 " + path(), "缓存存在 " + ("是" if exists(path()) else "否")]
    cached = sync.load_cache()
    lines.append("[载入缓存] " + ("成功" if cached.accepted else "无缓存"))
    lines.extend(_describe(sync.hub))
    changed, sync.hub = consume_update(sync.hub)
    lines.append("  · 内容变化 " + ("是" if changed else "否"))
    waited = None
    try:
        if options.hub_fetch:
            if fetch is None:
                raise ValueError("--hub-fetch 要求显式拉取后端")
            waited = fetch(sync, sync.environment.get("WOWBUDDY_HUB_URL", ""), FETCH_TIMEOUT_MS)
            lines.append("[联网拉取] " + sync.status)
            lines.extend(_describe(sync.hub))
            changed, sync.hub = consume_update(sync.hub)
            lines.append("  · 内容变化 " + ("是" if changed else "否"))
        final_path = path()
        payload = None
        if exists(final_path):
            try:
                payload = sync.files.read_bytes(final_path)
            except OSError:
                pass
        lines.append((f"[缓存文件] {len(payload)} 字节 · md5 {hashlib.md5(payload).hexdigest()}"
                      if payload is not None else "[缓存文件] 不存在"))
        code = int(not sync.hub.profiles)
        lines.append("判定 " + ("FAIL（没有规则可用）" if code else "PASS（有可用规则）"))
        report = "\n".join(lines) + "\n"
        destination = Path(sync.application_dir) / REPORT_NAME
        error = ""
        try:
            written = bool(write_report(destination, report.encode("utf-8")))
        except OSError as exc:
            written, error = False, str(exc)
        return CliHubResult(code, destination, report, written, sync.hub, sync.status, waited, error)
    finally:
        if waited is not None and waited.cleanup is not None:
            waited.cleanup()


def fetch_with_qt(synchronizer: HubSynchronizer, explicit_url: str, timeout_ms: int = FETCH_TIMEOUT_MS,
                  *, manager=None) -> FetchWait:
    """05fcc0：changed计数≥2才结束；第1个来自begin_request，20秒局部循环。

    须已有QCoreApplication；只创建网络客户端，不启动主窗或游戏后端。
    不把超时伪装成网络失败回包；调用方写完报告后再执行返回的cleanup。
    """
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
    from .qt_network import QtHubClient
    if QCoreApplication.instance() is None:
        raise RuntimeError("Qt拉取要求宿主先创建QCoreApplication/QApplication")
    loop, timer = QEventLoop(), QTimer()
    timer.setSingleShot(True)
    count, timed_out = 0, False
    previous = synchronizer.on_changed
    def changed(hub, status):
        nonlocal count
        count += 1
        result = previous(hub, status) if previous is not None else None
        if count >= 2:
            loop.quit()
        return result
    def expired():
        nonlocal timed_out
        timed_out = True
        loop.quit()
    timer.timeout.connect(expired)
    client = QtHubClient(synchronizer, manager=manager)
    synchronizer.on_changed = changed
    try:
        timer.start(timeout_ms)
        client.refresh(explicit_url)
        if count < 2:
            loop.exec()
    except BaseException:
        client.close()
        client.deleteLater()
        raise
    finally:
        timer.stop()
        synchronizer.on_changed = previous
    closed = False
    def close():
        nonlocal closed
        if not closed:
            closed = True
            client.close()
            client.deleteLater()
    return FetchWait(count, timed_out, close)


def run_local_hub_command(options: NativeCliOptions, *, application_dir: str | Path,
                          environment=None, files=None, exists=None,
                          fetch=None, write_report=None) -> CliHubResult:
    """宿主入口；无fetch标志时不会导入/创建QtHubClient或访问URL。

    environment不传时读取进程环境；可注入本机HTTP地址和临时WOWBUDDY_HOME。
    report始终放application_dir，缓存遵循hub_sync的HOME目录规则。
    """
    if options.command != "hub_selftest":
        raise ValueError("只接受已选中的 hub_selftest 命令")
    sync = CliHubSynchronizer(files if files is not None else LocalFileBackend(),
        application_dir=str(application_dir), environment=dict(os.environ if environment is None else environment))
    if write_report is None:
        from .cli_install import write_local_report
        write_report = write_local_report
    return run_hub_command(options, synchronizer=sync,
        exists=exists if exists is not None else lambda path: Path(path).exists(),
        fetch=fetch if fetch is not None else fetch_with_qt, write_report=write_report)
