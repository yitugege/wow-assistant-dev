"""自有插件0.2协议：24位无占位可用性位图，经版本标记转换为引擎旧布局。"""
from dataclasses import replace

from wowbuddy.core.auto_target import key_for_index, parse_auto_target
from wowbuddy.core.candidates import Candidate

DEV_VERSION = 0x574201
MAX_AVAILABILITY_SPELLS = 24


def normalize_availability(frame):
    if not frame.ok or frame.version_code != DEV_VERSION:
        return frame
    row = next((row for row in frame.rows if row.key == 'action_avail'), None)
    if row is None:
        return replace(frame, status='missing_availability')
    # 新版明确规定全白为24项全就绪，不是未知哨兵；旧版绝不走此转换。
    wire = row.decoded.raw_value
    text = str((wire << 1) | 1)
    decoded = replace(row.decoded, value_text=text,
                      detail='开发协议24位技能状态；已转换为引擎位图')
    rows = tuple(replace(item, decoded=decoded) if item is row else item for item in frame.rows)
    values = dict(frame.values, action_avail=text)
    return replace(frame, values=values, rows=rows)


RECOVERY_PACKET_BASE = 0xE00000
_RECOVERY_PAUSE = {
    3: "正在恢复，或等待停步、读条结束及输入焦点释放。",
    4: "缺少已配置的食物。请补充背包物品或在 /pms 的自动恢复设置中更改。",
    5: "缺少已配置的饮水。请补充背包物品或在 /pms 的自动恢复设置中更改。",
    6: "无法确认角色状态、背包读数或恢复按键，已暂停攻击。",
    7: "已尝试两次，背包数量没有变化。请检查物品并重新保存恢复设置。",
    8: "补给操作未收到背包数量回执，等待冷却或补给状态变化后重试。",
}


def recovery_candidate(frame):
    """独立旧布局的 TTF 扩展。原协议及未启用恢复的帧保持原候选链。"""
    if not is_dev_frame(frame):
        return None
    try:
        value = int(frame.values.get("ttf", ""))
    except (TypeError, ValueError):
        return None
    offset = value - RECOVERY_PACKET_BASE
    if not 128 <= offset < 8 * 128:
        return None
    state, key_index = divmod(offset, 128)
    fields = frame.values
    if (state in (1, 2) and (key := key_for_index(key_index))
            and fields.get("master_switch") == "OFF"
            and fields.get("player_in_combat") == "OFF" and fields.get("player_valid") == "ON"):
        action, label = ("recovery_food", "自动进食") if state == 1 else ("recovery_water", "自动饮水")
        return Candidate(action=action, key=key, label=label, reason="脱战且资源不足，使用已配置的恢复物品。",
                         tag="恢复", hold_ms=3000, off_gcd=True)
    return Candidate(label="自动恢复中", reason=_RECOVERY_PAUSE.get(state, _RECOVERY_PAUSE[6]),
                     tag="恢复", stop=True)


RECOVERY_CONFIG_BASE = 0xC00000
RECOVERY_CONJURE_BASE = 0x800000
RECOVERY_NORMAL_GATE = 0x200000
RECOVERY_HANDOFF_BASE = 0xB00000
RECOVERY_DISABLED_BASE = 0xB08000
_RECOVERY_CONSUMING = 86
_RECOVERY_BAG_FULL = 87
_RECOVERY_NO_MANA = frozenset(("1488", "1491"))


def _pause_recovery(code):
    return Candidate(label="自动恢复中", reason=_RECOVERY_PAUSE[code], tag="恢复", stop=True)


def _decode_recovery_word(word):
    start, rest = divmod(word & 0x1FFFFF, 128 * 128)
    resume, status = divmod(rest, 128)
    if 0 <= start < resume <= 100 and 0 <= status <= _RECOVERY_BAG_FULL:
        return start, resume, status
    return None


def _resource_percent(fields, key):
    try:
        percent = float(fields.get(key, ""))
    except (TypeError, ValueError):
        return None
    return percent if 0 <= percent <= 100 else None


