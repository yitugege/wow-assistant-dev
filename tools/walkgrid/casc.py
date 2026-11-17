"""最小只读 CASC 读取器（寻路网格可行性验证 F1，实验脚本，不进仓库）。

只读打开本机客户端 Data 目录：.build.info → 构建配置 → 本地索引 → 数据文件 → BLTE → encoding → root。
"""
import os
import struct
import zlib
from pathlib import Path


def jenkins_hashlittle2(data: bytes, pc=0, pb=0):
    def rot(x, k):
        return ((x << k) | (x >> (32 - k))) & 0xFFFFFFFF
    length = len(data)
    a = b = c = (0xDEADBEEF + length + pc) & 0xFFFFFFFF
    c = (c + pb) & 0xFFFFFFFF
    i = 0
    while length > 12:
        a = (a + struct.unpack_from('<I', data, i)[0]) & 0xFFFFFFFF
        b = (b + struct.unpack_from('<I', data, i + 4)[0]) & 0xFFFFFFFF
        c = (c + struct.unpack_from('<I', data, i + 8)[0]) & 0xFFFFFFFF
        a = (a - c) & 0xFFFFFFFF; a ^= rot(c, 4); c = (c + b) & 0xFFFFFFFF
        b = (b - a) & 0xFFFFFFFF; b ^= rot(a, 6); a = (a + c) & 0xFFFFFFFF
        c = (c - b) & 0xFFFFFFFF; c ^= rot(b, 8); b = (b + a) & 0xFFFFFFFF
        a = (a - c) & 0xFFFFFFFF; a ^= rot(c, 16); c = (c + b) & 0xFFFFFFFF
        b = (b - a) & 0xFFFFFFFF; b ^= rot(a, 19); a = (a + c) & 0xFFFFFFFF
        c = (c - b) & 0xFFFFFFFF; c ^= rot(b, 4); b = (b + a) & 0xFFFFFFFF
        length -= 12
        i += 12
    if length == 0:
        return c, b
    tail = data[i:] + b'\0' * 12
    a = (a + struct.unpack_from('<I', tail, 0)[0]) & 0xFFFFFFFF
    if length > 4:
        b = (b + struct.unpack_from('<I', tail, 4)[0]) & 0xFFFFFFFF
    if length > 8:
        c = (c + struct.unpack_from('<I', tail, 8)[0]) & 0xFFFFFFFF
    # 只取 length 字节（tail 已补 0，等价于按字节掩码）
    c ^= b; c = (c - rot(b, 14)) & 0xFFFFFFFF
    a ^= c; a = (a - rot(c, 11)) & 0xFFFFFFFF
    b ^= a; b = (b - rot(a, 25)) & 0xFFFFFFFF
    c ^= b; c = (c - rot(b, 16)) & 0xFFFFFFFF
    a ^= c; a = (a - rot(c, 4)) & 0xFFFFFFFF
    b ^= a; b = (b - rot(a, 14)) & 0xFFFFFFFF
    c ^= b; c = (c - rot(b, 24)) & 0xFFFFFFFF
    return c, b


def name_hash(path: str) -> int:
    c, b = jenkins_hashlittle2(path.upper().replace('/', '\\').encode())
    return (c << 32) | b


class EncryptedError(Exception):
    pass


def blte(data: bytes) -> bytes:
    assert data[:4] == b'BLTE', data[:4]
    header_size = struct.unpack_from('>I', data, 4)[0]
    if header_size == 0:
        chunks = [(len(data) - 8, None)]
        pos = 8
    else:
        count = struct.unpack_from('>I', data, 8)[0] & 0xFFFFFF
        chunks = []
        for k in range(count):
            comp, decomp = struct.unpack_from('>II', data, 12 + k * 24)
            chunks.append((comp, decomp))
        pos = header_size
    out = []
    for comp, _ in chunks:
        chunk = data[pos:pos + comp]
        pos += comp
        mode = chunk[:1]
        if mode == b'N':
            out.append(chunk[1:])
        elif mode == b'Z':
            out.append(zlib.decompress(chunk[1:]))
        elif mode == b'E':
            raise EncryptedError('encrypted chunk')
        else:
            raise ValueError(f'BLTE mode {mode!r}')
    return b''.join(out)


