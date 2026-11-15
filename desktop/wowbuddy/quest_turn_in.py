"""根据游戏确认的任务界面执行交付，提交回执来自 QUEST_TURNED_IN。"""


class QuestTurnIn:
    def __init__(self, pin, reading):
        self.pin = pin
        self.receipt = reading.receipt_generation if reading else None
        self.complete = False
        self._sequence = None
        self._last_input = None
        self._world_inputs = {}
        self._submitted = False
        self._notice = None
        self._search_since = None

    def observe_receipt(self, reading):
        if reading is None or self.complete:
            return False
        previous, self.receipt = self.receipt, reading.receipt_generation
        self.complete = (previous is not None and previous != self.receipt
                         and reading.receipt_quest == self.pin.quest_id)
        return self.complete

    def waiting_for_receipt(self, now_ms):
        return self._submitted and now_ms - self._last_input[1] < 5000

    def native_dialog_active(self, reading):
        return reading is not None and reading.quest_id == self.pin.quest_id and 2 <= reading.stage <= 7

    def deferral_reason(self, reading, now_ms):
        if self.native_dialog_active(reading) and reading.stage in (5, 6):
            return None
        if self._submitted:
            if not self.waiting_for_receipt(now_ms):
                return '游戏未确认任务交付'
            return None
        # 已经进入原生对话时交给界面处理，尤其保留人工选择或确认。
        if self.native_dialog_active(reading):
            self._search_since = None
            return None
        if self._search_since is None:
            self._search_since = now_ms
        if now_ms - self._search_since >= 15000:
            return '暂未找到可交互的任务 NPC'

    @property
    def notice(self):
        return self._notice or '已到交付点，等待确认任务 NPC。'

    def _report(self, message):
        if self._notice != message:
            self._notice = message
            return message

    def observe(self, reading, now_ms, *, send):
        if (self.complete or reading is None or reading.quest_id != self.pin.quest_id
                or reading.sequence == self._sequence):
            return None
        self._sequence = reading.sequence
        stage = reading.stage
        if stage == 5:
            return self._report('任务有可选奖励，等待你选择。')
        if stage == 6:
            return self._report('任务要求支付费用，等待你确认。')
        if self._submitted:
            return self._report('已按下完成任务，等待游戏确认。')
        if stage == 7:
            return self._report('当前对话或界面尚未通过任务核对，暂停交付。')
        if stage == 0:
            return self._report('已到交付点，等待确认任务 NPC。')
        if self._last_input is not None:
            last_stage, last_time = self._last_input
            if (stage not in (1, 8) and stage == last_stage) or now_ms - last_time < 300:
                return None
        if stage in (1, 8):
            key = stage, reading.unit_token
            attempts, last = self._world_inputs.get(key, (0, 0))
            if attempts >= 2 or (attempts and now_ms - last < 1200):
                return None
            action, value = ('select', reading.clear_key) if stage == 8 else ('interact', reading.interact_vk)
            if send(action, value):
                self._world_inputs[key] = attempts + 1, now_ms
                self._last_input = stage, now_ms
                if stage == 8:
                    return self._report('已请求清除无可拾取物的尸体目标，等待游戏确认。')
                return self._report('已发送附近 NPC 的交互键，等待核对任务编号。')
        elif not reading.hovered:
            send('hover', reading.button)
        elif send('quest_click', reading.button):
            self._last_input = stage, now_ms
            if stage == 4:
                self._submitted = True
                return self._report('已按下完成任务，等待游戏确认。')
        return None
