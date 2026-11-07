"""0155D0安装解析路径；独立于packages中的严格审计读取器。"""
from .packages import Member,PackageError,Reader
from .qt_utf8 import decode_qt_utf8


def read_install_addon(data: bytes) -> list[Member]:
    from PySide6.QtCore import qUncompress
    reader=Reader(data)
    if len(data)<13 or reader.take(9)!=b'WBADDON1\n':
        raise PackageError('内嵌插件包损坏（magic 不匹配）')
    count=reader.integer('<I')
    if count>4096:
        raise PackageError(f'内嵌插件包条目数异常：{count}')
    members=[]
    for _ in range(count):
        # 原循环缺少下一项长度头时跳出，最终仅以已解析成员是否非空返回。
        if reader.offset+2>len(data):break
        name_size=reader.integer('<H')
        # 原版将名称和随后四字节数据长度头合并检查。
        if reader.offset+name_size+4>len(data):
            raise PackageError('内嵌插件包截断（条目名）')
        name=decode_qt_utf8(reader.take(name_size))
        compressed_size=reader.integer('<I')
        if reader.offset+compressed_size>len(data):
            raise PackageError('内嵌插件包截断（条目数据）')
        compressed=reader.take(compressed_size)
        raw=bytes(qUncompress(compressed))
        if not raw and compressed:
            raise PackageError('条目解压失败：'+name)
        members.append(Member(name,raw,compressed))
    if not members:
        # 原返回false而不设置错误QString；不能制造一个成功空包。
        raise PackageError('')
    # 原解析保留同名条目及顺序；不检查容器/压缩流尾随字节。
    return members
