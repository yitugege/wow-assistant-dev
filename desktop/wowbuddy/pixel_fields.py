"""旧像素协议的字段解码：返回原生使用的值文本和说明文本。

依据 FUN_140026570、FUN_1400295f0、FUN_14002f0e0 及 PE 常量。
不包含抓屏、行定位、readable 字段合成、规则判断或发键。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


SUPPORTED_TYPES = frozenset({
    "switch", "bool", "burst", "count", "distance", "isMoving", "health",
    "number", "castcolor", "cooldown", "validity", "aura_state", "playercast",
    "talents", "presence", "spell",
})


class UnsupportedFieldType(ValueError):
    """尚未确认的字段类型，不能静默套用其他类型规则。"""


@dataclass(frozen=True, slots=True)
class DecodedField:
    value_text: str
    detail: str
    raw_rgb: tuple[int, int, int]
    raw_value: int


def decode_field(
    field_type: str,
    rgb: Sequence[int],
    field_id: str = "",
    *,
    constants: Mapping[str, int] | None = None,
    talent_groups: Mapping[str, Sequence[str]] | None = None,
    sentinel601: Mapping[str, str] | None = None,
) -> DecodedField:
    """解码单个已定位的 RGB 样本。

    constants/talent_groups/sentinel601 可直接取 contract.json 的对应字典。
    返回文本与原生 decoder 一致，包括 UNKNOWN、十六进制色值、— 的区别。
    非法输入报错；已知类型的未知读数保留原版文本，不能转成 False 或 0。
    """
    if field_type not in SUPPORTED_TYPES:
        raise UnsupportedFieldType(f"未经确认的像素字段类型：{field_type!r}")
    if not isinstance(field_id, str):
        raise TypeError("field_id 必须是字符串")
    if (isinstance(rgb, (str, bytes)) or not isinstance(rgb, Sequence)
            or len(rgb) != 3):
        raise ValueError("RGB 必须包含三个整数分量")
    if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in rgb):
        raise ValueError("RGB 分量必须是 0..255 整数")
    r, g, b = rgb
    raw_rgb = (r, g, b)
    raw = (r << 16) | (g << 8) | b
    no_value = 0xFFFFFF if constants is None else constants.get("noValue", 0xFFFFFF)
    unavailable = 601 if constants is None else constants.get("cdUnavailable", 601)
    hexc = f"#{raw:06X}"

    def result(value_text: str, detail: str = "") -> DecodedField:
        return DecodedField(value_text, detail, raw_rgb, raw)

    def unavailable_reason() -> str:
        return (sentinel601 or {}).get(field_id, "601（无对应含义）")

    # 原生先判断 talents，再判断特殊 rage 字段，再分派其他类型。
    if field_type == "talents":
        if raw == no_value or max(rgb) > 100:
            return result("UNKNOWN", "天赋未读到")
        value_text = f"{r}/{g}/{b}"
        if max(rgb) == 0:
            return result(value_text, "未加点")
        # 原生用严格 >，并列最高取 R 优先、再 G、再 B。
        selected = max(range(3), key=lambda i: rgb[i])
        groups = (talent_groups or {}).get(field_id, ())
        detail = groups[selected] if len(groups) == 3 else f"第{selected + 1}系"
        return result(value_text, detail)
    if field_id == "rage" and (raw == no_value or raw > 100):
        return result("UNKNOWN", "怒气未读到")

    green = g >= 200 and r <= 80 and b <= 80
    red = r >= 200 and g <= 80 and b <= 80
    gray = all(30 <= c <= 90 for c in rgb) and max(rgb) - min(rgb) <= 24

    if field_type in {"switch", "bool"}:
        if green:
            return result("ON", "开启")
        if red:
            return result("OFF", "关闭")
        return result(hexc, "未知开关色")
    if field_type == "presence":
        if green:
            return result("ON", "光环生效")
        if gray:
            return result("OFF", "无光环")
        return result("UNKNOWN", "未识别到光环容器色块")
    if field_type in {"validity", "aura_state"}:
        if green:
            return result("ON", "已确认")
        if red:
            return result("OFF", "已确认不存在")
        if r >= 200 and g >= 200 and b <= 80:
            return result("UNKNOWN", "状态未确认")
        return result(hexc, "未知状态")
    if field_type == "burst":
        if raw_rgb == (0, 0, 255):
            return result("ON", "爆发中")
        if raw_rgb == (255, 255, 0):
            return result("OFF", "未爆发")
        return result(hexc, "未知")
    if field_type == "distance":
        if raw == no_value:
            return result("—", "无目标/无值")
        if raw == unavailable:
            return result("—", "无目标（601 → 60.1 码，超出量程）")
        return result(f"{raw / 10:.1f}", "码")
    if field_type == "count":
        if raw == no_value:
            return result("—", "无值")
        if raw == unavailable:
            return result("—", unavailable_reason())
        if field_id == "aoe_mode":
            return result(str(raw), {0: "自动", 1: "单体", 2: "群体"}.get(raw, f"模式{raw}"))
        return result(str(raw), "个")
    if field_type == "cooldown":
        if raw == no_value:
            return result("—", "无值")
        if raw == unavailable:
            return result("—", unavailable_reason())
        return result(f"{raw / 10:.1f}", "秒")
    if field_type == "health":
        # 原生此分支直接显示 B；不夹到100，也不把白色作为无值。
        return result(str(b), "%")
    if field_type == "spell":
        if green:
            return result("可用")
        if red:
            return result("不可用")
        return result(hexc)
    if field_type == "playercast":
        if r == 0 and g == 255:
            return result("读条中", f"代次 {b}")
        if r == 255 and g == 0:
            return result("空闲", f"代次 {b}")
        return result(hexc)
    if field_type == "castcolor":
        return result(hexc, "颜色编码")
    if field_type == "isMoving":
        if raw == 0x35D50F:
            return result("—", "无绑定")
        return result(str(raw), "移动档位")
    if field_type == "number":
        return result(str(raw))
    raise AssertionError("SUPPORTED_TYPES 与分派实现不同步")


class PixelFieldDecoder:
    """把解包契约的配置与纯解码函数连接，方便统一解码所有职业字段。"""

    def __init__(self, contract: Mapping):
        self.constants = dict(contract.get("constants", {}))
        self.talent_groups = {k: tuple(v) for k, v in contract.get("talentGroups", {}).items()}
        self.sentinel601 = dict(contract.get("sentinel601", {}))

    def decode(self, field: Mapping, rgb: Sequence[int]) -> DecodedField:
        return decode_field(
            field["type"], rgb, field.get("id", ""), constants=self.constants,
            talent_groups=self.talent_groups, sentinel601=self.sentinel601,
        )
