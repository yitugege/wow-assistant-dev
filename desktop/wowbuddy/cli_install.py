"""0624b0 独立安装命令：依赖注入执行器与显式本地文件适配。

不扫描真实游戏、不创建注册表设置、不联网；调用方显式提供检测和记录依赖。
--install-addon-dir 是直接安装位置，不使用 GUI 的游戏根目录归一化。
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable, Protocol, Sequence

from .addon_actions import LocalAddonFiles
from .addon_install import SettingsRecord, clean_path, plan_install
from .native_cli import NativeCliOptions


REPORT_NAME = "_install_addon_result.txt"
NO_GAME_WARNING = "未探测到游戏客户端（可传 --install-addon-dir=<AddOns 目录>）"


class DetectedInstallation(Protocol):
    addons_path: str


@dataclass(frozen=True)
class AddonPreparation:
    ok: bool
    error: str = ""


@dataclass(frozen=True)
class CliAddonInstallOutcome:
    ok: bool
    addon_name: str = ""
    details: str = ""
    error: str = ""


@dataclass(frozen=True)
class CliInstallResult:
    exit_code: int
    target: str = ""
    installation: CliAddonInstallOutcome | None = None
    report_path: Path | None = None
    report_text: str | None = None
    report_written: bool | None = None
    report_error: str = ""
    warning: str = ""


def install_report(target: str, result: CliAddonInstallOutcome) -> str:
    # 0624b0 用 argToQString 同时替换三个实参；不能重扫插入值内的 %1。
    if result.ok:
        return f"OK\n目标={target}\n随机目录名={result.addon_name}\n{result.details}"
    return f"FAIL\n目标={target}\n错误={result.error}\n{result.details}"


def run_install_command(options: NativeCliOptions, *, application_dir: str | Path,
                        detect: Callable[[], Sequence[DetectedInstallation]],
                        prepare: Callable[[], AddonPreparation],
                        install: Callable[[str], CliAddonInstallOutcome],
                        write_report: Callable[[Path, bytes], bool],
                        warn: Callable[[str], None]) -> CliInstallResult:
    """已选 install_addon 分支→退出码与结果；不自行创建任何业务依赖。

    detect 顺序须来自012730兼容快照；本层取首项，不能另行重新排序。
    prepare/安装返回 Qt 式结果；未预计的程序错误不伪装成安装成功。
    write_report 返回False或抛OSError都不改变原生安装退出码。
    """
    if options.command != "install_addon":
        raise ValueError("只接受已选中的 install_addon 命令")
    target = options.install_addon_dir or ""
    if target == "":
        games = detect()
        if not games:
            warn(NO_GAME_WARNING)
            return CliInstallResult(2, warning=NO_GAME_WARNING)
        target = games[0].addons_path
    prepared = prepare()
    if not prepared.ok:
        warning = "插件容器不可用：" + prepared.error
        warn(warning)
        return CliInstallResult(2, target, warning=warning)
    result = install(target)
    report_path = Path(application_dir) / REPORT_NAME
    report = install_report(target, result)
    error = ""
    try:
        written = bool(write_report(report_path, report.encode("utf-8")))
    except OSError as exc:
        written, error = False, str(exc)
    return CliInstallResult(0 if result.ok else 1, target, result,
                            report_path, report, written, error)


def write_local_report(path: Path, content: bytes) -> bool:
    """QFile WriteOnly|Truncate；不自动创建程序目录，不补换行。"""
    with path.open("wb") as stream:
        return stream.write(content) == len(content)


class LocalCliAddonInstaller:
    """显式本地适配；构造无文件/进程/网络操作。

    write_record 必须由宿主注入（可用隔离INI或内存），不隐式写生产注册表。
    复用已有安全执行器/清理器；失败可能留下原生同样会保留的部分文件。
    """
    def __init__(self, application_dir: str | Path, *,
                 write_record: Callable[[SettingsRecord], None],
                 files: LocalAddonFiles | None = None,
                 random_u32: Callable[[], int] | None = None):
        self.application_dir = Path(application_dir).absolute()
        self.package_path = self.application_dir / "addon.bin"
        self.write_record = write_record
        self.files = files if files is not None else LocalAddonFiles()
        self.random_u32 = random_u32

    def prepare(self) -> AddonPreparation:
        # 011fe0 仅检查9字节magic；正文完整性属于后续0135e0/0155d0。
        path = clean_path(str(self.package_path))
        if not self.package_path.exists():
            return AddonPreparation(False, f"找不到内嵌插件包：{path}")
        try:
            with self.package_path.open("rb") as source:
                header = source.read(9)
        except OSError:
            return AddonPreparation(False, f"内嵌插件包打不开：{path}")
        if header != b"WBADDON1\n":
            return AddonPreparation(False, f"内嵌插件包格式不对（magic 不匹配）：{path}")
        return AddonPreparation(True)

    def install(self, target: str) -> CliAddonInstallOutcome:
        # 0135e0 独立再检查容器；前置检查后文件消失属于安装失败1。
        prepared = self.prepare()
        if not prepared.ok:
            return CliAddonInstallOutcome(False, error=prepared.error)
        try:
            Path(target).mkdir(parents=True, exist_ok=True)
        except OSError:
            return CliAddonInstallOutcome(False, error=f"建不了目录：{target}")
        try:
            package = self.package_path.read_bytes()
            plan = plan_install(package, target,
                existing_entries=self.files.entries(target),
                existing_directories=self.files.directories(target),
                random_u32=self.random_u32, absolute_path=self.files.absolute_path)
            result = self.files.write_install(plan)
        except OSError as exc:
            return CliAddonInstallOutcome(False, error=str(exc))
        if not result.ok:
            # 原生 param3(details) 只在成功尾声赋值；失败调用方初始为空。
            return CliAddonInstallOutcome(False, error=result.error or result.status)
        if result.pending_record is not None:
            self.write_record(result.pending_record)
        notes, deleted = "", 0
        if result.pending_cleanup:
            try:
                cleanup = self.files.plan_cleanup(target, plan.addon_name, names=result.pending_cleanup)
                cleaned = self.files.execute_cleanup(cleanup, selected_path=target)
                notes, deleted = cleaned.notes, cleaned.deleted
            except (OSError, ValueError) as exc:
                # 安全清理器拒绝不是安装失败；避免任意旧目录删除。
                notes = f"  {exc}\n"
        details = (f"  内嵌插件包：{clean_path(str(self.package_path))}（{len(plan.files)} 个文件）\n"
                   f"  TOC 已改名为 {plan.addon_name}.toc，并同步 ## Title / ## Notes\n"
                   f"  已写入 {len(result.written)} 个文件 → {clean_path(plan.addons_path + '/' + plan.addon_name)}\n"
                   + notes + f"  清理旧目录：{deleted} 个\n")
        return CliAddonInstallOutcome(True, plan.addon_name, details)


def run_local_install_command(options: NativeCliOptions, *, application_dir: str | Path,
                              settings=None, environment=None,
                              window_backend_factory=None, warn=None) -> CliInstallResult:
    """独立命令的真实宿主入口，默认只使用重建测试版设置命名空间。

    可注入临时INI/环境/窗口后端工厂以验证同一入口。显式目录（包括非空
    空白字符串）不创建窗口后端；没有目录且禁用扫描时也不创建。
    该函数不执行 QApplication.exec，不构造主窗/抓屏/按键后端。
    """
    if options.command != "install_addon":
        raise ValueError("只接受已选中的 install_addon 命令")
    from .settings import open_test_settings
    from .addon_games import build_game_snapshot
    if settings is None:
        settings = open_test_settings()
    env = dict(os.environ if environment is None else environment)
    files = LocalAddonFiles()
    if warn is None:
        from PySide6.QtCore import qWarning
        warn = qWarning

    def detect():
        if "WOWBUDDY_NO_GAME_SCAN" in env:
            return ()
        factory = window_backend_factory
        if factory is None:
            from .game_windows import CtypesWindowBackend
            factory = CtypesWindowBackend
        return build_game_snapshot(files, factory(), settings, env)

    def record_installed(record):
        # 原版016c70只记installed键；无GUI的lastDir/history更新。
        # 不使用record中的原版应用名创建QSettings，始终写宿主隔离store。
        settings.qsettings.setValue(record.key, record.value)
        settings.qsettings.sync()  # 原生不把QSettings状态错误变成安装失败。

    backend = LocalCliAddonInstaller(application_dir, files=files, write_record=record_installed)
    return run_install_command(options, application_dir=application_dir, detect=detect,
        prepare=backend.prepare, install=backend.install,
        write_report=write_local_report, warn=warn)
