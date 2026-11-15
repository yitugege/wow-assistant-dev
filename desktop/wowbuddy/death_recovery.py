"""用已确认的暴雪弹窗接续死亡恢复流程。"""

import math

from .navigation import MapDestination
from .manual_routes import parse_manual_route
from .pixel_geometry import lround


_AVOID_RADIUS = 18
_DANGER_WINDOW_MS = 8000
_REDEATH_WINDOW_MS = 30_000
_UNATTENDED_LANDING_COMBAT_MS = 20_000
_UNATTENDED_REDEATH_WINDOW_MS = 45_000
_LANDING_EXIT_RADIUS = 40
_OUTWARD_PROBE_LIMIT = 35
_LANDING_THREAT_RADIUS = 12
_CORPSE_PROBE_YARDS = 16
_CORPSE_POPUP_WAIT_MS = 1500
_REVIVAL_RETRY_MS = 12_000
_INPUT_RETRY_DELAYS_MS = (3000, 6000, 12_000)
_CORPSE_SEGMENT_POINTS = 256
_CORPSE_START_STABLE_MS = 1200
_CORPSE_START_MAX_GAP_MS = 1000
_CORPSE_START_MAX_TRAVEL_YARDS = 25


class CorpseTrail:
    """记录灵魂实走的分地图路点，仅在尸体附近成功复活后提交。"""

    def __init__(self):
        self._session = None
        self._life = None
        self._goal = None
        self._goal_estimated = True
        self._segments = []
        self._last_position = None
        self._start_candidate = None
        self._start_position = None
        self._crossing = None
        self._invalid = None
        self._confirmed = False
        self.replay_blocked = False
        self.notice = None

    def cancel_recording(self):
        self._life = None
        self._goal = None
        self._goal_estimated = True
        self._segments.clear()
        self._last_position = self._crossing = None
        self._start_candidate = self._start_position = None
        self._invalid = None
        self._confirmed = False
        self.notice = None

    @staticmethod
    def _distance(position, point, origin):
        return math.hypot((point[0] - origin[0]) * position.width / 100,
                          (point[1] - origin[1]) * position.height / 100)

    @property
    def waiting_for_start(self):
        return self._life == 'ghost' and self._start_position is None

    def observe(self, session, state, position, *, now_ms, enabled=True):
        if self._session != session:
            self.__init__()
            self._session = session
        self.notice = None
        if state is None or state.life == 'unknown':
            return None
        if state.life == 'dead':
            self.cancel_recording()
            self.replay_blocked = False
            self._life = 'dead'
            return None
        if state.life == 'ghost':
            if self._life in ('dead', 'ghost'):
                if enabled and state.corpse is not None and (not state.corpse_estimated or self._goal_estimated):
                    self._goal = MapDestination(*state.corpse, 'ghost', '尸体')
                    self._goal_estimated = state.corpse_estimated
                if position is not None and position.life == 'ghost':
                    if self._start_position is None:
                        self._confirm_start(position, now_ms)
                        if enabled and self._start_position is not None:
                            self._record_position(self._start_position)
                    if enabled and self._start_position is not None:
                        self._record_position(position)
                actor = position or self._last_position
                if enabled and self._goal is not None and state.button is not None and actor is not None:
                    self._confirmed |= self._goal.contains(actor, radius=35)
                self._life = 'ghost'
            else:
                self._life = 'unarmed_ghost'
            return None
        if state.life == 'alive' and self._life in ('ghost', 'unarmed_ghost', 'dead'):
            armed = self._life != 'unarmed_ghost'
            self._life = 'alive'
            return self._finish(position, armed=armed) if enabled else None
        self._life = state.life
        return None

    def _confirm_start(self, position, now_ms):
        candidate = self._start_candidate
        if candidate is None:
            self._start_candidate = position, now_ms, position.sequence, now_ms
            return
        first, started, last_sequence, checked = candidate
        moved = self._distance(position, (position.x, position.y), (first.x, first.y))
        if (position.map_id != first.map_id or now_ms - checked > _CORPSE_START_MAX_GAP_MS
                or moved > _CORPSE_START_MAX_TRAVEL_YARDS):
            self._start_candidate = position, now_ms, position.sequence, now_ms
        elif position.sequence != last_sequence:
            self._start_candidate = first, started, position.sequence, now_ms
            if now_ms - started >= _CORPSE_START_STABLE_MS:
                self._start_position = first
                self._start_candidate = None

    def _finish(self, position, *, armed):
        end = position or self._last_position
        if not armed:
            reason = '未观察到释放灵魂前的死亡状态，缺少墓地起点'
        elif self._invalid:
            reason = self._invalid
        elif not self._segments:
            reason = '释放灵魂后的墓地坐标未达到稳定确认条件'
        elif self._crossing is not None:
            reason = f'进入地图 {self._crossing.map_id} 后缺少第二帧定位，无法确认跨图'
        elif self._goal is None:
            reason = '游戏未提供尸体地图或坐标'
        elif end.map_id != self._goal.map_id or self._segments[-1][0] != self._goal.map_id:
            reason = f'末段未到达尸体所在的地图 {self._goal.map_id}'
        elif not self._confirmed and (position is None or math.hypot(*self._goal.offset_from(position)) > 20):
            reason = '未看到有效的尸体复活按钮，复活位置也未能确认在尸体旁'
        elif math.hypot(*self._goal.offset_from(end)) > 35:
            reason = '复活位置距记录的尸体超过 35 码'
        else:
            self._sample(self._last_position, force=True)
            reason = self._invalid or next((f'地图 {map_id} 的有效路点不足两个'
                                            for map_id, points in self._segments if len(points) < 2), None)
        if reason:
            self.notice = f'跑尸路线未保存：{reason}。'
            return None
        encoded = []
        for map_id, points in self._segments:
            coords = '|'.join(f'{round(x * 100)},{round(y * 100)}' for x, y in points)
            encoded.append(f'WBDROUTE1|{map_id}|{coords}')
        corpse_x, corpse_y = round(self._goal.x * 100), round(self._goal.y * 100)
        header = f'WBDCORPSE1|{end.width},{end.height},{corpse_x},{corpse_y}'
        return ':'.join((header, *encoded))

    def _record_position(self, position):
        if self._invalid:
            return
        if not self._segments:
            self._segments.append((position.map_id, []))
            self.notice = f'已开始录制跑尸路线，墓地地图 {position.map_id}。'
        elif position.map_id != self._segments[-1][0]:
            pending = self._crossing
            if pending is None or pending.map_id != position.map_id:
                self._crossing = position
                return
            if pending.sequence == position.sequence:
                return
            self._sample(self._last_position, force=True)
            if self._invalid:
                return
            if len(self._segments) >= 8:
                self._invalid = '已超过 8 个地图路段'
                return
            self._segments.append((position.map_id, []))
            self.notice = f'跑尸录制已确认进入地图 {position.map_id}，开始记录第 {len(self._segments)} 段。'
            self._sample(pending)
        self._crossing = None
        self._sample(position)
        self._last_position = position

    def _sample(self, position, *, force=False):
        points = self._segments[-1][1]
        point = round(position.x, 2), round(position.y, 2)
        if points:
            distance = self._distance(position, point, points[-1])
            if distance == 0 or (distance < 8 and not force):
                return
            if distance > 90:
                self._invalid = f'地图 {position.map_id} 的定位中断，两次可用坐标相差 {distance:.0f} 码'
                return
            if not force and len(points) > 2:
                for index in range(len(points) - 3, 0, -1):
                    if self._distance(position, point, points[index]) <= 2:
                        # 回到原路后丢弃绕回原地的折返，保留靠拢位置。
                        points[index:] = [point]
                        return
            if len(points) > 1:
                start, corner = points[-2:]
                direct = self._distance(position, start, point)
                via = self._distance(position, start, corner) + distance
                if via - direct <= 0.18:
                    points[-1] = point
                    return
        if len(points) >= _CORPSE_SEGMENT_POINTS:
            self._invalid = f'地图 {position.map_id} 超过 {_CORPSE_SEGMENT_POINTS} 个可保存路点'
            return
        points.append(point)

    def replay(self, routes, position, goal):
        if self.replay_blocked:
            return ()
        best = ()
        best_distance = math.inf
        for text in routes:
            try:
                width, height = position.width, position.height
                if text.startswith('WBDCORPSE1|'):
                    header, *segments = text.split(':')
                    width, height, corpse_x, corpse_y = map(int, header.split('|')[1].split(','))
                    if not (1 <= width <= 100000 and 1 <= height <= 100000 and 1 <= len(segments) <= 8):
                        continue
                    if not (0 <= corpse_x <= 10000 and 0 <= corpse_y <= 10000):
                        continue
                    route = tuple(parse_manual_route(segment, max_points=_CORPSE_SEGMENT_POINTS)
                                  for segment in segments)
                    x, y = corpse_x / 100, corpse_y / 100
                else:
                    route = (parse_manual_route(text),)
                    x, y = route[-1].endpoint
            except ValueError:
                continue
            if route[0].map_id != position.map_id or route[-1].map_id != goal.map_id:
                continue
            if any(first.map_id == second.map_id for first, second in zip(route, route[1:])):
                continue
            start = self._distance(position, route[0].points[0], (position.x, position.y))
            end = math.hypot((x - goal.x) * width / 100, (y - goal.y) * height / 100)
            if start <= 15 and end <= 30 and start + end < best_distance:
                best, best_distance = route, start + end
        return best


