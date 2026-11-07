"""0b2f90旧解包清理的只读快照与纯计划；没有删除执行器。"""
from __future__ import annotations

from dataclasses import dataclass


APPLICATION_DIRECTORY = "WOW战斗助手"
NAME_FILTER = "app-*"
DIRECTORY_FILTER_FLAGS = 0x6001
SORT_FLAGS = 9
DEFAULT_BUDGET_MS = 1500


@dataclass(frozen=True)
class CleanupCandidate:
    name: str
    absolute_path: str
    is_symlink: bool = False


@dataclass(frozen=True)
class CleanupSnapshot:
    """entries须是Qt entryInfoList过滤/排序后的直接子目录快照。

    此输入不授予任何删除权限；尤其原生未排除链接，不能直接执行此计划。
    """
    application_directory: str
    current_name: str
    parent_reached: bool
    parent_name: str = ""
    parent_directory: str = ""
    entries: tuple[CleanupCandidate, ...] = ()


@dataclass(frozen=True)
class CleanupPlan:
    application_directory: str
    parent_directory: str
    current_name: str
    candidates: tuple[CleanupCandidate, ...]
    skipped_current: tuple[CleanupCandidate, ...]
    budget_ms: int
    disabled_reason: str = ""

    def cursor(self):
        return CleanupCursor(self)


def snapshot_qt_cleanup(application_directory: str) -> CleanupSnapshot:
    """只读QDir。原函数不检查LOCALAPPDATA、HOME、版本号或PE签名。"""
    from PySide6.QtCore import QDir
    current = QDir(str(application_directory))
    name = current.dirName()
    current_path = current.absolutePath()
    if not name.startswith("app-"):
        return CleanupSnapshot(current_path, name, False)
    parent = QDir(current)
    if not parent.cdUp():
        return CleanupSnapshot(current_path, name, False)
    parent_name, parent_path = parent.dirName(), parent.absolutePath()
    entries = ()
    if parent_name == APPLICATION_DIRECTORY:
        infos = parent.entryInfoList([NAME_FILTER], QDir.Filter(DIRECTORY_FILTER_FLAGS), QDir.SortFlag(SORT_FLAGS))
        entries = tuple(CleanupCandidate(item.fileName(), item.absoluteFilePath(), item.isSymLink()) for item in infos)
    return CleanupSnapshot(current_path, name, True, parent_name, parent_path, entries)


def plan_old_unpack_cleanup(snapshot: CleanupSnapshot, *, budget_ms: int = DEFAULT_BUDGET_MS) -> CleanupPlan:
    """纯结构计划；仅跳当前名字，不按mtime新旧版本/数量再过滤。"""
    if type(budget_ms) is not int or not -(2**31) <= budget_ms < 2**31:
        raise ValueError("原生预算参数必须是int32毫秒")
    reason = ("current_name_not_app_prefix" if not snapshot.current_name.startswith("app-") else
              "parent_unavailable" if not snapshot.parent_reached else
              "parent_name_mismatch" if snapshot.parent_name != APPLICATION_DIRECTORY else "")
    candidates = tuple(item for item in snapshot.entries if item.name != snapshot.current_name) if not reason else ()
    skipped = tuple(item for item in snapshot.entries if item.name == snapshot.current_name) if not reason else ()
    return CleanupPlan(snapshot.application_directory, snapshot.parent_directory, snapshot.current_name,
                       candidates, skipped, budget_ms, reason)


class CleanupCursor:
    """按模拟反馈推进原for循环，不计时、不读盘、不删除。

    宿主传入“枚举完成后启动计时器”的elapsed毫秒；一次next只提出一项。
    必须finish_attempt显式提供结果，无法预先假定成功以截断后续候选。
    """
    def __init__(self, plan: CleanupPlan):
        self.plan = plan
        self.successes = 0
        self.attempted_paths = []
        self.pending = None
        self.stop_reason = plan.disabled_reason
        self._index = 0

    def next_candidate(self, elapsed_ms: int) -> CleanupCandidate | None:
        if self.pending is not None:
            raise RuntimeError("上一候选尚未提供模拟结果")
        if self.stop_reason: return None
        if self._index >= len(self.plan.candidates):
            self.stop_reason = "exhausted"
            return None
        # 0b2f90：成功计数>0才检查时间，不是尝试计数>0。
        if self.successes > 0 and elapsed_ms >= self.plan.budget_ms:
            self.stop_reason = "budget_reached_after_success"
            return None
        self.pending = self.plan.candidates[self._index]
        self._index += 1
        return self.pending

    def finish_attempt(self, success: bool):
        if self.pending is None: raise RuntimeError("没有待反馈候选")
        if type(success) is not bool: raise TypeError("必须明确提供模拟removeRecursively的bool结果")
        self.attempted_paths.append(self.pending.absolute_path)
        self.successes += int(success)
        self.pending = None

    @property
    def startup_log_text(self) -> str | None:
        # 05f7f0固定1.5秒文案，即使独立调用方传入其他预算也不篡改原文字。
        return (f"已清理旧解包目录 {self.successes} 个（每次启动限 1.5 秒，剩余下次继续）"
                if self.successes > 0 else None)
