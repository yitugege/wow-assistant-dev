"""插件管理动作；依赖显式注入，不在导入/构造时读写游戏或打开对话框。"""
from __future__ import annotations

from dataclasses import dataclass
import ntpath
import os
from pathlib import Path
from typing import Callable, Protocol

from .addon_install import (GAME_VARIANTS, SIGNATURE_FILES, QT_WHITESPACE, LocalPathProbe, clean_path,
    cleanup_candidates, execute_install_plan, installed_record_key,
    normalize_addons_path, plan_install)
from .settings import SettingsStore
from .addon_rank_sort import sort_candidates


MISSING_PACKAGE = "插件包未随软件打包（addon.bin 缺失），无法安装。"
SELECT_DIRECTORY = "选择游戏目录，或点「自动检测」。"
BROWSE_TITLE = "选择游戏目录（World of Warcraft / 客户端目录 / Interface / AddOns 都行）"
DETECT_FAILED = "没找到游戏目录。请先启动一次游戏再点「自动检测」，或点「选择目录…」手动指到 World of Warcraft（任一层都行）。"
DETECT_FAILED_LOG = "插件安装| 自动检测失败：没找到无限客户端（_classic_beta_\\WowB.exe 或 _cn_beta_\\Wow.exe）"
CLEAR_HISTORY = "clear_history"


class UnsupportedAddonAction(NotImplementedError):
    pass


class AddonDialogs(Protocol):
    def choose_directory(self, title: str, initial: str) -> str: ...
    def choose_recent(self, paths: tuple[str, ...], position=None) -> str | None: ...
    def home_path(self) -> str: ...


@dataclass(frozen=True)
class CleanupPlan:
    root: str
    names: tuple[str, ...]
    resolved_root: str = ""
    link_targets: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()


@dataclass(frozen=True)
class CleanupResult:
    deleted: int = 0
    notes: str = ""


def _reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def _remove_plugin_directory(path: Path) -> None:
    """原014d10使用QDir递归删除，包含只读文件的重试语义。"""
    from PySide6.QtCore import QDir
    if not QDir(str(path)).removeRecursively():
        raise OSError("QDir.removeRecursively失败")


def _cleanup_link_targets(target: Path) -> tuple[tuple[str, str], ...]:
    """记录原Qt可能跟随的链接目标；循环目录不进入递归删除。"""
    links = {}
    for parent in target.parents:
        if parent.exists() and _reparse(parent):
            links[str(parent)] = str(parent.resolve())
    pending = [(target, frozenset())]
    while pending:
        path, ancestors = pending.pop()
        if not path.exists():
            continue
        resolved = path.resolve()
        if _reparse(path):
            links[str(path)] = str(resolved)
        if not path.is_dir():
            continue
        if resolved in ancestors:
            raise ValueError("清理目录包含循环重解析点")
        try:
            children = tuple(path.iterdir())
        except OSError:
            # 原Qt会在实际删除时处理不可枚举目录，不能中断其它候选。
            continue
        pending.extend((child, ancestors | {resolved}) for child in children)
    return tuple(sorted(links.items()))


