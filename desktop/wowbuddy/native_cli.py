"""原生命令行的纯解析/分支选择；不执行命令、不读文件、不联网。

qt_arguments 必须是 QApplication 处理后 QCoreApplication.arguments() 的
完整序列（包括 argv[0]）；native_arguments 是 CommandLineToArgvW 的完整
原始序列，供 --no-stealth 使用。未传时假定两者一致，不复刻 Qt 自身参数。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .window_identity import native_title_enabled


EARLY_COMMANDS = (
    ("--selftest", "selftest"),
    ("--install-addon", "install_addon"),
    ("--check-update", "check_update"),
    ("--update-now", "update_now"),
    ("--hub-selftest", "hub_selftest"),
)
AUTO_UPDATE_SUPPRESSORS = frozenset({
    "--selftest", "--dump-ui", "--install-addon", "--check-update",
    "--update-now", "--no-update",
})


@dataclass(frozen=True)
class DumpUiOptions:
    rotations_file: str = ""
    rotation_key: str = ""
    spec_ids: tuple[str, ...] = ()
    talent: str = "10/0/0"
    toggle_showall: bool = False

    @property
    def rotation_override_requested(self) -> bool:
        # 057ac0 先检查两者非空，之后才打开文件/验证 key。
        return bool(self.rotations_file and self.rotation_key)

    @property
    def rotation_parts(self) -> tuple[str, str, str] | None:
        """057ac0:178–262；保留空段，第 3 段及以后用 | 拼回名称。

        返回并不保证 JSON 内存在此循环。classId 原生转数字字符串后与
        第一段精确比较，因此这里不把 '08' 或带空白的段转成整数。
        """
        parts = self.rotation_key.split("|")
        return (parts[0], parts[1], "|".join(parts[2:])) if len(parts) >= 3 else None


@dataclass(frozen=True)
class NativeCliOptions:
    command: str
    native_title_enabled: bool
    suppress_auto_update: bool
    hub_fetch: bool = False
    install_addon_dir: str | None = None
    auto_start: bool = False
    dump_ui: DumpUiOptions | None = None


def _arguments(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("传入完整 argv 序列，不传未经分词的命令行")
    result = tuple(values)
    if any(not isinstance(item, str) for item in result):
        raise TypeError("argv 项须为字符串")
    return result


def _last_value(arguments: tuple[str, ...], prefix: str, default: str = "") -> str:
    value = default
    for argument in arguments:
        if argument.startswith(prefix):
            value = argument[len(prefix):]
    return value


def parse_native_cli(qt_arguments: Sequence[str], *,
                     native_arguments: Sequence[str] | None = None) -> NativeCliOptions:
    """075960 主入口优先级与晚期 GUI 参数；未知项静默保留原生忽略语义。

    参数全部区分大小写。没有 argparse 缩写、-- 结束标记、空格取值、trim
    或 shell 再分词。崩溃只返回描述，不制造异常或访问空指针。
    """
    args = _arguments(qt_arguments)
    raw = args if native_arguments is None else _arguments(native_arguments)
    command = "gui"
    for argument in args:
        if argument in ("--crash-test", "--crash-test=throw"):
            command = "crash_null" if argument == "--crash-test" else "crash_throw"
            break
    if command == "gui":
        command = next((name for flag, name in EARLY_COMMANDS if flag in args), "gui")
    gui = command == "gui"
    dump = None
    if gui and "--dump-ui" in args:
        dump = DumpUiOptions(
            rotations_file=_last_value(args, "--rotations="),
            rotation_key=_last_value(args, "--rotation="),
            spec_ids=tuple(arg[len("--spec="):] for arg in args if arg.startswith("--spec=")),
            talent=_last_value(args, "--talent=", "10/0/0"),
            toggle_showall="--toggle-showall" in args,
        )
    return NativeCliOptions(
        command=command,
        native_title_enabled=native_title_enabled(raw),
        suppress_auto_update=bool(AUTO_UPDATE_SUPPRESSORS.intersection(args)),
        hub_fetch=command == "hub_selftest" and "--hub-fetch" in args,
        install_addon_dir=(_last_value(args, "--install-addon-dir=")
                           if command == "install_addon" else None),
        auto_start=gui and "--auto" in args,
        dump_ui=dump,
    )
