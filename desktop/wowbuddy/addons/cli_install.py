"""0624b0 独立安装命令：依赖注入执行器（原版本地文件适配器 LocalCliAddonInstaller 已删除，开发版见 dev_cli_install）。

不扫描真实游戏、不创建注册表设置、不联网；调用方显式提供检测和记录依赖。
--install-addon-dir 是直接安装位置，不使用 GUI 的游戏根目录归一化。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from wowbuddy.native_cli import NativeCliOptions


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


