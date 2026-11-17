"""读取游戏世界地图导出的同地图路线。"""

from collections import deque
from dataclasses import dataclass
from math import hypot
import re


_COORDINATE = re.compile(r'[0-9]{1,5},[0-9]{1,5}')
_MAP = re.compile(r'[1-9][0-9]{0,5}')


@dataclass(frozen=True, slots=True)
class ManualRoute:
    map_id: int
    points: tuple[tuple[float, float], ...]
    zone: str = ''
    built_in: bool = False
    # 录制的循环路线：path 为完整轨迹，points 为沿轨迹取出的停留点，stop_indices 为停留点在 path 中的下标。
    path: tuple[tuple[float, float], ...] = ()
    stop_indices: tuple[int, ...] = ()
    recorded: bool = False
    scale: tuple[float, float] = ()   # 录制时地图的码数（宽、高），用于按码计算距离

    @property
    def endpoint(self):
        return self.points[-1]


# 哨兵岭两个建筑之间的石板路向北接出，绕过东侧建筑后再回到跑尸方向。
_SENTINEL_STONE_PATH = ((53.86, 52.75), (54.00, 52.30))
_SENTINEL_NORTH_EXIT = ((54.12, 51.95), (54.65, 51.90), (55.28, 51.90),
                        (55.62, 52.40), (56.10, 52.66), (56.95, 53.20))

GHOST_ACCESS_ROUTES = (
    # 赤脊山墓地围栏端柱。
    ManualRoute(1433, ((17.60, 58.20), (17.60, 58.00), (17.55, 57.63),
                       (17.85, 57.77), (18.14, 57.85), (18.45, 58.12)), built_in=True),
    # 哨兵岭灵魂出现位置、长屋门槛、东侧门廊和石板路。
    ManualRoute(1436, ((52.70, 52.80), (52.72, 52.50), (52.85, 52.22),
                       (53.20, 52.15), (54.00, 52.15)) + _SENTINEL_NORTH_EXIT, built_in=True),
    ManualRoute(1436, ((52.90, 54.00), (52.90, 53.90), (53.00, 53.10),
                       (53.20, 53.10), (53.55, 52.80)) + _SENTINEL_STONE_PATH + _SENTINEL_NORTH_EXIT,
                built_in=True),
    ManualRoute(1436, ((53.90, 54.40), (54.00, 54.30), (53.60, 53.50),
                       (53.70, 53.00)) + _SENTINEL_STONE_PATH + _SENTINEL_NORTH_EXIT, built_in=True),
    ManualRoute(1436, _SENTINEL_STONE_PATH + _SENTINEL_NORTH_EXIT, built_in=True),
    ManualRoute(1436, ((54.00, 52.30),) + _SENTINEL_NORTH_EXIT, built_in=True),
)


def parse_manual_route(text: str, *, max_points: int = 48) -> ManualRoute:
    return _parse_route(text, allow_point=False, max_points=max_points)


PATROL_STOP_YARDS = 40
RECORDED_MAX_POINTS = 256


