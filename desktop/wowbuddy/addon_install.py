"""插件安装计划：还原0135e0的改名、TOC与记录，默认不写文件。

执行器只写入全新插件目录，不删旧目录、不读写注册表、不访问网络。
目标选择017290、随机名0152b0、TOC017de0、安装记录0165c0/016c70。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
import hashlib
import ntpath
import os
from pathlib import Path
import re
import secrets
from typing import Protocol

from .packages import PackageError
from .native_addon_package import read_install_addon
from .qt_utf8 import decode_qt_utf8 as _decode_qt_utf8


ORIGINAL_TOC = "P07483180.toc"
NAME_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
GAME_VARIANTS = (("_classic_beta_", "WowB.exe"), ("_cn_beta_", "Wow.exe"))
SIGNATURE_FILES = frozenset(("actionkeycheck.lua", "forever_spell_ids.lua", "pixelbar.lua"))
QT_WHITESPACE = "\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def clean_path(path: str) -> str:
    """Windows路径的词法清理，返回Qt式正斜杠；不解析链接或访问磁盘。"""
    if not isinstance(path, str) or "\0" in path:
        raise ValueError("路径必须是无NUL字符串")
    if not path:
        return ""
    # 原程序直接使用QDir.cleanPath；ntpath会吞掉根目录以上的..，
    # 且UNC共享名和Windows长路径前缀的处理不同。
    from PySide6.QtCore import QDir
    return QDir.cleanPath(path)


def _join(root: str, name: str) -> str:
    return clean_path(ntpath.join(root, name))


class PathProbe(Protocol):
    def is_dir(self, path: str) -> bool: ...
    def exists(self, path: str) -> bool: ...
    def child_dirs(self, path: str) -> Iterable[str]: ...
    def absolute_path(self, path: str) -> str: ...


class LocalPathProbe:
    """仅只读文件系统探测；归一化函数也可以传入纯内存snapshot。"""
    def is_dir(self, path):
        return Path(path).is_dir()

    def exists(self, path):
        return Path(path).exists()

    def child_dirs(self, path):
        # Qt Dirs|NoDotAndDotDot 未包含Hidden；Windows隐藏属性也需排除。
        result = []
        try:
            for child in Path(path).iterdir():
                if child.is_dir() and (os.name == "nt" or not child.name.startswith(".")):
                    attrs = getattr(child.stat(), "st_file_attributes", 0)
                    if not attrs & 2:
                        result.append(child.name)
        except OSError:
            return ()
        return tuple(sorted(result, key=directory_name_key))

    def absolute_path(self, path):
        return clean_path(str(Path(path).absolute()))


def directory_name_key(name: str) -> bytes:
    """原QDir.entryList(...,Name=0)：区分大小写，按UTF16码元比较。"""
    return name.encode('utf-16-be', errors='surrogatepass')


def looks_like_game_root(path: str, probe: PathProbe) -> bool:
    """014910：已知版本目录+exe、唯一exe名或一层版本子目录。"""
    leaf = ntpath.basename(path).lower()
    for directory, executable in GAME_VARIANTS:
        if leaf == directory and probe.exists(_join(path, executable)):
            return True
    # 原生只有未与其它版本重复的exe名可在任意目录触发此分支。
    for _, executable in GAME_VARIANTS:
        if sum(executable.lower() == other.lower() for _, other in GAME_VARIANTS) == 1:
            if probe.exists(_join(path, executable)):
                return True
    for child in probe.child_dirs(path):
        for directory, executable in GAME_VARIANTS:
            if child.lower() == directory and probe.exists(_join(_join(path, child), executable)):
                return True
    return False


@dataclass(frozen=True)
class AddonTarget:
    status: str
    addons_path: str = ""
    game_root: str = ""
    needs_create: bool = False
    error: str = ""

    @property
    def ok(self):
        return self.status == "ok"


def normalize_addons_path(selected: str, *, probe: PathProbe | None = None) -> AddonTarget:
    """017290：解释用户选择的已有目录；不会创建AddOns。"""
    probe = probe or LocalPathProbe()
    path = clean_path(selected.strip(QT_WHITESPACE))
    if not path:
        return AddonTarget("empty_path", error="没有选择目录。")
    if not probe.is_dir(path):
        return AddonTarget("directory_missing", error=f"目录不存在：{path}")

    def result(addons, game=""):
        addons, game = clean_path(addons), clean_path(game)
        return AddonTarget("ok", addons, game, not probe.is_dir(addons))

    leaf = ntpath.basename(path).lower()
    if leaf == "addons":
        parent = clean_path(ntpath.dirname(path))
        game = ""
        if ntpath.basename(parent).lower() == "interface":
            candidate = probe.absolute_path(clean_path(ntpath.dirname(parent)))
            if looks_like_game_root(candidate, probe):
                game = candidate
        return result(path, game)
    if leaf == "interface":
        parent = probe.absolute_path(clean_path(ntpath.dirname(path)))
        game = parent if looks_like_game_root(parent, probe) else ""
        return result(_join(probe.absolute_path(path), "AddOns"), game)
    for directory, executable in GAME_VARIANTS:
        # 原生选中已知版本名时不检查exe是否存在。
        if leaf == directory:
            game = probe.absolute_path(path)
            return result(_join(game, "Interface/AddOns"), game)
        child = _join(probe.absolute_path(path), directory)
        if probe.is_dir(child) and probe.exists(_join(child, executable)):
            return result(_join(child, "Interface/AddOns"), child)
    if looks_like_game_root(path, probe):
        return result(_join(probe.absolute_path(path), "Interface/AddOns"), path)
    # 无已知游戏证据时，原版直接把所选已有目录作为目标。
    return result(path)


@dataclass(frozen=True)
class AddonName:
    name: str
    attempts: int
    fallback: bool


def generate_addon_name(*, random_u32: Callable[[], int] | None = None,
                        exists: Callable[[str], bool]) -> AddonName:
    """0152b0：8次uint32乘36取高位；64次冲突后wb+八位hex，不再查重。"""
    random_u32 = random_u32 or (lambda: secrets.randbits(32))

    def next_u32():
        value = random_u32()
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("随机源必须返回uint32")
        return value

    for attempt in range(1, 65):
        name = "".join(NAME_ALPHABET[(next_u32() * 36) >> 32] for _ in range(8))
        if not exists(name):
            return AddonName(name, attempt, False)
    return AddonName(f"wb{next_u32():08x}", 64, True)


def rewrite_toc(data: bytes, addon_name: str) -> bytes:
    """017de0：只替换原有Title/Notes，大小写敏感；不追加缺失行。"""
    if not re.fullmatch(r"[a-z0-9]{8}|wb[0-9a-f]{8}", addon_name):
        raise ValueError("不是原生随机目录名")
    text = _decode_qt_utf8(data)
    for key in ("Title", "Notes"):
        text = re.sub(r"(?m)^##\s*" + key + r"\s*:.*$",
                      lambda match: f"## {key}: {addon_name}", text, flags=re.ASCII)
    return text.encode("utf-8")


def installed_record_key(addons_path: str) -> str:
    """0165c0：cleanPath→toLower→UTF8→SHA1→前12个hex字符。"""
    from PySide6.QtCore import QLocale
    # C locale使用Qt默认大小写映射；Python会将词尾Σ转为ς，与原版不同。
    lowered = QLocale.c().toLower(clean_path(addons_path))
    digest = hashlib.sha1(lowered.encode("utf-8")).hexdigest()[:12]
    return "addon/installed/" + digest


@dataclass(frozen=True)
class SettingsRecord:
    organization: str
    application: str
    key: str
    value: str


def cleanup_candidates(addons_path: str, keep_name: str,
                       directories: Mapping[str, Iterable[str]]) -> tuple[str, ...]:
    """014d10/014590的只读候选判断，绝不执行删除。

