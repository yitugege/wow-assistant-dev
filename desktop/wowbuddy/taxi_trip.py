"""鲁瑟兰至奥伯丁的原生飞行界面交互。"""


class TaxiTrip:
    def __init__(self, *, departed=False):
        self.departed = departed
        self._armed = departed
        self._boarding_at = None
        self._sequence = None
        self._phase = None
        self._attempts = 0
        self._next_attempt = 0
        self._hover = None
        self._notice = None
        self._unavailable_since = None
        self._failure = None
        self._close_requested = False
        self.failed = False

    @property
    def boarding_started(self):
        return self.departed or self._boarding_at is not None

    def _report(self, message):
        if message != self._notice:
            self._notice = message
            return message

    def _finish_failure(self, reading, send):
        if not reading.panel_open:
            self.failed = True
            return self._report(self._failure)
        if reading.selected and not self._close_requested:
            self._close_requested = True
            send('close', None)
        return self._report(f'{self._failure}，等待游戏确认飞行面板已关闭。')

    def observe(self, reading, now, *, at_platform, ready, send):
        if at_platform:
            self._armed = True
        if not self._armed:
            return None
        if reading is None:
            self._hover = None
            self._unavailable_since = None
            if at_platform:
                return self._report('已到鲁瑟兰飞行台，等待新版插件提供航线读数。')
            return None
        if reading.sequence == self._sequence:
            return None
        self._sequence = reading.sequence
        if reading.riding:
            if not self.departed and (reading.map_id == 1438 or self._boarding_at is not None):
                self.departed = True
                return self._report('游戏已确认登机，等待奥伯丁落地。')
            return None
        if self.departed or reading.map_id != 1438 or not at_platform or not ready or reading.blocked:
            self._hover = None
            self._unavailable_since = None
            return None
        if self._failure is not None:
            return self._finish_failure(reading, send)
        if self._boarding_at is not None:
            if now - self._boarding_at >= 8000:
                self._failure = '游戏未确认登机'
                return self._finish_failure(reading, send)
            return None
        unavailable = reading.panel_open and reading.button is None
        if not unavailable:
            self._unavailable_since = None
        if reading.panel_open:
            if unavailable:
                self._hover = None
                if not reading.selected:
                    self._unavailable_since = None
                    return None
                if self._unavailable_since is None:
                    self._unavailable_since = now
                elif now - self._unavailable_since >= 1500:
                    self._failure = '飞行面板未确认可达的免费奥伯丁直飞航线'
                    return self._finish_failure(reading, send)
                return self._report('等待飞行面板确认免费奥伯丁直飞航线。')
            if self._hover != reading.button or not reading.hovered:
                if now >= self._next_attempt and send('hover', reading.button):
                    self._hover = reading.button
                    self._next_attempt = now + 500
                return None
            # 点击最多一次，即使系统无法确认输入是否完整投递。
            self._boarding_at = now
            send('board', reading.button)
            return self._report('已请求点击原生航线按钮，等待游戏确认登机。')
        self._hover = None
        phase = 'interact' if reading.selected else 'select'
        if phase != self._phase:
            self._phase = phase
            self._attempts = 0
            self._next_attempt = now
        value = reading.interact_vk if reading.selected else reading.select_key
        if not value:
            return self._report('飞行管理员按键不可用，等待可用的目标与交互绑定。')
        if self._attempts >= 2:
            if now >= self._next_attempt:
                self._failure = '游戏未确认飞行管理员交互'
                return self._finish_failure(reading, send)
            return None
        if now >= self._next_attempt and send(phase, value):
            self._attempts += 1
            self._next_attempt = now + 1500
        return None
