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
