"""同一地图内按坐标反馈向尸体或练级据点移动。"""

from collections import deque
from dataclasses import dataclass
import math
from threading import Lock, Timer
from time import monotonic

from wowbuddy.win32.game_windows import GAME_EXECUTABLES, executable_name
from wowbuddy.core.keybindings import is_extended_key
from wowbuddy.win32.windows_keys import KeyboardInput, is_foreground


_MANUAL_KEYS = (*map(ord, 'WASDQE'), *range(0x25, 0x29), 1, 2, 4, 0x10, 0x11, 0x12)
_STEERING_LIMIT = 0.65
_TARGET_RECEIPT_MS = 2000


def map_yards(position, x1, y1, x2, y2):
    """两点的地图坐标（0-100）按 position 所在地图的宽高（码）换算成直线距离。"""
    return math.hypot((x1 - x2) * position.width / 100, (y1 - y2) * position.height / 100)


@dataclass(frozen=True, slots=True)
class MapDestination:
    map_id: int
    x: float
    y: float
    life: str
    label: str
    radius: float | None = None
    allow_detour: bool = True
    blocked_reason: str | None = None
    precision_stop: bool = False
    elevation_range: tuple[float, float] | None = None

    @property
    def arrival_radius(self):
        if self.radius is not None:
            return self.radius
        return 8 if self.life == 'ghost' else 18

    def offset_from(self, position):
        return ((self.x - position.x) * position.width / 100,
                (position.y - self.y) * position.height / 100)

    def contains(self, position, *, radius=None):
        limit = self.arrival_radius if radius is None else radius
        return (position.life == self.life and position.map_id == self.map_id
                and self.has_elevation(position) and math.hypot(*self.offset_from(position)) <= limit)

    def has_elevation(self, position):
        return (self.elevation_range is None or
                (position.position_steps >= 1_000_000 and position.elevation is not None
                 and self.elevation_range[0] <= position.elevation <= self.elevation_range[1]))


def _angle_delta(goal, facing):
    return (goal - facing + math.pi) % math.tau - math.pi


