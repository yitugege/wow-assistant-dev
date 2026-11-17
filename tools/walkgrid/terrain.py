"""从本机客户端文件读取地形高度与物件碰撞（只读；docs/design/20261116-walk-grid-pathing.md）。

坐标约定：世界 X 向北、Y 向西、Z 向上；ADT 地块 (tx, ty) 中 tx 沿 Y、ty 沿 X。
物件摆放按 TrinityCore mmaps 的约定换算（v·R·s + p，再取反 X、Y）。2026-11-16 核对：赤脊山 62 个建筑的
模型包围盒按此换算后，与 MODF 记录的摆放包围盒最大相差 0.002 码；偏航取反时最大相差 139 码。
"""
from functools import lru_cache
import math
import struct

import numpy as np

TILE = 1600 / 3          # 533.333 码
CHUNK = TILE / 16
UNIT = CHUNK / 8
ORIGIN = 32 * TILE       # 17066.667

# 大陆 WDT 文件编号（wowf 1.60.1）
CONTINENT_WDT = {'eastern_kingdoms': 775971, 'kalimdor': 782779}
MAP_CONTINENT = {1433: 'eastern_kingdoms'}


def chunks(data):
    """遍历 IFF 块。ADT/WDT/WMO 的标记倒序存放（'REVM'），M2 的 'MD21' 不倒序，两者都原样返回倒序后的标记。"""
    p = 0
    while p + 8 <= len(data):
        tag = data[p:p + 4][::-1].decode('latin1')
        size = struct.unpack_from('<I', data, p + 4)[0]
        yield tag, data[p + 8:p + 8 + size]
        p += 8 + size


