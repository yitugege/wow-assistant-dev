"""本项目所用的 QString 占位符替换和固定一位小数格式。"""
from decimal import Decimal, ROUND_HALF_UP
import re


_PLACEHOLDER = re.compile(r'%(L?)([0-9]{1,2})')


def one_decimal(value: float) -> str:
    return str(Decimal.from_float(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def qt_arg(template: str, *values: str | int | float) -> str:
    """一次替换最低的编号，同批文本不重扫。数值遵循原调用的十进制或 f/1 格式。"""
    indices = sorted({int(match[2]) for match in _PLACEHOLDER.finditer(template)})
    replacements = dict(zip(indices, values))

    def replace(match: re.Match[str]) -> str:
        value = replacements.get(int(match[2]))
        if value is None:
            return match[0]
        if match[1] and not isinstance(value, str):
            from PySide6.QtCore import QLocale
            locale = QLocale()
            return locale.toString(value, 'f', 1) if isinstance(value, float) else locale.toString(value)
        return one_decimal(value) if isinstance(value, float) else str(value)

    return _PLACEHOLDER.sub(replace, template)