class LocalAddonFiles(LocalPathProbe):
    """明确调用才访问文件系统；清理仅执行本实例发出的计划。"""
    def __init__(self):
        self._cleanup_plans: dict[int, CleanupPlan] = {}

    def entries(self, path: str) -> tuple[str, ...]:
        return tuple(p.name for p in Path(path).iterdir()) if self.is_dir(path) else ()

    def directories(self, path: str) -> dict[str, tuple[str, ...]]:
        result = {}
        for name in self.child_dirs(path):
            directory = Path(path) / name
            try:
                result[name] = tuple(p.name for p in directory.iterdir())
            except OSError:
                # 原014590直接判断三个特征路径存在，不要求能枚举目录。
                # 单个目录被占用不能让其它旧插件的清理整体中断。
                result[name] = tuple(s for s in SIGNATURE_FILES if (directory / s).exists())
        return result

    def installed_name(self, path: str) -> str:
        # 013350/014590：仅根据三个文件名识别；不读 Lua 内容。
        for name, files in self.directories(path).items():
            if SIGNATURE_FILES.issubset({f.lower() for f in files}):
                return name
        return ""

    def write_install(self, plan):
        return execute_install_plan(plan)

    def plan_cleanup(self, path: str, keep: str = "", *, names=None) -> CleanupPlan:
        root = Path(path).absolute()
        if "addons" not in path.lower():
            raise ValueError(f"跳过清理：目标不是安全的 AddOns 目录（{path}）")
        resolved = root.resolve()
        candidates = cleanup_candidates(path, keep, self.directories(path))
        if names is not None:
            candidates = tuple(n for n in candidates if n in names)
        links = tuple((name, _cleanup_link_targets(root / name)) for name in candidates)
        plan = CleanupPlan(str(root), candidates, str(resolved), links)
        self._cleanup_plans[id(plan)] = plan
        return plan

    def execute_cleanup(self, plan: CleanupPlan, *, selected_path: str) -> CleanupResult:
        # 公开 dataclass 不赋予删除权限；拒绝伪造、重放、换目标。
        issued = self._cleanup_plans.pop(id(plan), None)
        if issued is not plan:
            raise ValueError("清理计划不是本实例生成或已使用")
        selected = Path(selected_path).absolute()
        root = Path(plan.root)
        if ("addons" not in selected_path.lower() or selected != root
                or str(selected.resolve()) != plan.resolved_root):
            raise ValueError("清理目标已经变化")
        deleted, notes = 0, []
        for name in plan.names:
            target = root / name
            try:
                if (not name or ntpath.basename(name) != name or name in (".", "..")
                        or target.parent != root
                        or not target.is_dir()):
                    raise ValueError("清理目录超出计划边界")
                files = {p.name.lower(): p for p in target.iterdir()}
                if not all(s in files and files[s].exists()
                           for s in SIGNATURE_FILES):
                    raise ValueError("清理目录特征文件已经变化")
                if _cleanup_link_targets(target) != dict(plan.link_targets)[name]:
                    raise ValueError("清理目录重解析点目标已经变化")
                # 最后核对选中根与记录的解析目标，再交给原同类Qt函数删除。
                if str(selected.resolve()) != plan.resolved_root or target.parent != root:
                    raise ValueError("清理目标已经变化")
                _remove_plugin_directory(target)
                deleted += 1
                notes.append(f"  已删除旧插件目录：{clean_path(str(target))}\n")
            except (OSError, ValueError) as exc:
                notes.append(f"  ! 删除失败（可能被游戏占用）：{clean_path(str(target))}\n")
                # 安全拒绝原因是重建新增信息，避免把拒绝伪报为游戏占用。
                if isinstance(exc, ValueError):
                    notes.append(f"  安全检查：{exc}\n")
        return CleanupResult(deleted, "".join(notes))


def validate_destination(path: str, probe) -> tuple[str, bool]:
    """018860：已有目录或可创建的后代；不预判写权限。"""
    path = clean_path(path.strip(QT_WHITESPACE))
    if not path:
        return "还没有选择目录。", False
    if probe.exists(path):
        return ("", False) if probe.is_dir(path) else (f"这不是一个目录：{path}", False)
    parent = clean_path(ntpath.dirname(probe.absolute_path(path)))
    if not probe.is_dir(parent):
        ancestor = clean_path(ntpath.dirname(parent))
        # QDir.cdUp只有紧邻上一级目录存在时才成功，不会跳过缺失层级。
        if ancestor == parent or not probe.is_dir(ancestor):
            return f"上层的目录都不存在：{path}", False
    return "", True


@dataclass(frozen=True)
class DetectedAddon:
    addons_path: str
    from_running_game: bool = False