class CorpseAccess:
    """尸体附近有限试探，复活是否可用仍由游戏弹窗确认。"""

    def __init__(self):
        self._key = None
        self._destination = None
        self._probes = None
        self._arrival = None

    def pause(self):
        self._arrival = None

    def _next_probe(self, position, goal):
        if self._probes is None:
            east, north = goal.offset_from(position)
            angle = math.atan2(-north, -east)
            probes = []
            for offset in (math.pi / 2, -math.pi / 2, math.pi, 0):
                heading = angle + offset
                x = goal.x + _CORPSE_PROBE_YARDS * math.cos(heading) * 100 / position.width
                y = goal.y - _CORPSE_PROBE_YARDS * math.sin(heading) * 100 / position.height
                if 0 < x < 100 and 0 < y < 100:
                    probes.append(MapDestination(goal.map_id, x, y, 'ghost', '尸体附近的备选接入点', radius=3))
            self._probes = iter(probes)
        self._arrival = None
        self._destination = next((probe for probe in self._probes if not probe.contains(position)), None)
        if self._destination is None:
            return None, '尸体附近的备选接入点已试完，等待游戏开放复活。'
        return self._destination, '尸体直达受阻或未出现复活按钮，尝试从附近接近。'

    def observe(self, session, position, goal, now_ms, *, blocked=None):
        key = session, goal
        if key != self._key:
            self._key = key
            self._destination = goal
            self._probes = self._arrival = None
        destination = self._destination
        if destination is None or position is None or position.life != 'ghost' or position.map_id != goal.map_id:
            self.pause()
            return destination, None
        if blocked == destination:
            return self._next_probe(position, goal)
        if position.moving or not destination.contains(position):
            self.pause()
        elif self._arrival is None:
            self._arrival = position.sequence, now_ms
        elif position.sequence != self._arrival[0] and now_ms - self._arrival[1] >= _CORPSE_POPUP_WAIT_MS:
            return self._next_probe(position, goal)
        return destination, None