def _loop_stops(points, width, height, spacing=PATROL_STOP_YARDS):
    """沿轨迹每约 spacing 码取一个停留点（下标），末点总是停留点；至少 2 个。"""
    stops, walked = [], 0.0
    for index in range(1, len(points)):
        (x0, y0), (x1, y1) = points[index - 1], points[index]
        walked += hypot((x1 - x0) * width / 100, (y1 - y0) * height / 100)
        if walked >= spacing:
            stops.append(index)
            walked = 0.0
    if not stops or stops[-1] != len(points) - 1:
        if stops and walked < spacing / 2 and len(stops) > 1:
            stops[-1] = len(points) - 1
        else:
            stops.append(len(points) - 1)
    if len(stops) < 2:
        stops.insert(0, len(points) // 2)
    return tuple(stops)


def parse_patrol_route(text: str) -> ManualRoute:
    """循环打怪路线：录制的 WBDLOOP1 轨迹，或游戏地图导出的 WBDROUTE1/WBDROUTE2 坐标路线。"""
    text = text.strip()
    if not text.startswith('WBDLOOP1|'):
        return parse_manual_route(text)
    _, map_id, scale, *coordinates = text.split('|')
    if not _MAP.fullmatch(map_id) or not 3 <= len(coordinates) <= RECORDED_MAX_POINTS:
        raise ValueError(f'录制的循环路线需要地图编号和 3 至 {RECORDED_MAX_POINTS} 个路点。')
    try:
        width, height = (float(value) for value in scale.split(','))
    except ValueError:
        raise ValueError('录制的循环路线缺少有效的地图尺寸。') from None
    if not (0 < width < 100000 and 0 < height < 100000):
        raise ValueError('录制的循环路线缺少有效的地图尺寸。')
    route = _parse_route(f'WBDROUTE1|{map_id}|' + '|'.join(coordinates), allow_point=False,
                         max_points=RECORDED_MAX_POINTS)
    stops = _loop_stops(route.points, width, height)
    return ManualRoute(route.map_id, tuple(route.points[index] for index in stops), path=route.points,
                       stop_indices=stops, recorded=True, scale=(width, height))


def patrol_leg(route: ManualRoute, index: int):
    """前往第 index 个循环点时经过的路点：坐标路线只有该点；录制路线为上一停留点之后到该停留点的轨迹。"""
    if not route.recorded:
        return (route.points[index],)
    path, stops = route.path, route.stop_indices
    current, previous = stops[index], stops[index - 1]
    if index:
        return path[previous + 1:current + 1]
    return path[previous + 1:] + path[:current + 1]


def nearest_on_loop(route: ManualRoute, xy, segments=None):
    """在录制环线上找离 xy 最近的位置：返回 (接下来应前往的路点下标, 距离码数)。

    视为已走过投影位置，指向所在小段的终点；距离相同时取先遇到的小段。segments 限定只看这些小段（起点下标）。
    """
    width, height = route.scale
    path = route.path
    px, py = xy[0] * width / 100, xy[1] * height / 100
    best = None
    for index in (range(len(path)) if segments is None else segments):
        (ax, ay), (bx, by) = path[index], path[(index + 1) % len(path)]
        ax, ay, bx, by = ax * width / 100, ay * height / 100, bx * width / 100, by * height / 100
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
        distance = hypot(px - (ax + t * dx), py - (ay + t * dy))
        if best is None or distance < best[1] - 1e-9:
            best = (index + 1) % len(path), distance
    return best


def path_distance(route: ManualRoute, xy, points):
    """xy 到折线 points（地图百分比坐标）的最近距离，按录制路线的地图码数计算。"""
    width, height = route.scale
    px, py = xy[0] * width / 100, xy[1] * height / 100
    scaled = [(x * width / 100, y * height / 100) for x, y in points]
    if len(scaled) == 1:
        return hypot(px - scaled[0][0], py - scaled[0][1])
    best = None
    for (ax, ay), (bx, by) in zip(scaled, scaled[1:]):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
        distance = hypot(px - (ax + t * dx), py - (ay + t * dy))
        best = distance if best is None else min(best, distance)
    return best


_CURRENT_LEG_YARDS = 25


def patrol_rejoin(route: ManualRoute, xy, index: int):
    """接回录制轨迹：返回 (停留点序号, 本段要走的路点, 离轨迹的码数)。

    从离 xy 最近的轨迹位置开始，到其所在段的停留点为止；index 仅在坐标路线时原样返回。
    """
    if not route.recorded:
        return index, (route.points[index],), None
    start, distance = nearest_on_loop(route, xy)
    stops, path = route.stop_indices, route.path
    if 0 <= index < len(stops) and len(stops) > 1:
        # 环线自交时，全环最近点可能落在更早的一段（2026-11-17 01:43 从第 8 点退回第 5 点）。
        # 离当前段（上一停留点 → 当前停留点）不远时，沿当前段接回。
        lo, hi = stops[index - 1], stops[index]
        count = (hi - lo) % len(path) or len(path)
        window = [(lo + step) % len(path) for step in range(count)]
        if (start - 1) % len(path) not in window:
            local = nearest_on_loop(route, xy, window)
            if local is not None and local[1] <= _CURRENT_LEG_YARDS:
                start, distance = local
    stop = next((number for number, stop_index in enumerate(stops) if stop_index >= start), 0)
    end = stops[stop]
    leg = path[start:end + 1] if start <= end else path[start:] + path[:end + 1]
    return stop, leg, distance


def parse_fixed_camp(text: str) -> ManualRoute:
    return _parse_route(text, allow_point=True)


def _parse_route(text: str, *, allow_point: bool, max_points: int = 48) -> ManualRoute:
    prefix, _, payload = text.strip().partition('|')
    map_id, *coordinates = payload.split('|')
    zone = ''
    if prefix == 'WBDROUTE2' and coordinates:
        zone = coordinates.pop(0)
        if (not zone or zone != zone.strip() or len(zone.encode('utf8')) > 72
                or any(ord(char) < 32 or ord(char) == 127 for char in zone)):
            raise ValueError('路线包含无效的地图名称。')
    elif prefix != 'WBDROUTE1' and not (allow_point and prefix == 'WBDPOINT1'):
        raise ValueError('请粘贴游戏地图导出的路线。')
    if prefix == 'WBDPOINT1':
        if not _MAP.fullmatch(map_id) or len(coordinates) != 1:
            raise ValueError('打怪点需要一个地图编号和一组坐标。')
    elif not _MAP.fullmatch(map_id) or not 2 <= len(coordinates) <= max_points:
        raise ValueError(f'请粘贴游戏地图导出的路线，每条路线需要 2 至 {max_points} 个路点。')
    points = []
    for coordinate in coordinates:
        if not _COORDINATE.fullmatch(coordinate):
            raise ValueError('路线包含无效坐标。')
        x, y = map(int, coordinate.split(','))
        if x > 10000 or y > 10000:
            raise ValueError('路线包含地图范围之外的路点。')
        point = x / 100, y / 100
        if points and points[-1] == point:
            raise ValueError('路线包含相邻的重复路点。')
        points.append(point)
    return ManualRoute(int(map_id), tuple(points), zone)


def parse_manual_connection(text: str):
    from wowbuddy.automation.walking_route import WalkingLeg

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 2:
        raise ValueError('请粘贴两段路线，第一行是出发地图，第二行是到达地图。')
    departure, arrival = map(parse_manual_route, lines)
    if departure.map_id == arrival.map_id:
        raise ValueError('两段路线须分别来自不同地图。')
    return WalkingLeg(departure.map_id, arrival.map_id, 1, departure.points,
                      arrival_road=arrival.points, manual=True,
                      source_name=departure.zone, destination_name=arrival.zone)


def manual_camp_road(routes, goal):
    """地图必须相同，最后一个标记必须在刷怪点的 1.5 地图坐标单位以内。"""
    nearby = []
    for route in routes:
        if route.map_id == goal.map_id:
            x, y = route.endpoint
            distance = hypot(goal.x - x, goal.y - y)
            if distance <= 1.5:
                nearby.append((distance, route))
    return min(nearby, key=lambda item: item[0])[1].points if nearby else ()


class LocalAccess:
    """从玩家标记的起点按顺序接入当前路线。"""

    def __init__(self, routes):
        self.routes = routes
        self._route = None
        self._points = deque()
        self._last_sample = None
        self._other_map = None
        self._spent = set()
        self._rejoining = False
        self._reported_rejoin_wait = False
        self.blocked = False

    @property
    def active(self):
        return self._route is not None

    def resume_after_revival(self):
        self._spent.clear()
        if self.active:
            self._last_sample = self._other_map = None
            self._rejoining = True
            self._reported_rejoin_wait = False

    def _on_pending_segment(self, position):
        from wowbuddy.automation.walking_route import _road_position

        if self._points[0].contains(position):
            return True
        points = self._route.points
        index = len(points) - len(self._points)
        scale = position.width / 100, position.height / 100
        return index > 0 and _road_position(points[index - 1:index + 1], position.x, position.y,
                                            scale=scale, limit=2) is not None

    def _route_at_start(self, position):
        nearby = []
        for route in self.routes:
            x, y = route.points[0]
            distance = hypot((x - position.x) * position.width, (y - position.y) * position.height) / 100
            if route.map_id != position.map_id or distance > 4:
                self._spent.discard(route)
            elif route not in self._spent:
                nearby.append((distance, route))
        return min(nearby, key=lambda entry: (entry[1].built_in, entry[0]))[1] if nearby else None

    def observe(self, position):
        from wowbuddy.automation.navigation import MapDestination

        if position is None:
            return None, None
        sample = position.map_id, position.sequence
        if self._route and self._route.map_id != position.map_id:
            previous = self._other_map
            self._other_map = sample
            if previous is None or previous[0] != sample[0] or previous == sample:
                return None, None
            self._route = None
            self._points.clear()
            self._rejoining = False
            self.blocked = False
        self._other_map = None
        if self.blocked:
            return None, None
        start_route = None
        if self._rejoining:
            if not self._on_pending_segment(position):
                start_route = self._route_at_start(position)
                if start_route is None:
                    if not self._reported_rejoin_wait:
                        self._reported_rejoin_wait = True
                        return None, '复活位置暂未接上原起点路线，等待靠近已走到的路段。'
                    return None, None
                self._route = None
                self._points.clear()
            self._rejoining = False

        status = None
        if not self.active:
            self._route = start_route or self._route_at_start(position)
            if self._route is None:
                return None, None
            self._points.extend(MapDestination(position.map_id, x, y, position.life, f'起点接入路点 {index}',
                                               radius=1.25, allow_detour=False,
                                               blocked_reason='未读到继续前进的位移。')
                                for index, (x, y) in enumerate(self._route.points, 1))
            source = '内置的' if self._route.built_in else '你标记的'
            status = f'开始沿{source} {len(self._points)} 个起点接入路点行走。'

        if sample != self._last_sample and self._points[0].contains(position):
            self._last_sample = sample
            self._points.popleft()
        if self._points:
            return self._points[0], status
        self._spent.add(self._route)
        self._route = None
        next_step = '继续前往尸体。' if position.life == 'ghost' else '继续原来的练级计划。'
        return None, '已走完起点接入路线，' + next_step
