"""把地形与物件碰撞画成 1 码格（numpy）：原始受阻、外扩一格、墙边与坡度代价。"""
import math

import numpy as np

from walkgrid.terrain import CHUNK, ORIGIN, TILE, UNIT, interpolate, placement_transform, split_mcvt

FLAT = 10
NEAR_WALL = 255
WALL_MARGIN_YARDS = 3.0
WALL_MARGIN_COST = 20


def tile_range(bounds):
    """覆盖世界边界的 ADT 地块 (tx 范围, ty 范围)。"""
    tx = range(int(math.floor(32 - bounds['left'] / TILE)), int(math.floor(32 - bounds['right'] / TILE)) + 1)
    ty = range(int(math.floor(32 - bounds['top'] / TILE)), int(math.floor(32 - bounds['bottom'] / TILE)) + 1)
    return tx, ty


class TerrainMosaic:
    def __init__(self, world, tx_range, ty_range):
        nr, nc = len(ty_range) * 128, len(tx_range) * 128
        self.outer = np.full((nr + 1, nc + 1), np.nan)
        self.inner = np.full((nr, nc), np.nan)
        self.hole = np.zeros((nr, nc), bool)
        self.r0, self.c0 = ty_range[0] * 128, tx_range[0] * 128
        for ty in ty_range:
            for tx in tx_range:
                if (tx, ty) not in world.tiles:
                    continue
                for px, py, heights, holes in world.terrain_chunks(tx, ty):
                    gr = round((ORIGIN - px) / UNIT) - self.r0
                    gc = round((ORIGIN - py) / UNIT) - self.c0
                    outer, inner = split_mcvt(heights)
                    self.outer[gr:gr + 9, gc:gc + 9] = outer
                    self.inner[gr:gr + 8, gc:gc + 8] = inner
                    self.hole[gr:gr + 8, gc:gc + 8] = holes

    def height(self, wx, wy):
        fr = (ORIGIN - wx) / UNIT - self.r0
        fc = (ORIGIN - wy) / UNIT - self.c0
        r = np.clip(np.floor(fr).astype(int), 0, self.inner.shape[0] - 1)
        c = np.clip(np.floor(fc).astype(int), 0, self.inner.shape[1] - 1)
        return interpolate(self.outer, self.inner, fr, fc), self.hole[r, c]


def dilate(mask, steps=1):
    out = mask.copy()
    for _ in range(steps):
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        grown[1:, 1:] |= out[:-1, :-1]
        grown[1:, :-1] |= out[:-1, 1:]
        grown[:-1, 1:] |= out[1:, :-1]
        grown[:-1, :-1] |= out[1:, 1:]
        out = grown
    return out


