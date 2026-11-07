"""可携带的离线帧输入；数据标签不是原版动态观测结果。

仅依赖标准库和 RGBImage，不抓屏、发键、载入原 EXE 或建立 Qt 窗口。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from .pixel_geometry import RGBImage


OLD_SCALES = (1.0, 1.125, 1.2, 1.25, 1.3333, 2.0)
READABLE_PITCHES = (4, 5, 8)
MARKER_COLORS = (0x13E395, 0xF1AD25, 0x3D6DD3)
BACKGROUND = 0x0D0D0D


@dataclass(frozen=True)
class FixtureField:
    key: str
    physical_row: int
    source_rgb: int


@dataclass(frozen=True)
class FrameFixture:
    name: str
    protocol: str
    spec_id: str
    class_name: str
    profile: str
    image: RGBImage
    fields: tuple[FixtureField, ...]
    # 期望状态来自静态分支理解，必须与未来 native_observation 分开存储。
    predicted_status: str = "ok"


def _value(kind: str, key: str, index: int, profile: str) -> int:
    if profile == "unknown":
        return 0xFFFFFF
    if profile != "mixed":
        raise ValueError("profile 必须为 mixed 或 unknown")
    if kind in {"switch", "bool", "validity", "aura_state", "spell"} or key.endswith("_ready"):
        return 0x00FF00 if index % 2 == 0 else 0xFF0000
    if kind == "presence":
        return 0x00FF00 if index % 2 == 0 else 0x333333
    if kind == "burst":
        return 0x0000FF
    if kind == "playercast":
        return 0x00FF09
    if kind == "talents":
        return 0x051F0F
    if kind == "health" or key.endswith("_health_pct"):
        return 20 + index % 81
    if kind == "cooldown":
        return (0, 1, 600, 601)[index % 4]
    if kind == "distance":
        return 125
    if kind == "castcolor":
        return 0x123456
    if key == "aoe_mode":
        return 2
    # 保持 rage 的有效范围；不同相邻数值同时给 pitch 精化提供边界。
    return 1 + index % 99


def _paint(pixels: list[list[int]], x0: int, y0: int, x1: int, y1: int, color: int) -> None:
    for y in range(max(0, y0), min(len(pixels), y1)):
        pixels[y][max(0, x0):min(len(pixels[y]), x1)] = [color] * max(
            0, min(len(pixels[y]), x1) - max(0, x0))


def old_fixture(contract: Mapping, spec_id: str, *, scale: float = 1.0,
                profile: str = "mixed", fault: str | None = None) -> FrameFixture:
    if not math.isfinite(scale) or scale not in OLD_SCALES:
        raise ValueError("本样本集仅接受原生自测的六个 scale")
    if fault not in {None, "no_marker", "version_mismatch", "unknown_spec", "truncated"}:
        raise ValueError("未知 old 故障类型")
    spec = contract["specs"][spec_id]
    defs = [*contract["commonFields"], *spec.get("fields", []), *spec.get("presenceFields", [])]
    colors = [_value(d["type"], d["id"], i, profile) for i, d in enumerate(defs)]
    colors[6] = 123 if fault == "unknown_spec" else int(spec_id)
    colors[18] = 0 if fault == "version_mismatch" else contract["constants"]["expectedVersion"]
    height = round(max(132, len(colors) * 4) * scale) + 16
    if fault == "truncated":
        height = round(200 * scale)
    pixels = [[BACKGROUND] * 24 for _ in range(height)]
    for row, color in enumerate(colors):
        _paint(pixels, 0, round(row * 4 * scale), max(1, round(4 * scale)),
               round((row + 1) * 4 * scale), color)
    if fault != "no_marker":
        _paint(pixels, round(4 * scale), round(128 * scale), round(8 * scale),
               round(132 * scale), 0xFF00FF)
    return FrameFixture(
        f"old-{spec_id}-{profile}-s{scale:g}" + (f"-{fault}" if fault else ""),
        "old", spec_id, contract.get("classNames", {}).get(spec_id, spec_id), profile,
        RGBImage(pixels), tuple(FixtureField(d["id"], i, colors[i]) for i, d in enumerate(defs)),
        "out_of_bounds" if fault == "truncated" else fault or "ok")


def readable_fixture(old_contract: Mapping, contract: Mapping, spec_id: str, *,
                     pitch: int = 4, profile: str = "mixed",
                     fault: str | None = None) -> FrameFixture:
    if pitch not in READABLE_PITCHES:
        raise ValueError("readable 样本 pitch 必须为 4、5 或 8")
    if fault not in {None, "no_marker", "unknown_spec", "zero_version", "truncated"}:
        raise ValueError("未知 readable 故障类型")
    spec = contract["specs"][spec_id]
    pairs = list(zip(spec["classicKeys"], spec["classicRows"]))
    allowed = set(spec["presenceRows"])
    presence = [p for p in spec["presenceFields"] if p["row"] in allowed]
    physical = {}
    for i, (key, row) in enumerate(pairs):
        if row >= 0:
            kind = "burst" if key == "burst" else "number"
            physical[row] = _value(kind, key, i, profile)
    for i, entry in enumerate(presence):
        physical[entry["row"]] = _value("presence", entry["key"], i, profile)
    # 原生先用通用 1489 布局取身份和版本，不依赖被测职业自己的布局。
    generic = dict(zip(contract["specs"]["1489"]["classicKeys"],
                       contract["specs"]["1489"]["classicRows"]))
    physical[generic["spec_id"]] = 123 if fault == "unknown_spec" else int(spec_id)
    physical[generic["addon_version_code"]] = (0 if fault == "zero_version" else
                                               contract["header"]["addonVersionCode"])
    x, y = 20, 2
    # 本模块是被主程序消费的字段样本，不冒充完整 Lua 文本/receipt 发射器。
    height = y + pitch * (max(physical, default=2) + 1)
    if fault == "truncated":
        height = y + pitch * 32
    pixels = [[BACKGROUND] * 64 for _ in range(height)]
    for row, color in {**dict(enumerate(MARKER_COLORS)), **physical}.items():
        if fault == "no_marker" and row == 0:
            continue
        _paint(pixels, x, y + row * pitch, x + pitch, y + (row + 1) * pitch, color)
    fields = tuple(FixtureField(key, row, physical.get(row, 0)) for key, row in pairs)
    fields += tuple(FixtureField(p["key"], p["row"], physical[p["row"]]) for p in presence)
    return FrameFixture(
        f"readable-{spec_id}-{profile}-p{pitch}" + (f"-{fault}" if fault else ""),
        "readable", spec_id, old_contract.get("classNames", {}).get(spec_id, spec_id), profile,
        RGBImage(pixels), fields, fault if fault in {"no_marker", "unknown_spec"} else "ok")


def fixture_suite(old_contract: Mapping, readable_contract: Mapping) -> tuple[FrameFixture, ...]:
    """所有两个契约共有职业：54 old 缩放 + 27 readable 几何 + 18 未知 + 8 坏帧。"""
    fixtures = []
    specs = sorted(set(old_contract["specs"]) & set(readable_contract["specs"]))
    for spec in specs:
        fixtures.extend(old_fixture(old_contract, spec, scale=s) for s in OLD_SCALES)
        fixtures.extend(readable_fixture(old_contract, readable_contract, spec, pitch=p)
                        for p in READABLE_PITCHES)
        fixtures.append(old_fixture(old_contract, spec, profile="unknown"))
        fixtures.append(readable_fixture(old_contract, readable_contract, spec, profile="unknown"))
    for fault in ("no_marker", "version_mismatch", "unknown_spec", "truncated"):
        fixtures.append(old_fixture(old_contract, "1489", fault=fault))
    for fault in ("no_marker", "unknown_spec", "zero_version", "truncated"):
        fixtures.append(readable_fixture(old_contract, readable_contract, "1489", fault=fault))
    return tuple(fixtures)


def ppm_bytes(image: RGBImage) -> bytes:
    """P6 无损 RGB，标准库生成；QImage 可直接读入，无显示窗口。"""
    if image.width <= 0 or image.height <= 0:
        raise ValueError("P6 不接受空图像")
    return (f"P6\n{image.width} {image.height}\n255\n".encode("ascii") +
            bytes(component for row in image.rows for pixel in row
                  for component in ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255)))