class AddonDetector:
    """0180a0/012730/011640；运行进程路径及 game/roots 都由调用方提供。"""
    def __init__(self, probe, *, running_executable: Callable[[], str],
                 saved_roots: Callable[[], tuple[str, ...]], installed_name: Callable[[str], str],
                 environment=None):
        self.probe, self.running_executable = probe, running_executable
        self.saved_roots, self.installed_name = saved_roots, installed_name
        self.environment = os.environ if environment is None else environment

    def detect(self) -> DetectedAddon | None:
        if "WOWBUDDY_NO_GAME_SCAN" in self.environment:
            return None
        executable = self.running_executable()
        return self._running_match(executable) or self._candidate_match(executable)

    def startup_fallback(self) -> DetectedAddon | None:
        # 082920后备分支无条件先0180A0再012730，最后优先运行客户端结果。
        if "WOWBUDDY_NO_GAME_SCAN" in self.environment:
            return None
        executable = self.running_executable()
        running = self._running_match(executable)
        candidate = self._candidate_match(executable)
        return running or candidate

    def _running_match(self, executable):
        current = clean_path(ntpath.dirname(executable)) if executable else ""
        parent = current
        for _ in range(3):
            if not parent:
                break
            if ntpath.basename(parent).lower() in {v for v, _ in GAME_VARIANTS}:
                return DetectedAddon(clean_path(parent + "/Interface/AddOns"), True)
            parent = clean_path(ntpath.dirname(parent))
        return None

    def _candidate_match(self, executable):
        current = clean_path(ntpath.dirname(executable)) if executable else ""
        roots = [clean_path(p.strip()) for p in self.saved_roots() if p.strip()]
        if ntpath.basename(current).lower() in {v for v, _ in GAME_VARIANTS}:
            parent = clean_path(ntpath.dirname(current))
            if parent not in roots:
                roots.append(parent)
        for drive in "CDEFGHIJ":
            if not self.probe.is_dir(drive + ":/"):
                continue
            for suffix in ("World of Warcraft", "Games/World of Warcraft", "Blizzard/World of Warcraft"):
                path = drive + ":/" + suffix
                if self.probe.is_dir(path) and path not in roots:
                    roots.append(path)
        candidates, seen = [], set()
        for root in roots:
            for variant, exe in GAME_VARIANTS:
                game = clean_path(root + "/" + variant)
                if not self.probe.is_dir(game) or not self.probe.exists(game + "/" + exe):
                    continue
                addons = clean_path(game + "/Interface/AddOns")
                if addons.lower() in seen:
                    continue
                seen.add(addons.lower())
                rank = (0 if ntpath.basename(current).lower() == variant else 2)
                rank += not bool(self.installed_name(addons))
                candidates.append((rank, addons))
        return DetectedAddon(sort_candidates(candidates)[0][1]) if candidates else None