directories为调用者提供的直接子目录→已存在相对路径snapshot。
"""
    if not addons_path.strip() or "addons" not in addons_path.lower():
        return ()
    return tuple(name for name in sorted(directories, key=directory_name_key)
                 if name != keep_name and SIGNATURE_FILES.issubset(
                     {clean_path(member).lower() for member in directories[name]}))


@dataclass(frozen=True)
class PlannedFile:
    source_name: str
    relative_path: str
    content: bytes = field(repr=False)
    toc_rewritten: bool = False

    @property
    def sha256(self):
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class AddonInstallPlan:
    status: str
    addons_path: str = ""
    addon_name: str = ""
    files: tuple[PlannedFile, ...] = ()
    record: SettingsRecord | None = None
    cleanup_candidates: tuple[str, ...] = ()
    name_choice: AddonName | None = None
    error: str = ""
    cleanup_evaluated: bool = False

    @property
    def ok(self):
        return self.status == "ready"


def plan_install(package: bytes, target: AddonTarget | str, *,
                 existing_entries: Iterable[str],
                 existing_directories: Mapping[str, Iterable[str]] | None = None,
                 random_u32: Callable[[], int] | None = None,
                 absolute_path: Callable[[str], str] | None = None) -> AddonInstallPlan:
    """生成成员→AddOns相对路径+内容的计划，不创建目录/写文件/读写注册表。