def build(world, bounds, rows, cols, *, slope_limit=55.0, band=(0.6, 2.2), spacing=0.35, log=print):
    """返回 dict(cost=uint8[rows, cols], ground, steep, objects, holes, stats)。"""
    tx_range, ty_range = tile_range(bounds)
    mosaic = TerrainMosaic(world, tx_range, ty_range)
    top, left = bounds['top'], bounds['left']
    cell_x = (left - bounds['right']) / cols
    cell_y = (top - bounds['bottom']) / rows
    rr, cc = np.mgrid[0:rows, 0:cols]
    ground, holes = mosaic.height(top - (rr + .5) * cell_y, left - (cc + .5) * cell_x)
    missing = np.isnan(ground)
    ground = np.where(missing, np.nanmin(ground) if (~missing).any() else 0, ground)
    gy, gx = np.gradient(ground, cell_y, cell_x)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    steep = slope > slope_limit
    objects = np.zeros((rows, cols), bool)
    seen = set()
    stats = dict(tiles=len(tx_range) * len(ty_range), m2=0, wmo=0, triangles=0)
    for ty in ty_range:
        for tx in tx_range:
            if (tx, ty) not in world.tiles:
                continue
            m2s, wmos = world.placements(tx, ty)
            for kind, items in (('m2', m2s), ('wmo', wmos)):
                for uid, fid, pos, rot, scale in items:
                    if (kind, uid) in seen:
                        continue
                    seen.add((kind, uid))
                    try:
                        collision = world.m2_collision(fid) if kind == 'm2' else world.wmo_collision(fid)
                    except Exception as error:     # 单个模型读不出不影响整张图
                        log(f'跳过 {kind} {fid}：{error}')
                        continue
                    if collision is None:
                        continue
                    verts, idx = collision
                    w = placement_transform(verts, pos, rot, scale)
                    if (w[:, 0].max() < bounds['bottom'] or w[:, 0].min() > top
                            or w[:, 1].max() < bounds['right'] or w[:, 1].min() > left):
                        continue
                    stats[kind] += 1
                    stats['triangles'] += len(idx)
                    _rasterize(w, idx, top, left, cell_x, cell_y, rows, cols, mosaic, objects, band, spacing)
    raw = steep | objects | holes | missing
    near = dilate(raw, 1) & ~raw
    cost = (FLAT + np.round(np.clip(slope, 0, slope_limit) / slope_limit * 10)).astype(np.int32)
    margin_steps = max(1, math.ceil(WALL_MARGIN_YARDS / min(cell_x, cell_y)))
    previous = raw
    for step in range(1, margin_steps + 1):
        ring = dilate(raw, step) & ~previous
        yards = step * min(cell_x, cell_y)
        cost[ring] += round(WALL_MARGIN_COST * max(0.0, 1 - yards / WALL_MARGIN_YARDS))
        previous = previous | ring
    cost = np.clip(cost, FLAT, 254).astype(np.uint8)
    cost[near] = NEAR_WALL
    cost[raw] = 0
    stats.update(steep=int(steep.sum()), objects=int(objects.sum()), holes=int((holes | missing).sum()),
                 blocked=float(raw.mean()))
    return dict(cost=cost, ground=ground, steep=steep, objects=objects, holes=holes | missing, stats=stats)


def _rasterize(w, idx, top, left, cell_x, cell_y, rows, cols, mosaic, objects, band, spacing):
    a, b, c = w[idx[:, 0]], w[idx[:, 1]], w[idx[:, 2]]
    edge = np.maximum(np.linalg.norm(b - a, axis=1),
                      np.maximum(np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)))
    n = np.maximum(1, np.ceil(edge / spacing)).astype(int)
    pts = []
    for k in np.unique(n):
        sel = n == k
        i, j = np.mgrid[0:k + 1, 0:k + 1]
        m = (i + j) <= k
        l1 = (i[m] / k)[None, :, None]
        l2 = (j[m] / k)[None, :, None]
        p = a[sel][:, None, :] * (1 - l1 - l2) + b[sel][:, None, :] * l1 + c[sel][:, None, :] * l2
        pts.append(p.reshape(-1, 3))
    p = np.concatenate(pts)
    r = ((top - p[:, 0]) / cell_y).astype(int)
    cc = ((left - p[:, 1]) / cell_x).astype(int)
    ok = (r >= 0) & (r < rows) & (cc >= 0) & (cc < cols)
    p, r, cc = p[ok], r[ok], cc[ok]
    ground, _ = mosaic.height(top - (r + .5) * cell_y, left - (cc + .5) * cell_x)
    dz = p[:, 2] - ground
    hit = (dz > band[0]) & (dz < band[1])
    objects[r[hit], cc[hit]] = True


def preview(cost, ground):
    """RGB 预览：地形明暗，红 = 原始受阻，深红 = 贴墙，绿色深浅 = 通行代价。"""
    gy, gx = np.gradient(ground)
    shade = np.clip(0.55 + 0.45 * (-gx + gy) / (np.hypot(gx, gy) + 0.6), 0.15, 1)
    rgb = np.stack([70 + 0 * shade, 120 * shade + 40, 60 + 0 * shade], -1)
    rgb[cost == NEAR_WALL] = (150, 60, 50)
    rgb[cost == 0] = (220, 40, 40)
    return rgb.astype(np.uint8)
