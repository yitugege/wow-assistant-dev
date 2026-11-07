"""原生更新文件替换与重启交接；必须明确提供已校验下载及测试程序范围。

原版直接用 QFile/MoveFileExW/QProcess，不生成或执行脚本。
构造后端不访问文件；只有显式 plan/execute 才读取或修改指定测试文件。
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ntpath
import os
from pathlib import Path
import re
import sys
from typing import Callable, Protocol

from .updater import VerifiedDownload, part_file_path


class HandoffSafetyError(ValueError):
    pass


@dataclass(frozen=True)
class TestProgramScope:
    """调用方明确授权的测试目录和唯一 EXE，不能仅给磁盘根或任意目标列表。"""
    directory: str
    executable: str


@dataclass(frozen=True)
class PathState:
    canonical: str
    exists: bool
    is_file: bool
    is_dir: bool
    has_reparse: bool = False
    links: int = 1


class HandoffProbe(Protocol):
    def inspect(self, path: str) -> PathState: ...
    def read_chunks(self, path: str): ...


class HandoffOperations(HandoffProbe, Protocol):
    def remove(self, path: str) -> bool: ...
    def rename(self, source: str, target: str) -> bool: ...
    def move_file_ex(self, source: str, target: str, flags: int) -> bool: ...
    def start_detached(self, program: str, arguments: tuple[str, ...], cwd: str) -> bool: ...


class LocalHandoffProbe:
    """只读探针，逐层检查 Windows reparse 属性与符号链接。"""
    def inspect(self, path):
        value = Path(path)
        reparse = False
        for parent in (value, *value.parents):
            try:
                stat = parent.lstat()
            except FileNotFoundError:
                continue
            reparse |= parent.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)
        exists = value.exists()
        return PathState(str(value.resolve()), exists, value.is_file(), value.is_dir(), reparse,
                         value.stat().st_nlink if exists else 1)

    def read_chunks(self, path):
        with open(path, "rb") as stream:
            while chunk := stream.read(0x100000):
                yield chunk


def _absolute(path: str) -> str:
    if not isinstance(path, str) or not path or any(ord(c) < 32 for c in path):
        raise HandoffSafetyError("路径必须是非空且无控制字符的字符串")
    path = path.replace("/", "\\")
    drive, tail = ntpath.splitdrive(path)
    if (not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith("\\")
            or ":" in tail or any(c in tail for c in '<>"|?*')
            or any(p in (".", "..") or p.endswith((".", " ")) for p in tail.split("\\") if p)):
        raise HandoffSafetyError("仅支持无穿越、ADS、设备或 UNC 前缀的绝对本地 Windows 路径")
    return ntpath.normpath(path)


def _same(left, right):
    return ntpath.normcase(_absolute(left)) == ntpath.normcase(_absolute(right))


def _paths(scope: TestProgramScope, verified: VerifiedDownload, probe: HandoffProbe,
           *, require_files=True):
    root, target = _absolute(scope.directory), _absolute(scope.executable)
    if root == ntpath.dirname(root) or not _same(ntpath.dirname(target), root):
        raise HandoffSafetyError("测试 EXE 必须是指定非磁盘根目录下的直接文件")
    if ntpath.splitext(target)[1].lower() != ".exe" or not _same(target, verified.target_path):
        raise HandoffSafetyError("更新目标不是本次明确授权的测试 EXE")
    part, old = _absolute(part_file_path(target)), target + ".old"
    if not _same(part, verified.part_path):
        raise HandoffSafetyError("part 路径必须是测试 EXE 同目录的 completeBaseName.update.part")
    states = {}
    for path in (root, target, part, old):
        state = probe.inspect(path)
        if state.has_reparse or not _same(state.canonical, path):
            raise HandoffSafetyError("更新路径包含重解析点或最终路径变化：" + path)
        if path == root:
            if not state.is_dir:
                raise HandoffSafetyError("测试程序目录不存在")
        elif state.exists and (not state.is_file or state.links != 1):
            raise HandoffSafetyError("更新路径不是唯一普通文件：" + path)
        states[path] = state
    if require_files and not all(states[p].is_file for p in (target, part)):
        raise HandoffSafetyError("测试 EXE 或已下载 part 不存在")
    return root, target, part, old, states


def _fingerprint(probe, path):
    digest, size = hashlib.sha256(), 0
    for chunk in probe.read_chunks(path):
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def restart_arguments(application_arguments) -> tuple[str, ...]:
    """0b6630：移除argv[0]，两个前缀及一个精确标记，大小写敏感。"""
    args = tuple(application_arguments)
    if not all(isinstance(arg, str) and "\0" not in arg for arg in args):
        raise HandoffSafetyError("启动参数必须是无 NUL 的字符串列表")
    return tuple(arg for arg in args[1:] if not arg.startswith(("--check-update", "--update-now"))
                 and arg != "--no-update")


@dataclass(frozen=True)
class HandoffPlan:
    verified: VerifiedDownload
    scope: TestProgramScope
    directory: str
    target_path: str
    part_path: str
    backup_path: str
    arguments: tuple[str, ...]
    source_arguments: tuple[str, ...]
    part_sha256: str
    target_sha256: str
    backup_sha256: str | None
    scripts: tuple = ()  # 本链没有脚本；非空计划拒绝执行。


def plan_handoff(verified: VerifiedDownload, *, scope: TestProgramScope,
                 probe: HandoffProbe, application_arguments=()) -> HandoffPlan:
    if not isinstance(verified, VerifiedDownload) or not verified.info.has_update:
        raise HandoffSafetyError("必须提供有更高有效版本的 VerifiedDownload")
    root, target, part, old, states = _paths(scope, verified, probe)
    size, digest = _fingerprint(probe, part)
    if size != verified.actual_size or (verified.info.size > 0 and size != verified.info.size):
        raise HandoffSafetyError("part 大小与已校验下载记录不符")
    for expected in (verified.actual_sha256, verified.info.sha256):
        if expected and digest.lower() != expected.lower():
            raise HandoffSafetyError("part 摘要与已校验下载记录不符")
    args = tuple(application_arguments)
    return HandoffPlan(verified, scope, root, target, part, old, restart_arguments(args), args,
        digest, _fingerprint(probe, target)[1],
        _fingerprint(probe, old)[1] if states[old].exists else None)


@dataclass(frozen=True)
class HandoffResult:
    phase: str
    text: str
    rename_attempts: int = 0
    move_attempts: int = 0
    rollback_attempted: bool = False
    rollback_succeeded: bool | None = None
    restart_started: bool = False
    exit_scheduled: bool = False


def execute_handoff(plan: HandoffPlan, *, scope: TestProgramScope, backend: HandoffOperations,
                    sleep_ms: Callable[[int], None], process_events: Callable[[], None],
                    schedule_exit: Callable[[int, Callable], None], quit_callback: Callable,
                    on_status=lambda text: None, on_log=lambda text: None,
                    restart=True, schedule_restart_exit=True,
                    on_replaced=lambda text: None) -> HandoffResult:
    """只调用显式注入的动作；重验计划后按原版两分支重试。

