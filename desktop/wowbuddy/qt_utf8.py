"""原QString::fromUtf8解码语义，供TOC内容和包成员名称共用。"""

def decode_qt_utf8(data: bytes) -> str:
    """QString::fromUtf8：去掉首个BOM，每个非法字节生成一个替代字符。"""
    data = data.removeprefix(b"\xef\xbb\xbf")
    parts = []
    offset = 0
    while offset < len(data):
        try:
            parts.append(data[offset:].decode("utf-8"))
            break
        except UnicodeDecodeError as error:
            parts.append(data[offset:offset + error.start].decode("utf-8"))
            parts.append("\ufffd" * (error.end - error.start))
            offset += error.end
    return "".join(parts)


