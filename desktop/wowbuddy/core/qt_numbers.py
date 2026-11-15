"""原程序 Qt 十进制整数转换（QString::toInt / toLongLong，base 10）的统一实现。"""
import re

_DECIMAL = re.compile(r"[+-]?[0-9]+")


def qt_to_int(text: str, bits: int = 64) -> int | None:
    """在 NUL 处截断、只去 ASCII 空白（不做 Unicode trimmed），允许任意前导零。

    bits 为 32（toInt）或 64（toLongLong）；格式非法或超出有符号范围时返回 None，
    失败时的替代值（-1 或 None）由调用方决定。先按有效位数限长，避免 Python 长整数转换上限异常。
    """
    text = text.split("\0", 1)[0].strip(" \t\n\r\v\f")
    if not _DECIMAL.fullmatch(text):
        return None
    digits = text.lstrip("+-").lstrip("0") or "0"
    if len(digits) > (19 if bits == 64 else 10):
        return None
    value = int(digits) * (-1 if text.startswith("-") else 1)
    limit = 1 << (bits - 1)
    return value if -limit <= value < limit else None
