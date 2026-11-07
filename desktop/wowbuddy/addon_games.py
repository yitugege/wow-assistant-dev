"""012730/011640 全量游戏安装快照；所有外部读取均显式注入。

不会默认构造 Win32 后端、打开注册表或扫描真实驱动器。运行状态刻意保留
原版按一个优选窗口的客户端目录名匹配全部安装根目录的行为。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import ntpath
from typing import Protocol

from .addon_install import PathProbe, clean_path, installed_record_key
from .addon_update import AddonGame
from .game_windows import WindowBackend, find_game_window


@dataclass(frozen=True)
class GameVariant:
    directory: str
    id: str
    label: str
    executable: str


# PE 指针表 1400D0AF0..1400D0B2F，每项四个 char*。
VARIANTS = (
    GameVariant("_classic_beta_", "classic_beta", "无限", "WowB.exe"),
    GameVariant("_cn_beta_", "cn_beta", "无限（国服）", "Wow.exe"),
)
ROOT_SUFFIXES = ("World of Warcraft", "Games/World of Warcraft",
                 "Blizzard/World of Warcraft")
SIGNATURE_NAMES = ("ActionKeyCheck.lua", "forever_spell_ids.lua", "PixelBar.lua")


class SnapshotSettings(Protocol):
    """SettingsStore 接口；测试也可注入只读内存实现。"""
    def _read(self, key: str, default: object, kind: str): ...


@dataclass(frozen=True)
class GameInstallation(AddonGame):
    """AddonGame 兼容投影，加上原生记录其余字段。"""
    id: str = ""
    game_path: str = ""
    addons_exists: bool = False

    @property
    def sort_rank(self) -> int:
        return (0 if self.running else 2) + (not self.installed_name)


def selected_executable(window_backend: WindowBackend) -> str:
    """0B7AF0→0B81B0：重新查询优选 HWND 的 PID/完整路径。"""
    hwnd = find_game_window(window_backend)
    if not hwnd:
        return ""
    pid = window_backend.window_pid(hwnd)
    return window_backend.process_path(pid) if pid else ""


def _parent(probe: PathProbe, executable: str) -> str:
    return clean_path(ntpath.dirname(probe.absolute_path(executable))) if executable else ""


def discover_game_roots(probe: PathProbe, window_backend: WindowBackend,
                        settings: SnapshotSettings) -> tuple[str, ...]:
    """011640：保存的根目录→当前优选客户端父目录→C..J 常见目录。

    保存列表不去重、不要求存在；自动补入时按大小写敏感 QStringList.contains。
    本函数对应原辅助入口，不单独检查 WOWBUDDY_NO_GAME_SCAN。
    """
    roots = [clean_path(p.strip()) for p in settings._read("game/roots", [], "strings")
             if p.strip()]
    current = _parent(probe, selected_executable(window_backend))
    if ntpath.basename(current).lower() in {v.directory for v in VARIANTS}:
        root = clean_path(ntpath.dirname(current))
        if root not in roots:
            roots.append(root)
    for drive in "CDEFGHIJ":
        drive_root = drive + ":/"
        if not probe.is_dir(drive_root):
            continue
        for suffix in ROOT_SUFFIXES:
            root = clean_path(drive_root + suffix)
            if probe.is_dir(root) and root not in roots:
                roots.append(root)
    return tuple(roots)


def scan_installed_name(probe: PathProbe, addons_path: str) -> str:
    """012730 内联 013350/014590：首个含三个签名路径的非隐藏子目录。

    child_dirs 应提供 QDir Dirs|NoDotAndDotDot 名称；默认排序 Name|IgnoreCase。
    QFile.exists 并不要求签名项是普通文件，也不检查内容或 TOC。
    """
    if not probe.is_dir(addons_path):
        return ""
    for name in sorted(probe.child_dirs(addons_path), key=str.lower):
        directory = clean_path(ntpath.join(addons_path, name))
        if probe.is_dir(directory) and all(
                probe.exists(clean_path(ntpath.join(directory, signature)))
                for signature in SIGNATURE_NAMES):
            return name
    return ""


def _sort_games(games: list[GameInstallation]) -> None:
    """00E730/00D430/00D930/00D7F0：保留 >32 项时原分区的同分交换。"""
    def rank(index):
        return games[index].sort_rank

    def swap(left, right):
        games[left], games[right] = games[right], games[left]

    def median(first, middle, last):
        if rank(middle) < rank(first):
            swap(middle, first)
        if rank(last) < rank(middle):
            swap(last, middle)
            if rank(middle) < rank(first):
                swap(middle, first)

    def partition(first, last):
        middle, final = (first + last) // 2, last - 1
        if final - first > 40:
            step = (last - first) // 8
            median(first, first + step, first + 2 * step)
            median(middle - step, middle, middle + step)
            median(final - 2 * step, final - step, final)
            median(first + step, middle, final - step)
        else:
            median(first, middle, final)
        pivot_first, pivot_last = middle, middle + 1
        while first < pivot_first and rank(pivot_first - 1) == rank(pivot_first):
            pivot_first -= 1
        while pivot_last < last and rank(pivot_last) == rank(pivot_first):
            pivot_last += 1
        greater_first, less_last = pivot_last, pivot_first
        while True:
            while greater_first < last:
                if rank(pivot_first) < rank(greater_first):
                    greater_first += 1
                    continue
                if rank(greater_first) < rank(pivot_first):
                    break
                if pivot_last != greater_first:
                    swap(pivot_last, greater_first)
                pivot_last += 1
                greater_first += 1
            while first < less_last:
                if rank(less_last - 1) < rank(pivot_first):
                    less_last -= 1
                    continue
                if rank(pivot_first) < rank(less_last - 1):
                    break
                pivot_first -= 1
                if pivot_first != less_last - 1:
                    swap(pivot_first, less_last - 1)
                less_last -= 1
            if less_last == first and greater_first == last:
                return pivot_first, pivot_last
            if less_last == first:
                if pivot_last != greater_first:
                    swap(pivot_first, pivot_last)
                pivot_last += 1
                swap(pivot_first, greater_first)
                pivot_first += 1
                greater_first += 1
            elif greater_first == last:
                less_last -= 1
                pivot_first -= 1
                if less_last != pivot_first:
                    swap(less_last, pivot_first)
                pivot_last -= 1
                swap(pivot_first, pivot_last)
            else:
                less_last -= 1
                swap(greater_first, less_last)
                greater_first += 1

    def sort(first, last, ideal):
        while last - first > 32:
            # 比较器只有四种 rank；每次排除一种，最多四层，堆排序分支不可达。
            if ideal < 1:
                raise AssertionError("原生四值比较器分区预算不应耗尽")
            low, high = partition(first, last)
            ideal = (ideal >> 1) + (ideal >> 2)
            if low - first < last - high:
                sort(first, low, ideal)
                first = high
            else:
                sort(high, last, ideal)
                last = low
        for index in range(first + 1, last):
            value, target = games[index], index
            while target > first and value.sort_rank < games[target - 1].sort_rank:
                games[target] = games[target - 1]
                target -= 1
            games[target] = value

    sort(0, len(games), len(games))


def build_game_snapshot(probe: PathProbe, window_backend: WindowBackend,
                        settings: SnapshotSettings,
                        environment: Mapping[str, str]) -> tuple[GameInstallation, ...]:
    """012730：显式调用才读注入依赖；无写入、删除、安装或进程操作。

    可注入 LocalAddonFiles()/CtypesWindowBackend()/SettingsStore，亦可全用 fake。
    原版两次窗口枚举之间可能变化：第一次决定 running，第二次补充 roots。
    """
    if "WOWBUDDY_NO_GAME_SCAN" in environment:
        return ()
    current = _parent(probe, selected_executable(window_backend))
    current_variant = ntpath.basename(current).lower()
    roots = discover_game_roots(probe, window_backend, settings)
    games, seen = [], set()
    for root in roots:
        for variant in VARIANTS:
            game = clean_path(probe.absolute_path(ntpath.join(root, variant.directory)))
            if not probe.is_dir(game) or not probe.exists(
                    clean_path(ntpath.join(game, variant.executable))):
                continue
            addons = clean_path(ntpath.join(game, "Interface", "AddOns"))
            key = addons.lower()
            if key in seen:
                continue
            seen.add(key)
            exists = probe.is_dir(addons)
            installed = settings._read(installed_record_key(addons), "", "string")
            if not installed:
                installed = scan_installed_name(probe, addons)
            games.append(GameInstallation(
                label=variant.label, addons_path=addons,
                running=current_variant == variant.directory, installed_name=installed,
                id=variant.id, game_path=game, addons_exists=exists))
    _sort_games(games)
    return tuple(games)