class ForegroundMovement:
    def __init__(self, keyboard, processes, *, on_forward=None):
        self.keyboard = keyboard
        self.processes = processes
        self.on_forward = on_forward
        self._lock = Lock()
        self._forward = None
        self._pending_pulse_release = None
        self._watchdog = None
        self._deadline = 0.0
        # 最近一次拒绝发键的原因与时间（monotonic 秒）；成功通过检查后清空。只用于日志与状态快照。
        self.blocked_reason = None
        self.blocked_at = None

    def can_input(self, hwnd, keys):
        return self._can_input(hwnd, keys, owned_key=None)

    def in_foreground(self, hwnd):
        return is_foreground(self.keyboard, hwnd)

    def _can_input(self, hwnd, keys, owned_key):
        reason = self._input_block(hwnd, keys, owned_key)
        if reason is None:
            self.blocked_reason = self.blocked_at = None
            return True
        self.blocked_reason, self.blocked_at = reason, monotonic()
        return False

    def _input_block(self, hwnd, keys, owned_key):
        keyboard = self.keyboard
        if not hwnd or not keyboard.IsWindow(hwnd) or not keyboard.GetAncestor(hwnd, 2):
            return '游戏窗口无效'
        if not self.in_foreground(hwnd):
            return '游戏不在前台'
        pid = self.processes.window_pid(hwnd)
        if not pid or executable_name(self.processes.process_path(pid)) not in GAME_EXECUTABLES:
            return '不是游戏进程'
        if any(keyboard.GetAsyncKeyState(vk) & 0x8000 for vk in (*keys, *_MANUAL_KEYS) if vk != owned_key):
            return '检测到手动按键'
        return None if self.in_foreground(hwnd) else '游戏不在前台'

    def keep_forward(self, hwnd, keys):
        """每次轮询都检查前台和接管按键，只有新定位帧才续期。"""
        with self._lock:
            if self._pending_pulse_release is not None:
                self._release_forward()
                return False
            if self._forward is None:
                return False
            owner, event = self._forward
            if (owner == hwnd and event.vk == keys[0]
                    and self._can_input(hwnd, keys, owned_key=event.vk)
                    and self.keyboard.GetAsyncKeyState(event.vk) & 0x8000):
                return True
            self._release_forward()
            return False

    def hold_forward(self, hwnd, keys):
        with self._lock:
            if self._pending_pulse_release is not None:
                self._release_forward()
                return False
            key = keys[0]
            if self._forward is None:
                if not self.can_input(hwnd, keys):
                    return False
                event = self._keydown(key)
                if self.keyboard.SendInput((event,)) != 1:
                    return False
                self._forward = hwnd, event
                if self.on_forward is not None:
                    self.on_forward()
            elif self._forward[0] != hwnd or self._forward[1].vk != key:
                self._release_forward()
                return False
            elif not self._can_input(hwnd, keys, owned_key=key):
                self._release_forward()
                return False
            self._deadline = monotonic() + 0.7
            if self._watchdog is None:
                self._schedule_watchdog(0.7)
            return True

    def _schedule_watchdog(self, seconds):
        timer = Timer(seconds, lambda: self._expire(timer))
        timer.daemon = True
        self._watchdog = timer
        timer.start()

    def _expire(self, timer):
        with self._lock:
            if self._watchdog is not timer:
                return
            self._watchdog = None
            remaining = self._deadline - monotonic()
            if remaining > 0:
                self._schedule_watchdog(remaining)
            else:
                self._release_forward()

    def release_forward(self):
        with self._lock:
            return self._release_forward()

    @property
    def holding_forward(self):
        with self._lock:
            return self._forward is not None

    def _cancel_watchdog(self):
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None

    def _release_forward(self):
        self._cancel_watchdog()
        if self._forward is not None:
            _, event = self._forward
            if self._keyup(event):
                self._forward = None
        if self._pending_pulse_release is not None and self._keyup(self._pending_pulse_release):
            self._pending_pulse_release = None
        if self._forward is not None or self._pending_pulse_release is not None:
            self._deadline = 0.0
            self._schedule_watchdog(0.1)
            return False
        return True

    def _keydown(self, key):
        scan = self.keyboard.MapVirtualKeyW(key, 0) & 0xFFFF
        return KeyboardInput(key, scan, int(is_extended_key(key)))

    def _keyup(self, event):
        release = (KeyboardInput(event.vk, event.scan, event.flags | 2),)
        return self.keyboard.SendInput(release) == 1 or self.keyboard.SendInput(release) == 1

    def pulse(self, hwnd, key, milliseconds, movement_keys, *, steering=False, limit=None):
        if steering:
            if not self.keep_forward(hwnd, movement_keys):
                return False
        elif not self.release_forward() or not self.can_input(hwnd, movement_keys):
            return False

        event = self._keydown(key)
        if self.keyboard.SendInput((event,)) != 1:
            return False
        forward = key == movement_keys[0]
        try:
            if forward and self.on_forward is not None:
                self.on_forward()
            cap = 280 if not steering and key in movement_keys else 120
            if limit is not None and not steering and key in movement_keys[1:]:
                cap = max(cap, min(1000, limit))     # 只放宽转向键：朝向搜索的半圈转身
            self.keyboard.Sleep(max(20, min(cap, milliseconds)))
        finally:
            released = self._keyup(event)
            if not released:
                with self._lock:
                    if forward:
                        self._forward = hwnd, event
                    else:
                        self._pending_pulse_release = event
                    self._cancel_watchdog()
                    self._deadline = 0.0
                    self._schedule_watchdog(0.1)
        return released


class NovaSpacing:
    """定身回执仍有效时短步后退，只有距离增加才允许再退。"""

    def __init__(self, movement):
        self.movement = movement
        self.cast = self.last = None
        self.steps = 0

    def observe(self, session, cast, sample):
        identity = session, cast
        if identity != self.cast:
            self.cast, self.last, self.steps = identity, None, 0
        if self.steps >= 4 or (sample.event_only and self.steps):
            return False
        if self.last is not None:
            if sample.sequence == self.last.sequence:
                return False
            if (sample.revision != self.last.revision or sample.keys != self.last.keys
                    or sample.distance - self.last.distance < 0.25):
                self.steps = 4
                return False
        if not self.movement.pulse(session[0], sample.keys[0], 280, sample.keys):
            return False
        self.last = sample
        self.steps = 4 if sample.event_only else self.steps + 1
        return True


class CombatFacing:
    """只在游戏确认朝向错误后转向，每条施法回执最多一次。"""

    def __init__(self, movement):
        self.movement = movement
        self.reset()

    def reset(self):
        self.target = None
        self.last_sequence = None
        self.attempts = 0

    def observe(self, session, sample, sequence):
        target = session, sample.revision
        if target != self.target:
            self.reset()
            self.target = target
        if sequence == self.last_sequence or self.attempts >= 8:
            return False
        _, left, right = sample.keys
        turn, hold = right, 280
        if sample.heading is not None:
            error = _angle_delta(sample.target_heading, sample.heading)
            turn = left if error > 0 else right
            hold = min(280, max(45, round(abs(error) * 318)))
            sent = self.movement.pulse(session[0], turn, hold, sample.keys)
        elif self.attempts == 0:
            # 经典版拿不到怪物方位。朝向错误说明目标在身后半圈：先转半圈（约 1 秒），一定落到正面半圈。
            sent = self.movement.pulse(session[0], turn, 1000, sample.keys, limit=1000)
        else:
            sent = self.movement.pulse(session[0], turn, hold, sample.keys)
        if not sent:
            return False
        self.last_sequence = sequence
        self.attempts += 1
        return True


