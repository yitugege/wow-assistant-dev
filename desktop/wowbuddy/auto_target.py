"""还原 TTD 载体中的自动选怪包；不决定发键，也不改变战斗闸门。

证据：主程序 FUN_14003cba0、FUN_14003b5c0 和 0x1400d2820 的
27 项原生字符串指针表。参见 evidence/像素协议.md。
"""

from dataclasses import dataclass
import math


PACKET_BASE = 0xD00000
_BASE_KEYS = (
    "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "8", "9", "0", "-", "=", "[", "]", ";", "'", ",", ".", "\\",
    "UP", "DOWN", "LEFT", "RIGHT", "INSERT", "DELETE", "HOME", "END",
)


@dataclass(frozen=True, slots=True)
class AutoTargetPacket:
    """原生成功解码结果；state 数字保持原样，不据此推定应发键。"""

    key_index: int
    state: int
    ack: int
    sequence: int
    key: str


def key_for_index(index: int) -> str:
    """03b5c0：81项键表，边界外返回空字符串。"""
    if not 1 <= index <= 81:
        return ""
    group, key_offset = divmod(index - 1, 27)
    return ("", "CTRL-", "ALT-")[group] + _BASE_KEYS[key_offset]


def parse_auto_target(value: int | float) -> AutoTargetPacket | None:
    """解析原生可接受的包，非法值返回 None。

    原生参数是 double，转整数时截断小数；因此 0.9 的小数尾数不会
    改变一个有效包。Python 边界额外拒绝 bool、字符串、NaN 和无穷值，
    避免语言自动转换把无效输入误当作像素数据。实际像素载体是整数。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value <= 0:
        return None
    packed = int(value)
    if packed < PACKET_BASE:
        return None
    key_index, rest = divmod(packed - PACKET_BASE, 8192)
    # 接收端只支持 27 基础键、27 CTRL 键、27 ALT 键。
    # Lua 的 127 项上限不是这个原生解析器的接受范围。
    if not 1 <= key_index <= 81:
        return None
    state, rest = divmod(rest, 1024)
    ack, sequence = divmod(rest, 32)
    if not (0 <= state <= 4 and 0 <= ack <= 31 and 1 <= sequence <= 31):
        return None
    return AutoTargetPacket(key_index, state, ack, sequence, key_for_index(key_index))
