"""按原程序 QString 语义处理文本：长度以 UTF-16 单元计，%N 占位符按编号下降替换。"""


def utf16_units(text: str) -> int:
    """QString::size：UTF-16 单元数（CJK 记 1，增补平面字符记 2），不是终端显示列宽。"""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def utf16_pad(text: str, width: int) -> str:
    """QString::leftJustified(width)：不足 width 个 UTF-16 单元时在右侧补空格，超出不截断。"""
    return text + " " * max(0, width - utf16_units(text))


def utf16_left(text: str, units: int) -> str:
    """QString::left(units)：取前 units 个 UTF-16 单元。"""
    return text.encode("utf-16-le", "surrogatepass")[:units * 2].decode("utf-16-le", "surrogatepass")


def substitute_descending(template: str, *values: object) -> str:
    """把 %1..%N 依次替换为 values；编号从大到小替换，避免 %1 先吃掉 %10 的前缀。

    只适用于替换值本身不含占位符的自测模板；界面文本的 Qt arg 语义见 wowbuddy.qt_arg。
    """
    for index in range(len(values), 0, -1):
        template = template.replace(f"%{index}", str(values[index - 1]))
    return template
