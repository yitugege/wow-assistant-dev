"""保存当前帧（docs/design/20261115-assistant-mcp.md）。

只裁剪像素条所在的左侧窄条（按协议几何），不保存整窗画面；写 PNG 与同名 JSON，
供把游戏现场写成离线复现测试：read_png(path) 得到可直接交给 pipeline.decode 的 RGBImage。
本模块不导入 Qt，PNG 用标准库 zlib 编解码。
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from math import ceil
from pathlib import Path
import json
import struct
import zlib

from wowbuddy.core.pixel_geometry import RGBImage

PER_MINUTE = 10
KEEP = 50
_BAR_COLUMNS = 3     # 像素条宽两格，多留一格余量
_MARGIN = 2


class DumpRefused(Exception):
    """无有效帧或超出频率限制。"""


def crop_bar(image: RGBImage, geometry) -> RGBImage:
    width = min(image.width, ceil(geometry.origin_x + geometry.anchor_x + _BAR_COLUMNS * geometry.pitch) + _MARGIN)
    return RGBImage([row[:width] for row in image.rows])


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def encode_png(image: RGBImage) -> bytes:
    raw = bytearray()
    for row in image.rows:
        raw.append(0)
        for pixel in row:
            raw += bytes(((pixel >> 16) & 0xff, (pixel >> 8) & 0xff, pixel & 0xff))
    header = struct.pack('>IIBBBBB', image.width, image.height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', header) + _chunk(b'IDAT', zlib.compress(bytes(raw), 6))
            + _chunk(b'IEND', b''))


def read_png(path) -> RGBImage:
    """读取本模块写出的 8 位 RGB PNG（过滤类型 0）。"""
    data = Path(path).read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('不是 PNG 文件')
    offset, chunks = 8, {}
    idat = b''
    while offset < len(data):
        length, = struct.unpack('>I', data[offset:offset + 4])
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b'IDAT':
            idat += body
        else:
            chunks[kind] = body
    width, height, depth, color, _, _, interlace = struct.unpack('>IIBBBBB', chunks[b'IHDR'])
    if (depth, color, interlace) != (8, 2, 0):
        raise ValueError('只支持 8 位 RGB、非隔行 PNG')
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = []
    for y in range(height):
        line = raw[y * stride:(y + 1) * stride]
        if line[0] != 0:
            raise ValueError('只支持无过滤的 PNG 行')
        rows.append([(line[1 + 3 * x] << 16) | (line[2 + 3 * x] << 8) | line[3 + 3 * x] for x in range(width)])
    return RGBImage(rows)


class FrameDumper:
    def __init__(self, data_dir, *, per_minute: int = PER_MINUTE, keep: int = KEEP):
        self.directory = Path(data_dir) / 'frames'
        self.per_minute, self.keep = per_minute, keep
        self._recent = deque()

    def dump(self, image, frame, extra: dict, *, now: float) -> str:
        """写出 PNG + JSON，返回 PNG 路径；无有效帧或超频时抛 DumpRefused。"""
        if image is None or frame is None:
            raise DumpRefused('还没有抓到画面（需先开始监控）。')
        geometry = getattr(frame, 'geometry', None)
        if not getattr(frame, 'ok', False) or geometry is None:
            raise DumpRefused(f'当前帧无效：{getattr(frame, "status", "未知")}')
        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        if len(self._recent) >= self.per_minute:
            raise DumpRefused(f'每分钟最多保存 {self.per_minute} 帧。')
        self._recent.append(now)
        self.directory.mkdir(parents=True, exist_ok=True)
        stem = datetime.fromtimestamp(now).strftime('%Y%m%d-%H%M%S-') + f'{int(now * 1000) % 1000:03d}'
        path = self.directory / f'{stem}.png'
        number = 1
        while path.exists():
            number += 1
            path = self.directory / f'{stem}-{number}.png'
        path.write_bytes(encode_png(crop_bar(image, geometry)))
        meta = dict(extra, saved_at=now, status=frame.status, protocol=getattr(frame, 'protocol', None),
                    spec_id=getattr(frame, 'spec_id', None), geometry=vars(geometry) if hasattr(geometry, '__dict__')
                    else str(geometry), fields=dict(frame.values), source_size=[image.width, image.height])
        path.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), 'utf-8')
        self._prune()
        return str(path)

    def _prune(self):
        frames = sorted(self.directory.glob('*.png'), key=lambda item: item.name)
        for old in frames[:-self.keep] if len(frames) > self.keep else ():
            for item in (old, old.with_suffix('.json')):
                try:
                    item.unlink()
                except OSError:
                    pass
