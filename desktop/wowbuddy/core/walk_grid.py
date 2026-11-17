"""地图可走格子与 A* 规划（docs/design/20261116-walk-grid-pathing.md）。

只用标准库。格子以“地图百分比”为坐标：第 r 行、第 c 列覆盖 x∈[c, c+1)·100/cols、y∈[r, r+1)·100/rows。
每格一个字节：0 = 原始受阻（墙、陡坡、空洞）；255 = 角色半径外扩（贴墙不可站）；1–254 = 通行代价（10 为平地）。
"""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import json
import math
import zlib

MAGIC = b'WBDGRID1'
BLOCKED = 0
NEAR_WALL = 255
FLAT = 10
_SQRT2 = math.sqrt(2)
_SNAP_YARDS = 6.0
_SELF_YARDS = 0.75
_BODY_YARDS = 0.5          # 检查连线时角色左右各留的宽度
_SEGMENT_YARDS = 20.0
_CORNER_YARDS = 5.0
_WALL_MARGIN_YARDS = 3.0
_WALL_MARGIN_COST = 20


@dataclass(frozen=True, slots=True)
class GridPath:
    points: tuple[tuple[float, float], ...]     # 地图百分比，首点为起点、末点为终点
    yards: float
    expanded: int


class WalkGrid:
    def __init__(self, *, map_id, rows, cols, width, height, cost, meta=None):
        if len(cost) != rows * cols:
            raise ValueError('格子数据长度与行列数不符')
        self.map_id, self.rows, self.cols = int(map_id), int(rows), int(cols)
        self.width, self.height = float(width), float(height)
        self.meta = dict(meta or {})
        self._cost = bytes(cost)
        self._temporary = {}          # 填充后下标 → 到期时刻（None 为不过期）
        # 外围补一圈受阻格，搜索时不必判断越界。
        stride = self.cols + 2
        padded = bytearray(stride * (self.rows + 2))
        for r in range(self.rows):
            start = (r + 1) * stride + 1
            padded[start:start + self.cols] = self._cost[r * self.cols:(r + 1) * self.cols]
        self._padded = padded
        self._stride = stride
        self.cell_x = self.width / self.cols         # 每格码数
        self.cell_y = self.height / self.rows

    # ---------- 读写 ----------
    @classmethod
    def from_blocked(cls, *, map_id, rows, cols, width, height, blocked, meta=None):
        """由原始受阻格集合生成：外扩一格为贴墙，墙边 3 码内加代价（测试与小图用，纯 Python）。"""
        cost = bytearray([FLAT]) * (rows * cols)
        cell = min(width / cols, height / rows)
        reach = max(1, math.ceil(_WALL_MARGIN_YARDS / cell))
        for r, c in blocked:
            for dr in range(-reach, reach + 1):
                for dc in range(-reach, reach + 1):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        index = nr * cols + nc
                        if max(abs(dr), abs(dc)) <= 1:
                            if cost[index] != BLOCKED:
                                cost[index] = NEAR_WALL
                        elif cost[index] not in (BLOCKED, NEAR_WALL):
                            yards = math.hypot(dr, dc) * cell
                            extra = round(_WALL_MARGIN_COST * max(0.0, 1 - yards / _WALL_MARGIN_YARDS))
                            cost[index] = max(cost[index], min(254, FLAT + extra))
        for r, c in blocked:
            if 0 <= r < rows and 0 <= c < cols:
                cost[r * cols + c] = BLOCKED
        return cls(map_id=map_id, rows=rows, cols=cols, width=width, height=height, cost=cost, meta=meta)

    @classmethod
    def from_bytes(cls, data):
        if not data.startswith(MAGIC + b'\n'):
            raise ValueError('不是地图格子文件')
        end = data.index(b'\n', len(MAGIC) + 1)
        header = json.loads(data[len(MAGIC) + 1:end].decode('utf-8'))
        if header.get('version') != 1:
            raise ValueError('地图格子文件版本不符')
        cost = zlib.decompress(data[end + 1:])
        return cls(map_id=header['map_id'], rows=header['rows'], cols=header['cols'], width=header['width'],
                   height=header['height'], cost=cost, meta=header.get('meta'))

    def to_bytes(self):
        header = dict(version=1, map_id=self.map_id, rows=self.rows, cols=self.cols, width=self.width,
                      height=self.height, meta=self.meta)
        return (MAGIC + b'\n' + json.dumps(header, ensure_ascii=False).encode('utf-8') + b'\n'
                + zlib.compress(self._cost, 9))

    # ---------- 坐标 ----------
    def cell_of(self, x, y):
        """地图百分比 → 浮点行列。"""
        return y / 100 * self.rows, x / 100 * self.cols

    def point_of(self, r, c):
        """格子中心 → 地图百分比。"""
        return (c + .5) * 100 / self.cols, (r + .5) * 100 / self.rows

    def cost_at(self, r, c):
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return BLOCKED
        index = (r + 1) * self._stride + c + 1
        if index in self._temporary:
            return BLOCKED
        return self._padded[index]

    def _yards(self, dr, dc):
        return math.hypot(dr * self.cell_y, dc * self.cell_x)

    # ---------- 临时障碍 ----------
    def block_ahead(self, x, y, heading, *, near=1.0, far=3.0, half_width=1.5, expires=None):
        """把朝向前方 near–far 码、左右 half_width 码内的可走格记为临时障碍（只在内存，expires 到期后失效）。"""
        east, north = -math.sin(heading), math.cos(heading)
        r0, c0 = self.cell_of(x, y)
        reach = far + half_width
        marked = 0
        for r in range(int(r0 - reach / self.cell_y) - 1, int(r0 + reach / self.cell_y) + 2):
            for c in range(int(c0 - reach / self.cell_x) - 1, int(c0 + reach / self.cell_x) + 2):
                if not (0 <= r < self.rows and 0 <= c < self.cols):
                    continue
                de = (c + .5 - c0) * self.cell_x
                dn = (r0 - (r + .5)) * self.cell_y
                along = de * east + dn * north
                across = abs(-de * north + dn * east)
                if near <= along <= far and across <= half_width:
                    index = (r + 1) * self._stride + c + 1
                    if self._padded[index] != BLOCKED and index not in self._temporary:
                        self._temporary[index] = expires
                        marked += 1
        return marked

    def clear_temporary(self):
        self._temporary.clear()

    def expire_temporary(self, now):
        stale = [index for index, expires in self._temporary.items() if expires is not None and expires <= now]
        for index in stale:
            del self._temporary[index]
        return len(stale)

    @property
    def temporary_count(self):
        return len(self._temporary)

    # ---------- 吸附 ----------
    def _standable(self, r, c):
        value = self.cost_at(r, c)
        return value != BLOCKED and value != NEAR_WALL

    def _line_clear(self, r1, c1, r2, c2, *, standable, skip_near=None, body=0.0):
        """浮点行列之间按 0.25 格采样。standable 为真时贴墙格也算不通；skip_near 为起点附近豁免半径（码）；
        body 为角色半宽（码），大于 0 时左右平移 body 码各再查一条线。"""
        if body > 0:
            east, south = (c2 - c1) * self.cell_x, (r2 - r1) * self.cell_y
            length = math.hypot(east, south)
            if length > 0:
                dr, dc = east / length * body / self.cell_y, -south / length * body / self.cell_x
                for sign in (1, -1):
                    if not self._line_clear(r1 + sign * dr, c1 + sign * dc, r2 + sign * dr, c2 + sign * dc,
                                            standable=standable, skip_near=skip_near):
                        return False
        steps = max(1, int(max(abs(r2 - r1), abs(c2 - c1)) * 4))
        own = int(r1), int(c1)
        for k in range(steps + 1):
            r = r1 + (r2 - r1) * k / steps
            c = c1 + (c2 - c1) * k / steps
            # 豁免起点附近：角色所在的这一格（物件只占格子一部分），以及 skip_near 码以内。
            if skip_near is not None and ((int(r), int(c)) == own or self._yards(r - r1, c - c1) <= skip_near):
                continue
            value = self.cost_at(int(r), int(c))
            if value == BLOCKED or (standable and value == NEAR_WALL):
                return False
        return True

    def snap(self, x, y, *, radius=_SNAP_YARDS, prefer=None):
        """返回最近的可站格 (r, c)。所在格可站则直接返回；否则在 radius 码内找、且从精确位置连线不穿原始受阻格。"""
        fr, fc = self.cell_of(x, y)
        r, c = int(fr), int(fc)
        if self._standable(r, c):
            return r, c
        pr, pc = self.cell_of(*prefer) if prefer is not None else (None, None)
        reach_r, reach_c = int(radius / self.cell_y) + 1, int(radius / self.cell_x) + 1
        best = None
        for nr in range(r - reach_r, r + reach_r + 1):
            for nc in range(c - reach_c, c + reach_c + 1):
                if not self._standable(nr, nc):
                    continue
                yards = self._yards(nr + .5 - fr, nc + .5 - fc)
                if yards > radius:
                    continue
                if not self._line_clear(fr, fc, nr + .5, nc + .5, standable=False, skip_near=_SELF_YARDS,
                                        body=_BODY_YARDS):
                    continue
                score = yards if pr is None else yards + self._yards(nr + .5 - pr, nc + .5 - pc)
                if best is None or score < best[0]:
                    best = score, (nr, nc)
        return best[1] if best else None

    # ---------- 规划 ----------
    def find_path(self, start, goal, *, max_expansions=400_000, prefer=None, ignore_temporary=False):
        """start、goal 为地图百分比 (x, y)。返回 (GridPath, None) 或 (None, 原因)。"""
        if ignore_temporary:
            saved, self._temporary = self._temporary, {}
            try:
                return self.find_path(start, goal, max_expansions=max_expansions, prefer=prefer)
            finally:
                self._temporary = saved
        source = self.snap(*start, prefer=prefer)
        if source is None:
            return None, '起点附近没有可走格子'
        target = self.snap(*goal)
        if target is None:
            return None, '目标附近没有可走格子'
        stride = self._stride
        grid = self._padded
        temporary = self._temporary
        s = (source[0] + 1) * stride + source[1] + 1
        g = (target[0] + 1) * stride + target[1] + 1
        gr, gc = divmod(g, stride)
        cy, cx = self.cell_y, self.cell_x
        diagonal = math.hypot(cy, cx)
        steps = ((1, cx), (-1, cx), (stride, cy), (-stride, cy),
                 (stride + 1, diagonal), (stride - 1, diagonal), (-stride + 1, diagonal), (-stride - 1, diagonal))
        best = {s: 0.0}
        previous = {}
        queue = [(0.0, 0.0, s)]
        expanded = 0
        found = False
        while queue:
            _, cost, current = heapq.heappop(queue)
            if current == g:
                found = True
                break
            if cost > best[current]:
                continue
            expanded += 1
            if expanded > max_expansions:
                return None, f'搜索超过上限（{max_expansions} 格）'
            for offset, length in steps:
                neighbor = current + offset
                value = grid[neighbor]
                if value == BLOCKED or value == NEAR_WALL or neighbor in temporary:
                    continue
                next_cost = cost + length * value / FLAT
                if next_cost < best.get(neighbor, math.inf):
                    best[neighbor] = next_cost
                    previous[neighbor] = current
                    r, c = divmod(neighbor, stride)
                    heapq.heappush(queue, (next_cost + math.hypot((r - gr) * cy, (c - gc) * cx), next_cost, neighbor))
        if not found:
            return None, '格子图上无路可达'
        cells = [g]
        while cells[-1] != s:
            cells.append(previous[cells[-1]])
        cells.reverse()
        rc = [(index // stride - 1 + .5, index % stride - 1 + .5) for index in cells]
        start_rc = self.cell_of(*start)
        goal_rc = self.cell_of(*goal)
        waypoints = self._simplify([start_rc, *rc, goal_rc])
        points = tuple((round(c * 100 / self.cols, 4), round(r * 100 / self.rows, 4)) for r, c in waypoints[1:-1])
        points = (tuple(start), *points, tuple(goal))
        yards = sum(math.hypot((b[0] - a[0]) * self.width / 100, (b[1] - a[1]) * self.height / 100)
                    for a, b in zip(points, points[1:]))
        return GridPath(points, yards, expanded), None

    def _simplify(self, cells):
        """贪心视线压缩：每段不穿受阻或贴墙格、不长于 20 码，且从上一路点前 5 码切向下一点也不穿。"""
        out = [cells[0]]
        anchor = 0
        last = len(cells) - 1
        window = math.ceil(_SEGMENT_YARDS / min(self.cell_x, self.cell_y)) + 2
        while anchor < last:
            chosen = anchor + 1
            candidates = range(min(last - 1, anchor + window), anchor + 1, -1)
            for candidate in (last, *candidates):
                if self._segment_ok(out, cells[anchor], cells[candidate], first=anchor == 0,
                                    final=candidate == last):
                    chosen = candidate
                    break
            out.append(cells[chosen])
            anchor = chosen
        return out

    def _segment_ok(self, out, a, b, *, first, final):
        if self._yards(b[0] - a[0], b[1] - a[1]) > _SEGMENT_YARDS:
            return False
        # 起点可能就在贴墙格（甚至墙格）里，只要求离开起点 0.75 码后连线畅通；终点同理放宽。
        skip = _SELF_YARDS if first else None
        if final:
            if not self._line_clear(b[0], b[1], a[0], a[1], standable=True, skip_near=_SELF_YARDS):
                return False
        elif not self._line_clear(a[0], a[1], b[0], b[1], standable=True, skip_near=skip):
            return False
        if len(out) >= 2:
            # 道路路点到点半径 5 码：角色可能在上一路点前 5 码（沿已保留的折线往回量，可跨多段）就转向下一点。
            early, at_start = self._walk_back(out, _CORNER_YARDS)
            if not self._line_clear(early[0], early[1], b[0], b[1], standable=False,
                                    skip_near=_SELF_YARDS if at_start else None, body=_BODY_YARDS):
                return False
        return True

    def _walk_back(self, out, yards):
        """沿折线 out 从末点往回量 yards 码，返回 (点, 是否退到了起点)。"""
        remaining = yards
        for index in range(len(out) - 1, 0, -1):
            a, b = out[index], out[index - 1]
            length = self._yards(a[0] - b[0], a[1] - b[1])
            if length >= remaining and length > 0:
                t = remaining / length
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), False
            remaining -= length
        return out[0], True