class _LocalDetour:
    grid = False
    radius = 1.35
    pulse_limit = 100
    stall_limit = 18

    @staticmethod
    def has_precision(position):
        return max(position.width, position.height) <= 0.75 * position.position_steps

    def __init__(self, position, destination, trail=(), *, wider=False):
        self.anchor = MapDestination(position.map_id, position.x, position.y, position.life, '绕行起点')
        self.plans = []
        east, north = destination.offset_from(position)
        distance = math.hypot(east, north)
        self.initial_distance = distance
        side_distance, advance_distance = (11, 16) if wider else (6, 12)
        self.range_limit = 24 if wider else 18
        if self.has_precision(position):
            retreat = self._retreat_path(position, trail)
            for approach in ((), retreat) if retreat else ((),):
                back_east, back_north = approach[-1].offset_from(position) if approach else (0, 0)
                for side in (1, -1):
                    side_east = -side * north * side_distance / distance
                    side_north = side * east * side_distance / distance
                    ahead = (side_east + east * advance_distance / distance,
                             side_north + north * advance_distance / distance)
                    self._add_plan(position, approach, (back_east + side_east, back_north + side_north), ahead)
        self.waypoints = self.plans.pop(0)[1] if self.plans else []
        self.visited = []
        self.returning = False
        self.pulses = 0
        self.stalled_pulses = 0
        self.best_distance = None

    def observe_distance(self, distance):
        if self.best_distance is None or self.best_distance - distance >= 0.5:
            self.best_distance = distance
            self.stalled_pulses = 0

    def note_pulse(self):
        self.pulses += 1
        self.stalled_pulses += 1

    def _retreat_path(self, position, trail):
        retreat = []
        for point in reversed(trail):
            distance = math.hypot(*point.offset_from(position))
            if distance > 10:
                break
            if distance > self.radius:
                retreat.append(point)
            if distance >= 6:
                return retreat
        return ()

    def _add_plan(self, position, retreat, side, ahead):
        points = [MapDestination(position.map_id, position.x + dx * 100 / position.width,
                                 position.y - dy * 100 / position.height, position.life, '绕行点')
                  for dx, dy in (side, ahead)]
        if all(0.05 <= point.x <= 99.95 and 0.05 <= point.y <= 99.95 for point in points):
            self.plans.append((bool(retreat), [*retreat, *points]))

    def advance(self):
        point = self.waypoints.pop(0)
        self.best_distance = None
        self.stalled_pulses = 0
        if not self.returning:
            self.visited.append(point)
        if not self.waypoints and self.returning:
            self.returning = False
            self.visited.clear()
            self.pulses = 0
            use_trail, self.waypoints = self.plans.pop(0)
            return 'backtrack' if use_trail else 'alternate'
        return 'next' if self.waypoints else 'complete'

    def try_other_side(self):
        if self.returning or not self.plans:
            return False
        self.returning = True
        self.waypoints = [*reversed(self.visited), self.anchor]
        self.pulses = self.stalled_pulses = 0
        self.best_distance = None
        return True


class _GridDetour(_LocalDetour):
    """按地图格子算出的绕行路点（docs/design/20261116-walk-grid-pathing.md）。

    沿用 _LocalDetour 的路点跟随、脉冲与停滞计数；范围与脉冲上限按路线长度放宽，没有“另一侧”方案。
    """
    grid = True
    radius = 2.5
    stall_limit = 30

    def __init__(self, position, destination, points):
        self.anchor = MapDestination(position.map_id, position.x, position.y, position.life, '绕行起点')
        self.plans = []
        self.waypoints = [MapDestination(position.map_id, x, y, position.life, '格子绕行点') for x, y in points]
        self.initial_distance = math.hypot(*destination.offset_from(position))
        far = max((math.hypot(*point.offset_from(position)) for point in self.waypoints), default=0)
        length, previous = 0.0, (position.x, position.y)
        for point in self.waypoints:
            length += map_yards(position, previous[0], previous[1], point.x, point.y)
            previous = point.x, point.y
        self.range_limit = far + 15
        self.pulse_limit = 100 + int(length * 4)
        self.visited = []
        self.returning = False
        self.pulses = 0
        self.stalled_pulses = 0
        self.best_distance = None


