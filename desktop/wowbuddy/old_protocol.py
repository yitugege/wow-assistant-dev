"""旧式4×4像素条整帧解码，保持主程序的三次采样和身份判断顺序。

数据路径：092c90 → 0201b0 → 02f430 → 025ef0 → 026570。
仅接受图像与契约，不捕获屏幕、不改UI、不发送按键。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from .expressions import _double, _int
from .pixel_fields import DecodedField, PixelFieldDecoder
from .pixel_geometry import BarGeometry, RGBImage, locate_old_bar, sample_old_bar


@dataclass(frozen=True)
class FrameRow:
    index: int
    key: str
    label: str
    type: str
    applicable: bool
    decoded: DecodedField
    is_common: bool = False
    note: str = ""


@dataclass(frozen=True)
class OldFrame:
    status: str
    spec_id: str = ""
    hero_id: int = -1
    version_code: int | None = None
    geometry: BarGeometry | None = None
    values: Mapping[str, str] = field(default_factory=dict)
    rows: tuple[FrameRow, ...] = ()
    raw_colors: tuple[int, ...] = ()
    fallback_readable: bool = False
    allow_unknown_availability: bool = False
    protocol: str = "old"

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def decode_identity(encoded: int, shift: int = 4096) -> tuple[int, int]:
    """FUN_14002f430；整除但余数为0时不拆分，这与readable不同。"""
    if encoded <= 0:
        return -1, -1
    if shift <= 0:
        raise ValueError("identityHeroShift必须为正；无效契约不进入原生除零路径")
    if encoded >= shift:
        spec, hero = divmod(encoded, shift)
        if spec > 0 and hero > 0:
            return spec, hero
    return encoded, -1


class OldDecoder:
    def __init__(self, contract: Mapping, *, additional_versions=()):
        self.contract = contract
        constants = contract.get("constants", {})
        self.expected_version = int(_double(constants.get("expectedVersion"), 0.0))
        self.accepted_versions = frozenset((self.expected_version, *additional_versions))
        self.common_count = max(1, _int(constants.get("commonCount"), 29))
        self.identity_shift = _int(constants.get("identityHeroShift"), 4096)
        self.field_decoder = PixelFieldDecoder(contract)
        self.specs = contract.get("specs", {})

    def field_definitions(self, spec_id: str) -> list[Mapping]:
        """025ef0 按common、职业fields、presenceFields拼接；不删不适用字段。"""
        spec = self.specs.get(spec_id, {})
        return list(self.contract.get("commonFields", [])) + list(spec.get("fields", [])) + list(spec.get("presenceFields", []))

    def decode(self, image: RGBImage, geometry: BarGeometry | None = None, *,
               retained_descriptors: Sequence[Mapping] | None = None,
               descriptor_resolver: Callable[[str], Sequence[Mapping]] | None = None) -> OldFrame:
        """身份解析仍用公共头；整帧采样长度由当前描述表决定。

        retained_descriptors 由上层在身份未变时显式提供，不自行推断协议状态。
        可携带 applicable/is_common 元数据，避免按新职业重新推断旧描述属性。
        """
        if retained_descriptors is not None and descriptor_resolver is not None:
            raise ValueError("留存描述表与描述解析器不能同时提供")
        geometry = geometry if geometry is not None else locate_old_bar(image)
        if geometry is None:
            return OldFrame("no_marker", fallback_readable=True)

        # 原版先独立采样19格检查第19格；不直接复用最终整帧采样。
        header = sample_old_bar(image, geometry, 19)
        if len(header) <= 18 or header[18] not in self.accepted_versions:
            return OldFrame("version_mismatch", version_code=header[18] if len(header) > 18 else None,
                            geometry=geometry, fallback_readable=True)
        common = sample_old_bar(image, geometry, self.common_count)
        if len(common) < self.common_count:
            return OldFrame("out_of_bounds", version_code=header[18], geometry=geometry)
        if len(common) <= 18:
            raise ValueError("旧协议契约commonCount小于固定版本字段索引")
        if common[18] not in self.accepted_versions:
            return OldFrame("version_mismatch", version_code=common[18], geometry=geometry)

        spec, hero = decode_identity(common[6], self.identity_shift)
        spec_key = str(spec) if spec > 0 and str(spec) in self.specs else ""
        if descriptor_resolver is not None:
            retained_descriptors = descriptor_resolver(spec_key)
        if not spec_key:
            return OldFrame("unknown_spec", hero_id=hero, version_code=common[18], geometry=geometry)

        definitions = (self.field_definitions(spec_key) if retained_descriptors is None
                       else retained_descriptors)
        colors = sample_old_bar(image, geometry, len(definitions))
        if len(colors) < len(definitions):
            return OldFrame("out_of_bounds", spec_id=spec_key, hero_id=hero,
                            version_code=common[18], geometry=geometry)
        rows = []
        values = {}
        class_only = self.contract.get("classOnlyFields", {})
        for index, (definition, color) in enumerate(zip(definitions, colors)):
            rgb = ((color >> 16) & 255, (color >> 8) & 255, color & 255)
            decoded = self.field_decoder.decode(definition, rgb)
            key = definition["id"]
            applicable = (key not in class_only or spec in class_only[key]) if retained_descriptors is None else bool(definition.get("applicable", True))
            rows.append(FrameRow(index, key, definition.get("label", ""), definition["type"], applicable,
                                 decoded, (index < len(self.contract.get("commonFields", [])) if retained_descriptors is None
                                           else bool(definition.get("is_common", False))),
                                 definition.get("note", "")))
            values[key] = decoded.value_text  # QHash后值覆盖；不是给规则引擎的带单位UI文字。
        return OldFrame("ok", spec_key, hero, common[18], geometry, values, tuple(rows), tuple(colors))