状态/日志 callback 不应抛异常。schedule_exit 只安排 quit_callback，不能同步退出。
"""
    if scope != plan.scope:
        raise HandoffSafetyError("交接范围与计划不一致")
    current = plan_handoff(plan.verified, scope=scope, probe=backend,
                           application_arguments=plan.source_arguments)
    if current != plan:
        raise HandoffSafetyError("交接计划或文件自计划生成后已改变")
    target, part, old = plan.target_path, plan.part_path, plan.backup_path

    def guard():
        return _paths(scope, plan.verified, backend, require_files=False)[4]

    def remove(path, expected_digest=None):
        states = guard()
        if states[path].exists:
            if expected_digest is None or _fingerprint(backend, path)[1] != expected_digest:
                raise HandoffSafetyError("拒绝删除内容已变化的文件：" + path)
        try:
            return backend.remove(path)
        except OSError:
            return False

    def rename(source, destination):
        states = guard()
        if states[source].exists and _fingerprint(backend, source)[1] != plan.target_sha256:
            raise HandoffSafetyError("拒绝改名内容已变化的文件：" + source)
        try:
            return backend.rename(source, destination)
        except OSError:
            return False

    def move():
        states = guard()
        if _fingerprint(backend, part) != (plan.verified.actual_size, plan.part_sha256):
            raise HandoffSafetyError("替换前 part 已变化")
        if states[target].exists and _fingerprint(backend, target)[1] != plan.target_sha256:
            raise HandoffSafetyError("替换前目标已变化")
        try:
            return backend.move_file_ex(part, target, 9)  # REPLACE_EXISTING|WRITE_THROUGH
        except OSError:
            return False

    def pause():
        sleep_ms(250)
        process_events()

    on_status("正在替换程序文件…")
    remove(old, plan.backup_sha256)
    renamed = False
    renames = moves = 0
    for _ in range(5):
        renames += 1
        # No overwriting rename; Qt QFile::rename semantics are required.
        if rename(target, old):
            renamed = True
            break
        pause()  # 原版最后一次失败也等待并processEvents。
    moved = False
    for _ in range(5 if renamed else 1):
        moves += 1
        if move():
            moved = True
            break
        if renamed:
            pause()
    if not moved:
        rolled_back = rename(old, target) if renamed else None
        reason = (f"无法写入目标文件（可能被占用或没有权限）：{target}" if renamed
                  else f"目标文件被占用或所在目录不可写：{target}")
        remove(part, plan.part_sha256)
        text = "替换失败：" + reason
        on_status(text)
        on_log("自动更新未完成：" + text)
        return HandoffResult("replacement_failed", text, renames, moves, renamed, rolled_back)
    # Native ignores .old deletion failure. Digest guard prevents deleting an unrelated file.
    remove(old, plan.target_sha256 if renamed else plan.backup_sha256)
    guard()
    if _fingerprint(backend, target) != (plan.verified.actual_size, plan.part_sha256):
        raise HandoffSafetyError("启动前目标不等于已校验安装包")
    success = f"已更新到 v{plan.verified.info.version}"
    on_replaced(success)
    if not restart:
        return HandoffResult("replacement_complete", success, renames, moves)
    on_log("自动更新完成：" + success + "，正在重启…")
    try:
        started = backend.start_detached(target, plan.arguments, plan.directory)
    except OSError:
        started = False
    if started:
        text = success + "，正在重启…"
        on_status(text)
        if schedule_restart_exit:
            schedule_exit(300, quit_callback)
        return HandoffResult("restart_started", text, renames, moves,
                             restart_started=True, exit_scheduled=schedule_restart_exit)
    text = success + "，重启失败，请手动重新打开程序"
    on_status(text)
    on_log("自动更新：重启失败，请手动打开程序")
    return HandoffResult("restart_failed", text, renames, moves)


class QtWin32HandoffBackend(LocalHandoffProbe):
    """真实通道仅暴露高层 execute；构造不导入Qt、不加载DLL、不读写文件。

