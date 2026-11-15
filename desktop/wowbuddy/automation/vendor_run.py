"""根据背包和装备回执执行补给，只操作游戏原生商店。"""


def vendor_due(reading):
    return reading.free == 0 or (reading.free <= 2 and reading.junk > 0)


def read_vendor_travel(path, identity, character, route_settings):
    from wowbuddy.automation.leveling_route import read_recent_travel

    record = read_recent_travel(path)
    if (record is None or record.get('character') != identity or record.get('settings') != route_settings
            or record.get('map') != character.map_id or record.get('zone') != character.zone
            or type(record.get('catalog')) is not bool or type(record.get('returning')) is not bool
            or type(record.get('level')) is not int or not 1 <= record['level'] <= 255
            or type(record.get('repair', False)) is not bool
            or type(record.get('free')) is not int
            or not 0 <= record['free'] <= (1023 if record.get('repair') else 2)):
        return None
    def coordinate_pair(pair):
        return (isinstance(pair, list) and len(pair) == 2
                and all(type(value) in (int, float) and 0 <= value <= 100 for value in pair))

    for key in ('outbound', 'inbound'):
        road = record.get(key)
        if not isinstance(road, list) or not 1 <= len(road) <= 200 or not all(map(coordinate_pair, road)):
            return None
    camp = record.get('camp')
    if (not isinstance(camp, list) or len(camp) != 4 or not coordinate_pair(camp[:2])
            or not isinstance(camp[2], str) or not 0 < len(camp[2]) <= 160
            or (camp[3] is not None and (type(camp[3]) not in (int, float) or not 0 < camp[3] <= 100))):
        return None
    return record


