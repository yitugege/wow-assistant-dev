"""插件重装策略：对已校验的当前插件包按游戏逐个重装或延后，并重试延后项。

原版的 addonBin 联网元数据检查、下载与缓存替换（旧更新服务）已删除；包的来源由调用方负责
（开发版经 GitHub Release 下载并校验，见 dev_addon_update）。存储、安装器与游戏列表均由调用方注入。
"""
from dataclasses import dataclass, replace
from typing import Protocol
import ntpath


STARTUP_DELAY_MS = 5000
PENDING_KEY = "addonPendingReinstall"
@dataclass(frozen=True)
class AddonGame:
    """012730 record projection: label+18, AddOns+48, running+61, installed+68."""
    label: str
    addons_path: str
    running: bool = False
    installed_name: str = ""


@dataclass(frozen=True)
class ReinstallResult:
    ok: bool
    addon_name: str = ""
    error: str = ""


@dataclass(frozen=True)
class GameUpdateAction:
    path: str
    status: str
    addon_name: str = ""
    error: str = ""


@dataclass(frozen=True)
class AddonUpdateState:
    phase: str = "idle"
    busy: bool = False
    cache_changed: bool = False
    error: str = ""
    actions: tuple[GameUpdateAction, ...] = ()
    pending: tuple[str, ...] = ()


class AddonUpdateFS(Protocol):
    def read_first_line(self, path: str) -> bytes: ...
    def read_bytes(self, path: str) -> bytes: ...
    def open_atomic(self, path: str): ...  # write, commit, cancel, close; described below


class PendingAddons(Protocol):
    def read(self) -> tuple[str, ...]: ...
    def write(self, paths: tuple[str, ...]) -> None: ...


class SettingsPendingAddons:
    """Explicit bridge to the existing SettingsStore; construction does no I/O."""
    def __init__(self, settings):
        self.settings = settings

    def read(self):
        return tuple(self.settings._read(PENDING_KEY, [], "strings"))

    def write(self, paths):
        self.settings.qsettings.setValue(PENDING_KEY, list(paths))


class AddonUpdater:
    def __init__(self, http, fs: AddonUpdateFS, pending: PendingAddons, *,
                 env, application_dir, games, installed_name, install,
                 on_log=None, on_state=None, on_session_end=None):
        """games()->fresh AddonGame sequence; install(path)->ReinstallResult.

        install must use the current addon.bin through the existing installer
        (plan_install/write_install/record/cleanup), not a cached startup payload.
        installed_name(path) is the existing signature-directory fallback scan.
        No implicit success callback/default game enumeration is supplied.
        """
        self.http, self.fs, self.pending = http, fs, pending
        self.env, self.application_dir = env, application_dir
        self.games, self.installed_name, self.install = games, installed_name, install
        self.on_log, self.on_state = on_log, on_state
        self.on_session_end = on_session_end
        self.cache_path = ntpath.abspath(ntpath.join(application_dir, "addon.bin"))
        self.state = AddonUpdateState()
        self.active = None
        self._session_id = 0

    @property
    def busy(self):
        return self.state.busy

    def _state(self, **changes):
        self.state = replace(self.state, **changes)
        if self.on_state is not None:
            self.on_state(self.state)

    def _log(self, text):
        if self.on_log is not None:
            self.on_log(text)

    def _end(self, phase, error="", **fields):
        # 原完成槽先安排会话管理器释放，再清除忙标记。
        if self.on_session_end is not None:
            self.on_session_end(self._session_id)
        self.active = None
        self._state(phase=phase, busy=False, error=error, **fields)
        return self.state

    def _install(self, path):
        result = self.install(path)
        if not isinstance(result, ReinstallResult):
            raise TypeError("install callback must return ReinstallResult; success cannot be inferred")
        return result

    def reinstall_games(self):
        """对已校验并提交的当前包执行原重装策略；包来源由调用方负责。"""
        actions = []
        for game in self.games():
            path = game.addons_path
            if not path:
                actions.append(GameUpdateAction(path, "skipped_empty_path"))
                continue
            name = game.installed_name or self.installed_name(path)
            if not name:
                actions.append(GameUpdateAction(path, "skipped_not_installed"))
                continue
            if game.running:
                self._log(f"  {game.label} 正在运行，插件下次启动软件时重装")
                paths = tuple(self.pending.read())
                if path not in paths:  # Native QStringList.contains(CaseSensitive).
                    self.pending.write(paths + (path,))
                actions.append(GameUpdateAction(path, "deferred", name))
                continue
            outcome = self._install(path)
            if outcome.ok:
                self._log(f"  {game.label} 已重装 ✓（目录 {outcome.addon_name}）")
                actions.append(GameUpdateAction(path, "installed", outcome.addon_name))
            else:
                self._log(f"  {game.label} 重装失败：{outcome.error}")
                actions.append(GameUpdateAction(path, "install_failed", error=outcome.error))
            # Native neither queues failures here nor clears existing pending on success.
        self._log("插件热更完成（游戏里 /reload 后生效）")
        return self._end("cache_updated", actions=tuple(actions), pending=tuple(self.pending.read()))

    def _retry_pending(self):
        pending = tuple(self.pending.read())
        if not pending:
            return (), ()  # Native does not enumerate games or rewrite the empty setting.
        games = tuple(self.games())
        remaining, actions = [], []
        succeeded = False
        for path in pending:
            game = next((game for game in games if game.addons_path == path), None)
            if game is None:
                actions.append(GameUpdateAction(path, "dropped_not_detected"))
                continue
            if game.running:
                remaining.append(path)
                actions.append(GameUpdateAction(path, "still_running"))
                continue
            outcome = self._install(path)  # No installed-name requirement in pending branch.
            if outcome.ok:
                self._log(f"插件补装：{game.label} 已重装 ✓（目录 {outcome.addon_name}）")
                succeeded = True
                actions.append(GameUpdateAction(path, "installed", outcome.addon_name))
            else:
                self._log(f"插件补装：{game.label} 失败：{outcome.error}")
                remaining.append(path)
                actions.append(GameUpdateAction(path, "install_failed", error=outcome.error))
        self.pending.write(tuple(remaining))
        if succeeded:
            self._log("插件补装完成（游戏里需重启客户端后生效）")
        return tuple(actions), tuple(remaining)

    def retry_pending(self):
        """Explicit standalone 0a05a0 entry; scheduler determines when to invoke it.

        This method does not add another native busy gate to the standalone slot.
        """
        actions, paths = self._retry_pending()
        self._state(actions=actions, pending=paths)
        return actions