str target表示已经选定的AddOns目标；用户选择目录请先normalize_addons_path。
existing_*由调用者提供快照；没有这些快照就不能断言无名称冲突或无需清理。
"""
    if isinstance(target, AddonTarget):
        if not target.ok:
            return AddonInstallPlan("invalid_target", error=target.error)
        target = target.addons_path
    target = clean_path(target)
    if not target:
        return AddonInstallPlan("invalid_target", error="安装目标为空")
    try:
        members = read_install_addon(package)
    except PackageError as exc:
        return AddonInstallPlan("package_error", error=str(exc))
    entries = {entry.lower() for entry in existing_entries}
    entries.update(name.lower() for name in (existing_directories or {}))
    choice = generate_addon_name(random_u32=random_u32, exists=lambda name: name.lower() in entries)
    root = clean_path((absolute_path or LocalPathProbe().absolute_path)(target))
    planned = []
    toc_count = 0
    for member in members:
        is_toc = member.name.lower() == ORIGINAL_TOC.lower()
        relative = choice.name + "/" + (choice.name + ".toc" if is_toc else member.name.replace("\\", "/"))
        # 原生在改名后做indexOf("..")，包括非穿越含双点名称也拒绝。
        if ".." in relative:
            return AddonInstallPlan("invalid_member_path", root, choice.name, tuple(planned),
                                    error=f"插件包内有非法路径：{member.name}", name_choice=choice)
        content = rewrite_toc(member.data, choice.name) if is_toc else member.data
        toc_count += int(is_toc)
        planned.append(PlannedFile(member.name, relative, content, is_toc))
    if toc_count != 1:
        return AddonInstallPlan("toc_count_error", root, choice.name, tuple(planned),
                                name_choice=choice,
                                error=f"插件包里 {ORIGINAL_TOC}.toc 的数量异常（{toc_count} 个）")
    record = SettingsRecord("wowbuddy.cn", "WOW战斗助手", installed_record_key(target), choice.name)
    return AddonInstallPlan("ready", root, choice.name, tuple(planned), record,
                            cleanup_candidates(target, choice.name, existing_directories or {}), choice,
                            cleanup_evaluated=existing_directories is not None)


@dataclass(frozen=True)
class InstallWriteResult:
    status: str
    written: tuple[str, ...] = ()
    pending_record: SettingsRecord | None = None
    pending_cleanup: tuple[str, ...] = ()
    error: str = ""

    @property
    def ok(self):
        return self.status == "written"


def execute_install_plan(plan: AddonInstallPlan) -> InstallWriteResult:
    """按原mkpath及WriteOnly|Truncate写入选定插件目录；不删除、不执行QSettings记录。

