"""循环路线行走中按选怪键找怪（docs/design/20261117-patrol-scan.md）。不导入 Qt。

只负责“何时按、按后是否选到、交战何时结束”；交战时由窗口停住行程，交给现有循环、射程外接近与清目标逻辑。
"""
from wowbuddy.core.auto_target import parse_auto_target
from wowbuddy.core.candidates import Candidate

PRESS_INTERVAL_MS = 2500
SELECT_WAIT_MS = 2000
ENGAGE_LIMIT_MS = 30_000
SETTLE_MS = 1500
REJECTION_LIMIT = 3
ATTACK_RANGE_YARDS = 35
# 行走中开怪只在状态充足时进行：2026-11-17 01:12 血量 71% 时开怪连拉 4 只死亡。
MIN_HEALTH_PCT = 80
MIN_MANA_PCT = 50


def _ready_to_pull(fields):
    try:
        health = int(fields.get('player_health_pct', ''))
    except (TypeError, ValueError):
        return False
    if health < MIN_HEALTH_PCT:
        return False
    mana = fields.get('mana_pct')
    if mana in (None, '', '—'):
        return True                      # 无法力职业
    try:
        return int(mana) >= MIN_MANA_PCT
    except (TypeError, ValueError):
        return False


def _out_of_range(tick, fields):
    """目标在射程外：管线射程探测或插件距离读数。经典版拿不到怪物方位，射程外的目标无法主动接近。"""
    if tick.decision.attack_blocked_by_range:
        return True
    try:
        return float(fields.get('distance', '')) > ATTACK_RANGE_YARDS
    except (TypeError, ValueError):
        return False


class TravelScan:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self._segment = None
        self._reset_segment()

    def _reset_segment(self):
        self.presses = 0
        self.rejections = 0
        self._last_press = None
        self._pending_until = None
        self._watching = False       # 选到的目标在射程外：继续走，进入射程再停
        self.engaged = None          # (session, 开始时刻)
        self._fought = False
        self._clear_since = None

    def _enter(self, segment):
        if segment != self._segment:
            self._segment = segment
            self._reset_segment()

    def engaged_for(self, session):
        return self.engaged is not None and self.engaged[0] == session

    @property
    def watching(self):
        """已选到射程外的目标，正在等它进入射程（期间继续沿路走）。"""
        return self._watching and self.engaged is None

    def scanned(self, segment):
        """本段行走中是否按过选怪键（到点后可少扫一个方向）。"""
        return self._segment == segment and self.presses > 0

    def cancel(self):
        self._segment = None
        self._reset_segment()

    def status(self):
        return dict(presses=self.presses, rejections=self.rejections, engaged=self.engaged is not None)

    def observe(self, session, segment, *, walking, position, tick, now_ms, send_interval_ms):
        """每帧调用。segment 为 (会话, 停留点序号)。返回日志文字或 None。"""
        self._enter(segment)
        if tick is None or not tick.decision.frame.ok:
            return None
        fields = tick.decision.frame.values
        in_combat = fields.get('player_in_combat') == 'ON'
        target = fields.get('target_valid') == 'ON'

        if self.engaged is not None:
            if in_combat:
                self._fought = True
                self._clear_since = None
                return None
            if not target:
                if self._clear_since is None:
                    self._clear_since = now_ms
                if now_ms - self._clear_since < SETTLE_MS:
                    return None
                fought = self._fought
                self.engaged = None
                self._fought = False
                self._clear_since = None
                if not fought:
                    self.rejections += 1
                    return '途中选到的目标未能开始战斗，已放弃'
                return '途中交战结束'
            self._clear_since = None
            if not self._fought and now_ms - self.engaged[1] >= ENGAGE_LIMIT_MS:
                self.engaged = None
                self.rejections += 1
                return '途中选到的目标 30 秒内未能开始战斗，继续赶路'
            return None

        if self._pending_until is not None or self._watching:
            if target or in_combat:
                rejected = tick.decision.target_rejection
                if not in_combat and not rejected and _out_of_range(tick, fields):
                    # 射程外：经典版没有怪物方位，停下也无法接近；继续沿路走，进入射程再停。
                    self._pending_until = None
                    self._watching = True
                    return None
                # 选到射程内的目标（或游戏不认可的目标）：停住行程，交给现有循环、接近与清目标逻辑。
                self._pending_until = None
                self._watching = False
                self.engaged = session, now_ms
                self._fought = in_combat
                self._clear_since = None
                return '行走中选到目标，停下交战'
            if self._watching:
                self._watching = False          # 射程外的目标已丢失，可以再按选怪键
            elif now_ms >= self._pending_until:
                self._pending_until = None
                return None
            else:
                return None

        if (not walking or position is None or in_combat or target or self.rejections >= REJECTION_LIMIT
                or fields.get('player_valid') != 'ON' or not tick.decision.recovery_ready
                or not _ready_to_pull(fields)):
            return None
        if self._last_press is not None and now_ms - self._last_press < PRESS_INTERVAL_MS:
            return None
        if tick.display_now_ms - self.dispatcher.state.last_sent_ms < send_interval_ms:
            return None
        try:
            packet = parse_auto_target(int(fields.get('ttd', '')))
        except (TypeError, ValueError):
            return None
        if packet is None or packet.state != 0 or packet.key_index != position.idle_key_index or not packet.key:
            return None
        candidate = Candidate(action='auto_target', key=packet.key, label='行走选怪', tag='选目标', off_gcd=True)
        result = self.dispatcher.dispatch(candidate, hwnd=session[0], fields=fields)
        self._last_press = now_ms
        if result.success:
            self.presses += 1
            self._pending_until = now_ms + SELECT_WAIT_MS
        return None