def bag_recovery_walk_safe(frame):
    """满包的补给改道仍要求新读数、脱战和足够的生命值。"""
    fields = frame.values
    if (not frame.ok or not is_dev_frame(frame)
            or frame.spec_id != '1482' or fields.get('player_valid') != 'ON'
            or fields.get('player_in_combat') != 'OFF' or fields.get('master_switch') != 'OFF'):
        return False
    try:
        food, water = (int(fields.get(key, '')) for key in ('ttf', 'combat_time'))
    except (TypeError, ValueError):
        return False
    if (not 0 <= food < 0xFFFFFF or not 0 <= water < 0xFFFFFF
            or (food & 0xC00000) not in (RECOVERY_CONFIG_BASE, RECOVERY_CONJURE_BASE)
            or (water & 0xE00000) not in (RECOVERY_CONFIG_BASE, RECOVERY_CONJURE_BASE)):
        return False
    health = _decode_recovery_word(food)
    percent = _resource_percent(fields, 'player_health_pct')
    return (health is not None and _decode_recovery_word(water) is not None
            and percent is not None and percent >= max(35, health[0]))


def is_dev_frame(frame):
    """帧来自本工程插件的独立协议（旧版帧格式 + 当前开发版版本号）。"""
    return frame.protocol == "old" and frame.version_code == DEV_VERSION


def _short_of(fields, spec_id, health, mana):
    """生命或法力百分比低于非零阈值（无法力专精不看法力）；读数缺失也算不足。"""
    if spec_id in _RECOVERY_NO_MANA:
        mana = 0
    for key, threshold in (("player_health_pct", health), ("mana_pct", mana)):
        if threshold:
            percent = _resource_percent(fields, key)
            if percent is None or percent < threshold:
                return True
    return False


def disabled_recovery_ready(frame):
    """仅在插件明确报告自动吃喝关闭时按开始阈值判断交接。"""
    fields = frame.values
    if (not is_dev_frame(frame)
            or fields.get("player_valid") != "ON" or fields.get("player_in_combat") != "OFF"):
        return None
    try:
        offset = int(fields.get("ttf", "")) - RECOVERY_DISABLED_BASE
    except (TypeError, ValueError):
        return None
    if not 0 <= offset < 128 * 128:
        return None
    health, mana = divmod(offset, 128)
    if health > 99 or mana > 99:
        return None
    return not _short_of(fields, frame.spec_id, health, mana)