class MapNavigator:
    def __init__(self, movement):
        self.movement = movement
        self._target = None
        self._path = None
        self._sequence = None
        self._previous = None
        self._forward_failures = self._turn_failures = 0
        self._finished = False
        self.blocked = False
        self._other_map = None
        self._detour = None
        self._detour_count = 0
        self._detour_origin = None
        # 地图格子（automation/grid_route.GridRoutes）；None 时只用固定局部绕行。
        self.grid = None
        self._grid_attempts = 0
        self._trail = deque(maxlen=10)
        self._last_position = None
        self._position_paused = False
        # 只读计数，供转向指标统计（automation/steering_stats）：不参与控制判断。
        self.counters = {'stop_turns': 0, 'steer_pulses': 0, 'stalls': 0}

    def pause(self, session):
        if self._target is not None and self._target[0] == session:
            self._previous = None
            self._position_paused = True

    def _remember_progress(self, position):
        if self._trail:
            distance = math.hypot(*self._trail[-1].offset_from(position))
            if distance < 1.5:
                return
            if distance > 5:
                self._trail.clear()
        self._trail.append(MapDestination(position.map_id, position.x, position.y, position.life, '已通过位置'))

    def _reset_feedback(self):
        self._previous = None
        self._forward_failures = self._turn_failures = 0

    def _stop(self, destination, reason):
        self._finished = True
        self.blocked = True
        self.movement.release_forward()
        return f'已暂停前往「{destination.label}」。{reason}'

    def _grid_detour(self, position, destination):
        """返回 (_GridDetour 或 None, 未用格子的原因或 None)。"""
        if self.grid is None or self.grid.grid(position.map_id) is None:
            return None, None
        if self._grid_attempts >= 3:
            return None, '本段已按格子重算三次'
        if not _LocalDetour.has_precision(position):
            return None, '坐标精度不足'
        self._grid_attempts += 1
        self.grid.note_blocked(position)
        prefer = None
        for point in reversed(self._trail):
            if math.hypot(*point.offset_from(position)) >= 1.5:
                prefer = point.x, point.y
                break
        points, reason = self.grid.plan(position, destination, prefer=prefer)
        if not points:
            return None, reason
        detour = _GridDetour(position, destination, points[1:-1])
        if not detour.waypoints:
            return None, '格子图上直线可达，但实际受阻'
        return detour, None

    def _start_detour(self, position, destination, cause=None):
        """受阻后先试格子绕行，再退回固定局部绕行（次数上限不变）。"""
        lead = f'{cause}，' if cause else '直行受阻，'
        detour, grid_failure = self._grid_detour(position, destination)
        if detour is not None:
            self._detour = detour
            self._detour_origin = detour.anchor
            return f'{lead}按地图格子绕行前往「{destination.label}」（{len(detour.waypoints)} 个路点）。'
        note = f'地图格子未找到绕行路线（{grid_failure}），' if grid_failure else ''
        if self._detour_count >= 2:
            return self._stop(destination, note + '本次已尝试两次局部绕行。')
        detour = _LocalDetour(position, destination, self._trail, wider=self._detour_count > 0)
        if not detour.waypoints:
            return self._stop(destination, note + '当前位置缺少足够精度或空间来尝试绕行。')
        self._detour_count += 1
        self._detour = detour
        self._detour_origin = detour.anchor
        return f'{note}{lead}尝试绕行前往「{destination.label}」。'

    def observe(self, session, hwnd, position, destination, *, path=None):
        target = session, destination
        if (path is self._path and self._target is not None and self._target[0] == session
                and ((position is None and destination is not None and target == self._target)
                     or (path is not None and destination is None))):
            # 行走计划暂时没有新定位，保留同一路点已确认的受阻次数和绕行。
            self.movement.release_forward()
            self.pause(session)
            return None
        if target != self._target or path is not self._path:
            previous_session, previous_destination = self._target or (None, None)
            same_route = (path is not None and path is self._path and not self.blocked and self._detour is None
                          and session == previous_session and previous_destination is not None and destination is not None
                          and position is not None and previous_destination.map_id == destination.map_id == position.map_id
                          and previous_destination.life == destination.life == position.life)
            if not same_route or not position.continuous or destination.precision_stop:
                self.movement.release_forward()
            # 已走到同一路线的上一个路点，允许沿实际走过的短段退回。
            if (same_route and self._trail and previous_destination.allow_detour and destination.allow_detour
                    and previous_destination.contains(position)):
                self._remember_progress(position)
            else:
                self._trail.clear()
            self._target = target
            self._path = path
            self._sequence = None
            self._reset_feedback()
            self._finished = False
            self.blocked = False
            self._other_map = None
            self._detour = None
            self._detour_count = 0
            self._grid_attempts = 0
            self._detour_origin = None
            self._last_position = None
            self._position_paused = False
        if self.blocked or destination is None or position is None or position.life != destination.life:
            self.movement.release_forward()
            self._reset_feedback()
            return None
        if position.map_id != destination.map_id:
            self.movement.release_forward()
            if self._other_map != position.map_id:
                self._other_map = position.map_id
                self._detour = None
                self._detour_count = 0
                self._grid_attempts = 0
                self._detour_origin = None
                self._trail.clear()
                self._last_position = None
                self._reset_feedback()
                return f'「{destination.label}」位于其他地图。当前导航等待进入该地图。'
            return None
        self._other_map = None
        if not destination.has_elevation(position):
            self.movement.release_forward()
            self._reset_feedback()
            return None
        holding = position.continuous and self.movement.keep_forward(hwnd, position.keys)
        if not holding and (position.moving or not self.movement.can_input(hwnd, position.keys)):
            # 玩家输入或自动跑会使上一条导航指令的反馈失效。
            self.movement.release_forward()
            self._sequence = position.sequence
            self._reset_feedback()
            self._trail.clear()
            self._last_position = None
            return None
        if self._detour is not None and not self._detour.has_precision(position):
            self.movement.release_forward()
            self.pause(session)
            return None
        if position.sequence == self._sequence:
            return None
        self._sequence = position.sequence
        position_was_paused, self._position_paused = self._position_paused, False
        previous_position, self._last_position = self._last_position, position
        if self._trail and previous_position and (self._previous is None or self._previous[2] != 0):
            moved = math.hypot((position.x - previous_position.x) * position.width,
                               (position.y - previous_position.y) * position.height) / 100
            if moved > 1.5:
                self._trail.clear()

        direct_offset = destination.offset_from(position)
        remaining = math.hypot(*direct_offset)
        if remaining <= destination.arrival_radius:
            if self._finished:
                return None
            self._finished = True
            self.movement.release_forward()
            return f'已到达「{destination.label}」附近。'
        if self._finished:
            self._finished = False
            self._detour = None
            self._detour_count = 0
            self._grid_attempts = 0
            self._detour_origin = None
            self._trail.clear()
            self._reset_feedback()

        detour = self._detour
        if detour is not None and not detour.anchor.contains(position, radius=detour.range_limit):
            if previous_position is not None and not position_was_paused:
                return self._stop(destination, '已离开局部绕行范围。')
            # 接管期间离开了旧障碍附近，从新位置重新评估同一路点。
            detour = self._detour = None
            self._detour_count = 0
            self._detour_origin = None
            self._trail.clear()
            self._reset_feedback()
        if detour is None and self._detour_origin and not self._detour_origin.contains(position, radius=24):
            self._detour_count = 0
            self._grid_attempts = 0
            self._detour_origin = None
        if detour is None and not self._trail and destination.allow_detour:
            self._remember_progress(position)
        east, north = direct_offset if detour is None else detour.waypoints[0].offset_from(position)
        distance = math.hypot(east, north)
        if detour is not None and distance <= detour.radius:
            self._reset_feedback()
            if holding and not self.movement.release_forward():
                return None
            if position.moving:
                return None
            transition = detour.advance()
            if transition == 'alternate':
                return f'已退回绕行起点，改从另一侧前往「{destination.label}」。'
            if transition == 'backtrack':
                return f'就地绕行受阻，沿刚走过的路线后退，再绕行前往「{destination.label}」。'
            if transition == 'complete':
                if detour.grid:
                    # 最后一个格子路点与目的地之间已确认无遮挡，交回直行。
                    self._detour = None
                    self._grid_attempts = 0
                    self._trail.clear()
                    return f'已通过格子绕行段，继续前往「{destination.label}」。'
                if detour.initial_distance - remaining >= 3:
                    self._detour = None
                    self._trail.clear()
                    return f'已通过绕行段，继续前往「{destination.label}」。'
                if detour.try_other_side():
                    return '绕行后未能接近目的地，先退回起点。'
                return self._stop(destination, '两侧绕行均未能接近目的地。')
            return None

        if self._previous is not None:
            previous_distance, previous_heading, direction = self._previous
            if direction == 0:
                progressed = previous_distance - distance >= 0.15
                self._forward_failures = 0 if progressed else self._forward_failures + 1
                if progressed and detour is None and destination.allow_detour:
                    self._remember_progress(position)
            else:
                turned = direction * _angle_delta(position.heading, previous_heading) >= 0.025
                self._turn_failures = 0 if turned else self._turn_failures + 1
            self._previous = None
            if self._turn_failures >= 5:
                return self._stop(destination, '连续五次按键未读到预期的转向。')
            if self._forward_failures >= 5:
                self.counters['stalls'] += 1
                self._reset_feedback()
                self.movement.release_forward()
                if not destination.allow_detour:
                    reason = destination.blocked_reason or '路口未确认切图，也未读到继续前进的位移。'
                    return self._stop(destination, reason)
                if detour is not None and detour.grid:
                    self._detour = None
                    return self._start_detour(position, destination, '格子绕行中受阻')
                if detour is not None:
                    if detour.try_other_side():
                        return '当前侧绕行受阻，先沿已走过的路径退回起点。'
                    reason = '退回起点时也未读到位移。' if detour.returning else '绕行各可用方向均受阻。'
                    return self._stop(destination, reason)
                return self._start_detour(position, destination)

        if detour is not None:
            detour.observe_distance(distance)
            if detour.pulses >= detour.pulse_limit or detour.stalled_pulses >= detour.stall_limit:
                self._reset_feedback()
                self.movement.release_forward()
                if detour.grid:
                    self._detour = None
                    return self._start_detour(position, destination, '格子绕行未能接近路点')
                if detour.try_other_side():
                    return '当前绕行方向未能接近路点，先退回绕行起点。'
                reason = '退回绕行起点时未能接近路点。' if detour.returning else '绕行各可用方向均未能接近路点。'
                return self._stop(destination, reason)

        angle = _angle_delta(math.atan2(-east, north), position.heading)
        forward, left, right = position.keys
        narrow_ramp = destination.elevation_range is not None
        continuous = (position.continuous and not narrow_ramp and (not destination.precision_stop or distance > 8)
                      and (detour is None or distance > detour.radius + 2.2))
        angle_limit = 0.09 if narrow_ramp else 0.16 if continuous and not holding else 0.20
        steering = False
        if abs(angle) > angle_limit:
            steering = holding and continuous and abs(angle) <= _STEERING_LIMIT
            if steering:
                if not self.movement.hold_forward(hwnd, position.keys):
                    return None
            else:
                if holding:
                    self.movement.release_forward()
                if position.moving:
                    return None
            direction = 1 if angle > 0 else -1
            key = left if direction == 1 else right
            rate, limit = (180, 100) if steering else (260, 120)
            hold = min(limit, max(20 if narrow_ramp else 35, round(rate * abs(angle))))
        else:
            if continuous:
                if (holding or not position.moving) and self.movement.hold_forward(hwnd, position.keys):
                    self._previous = distance, position.heading, 0
                    if detour is not None:
                        detour.note_pulse()
                return None
            if holding:
                self.movement.release_forward()
            if position.moving:
                return None
            direction, key = 0, forward
            hold = min(85, max(35, round(distance * 100))) if narrow_ramp else 120
        sent = (self.movement.pulse(hwnd, key, hold, position.keys, steering=True) if steering
                else self.movement.pulse(hwnd, key, hold, position.keys))
        if sent:
            self._previous = distance, position.heading, direction
            if steering:
                self.counters['steer_pulses'] += 1
            elif direction:
                self.counters['stop_turns'] += 1
            if detour is not None:
                detour.note_pulse()
        return None