class AddonActions:
    def __init__(self, settings: SettingsStore, files, dialogs: AddonDialogs, *,
                 package_provider: Callable[[], bytes], detector=None,
                 on_path=lambda value: None, on_status=lambda value: None,
                 on_log=lambda value: None, process_events=lambda: None,
                 random_u32=None):
        self.settings, self.files, self.dialogs = settings, files, dialogs
        self.package_provider, self.detector = package_provider, detector
        self.on_path, self.on_status, self.on_log = on_path, on_status, on_log
        self.process_events, self.random_u32 = process_events, random_u32
        self.path = self.status = ""
        self.path_valid = False

    def set_path(self, text: str):
        """用于 textChanged；不保存、不刷新，避免改写用户正在输入的文本。"""
        self.path = text

    def initialize_path(self, saved_path: str):
        """082920：初始化发生在路径信号连接之前，后备填充不保存历史。"""
        self.path = saved_path.strip(QT_WHITESPACE)
        self.on_path(self.path)
        if not self.path:
            self.detect()
        if not self._path():
            found = self.detector.startup_fallback()
            if found:
                self.path = found.addons_path
                self.on_path(self.path)
        return self.refresh_status()

    def text_changed(self, text: str):
        """08fdc0：输入时校验和刷新，不保存最近目录。"""
        self.path, self.path_valid = text, False
        if not text.strip():
            return self._status(SELECT_DIRECTORY)
        error, _ = validate_destination(text, self.files)
        if error:
            return self._status(error)
        self.path_valid = True
        return self.refresh_status()

    def finish_edit(self):
        """08ff10：editingFinished 仅保存有效的非空路径。"""
        path = self._path()
        if path and not validate_destination(path, self.files)[0]:
            self.settings.save_addon_dir(path)

    def _path(self):
        return clean_path(self.path.strip())

    def _status(self, text):
        self.status = text
        self.on_status(text)
        return text

    def _select(self, path):
        self.path = path
        self.on_path(path)
        self.settings.save_addon_dir(path)
        self.refresh_status()

    def installed_name(self, path):
        stored = self.settings._read(installed_record_key(path), "", "string")
        return stored or self.files.installed_name(path)

    def refresh_status(self):
        try:
            valid_package = self.package_provider()[:9] == b"WBADDON1\n"
        except OSError:
            valid_package = False
        if not valid_package:
            return self._status(MISSING_PACKAGE)
        path = self._path()
        if not path:
            return self._status(SELECT_DIRECTORY)
        error, create = validate_destination(path, self.files)
        if error:
            return self._status(error)
        name = self.installed_name(path)
        return self._status((f"已装：{name}" if name else "还没装（本目录）")
                            + ("　·　AddOns 目录将自动创建" if create else ""))

    def detect(self):
        if self.detector is None:
            raise UnsupportedAddonAction("未注入运行客户端/游戏根目录检测器")
        found = self.detector.detect()
        if found:
            self._select(found.addons_path)
            if found.from_running_game:
                self.on_log(f"插件安装| 自动检测：从运行中的游戏推断到 {found.addons_path}")
        else:
            self._status(DETECT_FAILED)
            self.on_log(DETECT_FAILED_LOG)
        return found

    def browse(self):
        selected = self.dialogs.choose_directory(BROWSE_TITLE, self._path() or self.dialogs.home_path())
        if not selected:
            return None
        target = normalize_addons_path(selected, probe=self.files)
        if not target.ok:
            self._status(target.error)
            return target
        self._select(target.addons_path)
        if not target.game_root:
            self._status(f"已使用所选目录作为安装位置：\n{target.addons_path}\n（这层目录里没认出无限客户端的可执行文件，如果不是游戏的 AddOns 目录，请改选游戏根目录。）")
        return target

    def recent(self, position=None):
        paths = tuple(self.settings._read("addon/history", [], "strings"))
        if not paths:
            return None
        chosen = self.dialogs.choose_recent(paths, position)
        if chosen == CLEAR_HISTORY:
            self.settings.clear_addon_history()
        elif chosen is not None:
            if chosen not in paths:
                raise ValueError("最近目录选择不是菜单项")
            self._select(chosen)
        return chosen

    def _cleanup(self, path, keep="", *, names=None):
        try:
            plan = self.files.plan_cleanup(path, keep, names=names)
            return self.files.execute_cleanup(plan, selected_path=path)
        except (OSError, ValueError) as exc:
            return CleanupResult(notes=f"  {exc}\n")

    def install(self):
        path = self._path()
        if not path:
            self._status("还没有选择安装目录，点「自动检测」或「选择目录…」。")
            return None
        error, _ = validate_destination(path, self.files)
        if error:
            self._status(error)
            return None
        self._status(f"正在安装到 {path} …")
        self.process_events()
        try:
            plan = plan_install(self.package_provider(), path, existing_entries=self.files.entries(path),
                existing_directories=self.files.directories(path), random_u32=self.random_u32,
                absolute_path=self.files.absolute_path)
            result = self.files.write_install(plan)
            if not result.ok:
                message = f"安装失败：{result.error}\n"
            else:
                if result.pending_record is not None:
                    self.settings.qsettings.setValue(result.pending_record.key, result.pending_record.value)
                cleanup = self._cleanup(path, plan.addon_name, names=result.pending_cleanup)
                message = (f"已装到 {path}\n随机目录名：{plan.addon_name}\n"
                    f"  已写入 {len(result.written)} 个文件 → {clean_path(plan.addons_path + '/' + plan.addon_name)}\n"
                    + cleanup.notes + f"  清理旧目录：{cleanup.deleted} 个\n")
                self.settings.save_addon_dir(path)
        except OSError as exc:
            result = None
            message = f"安装失败：{exc}\n"
        self.on_log("插件安装| " + message)
        self._status(message.strip())
        return result

    def cleanup(self):
        path = self._path()
        if not path:
            self._status("还没有选择目录，无法清理。")
            return None
        result = self._cleanup(path)
        message = f"清理 {path}：删除 {result.deleted} 个旧插件目录。\n{result.notes}"
        self.on_log("插件清理| " + message)
        self._status(message.strip())
        self.refresh_status()
        return result


class QtAddonDialogs:
    def __init__(self, parent, recent_anchor):
        self.parent, self.recent_anchor = parent, recent_anchor

    def home_path(self):
        from PySide6.QtCore import QDir
        return QDir.homePath()

    def choose_directory(self, title, initial):
        from PySide6.QtWidgets import QFileDialog
        return QFileDialog.getExistingDirectory(self.parent, title, initial,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)

    def choose_recent(self, paths, position=None):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self.parent)
        actions = {menu.addAction(path): path for path in paths}
        menu.addSeparator()
        clear = menu.addAction("清空最近记录")
        point = position if position is not None else QPoint(0, self.recent_anchor.height())
        chosen = menu.exec(self.recent_anchor.mapToGlobal(point))
        return CLEAR_HISTORY if chosen is clear else actions.get(chosen)
