"""抵达练级点后借用现有安全宏选第一只怪。"""

from collections import deque
from math import pi

from wowbuddy.core.auto_target import parse_auto_target
from wowbuddy.core.candidates import Candidate
from wowbuddy.core.keybindings import parse_keybinding
from wowbuddy.automation.navigation import _angle_delta


_REJECTED_TARGET_LIMIT = 3
_REJECTED_TARGET_WINDOW_MS = 60_000
_PULL_ATTEMPT_LIMIT = 2
_SCAN_SECTORS = 4
_TARGET_WAIT_MS = 8000
_PULL_RECEIPT_MS = 2000


class ArrivalPull:
    def __init__(self, dispatcher, foreground):
        self.dispatcher = dispatcher
        self.foreground = foreground
        self._destination = None
        self._rejections = deque(maxlen=_REJECTED_TARGET_LIMIT)
        self._reset()

    def _set_destination(self, session, destination):
        target = session, destination
        if target != self._destination:
            self._destination = target
            self._rejections.clear()
            self._reset()

    def record_rejected_target(self, session, destination, origin, now_ms):
        if not destination.contains(origin):
            return False
        self._set_destination(session, destination)
        self._rejections.append(now_ms)
        return (len(self._rejections) == _REJECTED_TARGET_LIMIT
                and now_ms - self._rejections[0] <= _REJECTED_TARGET_WINDOW_MS)

    def pause(self, session):
        if self._destination is None or self._destination[0] != session:
            return
        self._ready_sample = self._turn_until = self._pursuit_sample = None
        if self._target_until is not None:
            self._retarget_paused = True

    def _reset(self):
        self._ready_sample = None
        self._attempts = 0
        self._retry_at = 0
        self._ack = None
        self._confirmed_attempts = 0
        self._pull_acknowledged = False
        self._scan_heading = None
        self._scan_confirmed = 0
        self._scan_attempts = 0
        self._turn_until = None
        self._pull_revision = None
        self._selected_revision = None
        self._selection_until = None
        self._target_until = None
        self._retarget_paused = False
        self._pursuit_sample = None
        self._cycle_until = None
        self._finished = False
        self.empty = False

    def _finish_target(self, now_ms, message):
        self._finished = True
        self._retry_at = now_ms + 10_000
        return message

    def _confirm_selection(self, packet, position, now_ms):
        if self._selection_until is None or self._pull_revision is None:
            return False
        revision = position.target_revision if position is not None else None
        expected_revision = (self._pull_revision + 1) % 65521
        if now_ms > self._selection_until or revision not in (None, self._pull_revision, expected_revision):
            self._selection_until = None
            return False
        key_index, previous_ack = self._ack
        if (revision == expected_revision and packet is not None
                and packet.key_index == key_index and packet.ack == (previous_ack + 1) % 32):
            self._selected_revision = revision
            self._selection_until = None
            return True
        return False

    def _observe_selected(self, session, destination, position, tick, now_ms, send_interval_ms, pursuing,
                          allow_retarget):
        fields = tick.decision.frame.values
        revision = position.target_revision if position is not None else None
        changed = revision is not None and self._selected_revision is not None and revision != self._selected_revision
        if self._cycle_until is not None:
            if changed and fields.get('target_valid') == 'ON':
                return self._finish_target(now_ms, '游戏已确认切换目标，交给当前循环。')
            if now_ms >= self._cycle_until:
                return self._finish_target(now_ms, '重选后未读到新目标，已停止重选。')
            return None
        if changed:
            return self._finish_target(now_ms, '追踪的目标已变化，交给当前循环。')
        if not allow_retarget or position is None or position.moving or not tick.decision.recovery_ready:
            self._ready_sample = None
            self._retarget_paused = True
            return None
        if self._retarget_paused:
            self._retarget_paused = False
            self._target_until = now_ms + _TARGET_WAIT_MS
        if pursuing and position.sequence != self._pursuit_sample:
            self._pursuit_sample = position.sequence
            self._target_until = now_ms + _TARGET_WAIT_MS
        if now_ms < self._target_until:
            return None
        if (not destination.contains(position) or not position.retarget_key
                or self._selected_revision is None or revision != self._selected_revision
                or fields.get('target_valid') != 'ON' or fields.get('player_valid') != 'ON'
                or fields.get('player_in_combat') != 'OFF' or tick.selected is not None
                or not tick.decision.attack_blocked_by_range
                or tick.status not in ('no_candidates', 'suppressed')):
            return self._finish_target(now_ms, '已选到目标，游戏尚未进入战斗。请查看射程或当前循环的状态。')
        if tick.display_now_ms - self.dispatcher.state.last_sent_ms < send_interval_ms:
            self._ready_sample = None
            return None
        key = position.retarget_key
        keys = (*position.keys, key)
        if not self.foreground.can_input(session[0], keys):
            self._ready_sample = None
            self._retarget_paused = True
            return None
        if self._ready_sample is None:
            self._ready_sample = position.sequence
            return None
        if self._ready_sample == position.sequence:
            return None
        self._cycle_until = now_ms + _PULL_RECEIPT_MS
        if self.foreground.pulse(session[0], key, 35, keys):
            return '当前目标仍在射程外，已请求重选一次，等待游戏确认。'
        return self._finish_target(now_ms, '当前游戏输入不可用，已暂停重选。')

    def observe(self, session, destination, position, tick, now_ms, send_interval_ms, *, pursuing=False,
                allow_retarget=True):
        self._set_destination(session, destination)
        if destination is None or destination.life != 'alive':
            return None
        if tick is None or not tick.decision.frame.ok:
            self.pause(session)
            return None
        fields = tick.decision.frame.values
        if fields.get('player_in_combat') == 'ON' and not tick.decision.target_rejection:
            self._rejections.clear()
        if self._finished:
            if now_ms < self._retry_at:
                return None
            self._reset()
        try:
            packet = parse_auto_target(int(fields.get('ttd', '')))
        except (TypeError, ValueError):
            packet = None

        if self._ack is not None and fields.get('player_valid') == 'ON':
            acknowledged = packet and packet.key_index == self._ack[0] and packet.ack != self._ack[1]
            if acknowledged and not self._pull_acknowledged:
                self._confirmed_attempts += 1
                if self._scan_heading is not None:
                    self._scan_confirmed += 1
                    self._scan_attempts = 0
                self._pull_acknowledged = True
            if fields.get('player_in_combat') == 'ON':
                return self._finish_target(now_ms, '游戏已确认进入战斗，继续由当前循环处理。')
            if fields.get('target_valid') == 'ON' and not tick.decision.target_rejection:
                first_target = self._target_until is None
                if first_target:
                    self._target_until = now_ms + _TARGET_WAIT_MS
                    self._selection_until = now_ms + _PULL_RECEIPT_MS
                confirmed = self._confirm_selection(packet, position, now_ms)
                if first_target:
                    if acknowledged:
                        return '游戏已确认首次选怪键生效，并出现可攻击目标。'
                    return '游戏已出现可攻击目标，交给当前循环。'
                if confirmed:
                    return '已核对选怪回执和目标序号，继续追踪当前目标。'
        if tick.decision.target_rejection:
            # 保留已收到的选怪回执，等目标清除后接着扫下一方向。
            self._ready_sample = self._selected_revision = self._selection_until = None
            self._target_until = self._cycle_until = None
            self._retarget_paused = False
            return None
        if self._target_until is not None:
            return self._observe_selected(session, destination, position, tick, now_ms, send_interval_ms, pursuing,
                                          allow_retarget)

        if (position is None or position.moving or not destination.contains(position) or packet is None or packet.state != 0
                or packet.key_index != position.idle_key_index
                or fields.get('target_valid') != 'OFF' or fields.get('player_valid') != 'ON'
                or fields.get('player_in_combat') != 'OFF' or tick.selected is not None
                or tick.status not in ('stopped', 'no_candidates')
                or not tick.decision.recovery_ready):
            self.pause(session)
            return None
        if now_ms < self._retry_at or tick.display_now_ms - self.dispatcher.state.last_sent_ms < send_interval_ms:
            self._ready_sample = None
            return None
        scanning = self._scan_confirmed > 0
        attempts = self._scan_attempts if scanning else self._attempts
        if self._scan_confirmed == _SCAN_SECTORS or attempts >= _PULL_ATTEMPT_LIMIT:
            self._finished = True
            self.empty = (self._scan_confirmed == _SCAN_SECTORS if scanning
                          else self._confirmed_attempts == _PULL_ATTEMPT_LIMIT)
            self._retry_at = now_ms + 45_000
            if scanning:
                return '四个方向均未读到可攻击目标，已暂停重试。' if self.empty else '部分方向未收到选怪回执，已暂停重试。'
            return ('两次首次选怪均收到回执但未读到可攻击目标，已暂停重试。' if self.empty
                    else '首次选怪回执不足，已暂停重试。')

        binding = parse_keybinding(packet.key)
        hwnd = session[0]
        if not binding.valid or not self.foreground.can_input(hwnd, (*position.keys, binding.vk, *binding.modifiers)):
            self.pause(session)
            return None
        if self._ready_sample is None:
            self._ready_sample = position.sequence
            return None
        if self._ready_sample == position.sequence:
            return None

        if scanning:
            sector = self._scan_confirmed
            desired = self._scan_heading + sector * pi / 2
            angle = _angle_delta(desired, position.heading)
            if abs(angle) > 0.20:
                if self._turn_until is not None and now_ms >= self._turn_until:
                    self._finished = True
                    self._retry_at = now_ms + 45_000
                    return '未确认转到下一个寻怪方向，已暂停重试。'
                starting = self._turn_until is None
                if starting:
                    self._turn_until = now_ms + 5000
                _, left, right = position.keys
                key = left if angle > 0 else right
                hold = min(120, max(35, round(260 * abs(angle))))
                self._ready_sample = None
                if self.foreground.pulse(hwnd, key, hold, position.keys) and starting:
                    return f'当前方向未选到怪，开始查看第 {sector + 1} 个方向。'
                return None
            self._turn_until = None
        candidate = Candidate(action='auto_target', key=packet.key, label='首次选怪', tag='选目标', off_gcd=True)
        result = self.dispatcher.dispatch(candidate, hwnd=hwnd, fields=fields)
        if scanning:
            self._scan_attempts += 1
        else:
            self._attempts += 1
        self._retry_at = now_ms + _PULL_RECEIPT_MS
        self._ready_sample = None
        if result.success:
            if not scanning:
                self._scan_heading = position.heading if position.continuous else None
            self._ack = packet.key_index, packet.ack
            self._pull_revision = position.target_revision
            self._pull_acknowledged = False
            return f'已发出首次选怪键 {packet.key}，等待游戏确认目标。'
        return '首次选怪键发送失败，将在下一次满足条件时重试。'