失败保留已经写入的文件并报告written；不通过递归删除模拟回滚。
"""
    if not plan.ok and plan.status not in ("toc_count_error", "invalid_member_path"):
        return InstallWriteResult("invalid_plan", error=plan.error or plan.status)
    root = Path(plan.addons_path).resolve()
    directory = root / plan.addon_name
    # 再校验公开dataclass，避免调用者手工构造绝对路径或越界计划。
    if not re.fullmatch(r"[a-z0-9]{8}|wb[0-9a-f]{8}", plan.addon_name):
        return InstallWriteResult("invalid_plan", error="插件目录名非法")
    from PySide6.QtCore import QDir, QFileInfo, QFile, QIODevice
    destinations = []
    for entry in plan.files:
        try:
            raw = entry.relative_path.replace("\\", "/")
            if ".." in raw or ntpath.isabs(raw) or ntpath.splitdrive(raw)[0]:
                raise PackageError(f"不安全的成员路径：{entry.relative_path!r}")
            raw_parts = raw.split("/")
            if len(raw_parts)<2 or raw_parts[0]!=plan.addon_name:
                raise PackageError(f"不安全的成员路径：{entry.relative_path!r}")
            # 规范化仅供边界检查；Qt原始路径仍用于父目录创建和错误文字。
            normalized = "/".join(part for part in raw_parts if part not in ("", "."))
            # 文件名有效性由原生 QFile.open 决定；此处只校验目录边界。
        except PackageError as exc:
            return InstallWriteResult("unsafe_destination", error=str(exc))
        parts = normalized.split("/")
        if (parts[0] != plan.addon_name or any(p in ("", ".", "..") for p in parts)
                or ntpath.isabs(normalized) or ntpath.splitdrive(normalized)[0]
                or any(c in normalized for c in '\x00:')):
            return InstallWriteResult("unsafe_destination", error=entry.relative_path)
        destination = (root / normalized).resolve()
        if not destination.is_relative_to(directory.resolve()):
            return InstallWriteResult("unsafe_destination", error=entry.relative_path)
        native_path = QDir(clean_path(str(directory))).filePath(raw[len(plan.addon_name)+1:])
        parent = Path(QFileInfo(native_path).absolutePath())
        if not parent.resolve().is_relative_to(root):
            return InstallWriteResult("unsafe_destination", error=entry.relative_path)
        destinations.append((entry, destination, parent, native_path))
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return InstallWriteResult("root_create_failed", error=f"建不了目录：{plan.addons_path}")
    try:
        directory.mkdir(exist_ok=True)
    except FileExistsError:
        return InstallWriteResult("addon_dir_exists", error=f"建不了插件目录：{clean_path(str(directory))}")
    except OSError:
        return InstallWriteResult("addon_dir_create_failed", error=f"建不了插件目录：{clean_path(str(directory))}")
    written = []
    try:
        for entry, destination, parent, native_path in destinations:
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                # 原0135e0忽略父目录mkpath返回值，随后由QFile.open报告目标文件失败。
                pass
            if not destination.resolve().is_relative_to(directory.resolve()):
                return InstallWriteResult("unsafe_destination", tuple(written), error=str(destination))
            stream = QFile(native_path)
            if not stream.open(QIODevice.OpenModeFlag.WriteOnly | QIODevice.OpenModeFlag.Truncate):
                return InstallWriteResult("write_failed", tuple(written),
                                          error=f"写不了文件：{native_path}")
            try:
                # 原0135e0忽略write结果，close也不检查错误；Qt保留原Windows路径语义。
                stream.write(entry.content)
            finally:
                stream.close()
            written.append(entry.relative_path)
    except OSError as exc:
        return InstallWriteResult("write_failed", tuple(written), error=str(exc))
    # 原0135e0遇到非法成员时保留前面的写入；TOC数量在循环后检查。
    if plan.status in ("toc_count_error", "invalid_member_path"):
        return InstallWriteResult(plan.status, tuple(written), error=plan.error)
    return InstallWriteResult("written", tuple(written), plan.record, plan.cleanup_candidates)
