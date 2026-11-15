"""原程序 WBD1 / WBADDON1 容器读写。

格式证据：外壳资源 10/200/1033、内层 addon.bin、原生 FUN_1400155d0。
正常输入兼容；对异常输入额外拒绝尾随数据、重复路径和目录穿越。
不启动业务 EXE，不安装插件，不连接网络。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
import hashlib
import struct
import zlib


class PackageError(ValueError):
    pass


@dataclass(frozen=True)
class Member:
    name: str
    data: bytes = field(repr=False)
    packed: bytes | None = field(default=None, repr=False, compare=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def take(self, size: int) -> bytes:
        if size < 0 or size > len(self.data) - self.offset:
            raise PackageError(f"容器截断：offset={self.offset}, size={size}")
        start = self.offset
        self.offset += size
        return self.data[start:self.offset]

    def integer(self, fmt: str) -> int:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def finish(self):
        if self.offset != len(self.data):
            raise PackageError(f"存在尾随字节：{len(self.data) - self.offset}")


def _validate_name(name: str) -> str:
    # 同时按 Windows 和 POSIX 分隔符校验，避免在其他平台解析后在 Windows 越界。
    normalized = name.replace("\\", "/")
    path = PureWindowsPath(name)
    if (not name or path.is_absolute() or path.drive or path.root
            or any(p in ("", ".", "..") for p in normalized.split("/"))
            or any(c in name for c in '\x00:<>"|?*')
            or any(p.endswith((" ", ".")) for p in normalized.split("/"))):
        raise PackageError(f"不安全的成员路径：{name!r}")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)
    }
    if any(p.split(".")[0].upper() in reserved for p in normalized.split("/")):
        raise PackageError(f"Windows 保留路径：{name!r}")
    return normalized


def _check_members(members: list[Member]):
    seen = set()
    for member in members:
        key = _validate_name(member.name).casefold()
        if key in seen:
            raise PackageError(f"重复成员路径：{member.name}")
        seen.add(key)


def _decode_name(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageError("成员名称不是有效 UTF-8") from exc


def read_bundle(data: bytes) -> list[Member]:
    reader = Reader(data)
    if reader.take(4) != b"WBD1":
        raise PackageError("WBD1 签名不匹配")
    count = reader.integer("<I")
    if count > len(data) // 12:
        raise PackageError("WBD1 成员计数超出容器长度")
    members = []
    for _ in range(count):
        name = _decode_name(reader.take(reader.integer("<I")))
        members.append(Member(name, reader.take(reader.integer("<Q"))))
    reader.finish()
    _check_members(members)
    return members


def write_bundle(members: list[Member]) -> bytes:
    _check_members(members)
    parts = [b"WBD1", struct.pack("<I", len(members))]
    for member in members:
        name = member.name.encode("utf-8")
        parts.extend((struct.pack("<I", len(name)), name,
                      struct.pack("<Q", len(member.data)), member.data))
    return b"".join(parts)


def _uncompress(packed: bytes, max_member_size: int) -> bytes:
    if len(packed) < 4:
        raise PackageError("qCompress 数据不足 4 字节")
    expected = struct.unpack_from(">I", packed)[0]
    if expected > max_member_size:
        raise PackageError(f"解压大小超过本次上限：{expected}")
    try:
        stream = zlib.decompressobj()
        raw = stream.decompress(packed[4:], expected + 1)
    except zlib.error as exc:
        raise PackageError("zlib 数据损坏") from exc
    if len(raw) != expected or not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise PackageError("解压长度、流结束标记或尾随数据不匹配")
    return raw


def read_addon(data: bytes, *, max_member_size: int = 64 * 1024 * 1024) -> list[Member]:
    reader = Reader(data)
    if reader.take(9) != b"WBADDON1\n":
        raise PackageError("WBADDON1 签名不匹配")
    count = reader.integer("<I")
    if count > 4096:  # 原生 FUN_1400155d0 的 0x1000 限制。
        raise PackageError("插件成员数超过 4096")
    members = []
    for _ in range(count):
        name = _decode_name(reader.take(reader.integer("<H")))
        packed = reader.take(reader.integer("<I"))
        members.append(Member(name, _uncompress(packed, max_member_size), packed))
    reader.finish()
    _check_members(members)
    return members


def write_addon(members: list[Member], *, preserve_compression: bool = True) -> bytes:
    _check_members(members)
    if len(members) > 4096:
        raise PackageError("插件成员数超过 4096")
    parts = [b"WBADDON1\n", struct.pack("<I", len(members))]
    for member in members:
        name = member.name.encode("utf-8")
        if len(name) > 65535:
            raise PackageError("插件名称超过 uint16 长度")
        packed = member.packed if preserve_compression else None
        cache_size = struct.unpack_from(">I", packed)[0] if packed and len(packed) >= 4 else None
        if (packed is None or cache_size != len(member.data)
                or _uncompress(packed, max(len(member.data), 1)) != member.data):
            packed = struct.pack(">I", len(member.data)) + zlib.compress(member.data)
        parts.extend((struct.pack("<H", len(name)), name,
                      struct.pack("<I", len(packed)), packed))
    return b"".join(parts)


def compare_directory(members: list[Member], directory: Path) -> list[dict]:
    """逐个验证已有导出；不将多余文件删除，也不写入目录。"""
    root = directory.resolve()
    results = []
    for member in members:
        path = (root / _validate_name(member.name)).resolve()
        if not path.is_relative_to(root):
            raise PackageError(f"成员路径经链接越界：{member.name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        results.append({"name": member.name, "size": len(member.data),
                        "expected_sha256": member.sha256, "actual_sha256": actual,
                        "equal": actual == member.sha256})
    return results