class AutomaticRevival:
    def __init__(self, mouse, *, stop_movement=None, prefer_clearance=False, in_foreground=None):
        self.mouse = mouse
        self.stop_movement = stop_movement
        self.prefer_clearance = prefer_clearance
        self.in_foreground = in_foreground
        self.session = None
        self.life = None
        self._dialog_rect = None
        self._unsafe_landings = []
        self._landing = None
        self._revived_at = None
        self._under_attack = False
        self._last_combat_ms = None
        self._probe_clearance = False
        self._delayed_retry_used = False
        self._reset_landing_search()
        self._reset_attempts()

    def _reset_landing_search(self):
        self.landing_destination = None
        self._landing_origin = None
        self._tried_landings = []
        self._returning = False
        self._nearby_threat = None

    def _distance_from_unsafe(self, position):
        return min((math.hypot(*site.offset_from(position)) for site in self._unsafe_landings
                    if site.map_id == position.map_id), default=math.inf)

    def landing_blocked(self):
        if self.landing_destination is None:
            return None
        if not self._returning:
            self._returning = True
            self.landing_destination = self._landing_origin
            return None
        self.landing_destination = self._landing_origin = None
        self._returning = self._probe_clearance = False
        self.armed = self._retry_sample = None
        return '返回上一处复活位置也受阻，从当前位置重新确认复活或接入跑尸路线。'

    def _choose_landing(self, state, position, *, avoid_origin=False, threat=None):
        corpse_map, cx, cy = state.corpse
        if corpse_map != position.map_id:
            return None
        east = (position.x - cx) * position.width / 100
        north = (cy - position.y) * position.height / 100
        radius = math.hypot(east, north)
        angle = math.atan2(north, east)
        # 沿尸体等距线换一个方向，略向内收，游戏弹窗仍决定是否可复活。
        turn = min(math.pi / 2, 24 / max(radius, 1))
        radius = max(12, radius - 3)
        candidates = []
        unsafe = self._unsafe_landings
        if avoid_origin:
            unsafe = [*unsafe, MapDestination(position.map_id, position.x, position.y, 'ghost', '当前复活点')]
        for direction in (1, -1):
            heading = angle + direction * turn
            x = cx + radius * math.cos(heading) * 100 / position.width
            y = cy - radius * math.sin(heading) * 100 / position.height
            if not (0 < x < 100 and 0 < y < 100):
                continue
            destination = MapDestination(corpse_map, x, y, 'ghost', '备选复活点', radius=2)
            def separation(site):
                return math.hypot((site.x - x) * position.width / 100, (site.y - y) * position.height / 100)

            clearance = min((separation(site) for site in unsafe if site.map_id == corpse_map), default=math.inf)
            tried_nearby = any(separation(site) < 8 for site in self._tried_landings)
            if clearance >= _AVOID_RADIUS and not tried_nearby:
                candidates.append((separation(threat) if threat else clearance, destination))
        return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else None

    def _position_for_revival(self, state, position, threat):
        if self.landing_destination is None and state.button is None:
            return None
        if position is None:
            if (self.landing_destination is not None or self._unsafe_landings
                    or (self.prefer_clearance and state.corpse and not state.corpse_estimated)):
                return '等待有效的灵魂定位，再确认备选复活点。'
            return None
        threatened_here = threat is not None and threat.contains(position, radius=_LANDING_THREAT_RADIUS)
        if self.landing_destination is not None:
            if state.popup == 'missing' and not self._returning:
                self.landing_blocked()
                return '备选位置超出游戏复活范围，先返回上一个可用位置。'
            if not self.landing_destination.contains(position) or position.moving:
                return '正在换到备选复活位置。'
            if not self._returning:
                self._probe_clearance = threatened_here
            self.landing_destination = None
            self._returning = False
        if self._probe_clearance and not self._unsafe_landings and state.button and not position.moving:
            if state.corpse and not state.corpse_estimated and state.corpse[0] == position.map_id:
                _, cx, cy = state.corpse
                distance = math.hypot((position.x - cx) * position.width / 100,
                                      (position.y - cy) * position.height / 100)
                if 2 <= distance < _OUTWARD_PROBE_LIMIT and not self._tried_landings and threat is None:
                    factor = 10 / distance
                    x = position.x + (position.x - cx) * factor
                    y = position.y + (position.y - cy) * factor
                    if 0 < x < 100 and 0 < y < 100:
                        destination = MapDestination(position.map_id, x, y, 'ghost', '远离遇袭处的复活点', radius=2)
                        self._probe_clearance = False
                        self._start_landing(position, destination)
                        return '先尝试离尸体更远的复活位置。'
                if len(self._tried_landings) < 2:
                    destination = self._choose_landing(state, position, avoid_origin=True, threat=threat)
                    if destination is not None:
                        self._start_landing(position, destination)
                        self._tried_landings.append(destination)
                        return '先尝试从尸体侧面复活，避开当前落点。'
            self._probe_clearance = False
        if state.button is None:
            return None
        if self._distance_from_unsafe(position) >= _AVOID_RADIUS:
            if threatened_here:
                return '当前复活位置附近刚出现敌人，等待敌人离开。'
            return None
        if state.corpse is None or state.corpse_estimated:
            return '当前仍靠近曾遭袭的复活点，等待游戏确认尸体位置。'
        if len(self._tried_landings) < 2:
            destination = self._choose_landing(state, position, threat=threat)
            if destination is not None:
                self._start_landing(position, destination)
                self._tried_landings.append(destination)
                return '上次复活后遭袭，正在换到备选复活位置。'
        return '附近暂未确认其他可用复活位置，暂停重复复活。'

    def _start_landing(self, position, destination):
        self._landing_origin = MapDestination(position.map_id, position.x, position.y, 'ghost',
                                               '上一处可复活位置', radius=2)
        self.landing_destination = destination

    def _reset_attempts(self):
        self.armed = None
        self.attempts = 0
        self._last_popup_sequence = None
        self._background_sequence = None
        self._input_failures = 0
        self._last_click = None
        self._retry_sample = None
        self.next_attempt_ms = 0
        self.reported_exhausted = False
        self._last_wait = None

    def _waiting(self, message):
        if message != self._last_wait:
            self._last_wait = message
            return message
        return None

    def _retry_input(self, now_ms, message):
        self.next_attempt_ms = now_ms + _INPUT_RETRY_DELAYS_MS[self._input_failures]
        self._input_failures = min(self._input_failures + 1, len(_INPUT_RETRY_DELAYS_MS) - 1)
        self._retry_sample = None
        return self._waiting(message)

    def pause(self, session):
        if session == self.session:
            self.armed = self._retry_sample = None

    def observe(self, session, hwnd, state, rect, now_ms, *, position=None, in_combat=False, recovery_ready=False,
                nearby_hostile=False):
        if session != self.session:
            self.session = session
            self.life = None
            self._dialog_rect = None
            self._unsafe_landings.clear()
            self._landing = self._revived_at = None
            self._under_attack = False
            self._last_combat_ms = None
            self._probe_clearance = False
            self._delayed_retry_used = False
            self._reset_landing_search()
            self._reset_attempts()
        if state is None or state.life == 'unknown':
            self.pause(session)
            return None
        if state.life == 'alive' and in_combat:
            self._last_combat_ms = now_ms
        if state.life != self.life:
            previous, self.life = self.life, state.life
            self._dialog_rect = None
            self._delayed_retry_used = False
            self._reset_landing_search()
            self._reset_attempts()
            if previous is None and self.life == 'ghost':
                self._probe_clearance = self.prefer_clearance
            if previous == 'dead' and self.life == 'ghost':
                return '游戏已确认进入灵魂状态。'
            if previous in ('dead', 'ghost') and self.life == 'alive':
                self._revived_at = now_ms
                self._under_attack = in_combat and (self.prefer_clearance or not recovery_ready)
                return '游戏已确认角色复活。'
            if self.life == 'dead':
                self._probe_clearance = (self.prefer_clearance and self._last_combat_ms is not None
                                         and 0 <= now_ms - self._last_combat_ms <= 3000)
                self._last_combat_ms = None
                death_window = _UNATTENDED_REDEATH_WINDOW_MS if self.prefer_clearance else _REDEATH_WINDOW_MS
                if (self._landing and self._under_attack and self._revived_at is not None
                        and now_ms - self._revived_at <= death_window):
                    self._unsafe_landings = [*self._unsafe_landings[-2:], self._landing]
                self._landing = self._revived_at = None
                self._under_attack = False
        if self.life == 'alive' and self._revived_at is not None:
            elapsed = now_ms - self._revived_at
            if self.prefer_clearance:
                left_landing = (self._landing is not None and position is not None
                                and (position.map_id != self._landing.map_id
                                     or math.hypot(*self._landing.offset_from(position)) > _LANDING_EXIT_RADIUS))
                if left_landing or elapsed > _UNATTENDED_REDEATH_WINDOW_MS:
                    self._revived_at = None
                    self._under_attack = False
                elif in_combat and elapsed <= _UNATTENDED_LANDING_COMBAT_MS:
                    self._under_attack = True
            elif recovery_ready:
                self._revived_at = None
                self._under_attack = False
            elif in_combat and elapsed <= _DANGER_WINDOW_MS:
                self._under_attack = True
        if state.button is not None and self.in_foreground is not None and not self.in_foreground(hwnd):
            self.pause(session)
            self.next_attempt_ms = (self._last_click[1] + 3000) if self._last_click is not None else 0
            self._input_failures = 0
            self._background_sequence = state.sequence
            action = '释放灵魂' if self.life == 'dead' else '尸体复活'
            return self._waiting(f'等待游戏回到前台，再确认「{action}」按钮。')
        if state.sequence == self._background_sequence:
            return None
        self._background_sequence = None
        if self.life == 'ghost':
            if self.prefer_clearance and nearby_hostile and position is not None:
                threat = MapDestination(position.map_id, position.x, position.y, 'ghost', '附近出现敌人的位置')
                self._nearby_threat = now_ms, threat
                if len(self._tried_landings) < 2 and self.landing_destination is None:
                    self._probe_clearance = True
            threat = None
            if self._nearby_threat and now_ms - self._nearby_threat[0] <= _DANGER_WINDOW_MS:
                threat = self._nearby_threat[1]
                if position is not None and threat.map_id != position.map_id:
                    threat = None
            reposition = self._position_for_revival(state, position, threat)
            if reposition:
                self.armed = None
                self._retry_sample = None
                return self._waiting(reposition)
        if state.button is None:
            self.armed = None
            self._retry_sample = None
            if state.popup in ('missing', 'disabled') and self._dialog_rect is not None:
                self._dialog_rect = None
                self._reset_attempts()
            if self.life == 'dead':
                message = {
                    'input_blocked': '已读到死亡，等待插件允许输入。',
                    'disabled': '释放灵魂按钮暂不可用，等待游戏开放。',
                    'unreadable': '释放灵魂弹窗读数不可用，暂不点击。',
                    'ready': '释放灵魂按钮已就绪，等待游戏确认脱战。',
                }.get(state.popup, '已读到死亡，等待暴雪释放灵魂弹窗。')
                return self._waiting(message)
            if self.life == 'ghost':
                if state.popup == 'input_blocked':
                    return self._waiting('已读到灵魂状态，等待插件允许输入。')
                if state.popup == 'disabled':
                    return self._waiting('复活按钮暂不可用，等待游戏倒计时结束。')
                if state.popup == 'unreadable':
                    return self._waiting('复活弹窗读数不可用，暂不点击。')
                if state.corpse is None:
                    return self._waiting('已读到灵魂状态，等待尸体位置或复活弹窗。')
                if state.corpse_estimated:
                    return self._waiting('游戏尚未给出尸体坐标，先按角色死亡时的位置返回。')
            return None
        released = self.stop_movement is None or self.stop_movement()
        if not released or (self.life == 'ghost' and position is not None and position.moving):
            self.armed = None
            self._retry_sample = None
            return self._waiting('正在停步，等角色站定后确认复活流程按钮。')
        if rect is None or rect.empty:
            self.armed = None
            self._retry_sample = None
            return self._waiting('已读到复活流程按钮，等待有效的游戏窗口坐标。')
        if rect != self._dialog_rect:
            self._dialog_rect = rect
            self._reset_attempts()

        bx, by = state.button
        point = (rect.left + lround(rect.width * bx / 10000),
                 rect.top + lround(rect.height * by / 10000))
        if not (rect.left <= point[0] < rect.right and rect.top <= point[1] < rect.bottom):
            self.armed = None
            self._retry_sample = None
            return None
        fresh = state.sequence != self._last_popup_sequence
        self._last_popup_sequence = state.sequence
        if self.armed is not None:
            armed_point, sequence, deadline, delayed = self.armed
            if point != armed_point or (delayed and (state.popup != 'ready' or in_combat)):
                self.armed = None
            elif now_ms >= deadline:
                self.armed = None
                return self._retry_input(now_ms, '游戏未确认鼠标命中复活流程按钮，稍后重新定位。')
            elif fresh and state.sequence != sequence and state.hovered:
                self.armed = None
                if self.mouse.click(hwnd, point):
                    self.attempts += 1
                    self._input_failures = 0
                    if delayed:
                        self._delayed_retry_used = True
                    if state.popup == 'ready':
                        self._last_click = point, now_ms
                    action = '释放灵魂' if self.life == 'dead' else '尸体复活'
                    if self.life == 'ghost' and position is not None:
                        self._landing = MapDestination(position.map_id, position.x, position.y, 'ghost', '曾遭袭的复活点')
                    return f'已点击暴雪「{action}」按钮，等待游戏确认。'
                return self._retry_input(now_ms, '复活流程按钮点击未确认，等待重试。')
            return None

        if not fresh or now_ms < self.next_attempt_ms:
            return None
        delayed = self.attempts >= 2
        if delayed:
            can_retry = (not self._delayed_retry_used and state.popup == 'ready' and not in_combat
                         and self._last_click is not None and self._last_click[0] == point)
            if can_retry:
                if now_ms - self._last_click[1] < _REVIVAL_RETRY_MS:
                    return self._waiting('游戏仍显示复活流程按钮，延时确认后再尝试一次。')
                sample = point, state.sequence
                if self._retry_sample is None or self._retry_sample[0] != point:
                    self._retry_sample = sample
                    return None
                if sample == self._retry_sample:
                    return None
            else:
                self._retry_sample = None
                if not self.reported_exhausted:
                    self.reported_exhausted = True
                    count = '三次' if self.attempts > 2 else '两次'
                    return f'自动复活暂停。{count}尝试后未确认下一阶段。'
                return None
        if self.mouse.move(hwnd, point):
            self._retry_sample = None
            self.next_attempt_ms = now_ms + 3000
            self.armed = point, state.sequence, now_ms + 1000, delayed
            return self._waiting('已定位复活流程按钮，等待游戏确认鼠标命中。')
        return self._retry_input(now_ms, '复活流程按钮暂时无法安全定位鼠标，稍后重试。')
