"""readable 色条原生消费路径的纯 Python 重建。

依据 01ebc0/021540、01f940、02b710、02d1f0、095410。
契约含有的 OCR、分段时间、receipt 元数据未被该原生路径消费，不推测实现。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import math

from .pixel_fields import DecodedField, PixelFieldDecoder
from .pixel_geometry import BarGeometry, RGBImage, locate_old_bar, sample_cell, sample_old_bar


MARKERS = ((19, 227, 149), (241, 173, 37), (61, 109, 211))
_SWITCH_KEYS = frozenset({
    "master_switch", "isMoving", "gcd", "player_casting", "target_casting",
    "focus_casting", "mouseover_casting", "in_raid", "in_mythic_plus",
    "target_is_enemy_player", "focus_cast_unreachable", "_forever_healing_mode",
})
_OLD_AURAS = (
    "mark_wild", "thorns", "moonfire", "insect_swarm", "rake", "rip", "lacerate",
    "tigers_fury", "berserk", "regrowth_player", "regrowth_target",
    "regrowth_party1", "regrowth_party2", "regrowth_party3", "regrowth_party4",
    "rejuvenation_player", "rejuvenation_target", "rejuvenation_party1",
    "rejuvenation_party2", "rejuvenation_party3", "rejuvenation_party4",
    "wild_growth_player", "wild_growth_target", "wild_growth_party1",
    "wild_growth_party2", "wild_growth_party3", "wild_growth_party4",
)
_OLD_READY_IDS = (5221, 1079, 1082, 8921, 5570, 5217, 6807, 5229, 5487, 768,
                  467, 1126, 5176, 2912, 22812, 417141, 414644, 779, 22568, 8936, 774)


def locate_readable_bar(image: RGBImage) -> BarGeometry | None:
    """按首个标记匹配，不在首个候选失败后继续搜索下一条。"""
    width = min(image.width, 48)

    def matches(x: int, y: int, marker: tuple[int, int, int]) -> bool:
        # 原版越界 QImage::pixel 返回的无效值不能匹配三个标记。
        if not 0 <= y < image.height:
            return False
        color = image.pixel(x, y)
        return all(abs(((color >> shift) & 255) - c) < 4
                   for shift, c in zip((16, 8, 0), marker))

    first = next(((x, y) for y in range(min(image.height, 120))
                  for x in range(width) if matches(x, y, MARKERS[0])), None)
    if first is None:
        return None
    x, y1 = first
    xs = range(max(0, x - 2), min(width - 1, x + 2) + 1)

    def following(y: int, marker: tuple[int, int, int]) -> int | None:
        return next((yy for yy in range(y + 3, y + 10)
                     for xx in xs if matches(xx, yy, marker)), None)

    y2 = following(y1, MARKERS[1])
    if y2 is None:
        return None
    y3 = following(y2, MARKERS[2])
    if y3 is None or abs(2 * y2 - y3 - y1) >= 2:
        return None
    pitch = (y3 - y1) * 0.5
    return BarGeometry(float(x), float(y1), pitch, pitch, pitch * 0.25, x, y1)


def sample_readable_rows(image: RGBImage, geometry: BarGeometry | None,
                         rows: Sequence[int], *, native_argb: bool = False) -> list[int]:
    """01f940：坐标截断，缺失行和越界行明确返回原生零样本。"""
    if image.width == 0 or image.height == 0 or geometry is None or not rows:
        return []
    g = geometry
    if not all(math.isfinite(n) for n in (g.origin_x, g.origin_y, g.pitch)) or g.pitch <= 0:
        raise ValueError("readable 几何必须有限且 pitch 为正")
    x = max(0, min(image.width - 1, math.trunc(g.origin_x + g.pitch * 0.5)))
    colors = []
    for row in rows:
        if not isinstance(row, int) or isinstance(row, bool):
            raise TypeError("readable 行号必须为整数")
        start = math.trunc(row * g.pitch + g.origin_y)
        end = math.trunc((row + 1) * g.pitch + g.origin_y)
        if row >= 0 and start >= 0 and end <= image.height:
            color = sample_cell(image, x, start, end)
            colors.append(color | 0xff000000 if native_argb else color)
        else:
            colors.append(0)
    return colors


def readable_field_type(key: str) -> str:
    """02d1f0 的大小写敏感名称推断，不使用 old 契约的同名字段类型。"""
    if key in {"burst", "distance"}:
        return key
    if key.endswith("_health_pct"):
        return "health"
    if key.endswith("_ready"):
        return "switch"
    if key in {"aoe_mode", "active_enemies", "enemies_8yd"}:
        return "count"
    if key in {"trinket1_cd", "trinket2_cd"}:
        return "cooldown"
    return "switch" if key in _SWITCH_KEYS else "number"


@dataclass(frozen=True)
class ReadableRow:
    index: int
    physical_row: int
    key: str
    label: str
    type: str
    applicable: bool
    decoded: DecodedField
    is_common: bool = False
    note: str = ""


@dataclass(frozen=True)
class ReadableFrame:
    status: str
    spec_id: str = ""
    version_code: int | None = None
    geometry: BarGeometry | None = None
    values: Mapping[str, str] = field(default_factory=dict)
    rows: tuple[ReadableRow, ...] = ()
    raw_colors: tuple[int, ...] = ()
    legacy_overlay: bool = False
    allow_unknown_availability: bool = True
    protocol: str = "readable"
    sampled_argb: tuple[int, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class UnverifiedDescriptorTable(ValueError):
    """已知但尚未还原的原生描述表外读取，不能当作普通解码结果。"""


class ReadableDecoder:
    def __init__(self, old_contract: Mapping, readable_contract: Mapping):
        self.field_decoder = PixelFieldDecoder(old_contract)
        self.no_value = old_contract.get("constants", {}).get("noValue", 0xFFFFFF)
        self.contract = readable_contract
        self.specs = readable_contract.get("specs", {})
        # 02b710 将 classicKeys/Rows 长度不一致作为契约加载失败。
        for key, spec in self.specs.items():
            if len(spec.get("classicKeys", [])) != len(spec.get("classicRows", [])):
                raise ValueError(f"readable 契约 {key} 行表不一致")
            if any(not isinstance(row, int) or isinstance(row, bool)
                   for row in spec.get("classicRows", [])):
                raise ValueError(f"readable 契约 {key} 行号不是整数")

    def field_definitions(self, spec_id: str) -> list[tuple[str, str, int]]:
        spec = self.specs[spec_id]
        definitions = [(key, readable_field_type(key), row)
                       for key, row in zip(spec.get("classicKeys", []), spec.get("classicRows", []))]
        selected = set(spec.get("presenceRows", []))
        # presenceRows 是成员集合，顺序和重复项以 presenceFields 为准。
        definitions.extend((entry.get("key", ""), "presence", entry.get("row", -1))
                           for entry in spec.get("presenceFields", [])
                           if entry.get("row", -1) in selected)
        return definitions

    def _read(self, image: RGBImage, geometry: BarGeometry, key: str,
              spec_id: str = "1489") -> int | None:
        spec = self.specs.get(spec_id)
        if spec is None or key not in spec.get("classicKeys", []):
            return None
        index = spec["classicKeys"].index(key)
        row = spec["classicRows"][index]
        if row < 0:
            return None
        result = sample_readable_rows(image, geometry, [row])
        # 07f200 行号有效即成功；即使采样数组为空也使用局部初始值0。
        return result[0] if result else 0

    def decode(self, image: RGBImage, geometry: BarGeometry | None = None, *,
               retained_descriptors: Sequence[Mapping] | None = None,
               descriptor_resolver: Callable[[str], Sequence[Mapping]] | None = None) -> ReadableFrame:
        """按 readable 行表采样，可显式使用原主窗留存的字段描述。

        描述表不决定物理采样行；身份/血量补读及旧条覆盖仍按原路径执行。
        留存表短于本帧颜色数的原生表外行为尚未确定，不能静默截断或补零。
        调用者负责判断身份是否相同；默认保持独立帧解码。
        """
        if retained_descriptors is not None and descriptor_resolver is not None:
            raise ValueError("留存描述表与描述解析器不能同时提供")
        geometry = geometry if geometry is not None else locate_readable_bar(image)
        if geometry is None:
            return ReadableFrame("no_marker")
        encoded = self._read(image, geometry, "spec_id")
        identity = encoded >> 12 if encoded is not None and encoded > 4095 else encoded
        spec_id = str(identity) if identity is not None and identity > 0 else ""
        version = self._read(image, geometry, "addon_version_code")
        version = version if version is not None and version > 0 else None
        if spec_id not in self.specs:
            return ReadableFrame("unknown_spec", spec_id=spec_id, version_code=version, geometry=geometry)

        if descriptor_resolver is not None:
            retained_descriptors = descriptor_resolver(spec_id)
        definitions = self.field_definitions(spec_id)
        sampled_argb = sample_readable_rows(image, geometry, [row for _, _, row in definitions], native_argb=True)
        colors = [color & 0xffffff for color in sampled_argb]
        if len(colors) != len(definitions):
            return ReadableFrame("out_of_bounds", spec_id=spec_id, version_code=version, geometry=geometry)
        if retained_descriptors is not None and len(retained_descriptors) < len(colors):
            raise UnverifiedDescriptorTable(
                f"留存字段表短于 readable 采样数量；原生表外行为尚未验证（{spec_id}："
                f"{len(retained_descriptors)}/{len(colors)}）")
        values: dict[str, str] = {}
        decoded_rows = []
        for index, ((key, kind, row), color) in enumerate(zip(definitions, colors)):
            descriptor = ({"id": key, "type": kind} if retained_descriptors is None
                          else retained_descriptors[index])
            key, kind = descriptor["id"], descriptor["type"]
            decoded = self.field_decoder.decode(descriptor,
                                                (color >> 16, (color >> 8) & 255, color & 255))
            values[key] = decoded.value_text
            decoded_rows.append(ReadableRow(index, row, key, descriptor.get("label", key),
                                           kind, True, decoded, note=descriptor.get("note", "")))

        for unit in ("target", "player"):
            color = self._read(image, geometry, f"{unit}_health_pct")
            if color is not None:
                valid = color > 0 and color != self.no_value
                values[f"{unit}_valid"] = "ON" if valid else "OFF"
                if valid:
                    values[f"health_{unit}"] = str(color & 255)
        form = self._read(image, geometry, "druid_form", spec_id)
        if form is not None:
            values["form"] = str(form)
        for party in range(1, 5):
            color = self._read(image, geometry, f"party{party}_health_pct")
            if color is not None:
                valid = color > 0 and color != self.no_value
                values[f"health_party{party}"] = str(color & 255) if valid else "UNKNOWN"
                values[f"friendly_party{party}"] = "ON" if valid else "OFF"

        old_geometry = locate_old_bar(image)
        old_colors = sample_old_bar(image, old_geometry, 48) if old_geometry else []
        if len(old_colors) >= 48:
            for key, color in zip(_OLD_AURAS, old_colors[:27]):
                values[key] = "ON" if color == 0x00FF00 else "OFF"
            for spell_id, color in zip(_OLD_READY_IDS, old_colors[27:48]):
                values[f"spell_{spell_id}_ready"] = "ON" if color == 0x00FF00 else "OFF"
        return ReadableFrame("ok", spec_id, version, geometry, values, tuple(decoded_rows),
                             tuple(colors), len(old_colors) >= 48, sampled_argb=tuple(sampled_argb))