qfile/move_file_ex/qprocess 允许测试注入。真实使用需要 Windows+PySide6。
不会通过shell、脚本或命令字符串启动。对调用者只开放已校验输入的执行入口。
"""
    def __init__(self, scope: TestProgramScope, *, qfile=None, move_file_ex=None,
                 qprocess=None, sleep_ms=None, process_events=None, schedule_exit=None):
        self.scope = scope
        self._qfile, self._move, self._qprocess = qfile, move_file_ex, qprocess
        self._sleep, self._events, self._schedule = sleep_ms, process_events, schedule_exit
        self._executing = False

    def execute(self, verified: VerifiedDownload, *, application_arguments=(), quit_callback,
                on_status=lambda text: None, on_log=lambda text: None,
                restart=True, schedule_restart_exit=True, on_replaced=lambda text: None):
        if self._executing:
            raise HandoffSafetyError("更新交接正在执行，不能从 processEvents 重入")
        self._executing = True
        try:
            return self._execute(verified, application_arguments=application_arguments,
                quit_callback=quit_callback, on_status=on_status, on_log=on_log,
                restart=restart, schedule_restart_exit=schedule_restart_exit, on_replaced=on_replaced)
        finally:
            self._executing = False

    def _execute(self, verified, *, application_arguments, quit_callback, on_status, on_log,
                 restart, schedule_restart_exit, on_replaced):
        plan = plan_handoff(verified, scope=self.scope, probe=self,
                            application_arguments=application_arguments)
        from PySide6.QtCore import QFile, QProcess, QThread, QCoreApplication, QTimer
        qfile, qprocess = self._qfile or QFile, self._qprocess or QProcess
        move_api = self._move
        if move_api is None:
            if os.name != "nt":
                raise NotImplementedError("MoveFileExW 仅支持 Windows")
            import ctypes
            from ctypes import wintypes
            move_api = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
            move_api.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
            move_api.restype = wintypes.BOOL

        class Operations(LocalHandoffProbe):
            # Kept inside verified+scope entry; no unguarded public mutation API.
            def remove(self, path):
                return bool(qfile.remove(path))
            def rename(self, source, target):
                return bool(qfile.rename(source, target))
            def move_file_ex(self, source, target, flags):
                return bool(move_api(source, target, flags))
            def start_detached(self, program, arguments, cwd):
                if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
                    # 单文件重建版必须重新释放新版资源；继承旧 bootloader 环境会
                    # 出现新版脚本读取旧版 bundle 的混合运行。只改子进程环境。
                    from PySide6.QtCore import QProcessEnvironment
                    child = qprocess()
                    environment = QProcessEnvironment.systemEnvironment()
                    environment.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
                    child.setProcessEnvironment(environment)
                    child.setProgram(program)
                    child.setArguments(list(arguments))
                    child.setWorkingDirectory(cwd)
                    result = child.startDetached()
                else:
                    result = qprocess.startDetached(program, list(arguments), cwd)
                return bool(result[0] if isinstance(result, tuple) else result)

        return execute_handoff(plan, scope=self.scope, backend=Operations(),
            sleep_ms=self._sleep or QThread.msleep,
            process_events=self._events or QCoreApplication.processEvents,
            schedule_exit=self._schedule or QTimer.singleShot, quit_callback=quit_callback,
            on_status=on_status, on_log=on_log, restart=restart,
            schedule_restart_exit=schedule_restart_exit, on_replaced=on_replaced)