class RecoveryGate:
    """只比较桌面已经解码的数值。插件端只发布配置和物品状态。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self._settings = None
        self._needs = (False, False)
        self._rest_started = False

    def note_dispatch(self, action):
        if self._settings is not None and action in ("recovery_food", "recovery_water"):
            self._rest_started = True

    def post_kill_recovery(self, frame):
        """识别击杀交接字，并在未达到当前恢复目标时暂缓挑选下一只怪。"""
        if not is_dev_frame(frame):
            return False, None
        fields = frame.values
        try:
            offset = int(fields.get("ttf", "")) - RECOVERY_HANDOFF_BASE
            ttd = int(fields.get("ttd", ""))
        except (TypeError, ValueError):
            return False, None
        if not 0 <= offset < 128 * 128:
            return False, None
        health, mana = divmod(offset, 128)
        packet = parse_auto_target(ttd)
        if (health > 99 or mana > 99 or packet is None or packet.state != 1
                or fields.get("player_valid") != "ON" or fields.get("player_in_combat") != "ON"
                or fields.get("master_switch") != "ON"):
            return True, None
        if self._settings is not None:
            spec, health_config, mana_config = self._settings
            if (spec, health_config[0], mana_config[0]) == (frame.spec_id, health, mana):
                if self._needs[0]:
                    health = health_config[1]
                if self._needs[1]:
                    mana = mana_config[1]
        if _short_of(fields, frame.spec_id, health, mana):
            return True, Candidate(label="等待脱战", reason="击杀后等待游戏确认脱战，再检查恢复条件。",
                                   tag="恢复", stop=True)
        return True, None

    def evaluate(self, frame):
        if not is_dev_frame(frame):
            self.reset()
            return None
        fields = frame.values
        in_combat = fields.get("player_in_combat") == "ON"
        if (fields.get("player_valid") == "OFF" or (in_combat and not self._rest_started)
                or (self._settings is not None and frame.spec_id != self._settings[0])):
            self.reset()
        try:
            food, water = (int(fields.get(key, "")) for key in ("ttf", "combat_time"))
        except (ValueError, TypeError):
            food, water = 0, 0
        water_prefix = water & 0xE00000 if 0 <= water < 0xFFFFFF else 0
        if water_prefix not in (RECOVERY_CONFIG_BASE, RECOVERY_CONJURE_BASE):
            if in_combat:
                # 战斗中没有吃喝读数，保留本轮恢复目标，但继续处理战斗候选。
                return None
            # 同一轮恢复中，缺少恢复字段不足以确认已达标或用户已关闭功能。
            if (any(self._needs) and disabled_recovery_ready(frame) is None
                    and recovery_candidate(frame) is None):
                return False, _pause_recovery(6)
            self.reset()
            return None

        health = _decode_recovery_word(food)
        mana = _decode_recovery_word(water)
        food_prefix = food & 0xC00000 if 0 <= food < 0xFFFFFF else 0
        conjuring = (food_prefix == RECOVERY_CONJURE_BASE, water_prefix == RECOVERY_CONJURE_BASE)
        normal_gate = bool(food & RECOVERY_NORMAL_GATE)
        if (food_prefix not in (RECOVERY_CONFIG_BASE, RECOVERY_CONJURE_BASE) or health is None or mana is None
                or (any(conjuring) and frame.spec_id != '1482')
                or any(active and not key_for_index(config[2]) for active, config in zip(conjuring, (health, mana)))
                or fields.get("player_in_combat") != "OFF"
                or fields.get("player_valid") != "ON"
                or fields.get("master_switch") != "OFF"):
            return False, _pause_recovery(6)

        settings = (frame.spec_id, health[:2], mana[:2])
        if settings != self._settings:
            self.reset()
            self._settings = settings

        needs = []
        for index, (key, config) in enumerate(zip(("player_health_pct", "mana_pct"), (health, mana))):
            start, resume, _ = config
            if start == 0 or (index == 1 and frame.spec_id in _RECOVERY_NO_MANA):
                needs.append(False)
                continue
            percent = _resource_percent(fields, key)
            threshold = resume if self._needs[index] else start
            needs.append(None if percent is None else percent < threshold)
        # 未知读数不触发对应补给，也不清掉该资源已经开始的恢复。
        self._needs = tuple(previous if current is None else current
                            for previous, current in zip(self._needs, needs))
        if all(need is False for need in needs):
            self._rest_started = False
            return normal_gate, None

        statuses = health[2], mana[2]
        # 先备齐可制造的补给。各资源独立选择已经确认可用的动作。
        for index, conjure in ((1, True), (0, True), (0, False), (1, False)):
            if needs[index] and conjuring[index] == conjure and (key := key_for_index(statuses[index])):
                if conjure:
                    other = 1 - index
                    if statuses[other] == _RECOVERY_CONSUMING and needs[other] is not False:
                        return False, _pause_recovery(3)
                    action, label = (("recovery_conjure_food", "自动造食") if index == 0
                                     else ("recovery_conjure_water", "自动造水"))
                    return False, Candidate(action=action, key=key, label=label,
                                            reason="脱战补给不足，制造已学会的最高等级补给。",
                                            tag="恢复", hold_ms=4000)
                action, label = ("recovery_food", "自动进食") if index == 0 else ("recovery_water", "自动饮水")
                return False, Candidate(action=action, key=key, label=label,
                                        reason="脱战且资源不足，使用可用的恢复物品。",
                                        tag="恢复", hold_ms=3000, off_gcd=True)
        if None in needs:
            return False, _pause_recovery(6)
        if any(need and status == _RECOVERY_BAG_FULL for need, status in zip(needs, statuses)):
            if any(need and status == _RECOVERY_CONSUMING for need, status in zip(needs, statuses)):
                return False, _pause_recovery(3)
            return False, Candidate(action='recovery_bag_full', label='背包已满，无法制造补给',
                                    reason='背包没有空位，腾出空间后再制造食物或水。', tag='恢复', stop=True)
        status = health[2] if needs[0] else mana[2]
        code = {0: 4 if needs[0] else 5, 82: 3, 83: 6, 84: 7, 85: 8, _RECOVERY_CONSUMING: 3}.get(status, 6)
        return False, _pause_recovery(code)
