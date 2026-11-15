"""更新相关的共享数据结构与校验工具：版本比较、目标路径、替换预检、下载临时文件。

原版的联网检查与下载流程（旧更新服务 Updater / parse_manifest）已删除；开发版经 GitHub Release
检查与下载（github_client / github_outer），只复用这里的数据结构与工具函数。
"""
from dataclasses import dataclass
from typing import Protocol, Iterable
import ntpath
import re

CURRENT_VERSION = "1.0.38"
DEVELOPMENT_ERROR = "当前是开发模式（没有通过单文件引导器启动），无法自动替换程序；请到官网下载新版安装包"
class UpdateFS(Protocol):
    def read_first_line(self, path: str) -> bytes: ...
    def is_file(self, path: str) -> bool: ...
    def probe_write(self, path: str) -> bool: ...
    def remove(self, path: str) -> bool: ...
    def open_write(self, path: str): ...  # write(bytes), flush(), close(); OSError on failure
    def size(self, path: str) -> int: ...
    def read_chunks(self, path: str, chunk_size: int) -> Iterable[bytes]: ...


@dataclass(frozen=True)
class UpdateInfo:
    ok: bool = False
    error: str = ""
    current_version: str = CURRENT_VERSION
    version: str = ""
    date: str = ""
    size: int = 0
    sha256: str = ""
    download_url: str = ""
    channel: str = ""
    note: str = ""

    @property
    def has_update(self):
        return self.ok and bool(self.version) and compare_versions(self.version, self.current_version) > 0


@dataclass(frozen=True)
class VerifiedDownload:
    part_path: str
    target_path: str
    info: UpdateInfo
    actual_size: int
    actual_sha256: str | None


def resolve_target_path(env):
    if env.get("WOWBUDDY_EXE", ""):
        return env["WOWBUDDY_EXE"].replace("/", "\\")
    if env.get("WOWBUDDY_HOME", ""):
        return ntpath.join(env["WOWBUDDY_HOME"], "WOW战斗助手.exe").replace("/", "\\")
    return ""


def replacement_blocker(target_path, fs):
    if not target_path:
        return DEVELOPMENT_ERROR
    if not fs.is_file(target_path):
        return f"找不到要替换的程序文件：{target_path}"
    directory = ntpath.dirname(ntpath.abspath(target_path))
    try:
        writable = fs.probe_write(ntpath.join(directory, "wowbuddy_write_test.tmp"))
    except OSError:
        writable = False
    if not writable:
        # 原QFileInfo.absolutePath在Windows也使用正斜杠显示目录。
        display_directory = directory.replace("\\", "/")
        return f"程序所在目录不可写，无法自动更新：{display_directory}\n请手动下载新版"
    return ""


def part_file_path(target_path):
    # QFileInfo.completeBaseName removes only the final suffix.
    directory, name = ntpath.split(ntpath.abspath(target_path))
    base = name.rsplit(".", 1)[0] if "." in name else name
    return ntpath.join(directory, base + ".update.part")


def version_segments(version):
    # 0x1400b6b50：逐 UTF-16 字元积累数字段，分隔或结尾时 toLongLong。
    # QChar iterates UTF-16 units: supplementary-plane digit codepoints are NOT digits here.
    normalized = "".join(c if ord(c) <= 0xffff and c.isdecimal() else "." for c in version)
    result = []
    for group in re.findall(r"\d+", normalized):
        # QString::toLongLong uses C-locale ASCII parsing; failed/overflow conversion is zero.
        digits = group.lstrip("0") or "0"
        number = int(digits) if group.isascii() and len(digits) <= 19 else 0
        result.append(number if number <= 0x7fffffffffffffff else 0)
    return tuple(result)


def compare_versions(left, right):
    a, b = version_segments(left), version_segments(right)
    for i in range(max(len(a), len(b))):
        x, y = (a[i] if i < len(a) else 0), (b[i] if i < len(b) else 0)
        if x != y:
            return 1 if x > y else -1
    return 0