class Casc:
    def __init__(self, data_root, product):
        self.root_dir = Path(data_root)
        info = (self.root_dir / '.build.info').read_text().splitlines()
        names = [h.split('!')[0] for h in info[0].split('|')]
        rows = [dict(zip(names, line.split('|'))) for line in info[1:] if line]
        row = next(r for r in rows if r['Product'] == product)
        self.version = row['Version']
        self.build = self._config(row['Build Key'])
        self._load_indices()
        enc_ekey = self.build['encoding'].split()[1]
        self._load_encoding(self.read_ekey(bytes.fromhex(enc_ekey)))
        self._load_root(self.read_ckey(bytes.fromhex(self.build['root'].split()[0])))

    def _config(self, key):
        text = (self.root_dir / 'Data' / 'config' / key[:2] / key[2:4] / key).read_text()
        out = {}
        for line in text.splitlines():
            if ' = ' in line:
                k, v = line.split(' = ', 1)
                out[k] = v
        return out

    def _load_indices(self):
        best = {}
        for name in os.listdir(self.root_dir / 'Data' / 'data'):
            if name.endswith('.idx'):
                bucket, version = int(name[:2], 16), int(name[2:10], 16)
                if bucket not in best or version > best[bucket][0]:
                    best[bucket] = (version, name)
        self.index = {}
        for _, name in best.values():
            raw = (self.root_dir / 'Data' / 'data' / name).read_bytes()
            header_size = struct.unpack_from('<I', raw, 0)[0]
            ver, bucket, extra, size_len, off_len, key_len, off_bits = struct.unpack_from('<HBBBBBB', raw, 8)
            pos = (8 + header_size + 15) & ~15
            entries_size = struct.unpack_from('<I', raw, pos)[0]
            pos += 8
            entry = key_len + off_len + size_len
            for p in range(pos, pos + entries_size, entry):
                key = raw[p:p + key_len]
                off = int.from_bytes(raw[p + key_len:p + key_len + off_len], 'big')
                size = int.from_bytes(raw[p + key_len + off_len:p + entry], 'little')
                archive, offset = off >> off_bits, off & ((1 << off_bits) - 1)
                self.index.setdefault(key, (archive, offset, size))
        self.key_len = key_len

    def read_ekey(self, ekey: bytes) -> bytes:
        archive, offset, size = self.index[ekey[:self.key_len]]
        with open(self.root_dir / 'Data' / 'data' / f'data.{archive:03d}', 'rb') as f:
            f.seek(offset)
            raw = f.read(size)
        return blte(raw[0x1E:])

    def _load_encoding(self, data):
        assert data[:2] == b'EN'
        ck, ek = data[3], data[4]
        page_kb, _, page_count, spec_count = struct.unpack_from('>HHII', data, 5)
        spec_size = struct.unpack_from('>I', data, 18)[0]
        pos = 22 + spec_size + page_count * 32
        page = page_kb * 1024
        self.encoding = {}
        for n in range(page_count):
            p, end = pos + n * page, pos + (n + 1) * page
            while p < end:
                keys = data[p]
                if keys == 0:
                    break
                ckey = data[p + 6:p + 6 + ck]
                self.encoding[ckey] = data[p + 6 + ck:p + 6 + ck + ek]
                p += 6 + ck + ek * keys

    def read_ckey(self, ckey: bytes) -> bytes:
        return self.read_ekey(self.encoding[ckey])

    def _load_root(self, data):
        self.by_fdid, self.by_hash = {}, {}
        magic, = struct.unpack_from('<I', data, 0)
        assert magic == 0x4D465354, hex(magic)   # 'TSFM'
        header_size, version = struct.unpack_from('<II', data, 4)
        if header_size == 0x18 or version in (1, 2):
            total, named = struct.unpack_from('<II', data, 12)
            pos = header_size
        else:
            version = 0
            total, named = struct.unpack_from('<II', data, 4)
            pos = 12
        self.root_version = version
        self.blocks = []
        while pos < len(data):
            if version == 2:
                count, locale, f1, f2, f3 = struct.unpack_from('<IIIIB', data, pos)
                content = f1 | f2 | (f3 << 17)
                pos += 17
            else:
                count, content, locale = struct.unpack_from('<III', data, pos)
                pos += 12
            fdid = -1
            ids = struct.unpack_from(f'<{count}i', data, pos)
            pos += 4 * count
            ckeys = [data[pos + 16 * i:pos + 16 * i + 16] for i in range(count)]
            pos += 16 * count
            hashes = None
            if not (content & 0x10000000) and named:
                hashes = struct.unpack_from(f'<{count}Q', data, pos)
                pos += 8 * count
            self.blocks.append((count, hex(content), hex(locale), hashes is not None))
            for i in range(count):
                fdid += ids[i] + 1
                self.by_fdid.setdefault(fdid, []).append(ckeys[i])
                if hashes:
                    self.by_hash.setdefault(hashes[i], fdid)

    def fdid(self, path):
        return self.by_hash.get(name_hash(path))

    def read_fdid(self, fdid):
        last = None
        for ckey in self.by_fdid[fdid]:
            try:
                return self.read_ckey(ckey)
            except KeyError as error:
                last = error
        raise last

    def read_path(self, path):
        return self.read_fdid(self.fdid(path))