class VendorRun:
    def __init__(self, *, resume_session=None, repair=False):
        self.session = resume_session
        self.active = resume_session is not None
        self.repair = repair
        self._sequence = None
        self._phase = None
        self._attempts = 0
        self._next_attempt = 0
        self._before_sale = None
        self._partial_sale = None
        self._confirmed = False
        self._interrupted = False
        self._restored = resume_session is not None
        self._notice = None

    @property
    def notice(self):
        return self._notice

    def _report(self, message):
        if message != self._notice:
            self._notice = message
            return message

    def interrupt(self, session):
        if self.active and self.session == session:
            self._interrupted = True
            self._sequence = None
            self._attempts = self._next_attempt = 0
            self._partial_sale = None
            self._notice = None

    def observe(self, session, reading, now, *, ready, arrived, send):
        if session != self.session:
            self.__init__()
            self.session = session
        if reading is None or not ready or reading.sequence == self._sequence:
            return None
        self._sequence = reading.sequence
        if not self.active:
            if reading.repair_needed is True:
                self.active = self.repair = True
                return self._report('装备耐久已变红，前往营地修理。')
            if vendor_due(reading):
                self.active = True
                self.repair = False
                return self._report('普通背包已满，前往商人核对可售杂物。' if reading.free == 0
                                    else '普通背包剩余两格或更少，前往商人。')
            return None
        if not arrived:
            self._partial_sale = None
            return None
        if reading.merchant_open and not reading.matched:
            self._partial_sale = None
            return self._report('商店身份与已记录商人不符，暂停补给。')
        if reading.popup_blocked:
            self._partial_sale = None
            return self._report('游戏有其他弹窗，暂停商人操作。')
        if self.repair and reading.repair_needed is None:
            return self._report('等待游戏确认装备耐久。')
        repairing = self.repair and reading.repair_needed is True
        sale_received = self._before_sale and reading.junk == 0 and reading.free > self._before_sale[0]
        if self._interrupted:
            if reading.merchant_open:
                return self._report('补给中断后等待原商店关闭，再重新核对背包。')
            self._interrupted = False
            self._confirmed = False
            if not sale_received and self._phase != 'close':
                self._before_sale = self._phase = None
        if sale_received and not reading.confirming:
            self._before_sale = None
            self._confirmed = False
            self._phase = 'close'
            self._attempts = 0
            self._next_attempt = now
        if (not repairing and self._before_sale and reading.merchant_open and reading.matched and not reading.confirming
                and reading.free > self._before_sale[0] and 0 < reading.junk < self._before_sale[1]):
            inventory = reading.free, reading.junk
            if self._partial_sale is None or inventory != self._partial_sale[0]:
                self._partial_sale = inventory, now
            if now - self._partial_sale[1] < 1500:
                return self._report('已确认部分杂物卖出，等待背包读数稳定。')
            self._before_sale = self._phase = None
            self._confirmed = False
        self._partial_sale = None
        if repairing and reading.matched:
            if reading.confirming:
                phase, value = 'dismiss', None
            else:
                if reading.repair_status == 1:
                    return self._report('该商人无法修理，等待可用的修理商人。')
                if reading.repair_status == 2:
                    return self._report('角色金币不足，暂停修理。')
                if reading.repair_status != 3 or not reading.sell_point:
                    return self._report('等待游戏确认可用的个人修理按钮。')
                phase, value = 'repair', reading.sell_point
                if not reading.hovered:
                    if phase != self._phase or now >= self._next_attempt:
                        send('hover', value)
                    return None
        elif repairing:
            phase, value = ('interact', reading.interact_vk) if reading.selected else ('select', reading.select_key)
        elif sale_received and reading.confirming:
            phase, value = 'dismiss', None
        elif (self._phase == 'close' or (not self._before_sale and reading.junk == 0
                                      and (reading.free > 2 or reading.matched and reading.free > 0))
              or (self.repair and not self._before_sale and (reading.junk == 0 or not vendor_due(reading)))):
            if not reading.merchant_open:
                self.active = False
                self._phase = None
                return self._report('装备耐久警报已解除，返回打怪点。' if self.repair
                                    else '背包已腾出空间，返回打怪点。')
            phase, value = 'close', None
        elif self._before_sale and reading.junk == 0:
            return self._report('等待游戏确认出售后腾出的背包格。')
        elif self._restored and reading.matched and reading.confirming and self._before_sale is None:
            phase, value = 'dismiss', None
        elif reading.matched:
            if not reading.junk:
                return self._report('背包已满，原生商店未列出可售杂物，暂停练级。')
            if reading.confirming and self._before_sale != (reading.free, reading.junk):
                return self._report('出售确认框与本次请求的背包状态不符，暂停出售。')
            if self._confirmed and not reading.confirming:
                return self._report('已确认出售，等待游戏更新背包。')
            if not reading.sell_point:
                return self._report('游戏未提供可用的出售按钮，暂停出售。')
            phase, value = ('confirm' if reading.confirming else 'sell'), reading.sell_point
            if not reading.hovered:
                if phase != self._phase or now >= self._next_attempt:
                    send('hover', value)
                return None
        elif reading.selected:
            phase, value = 'interact', reading.interact_vk
        else:
            phase, value = 'select', reading.select_key
        if phase != self._phase:
            self._phase = phase
            self._attempts = 0
            self._next_attempt = now
        if phase in ('interact', 'select') and not value:
            return self._report('商人按键不可用，请检查插件商人设置和游戏交互键。')
        if self._attempts >= 2:
            return self._report('游戏未确认商人操作，已停止重试。')
        if now < self._next_attempt or not send(phase, value):
            return None
        self._attempts += 1
        self._next_attempt = now + 1500
        if phase == 'repair':
            return self._report('已点击游戏原生「全部修理」，等待耐久回执。')
        if phase == 'sell':
            self._restored = False
            if self._before_sale is None:
                self._before_sale = reading.free, reading.junk
            return self._report('已点击游戏原生「出售杂物」，等待确认框或背包回执。')
        if phase == 'confirm':
            self._confirmed = True
            return self._report('已确认出售杂物，等待背包回执。')
        return None