class TargetApproach:
    """按游戏定位对同一个可见目标做有限距离的接近。"""

    def __init__(self, movement):
        self.movement = movement
        self._target = None
        self._sequence = None
        self._pending_discard = None
        self._reselect_sent = False
        self._observed_alternate = None
        self._missing_bearing = None
        self._input_paused = False
        self._bearing_scan = None

    @property
    def pursuing(self):
        return self._sequence is not None and self._previous is not None and not self._finished

    @property
    def waiting_for_input_or_bearing(self):
        return self._input_paused or self._missing_bearing is not None

    def pause(self, session):
        if self._target is None or self._target[0] != session:
            return
        self._retarget_sample = None
        if self._pending_discard is not None and self._pending_discard[0][0] == session:
            target, origin, rejection, _ = self._pending_discard
            self._pending_discard = target, origin, rejection, None
        if not self._finished:
            self._sequence = self._previous = self._missing_bearing = None
            self._input_paused = True

    def exhausted_for(self, session, position):
        return (position is not None and position.target_revision is not None
                and self._target == (session, position.map_id, position.target_revision) and self._finished)

    def retarget(self, session, position, *, allowed, now_ms, target_rejection=None):
        if (not allowed or not self.exhausted_for(session, position)
                or position.moving or self._discard_attempts >= 2
                or self._pending_discard is not None
                or now_ms < max(self._reselect_until, self._discard_retry_at)):
            self._retarget_sample = None
            return None
        reselect = not (self._alternate or self._retarget_attempted) and bool(position.retarget_key)
        key = position.retarget_key if reselect else position.discard_key
        if not key:
            self._retarget_sample = None
            return None
        keys = (*position.keys, key)
        hwnd = session[0]
        if not self.movement.can_input(hwnd, keys):
            self._retarget_sample = None
            return None
        if self._retarget_sample is None:
            self._retarget_sample = position.sequence
            return None
        if position.sequence == self._retarget_sample:
            return None
        self._retarget_sample = None
        sent = self.movement.pulse(hwnd, key, 35, keys)
        if reselect:
            self._retarget_attempted = True
            self._reselect_sent = sent
            self._reselect_until = now_ms + _TARGET_RECEIPT_MS
            return ('当前目标接近失败，已请求重选一次，等待游戏确认。' if sent
                    else '当前目标接近失败，重选键未成功发送。')
        self._discard_attempts += 1
        self._discard_retry_at = now_ms + _TARGET_RECEIPT_MS
        if sent:
            self._pending_discard = self._target, self._selection_origin, target_rejection, self._discard_retry_at
            if target_rejection:
                return '已请求清除不适合练级的目标，等待游戏确认。'
            return ('重选的目标也无法接近，已请求清除，等待游戏确认。' if self._alternate
                    else '已请求清除无法接近的目标，等待游戏确认。')
        return '清除目标键未成功发送。'

    def confirmed_discard(self, session, position, target_valid, now_ms):
        if self._pending_discard is None:
            return None
        target, origin, rejection, until = self._pending_discard
        owner, map_id, revision = target
        if owner != session or (position is not None and (position.map_id != map_id or position.life != 'alive')):
            self._pending_discard = None
            return None
        if until is None:
            if position is None or position.target_revision is None:
                return None
            # 中断后从首个可用目标读数恢复回执等待。
            until = self._discard_retry_at = now_ms + _TARGET_RECEIPT_MS
            self._pending_discard = target, origin, rejection, until
        if now_ms > until:
            self._pending_discard = None
        elif position is not None and position.target_revision not in (None, revision):
            self._pending_discard = None
            if target_valid == 'OFF' and position.target_revision == (revision + 1) % 65521:
                return origin, rejection
        return None

    def observe_selection(self, session, position, target_valid, now_ms):
        if position is None or position.target_revision is None:
            return
        target = session, position.map_id, position.target_revision
        if self._observed_alternate != target or target_valid != 'ON':
            self._observed_alternate = None
        if (self._reselect_sent and target_valid == 'ON' and now_ms <= self._reselect_until
                and self._target[:2] == target[:2] and target[2] == (self._target[2] + 1) % 65521):
            self._observed_alternate = target
            self._reselect_sent = False

    @staticmethod
    def _displacement(origin, position):
        return map_yards(position, position.x, position.y, origin.x, origin.y)

    def _reset_approach_feedback(self, position, bearing):
        self._origin = position
        distance = bearing.distance if bearing is not None else None
        self._distance_limit = 8 if distance is None else min(60, distance + 5)
        self._best_distance = distance
        self._forward_stalls = self._turn_stalls = 0

    def _scan_for_bearing(self, hwnd, position):
        # 只原地转向。每次按键后先核对新一帧的真实转角。
        sample, heading, turned, attempts, stalls = self._bearing_scan or (None, position.heading, 0, 0, 0)
        if position.moving or sample == position.sequence:
            return None
        if sample is not None:
            delta = _angle_delta(position.heading, heading)
            turned += max(delta, 0)
            stalls = 0 if delta >= 0.03 else stalls + 1
        if turned >= math.tau - 0.2 or attempts >= 10 or stalls >= 2:
            self._finished = True
            return '原地探查未取得可靠目标方位，已停止转向。'
        if not self.movement.pulse(hwnd, position.keys[1], 240, position.keys):
            return None
        self._bearing_scan = position.sequence, position.heading, turned, attempts + 1, stalls
        if attempts == 0:
            return '战斗目标超出射程且方位不可读，开始原地转向寻找姓名板。'
        return None

    def observe(self, session, position, bearing, *, now_ms=0, allow_unlocated=False, sight_blocked=False,
                target_rejection=None, scan_in_combat=False):
        alive = position is not None and position.life == 'alive'
        track_unlocated = alive and (allow_unlocated or scan_in_combat) and position.target_revision is not None
        if not alive or (bearing is None and not track_unlocated):
            self._missing_bearing = None
            if not alive:
                self._retarget_sample = None
                self._reselect_sent = False
            if self._sequence is not None:
                self.movement.release_forward()
                self._previous = None
            self._sequence = None
            return None
        revision = bearing.revision if bearing is not None else position.target_revision
        target = session, position.map_id, revision
        if target != self._target:
            self._missing_bearing = None
            self._bearing_scan = None
            if self._sequence is not None:
                self.movement.release_forward()
                self._sequence = None
            if position.moving:
                return None
            self._alternate = self._observed_alternate == target or (
                               self._reselect_sent and self._target[:2] == target[:2]
                               and revision == (self._target[2] + 1) % 65521
                               and position.target_revision == revision
                               and now_ms <= self._reselect_until)
            self._observed_alternate = None
            self._reselect_sent = False
            self._target = target
            self._sequence = None
            if not self._alternate:
                self._selection_origin = position
            self._reset_approach_feedback(position, bearing)
            self._previous = None
            self._input_paused = False
            self._pulses = 0
            self._finished = False
            self._retarget_sample = None
            self._retarget_attempted = False
            self._discard_attempts = 0
            self._discard_retry_at = self._reselect_until = 0
        hwnd = session[0]
        continuous = bearing is not None and position.continuous and bearing.continuous
        holding = (not self._finished and position.continuous and (bearing is None or continuous)
                   and self.movement.keep_forward(hwnd, position.keys))
        if not self._finished and not holding and (position.moving or not self.movement.can_input(hwnd, position.keys)):
            # 交还控制后丢弃接近反馈，保留同一目标的按键次数上限。
            self.movement.release_forward()
            self._input_paused = True
            self._sequence = position.sequence
            self._previous = self._missing_bearing = None
            return None
        if self._input_paused and position.sequence == self._sequence:
            return None
        if bearing is None:
            if self._sequence is not None:
                self.movement.release_forward()
                self._sequence = self._previous = None
            if self._finished:
                return None
            if sight_blocked or target_rejection:
                self._finished = True
                self._missing_bearing = None
                if target_rejection:
                    return f'{target_rejection}，等待重选。'
                return '游戏连续回报视线受阻，等待重选可攻击目标。'
            if self._missing_bearing is None or now_ms - self._missing_bearing[1] > 1500:
                self._missing_bearing = now_ms, now_ms, position.sequence
                return None
            started, _, last_sample = self._missing_bearing
            if position.sequence != last_sample:
                self._missing_bearing = started, now_ms, position.sequence
                if now_ms - started >= 8000:
                    self._finished = True
                    return '同一目标持续缺少可读方位，已停止接近。'
                if scan_in_combat:
                    return self._scan_for_bearing(hwnd, position)
            return None
        if self._missing_bearing is not None:
            self._missing_bearing = None
            if not self._retarget_attempted and not self._discard_attempts:
                self._finished = False
            if self._pulses == 0 and bearing.distance is not None:
                self._distance_limit = min(60, bearing.distance + 5)
                self._best_distance = bearing.distance
        if self._finished:
            return None
        if position.sequence == self._sequence:
            return None
        previous_sequence, self._sequence = self._sequence, position.sequence
        if self._input_paused:
            self._input_paused = False
            self._reset_approach_feedback(position, bearing)
        if previous_sequence is None:
            return None

        # 正值需要右转。世界角度按屏幕方位的阈值等比例缩放。
        error = (bearing.x - 0.5 if bearing.heading is None
                 else -_angle_delta(bearing.heading, position.heading) / 2.5)
        offset = abs(error)
        if self._previous is not None:
            direction, old_offset, previous_position, previous_bearing = self._previous
            self._previous = None
            if (bearing.heading is None) != (previous_bearing.heading is None):
                self._best_distance = bearing.distance
                self._forward_stalls = self._turn_stalls = 0
            elif direction:
                improved = (old_offset - offset >= 0.004
                            and direction * _angle_delta(position.heading, previous_position.heading) >= 0.01)
                self._turn_stalls = 0 if improved else self._turn_stalls + 1
            else:
                distance = bearing.distance
                if bearing.estimated != previous_bearing.estimated or self._best_distance is None:
                    self._best_distance = distance
                closer = distance is not None and self._best_distance - distance >= 0.25
                if closer:
                    self._best_distance = distance
                moved = (bearing.estimated and self._displacement(previous_position, position) >= 0.25
                         and (distance is None or distance <= self._best_distance + 0.25))
                self._forward_stalls = 0 if closer or moved else self._forward_stalls + 1
        if self._turn_stalls >= 5 or self._forward_stalls >= 5:
            self._finished = True
            self.movement.release_forward()
            return '已暂停接近目标。游戏未读到预期的转向或距离变化。'
        distance_limit = min(8, self._distance_limit) if bearing.distance is None else self._distance_limit
        if self._displacement(self._origin, position) >= distance_limit or self._pulses >= 96:
            self._finished = True
            self.movement.release_forward()
            return '已暂停接近目标。达到本次移动范围上限。'

        forward, left, right = position.keys
        if offset > 0.045:
            direction = 1 if error < 0 else -1
            key = left if direction == 1 else right
            hold = min(100, max(35, round(400 * offset)))
            if holding and offset <= 0.12:
                sent = (self.movement.hold_forward(hwnd, position.keys)
                        and self.movement.pulse(hwnd, key, min(hold, 65), position.keys, steering=True))
            else:
                if holding:
                    self.movement.release_forward()
                sent = not position.moving and self.movement.pulse(hwnd, key, hold, position.keys)
        else:
            direction = 0
            sent = (self.movement.hold_forward(hwnd, position.keys) if continuous
                    else self.movement.pulse(hwnd, forward, 120, position.keys))
        if sent:
            self._pulses += 1
            self._previous = direction, offset, position, bearing
            if self._pulses == 1:
                return '开始接近当前射程外目标。'
        return None