def split_mcvt(heights):
    """MCVT 145 个高度 → 外点 9×9、内点 8×8（行沿 X 递减，列沿 Y 递减）。"""
    heights = np.asarray(heights, dtype=np.float64)
    outer = np.empty((9, 9))
    inner = np.empty((8, 8))
    k = 0
    for row in range(17):
        if row % 2 == 0:
            outer[row // 2] = heights[k:k + 9]
            k += 9
        else:
            inner[row // 2] = heights[k:k + 8]
            k += 8
    return outer, inner


def interpolate(outer, inner, fr, fc):
    """外点网格 outer[R+1, C+1]、内点 inner[R, C] 上，按每格四个三角形插值浮点行列 (fr, fc) 处的高度。"""
    r = np.clip(np.floor(fr).astype(int), 0, inner.shape[0] - 1)
    c = np.clip(np.floor(fc).astype(int), 0, inner.shape[1] - 1)
    u = fr - r
    v = fc - c
    h00, h01 = outer[r, c], outer[r, c + 1]
    h10, h11 = outer[r + 1, c], outer[r + 1, c + 1]
    hc = inner[r, c]
    du, dv = u - 0.5, v - 0.5
    top = du <= -np.abs(dv)
    bottom = du >= np.abs(dv)
    left = ~top & ~bottom & (dv < 0)
    right = ~top & ~bottom & ~left
    out = np.empty_like(np.asarray(u, dtype=np.float64))

    def tri(mask, pa, pb, ha, hb):
        ua, va = pa
        ub, vb = pb
        uu, vv = u[mask], v[mask]
        det = (ua - .5) * (vb - .5) - (ub - .5) * (va - .5)
        la = ((uu - .5) * (vb - .5) - (ub - .5) * (vv - .5)) / det
        lb = ((ua - .5) * (vv - .5) - (uu - .5) * (va - .5)) / det
        out[mask] = hc[mask] + la * (ha[mask] - hc[mask]) + lb * (hb[mask] - hc[mask])

    tri(top, (0, 0), (0, 1), h00, h01)
    tri(bottom, (1, 0), (1, 1), h10, h11)
    tri(left, (0, 0), (1, 0), h00, h10)
    tri(right, (0, 1), (1, 1), h01, h11)
    return out


def placement_transform(verts, pos, rot, scale):
    """模型坐标 → 世界坐标。pos、rot 为 MDDF/MODF 原始值（rot 为度）。"""
    rx, ry, rz = (math.radians(a) for a in rot)
    a, b, c = -rz, -rx, -ry
    rot_x = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    rot_y = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    rot_z = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    matrix = rot_x @ rot_y @ rot_z
    ipos = np.array([pos[2] - ORIGIN, pos[0] - ORIGIN, pos[1]])
    world = np.asarray(verts, dtype=np.float64) @ matrix * scale + ipos
    world[:, 0] *= -1
    world[:, 1] *= -1
    return world


class World:
    def __init__(self, casc, continent):
        self.casc = casc
        wdt = dict(chunks(casc.read_fdid(CONTINENT_WDT[continent])))
        maid = struct.unpack('<%dI' % (64 * 64 * 8), wdt['MAID'])
        self.tiles = {}
        for i in range(64 * 64):
            entry = maid[i * 8:i * 8 + 8]
            if entry[0]:
                self.tiles[(i % 64, i // 64)] = entry

    def terrain_chunks(self, tx, ty):
        """[(px, py, heights(145), holes(8×8))]，px/py 为地形块西北角的世界 X/Y。"""
        out = []
        for tag, d in chunks(self.casc.read_fdid(self.tiles[(tx, ty)][0])):
            if tag != 'MCNK':
                continue
            flags = struct.unpack_from('<I', d, 0)[0]
            px, py, pz = struct.unpack_from('<3f', d, 0x68)
            holes = np.zeros((8, 8), bool)
            if flags & 0x10000:
                raw = d[0x14:0x1C]
                for r in range(8):
                    for c in range(8):
                        holes[r, c] = (raw[r] >> c) & 1
            else:
                low = struct.unpack_from('<H', d, 0x3C)[0]
                for r in range(4):
                    for c in range(4):
                        if low & (1 << (r * 4 + c)):
                            holes[r * 2:r * 2 + 2, c * 2:c * 2 + 2] = True
            heights = None
            for sub, sd in chunks(d[0x80:]):
                if sub == 'MCVT':
                    heights = np.array(struct.unpack('<145f', sd[:580])) + pz
                    break
            if heights is not None:
                out.append((px, py, heights, holes))
        return out

    def placements(self, tx, ty):
        m2, wmo = [], []
        for tag, d in chunks(self.casc.read_fdid(self.tiles[(tx, ty)][1])):
            if tag == 'MDDF':
                for p in range(0, len(d), 36):
                    fid, uid = struct.unpack_from('<II', d, p)
                    pos = struct.unpack_from('<3f', d, p + 8)
                    rot = struct.unpack_from('<3f', d, p + 20)
                    scale, flags = struct.unpack_from('<HH', d, p + 32)
                    if flags & 0x40:
                        m2.append((uid, fid, pos, rot, scale / 1024))
            elif tag == 'MODF':
                for p in range(0, len(d), 64):
                    fid, uid = struct.unpack_from('<II', d, p)
                    pos = struct.unpack_from('<3f', d, p + 8)
                    rot = struct.unpack_from('<3f', d, p + 20)
                    flags, _doodad_set, _name_set, scale = struct.unpack_from('<HHHH', d, p + 56)
                    if flags & 0x8:
                        wmo.append((uid, fid, pos, rot, scale / 1024 if flags & 0x4 else 1.0))
        return m2, wmo

    @lru_cache(maxsize=None)
    def m2_collision(self, fid):
        data = self.casc.read_fdid(fid)
        md20 = data if data[:4] == b'MD20' else None
        if md20 is None:
            for tag, sd in chunks(data):
                if tag in ('MD21', '12DM'):
                    md20 = sd
                    break
        if md20 is None:
            return None
        ni, oi = struct.unpack_from('<II', md20, 0xD8)
        nv, ov = struct.unpack_from('<II', md20, 0xE0)
        if not ni or not nv:
            return None
        idx = np.frombuffer(md20, '<u2', ni, oi).reshape(-1, 3).astype(np.int32)
        verts = np.frombuffer(md20, '<f4', nv * 3, ov).reshape(-1, 3).astype(np.float64)
        return verts, idx

    @lru_cache(maxsize=None)
    def wmo_collision(self, fid):
        root = dict(chunks(self.casc.read_fdid(fid)))
        gfid = root.get('GFID', b'')
        groups = [g for g in struct.unpack('<%dI' % (len(gfid) // 4), gfid) if g]
        all_v, all_i, base = [], [], 0
        for group in groups:
            mogp = None
            for tag, sd in chunks(self.casc.read_fdid(group)):
                if tag == 'MOGP':
                    mogp = sd
            if mogp is None:
                continue
            sub = {}
            for tag, sd in chunks(mogp[0x44:]):
                sub.setdefault(tag, sd)
            if 'MOVT' not in sub or 'MOVI' not in sub:
                continue
            verts = np.frombuffer(sub['MOVT'], '<f4').reshape(-1, 3).astype(np.float64)
            idx = np.frombuffer(sub['MOVI'], '<u2').reshape(-1, 3).astype(np.int32)
            if 'MOPY' in sub:
                mopy = np.frombuffer(sub['MOPY'], np.uint8).reshape(-1, 2)
                if len(mopy) == len(idx):
                    flags = mopy[:, 0]
                    render = ((flags & 0x20) != 0) & ((flags & 0x04) == 0)
                    idx = idx[((flags & 0x08) != 0) | render]
            all_v.append(verts)
            all_i.append(idx + base)
            base += len(verts)
        if not all_v:
            return None
        return np.concatenate(all_v), np.concatenate(all_i)
