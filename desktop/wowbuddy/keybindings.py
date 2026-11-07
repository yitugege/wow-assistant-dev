"""恢复原生绑定键解析，不调用任何 Windows 输入接口。

依据 FUN_1400a9aa0、键表构造 FUN_1400a8250，以及 SendInput 参数构造
FUN_1400ab770 的扩展键判据。修饰键顺序和非法输入保留原版行为。
"""

from dataclasses import dataclass
from types import MappingProxyType


_KEYS = {
    **{f"F{number}": 0x6F + number for number in range(1, 13)},
    **{str(number): 0x30 + number for number in range(10)},
    ";": 0xBA, ":": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD,
    ".": 0xBE, "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC,
    "]": 0xDD, "'": 0xDE,
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    **{f"NUMPAD{number}": 0x60 + number for number in range(10)},
    "NUMPADPLUS": 0x6B, "NUMPADMINUS": 0x6D, "NUMPADMULTIPLY": 0x6A,
    "NUMPADDIVIDE": 0x6F, "NUMPADDECIMAL": 0x6E,
    "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "ESCAPE": 0x1B,
    "BACKSPACE": 0x08, "CAPSLOCK": 0x14,
    **{chr(vk): vk for vk in range(0x41, 0x5B)},
}
KEY_VKS = MappingProxyType(_KEYS)
"""原生主键表的 91 项；两个 NUMPAD 同义词由解析器预处理。"""

_ALIASES = {"NUMPADADD": "NUMPADPLUS", "NUMPADSUBTRACT": "NUMPADMINUS"}
_PREFIXES = (("ALT-", 0x12), ("CTRL-", 0x11), ("SHIFT-", 0x10))
EXTENDED_VKS = frozenset((*range(0x21, 0x29), 0x2D, 0x2E, 0x6F))

# QString::trimmed 使用 QChar::isSpace；Python strip 还会去掉 U+001C–001F，
# 因此不能直接用无参数 strip。显式集合也避免把零宽空格当成空白。
_QT_WHITESPACE = (
    "\t\n\v\f\r \x85\xa0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)


@dataclass(frozen=True, slots=True)
class KeyBinding:
    """对应原生结果的 VK、修饰键序列、成功位与错误文字。

    非法主键仍保留此前识别出的修饰键，但 valid=False、vk=0。
    modifiers 的顺序是按下顺序；原生发送端以相反顺序释放修饰键。
    """

    vk: int = 0
    modifiers: tuple[int, ...] = ()
    valid: bool = False
    error: str = ""

    @property
    def extended(self) -> bool:
        return is_extended_key(self.vk)


def is_extended_key(vk: int) -> bool:
    """原版 SendInput 对 VK 标记 KEYEVENTF_EXTENDEDKEY 的精确集合。

    这里只提供判据，不生成扫描码，也不注入输入。
    """
    return vk in EXTENDED_VKS


def parse_keybinding(value: str) -> KeyBinding:
    """按原版顺序解析，返回成功或带诊断的失败结果。

    仅去掉整串首尾空白、转大写，然后依次尝试 ALT-、CTRL-、SHIFT-
    各一次。不会重排修饰键、去掉内部空格、接受加号分隔或猜测别名。
    非字符串不属于原生 QString 接口的输入域，在 Python 边界抛 TypeError。
    """
    if not isinstance(value, str):
        raise TypeError("绑定键必须是字符串")
    key = value.strip(_QT_WHITESPACE)
    if not key:
        return KeyBinding(error="绑定键名为空")

    key = key.upper()
    modifiers = []
    for prefix, vk in _PREFIXES:
        if key.startswith(prefix):
            modifiers.append(vk)
            key = key[len(prefix):]
    key = _ALIASES.get(key, key)
    vk = KEY_VKS.get(key)
    if vk is None:
        return KeyBinding(
            modifiers=tuple(modifiers),
            error=f"未知主键名：{key}（原始 {value}）",
        )
    return KeyBinding(vk, tuple(modifiers), True)
