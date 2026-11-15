"""从独立插件色条旁的扩展读取角色与地图状态。"""

from dataclasses import dataclass
from math import ceil
import time

from .dev_protocol import DEV_VERSION
from .auto_target import key_for_index
from .keybindings import parse_keybinding


_SIGNATURE = 0x57424E
_SESSION_SIGNATURE = 0x574245
_TRAVEL_IDENTITY_SIGNATURE = 0x574255
_PROGRESS_SIGNATURE = 0x574249
_MOB_SIGNATURE = 0x574251
_DEATH_SIGNATURE = 0x574244
_NAVIGATION_SIGNATURE = 0x57424D
_PULL_SIGNATURE = 0x574250
_TARGET_SIGNATURE = 0x574254
_TARGET_WORLD_SIGNATURE = 0x574248
_MOVING_TARGET_SIGNATURE = 0x574241
_ESTIMATED_TARGET_SIGNATURE = 0x574242
_WAND_SIGNATURE = 0x574257
_RETARGET_SIGNATURE = 0x574252
_DISCARD_SIGNATURE = 0x574243
_SIGHT_SIGNATURE = 0x574253
_PRECISE_POSITION_SIGNATURE = 0x574246
_ELEVATION_SIGNATURE = 0x574274
_TAXI_SIGNATURE = 0x574275
_QUEST_SIGNATURE = 0x574276
_QUEST_DIALOG_SIGNATURE = 0x574277
_TARGET_REJECTION_SIGNATURE = 0x57424B
_CAST_FEEDBACK_SIGNATURE = 0x574256
_COMBAT_FACING_SIGNATURE = 0x574259
_COMBAT_FACING_ACTION_SIGNATURE = 0x57425A
_NOVA_SPACING_SIGNATURE = 0x574247
_NOVA_SPACING_EVENT_SIGNATURE = 0x57424C
_NOVA_SPACING_BLOCKED_SIGNATURE = 0x57424F
_NOVA_SPACING_BLOCKERS = ('战斗或游戏输入条件未满足', '角色未确认站定', '目标已变化或不可攻击', '移动键绑定未确认',
                          '角色朝向不可读', '目标方位或距离不可读', '距离或角度不适合后退', '自身定身光环未确认')
_NOVA_DIRECTION_ISSUES = ('', '角色世界坐标不可读', '目标世界坐标不可读', '角色和目标世界坐标不在同一区域', '目标世界距离超出读数范围')
_NOVA_ROOT_ISSUES = ('', '定身光环查询不可读', '未找到冰霜新星光环', '光环技能不可读', '定身施法者不可读',
                    '定身未确认来自当前角色', '定身剩余时间不可读', '定身剩余时间不足')
_CAST_STAGES = ('提交', '开始读条', '成功', '失败', '中断')
_CAST_ERROR_KINDS = ('未分类', '朝向', '视线', '距离', '移动', '资源不足', '冷却')
_POSITION_STEPS = 10_000
_PRECISE_POSITION_STEPS = 1_000_000
# 所有色格均避开原条用于定位的 FF00FF。
_CHECKSUM_MOD = 0xFEFFFD
_NO_POSITION = 0xFFFFFF
_LIFE_STATES = ('unknown', 'alive', 'dead', 'ghost')
_FACTIONS = (None, 'alliance', 'horde')
_POPUP_STATES = ('legacy', 'input_blocked', 'missing', 'disabled', 'unreadable', 'ready')
STALE_FRAME = '游戏画面未更新，已暂停游戏输入'


@dataclass(frozen=True, slots=True)
class CharacterState:
    life: str
    outdoors: bool
    simplified_chinese: bool
    faction: str | None
    level: int | None
    map_id: int | None
    zone: str | None
    x: float | None
    y: float | None
    elevation: float | None = None

    @property
    def route_key(self):
        return self.faction, self.level, self.map_id, self.zone


@dataclass(frozen=True, slots=True)
class LevelProgress:
    level: int
    current: int | None
    maximum: int | None
    combat_notices: int | None


@dataclass(frozen=True, slots=True)
class DeathState:
    life: str
    sequence: int
    button: tuple[int, int] | None
    hovered: bool
    corpse: tuple[int, float, float] | None
    popup: str = 'legacy'
    corpse_estimated: bool = False


@dataclass(frozen=True, slots=True)
class NavigationState:
    life: str
    sequence: int
    map_id: int
    x: float
    y: float
    heading: float
    width: int
    height: int
    keys: tuple[int, int, int]
    idle_key_index: int = 0
    continuous: bool = False
    moving: bool = False
    target_revision: int | None = None
    retarget_key: int = 0
    discard_key: int = 0
    sight_blocked: bool = False
    position_steps: int = _POSITION_STEPS
    elevation: float | None = None


@dataclass(frozen=True, slots=True)
class TargetBearing:
    revision: int
    x: float | None
    distance: float | None
    continuous: bool = False
    estimated: bool = False
    heading: float | None = None


@dataclass(frozen=True, slots=True)
class CastFeedback:
    sequence: int
    spell: int
    stages: tuple[str, ...]
    error_code: int | None = None
    error_kind: str | None = None


@dataclass(frozen=True, slots=True)
class CombatFacingSample:
    revision: int
    keys: tuple[int, int, int]
    heading: float | None = None
    target_heading: float | None = None
    action_spell: int | None = None


@dataclass(frozen=True, slots=True)
class NovaSpacingSample:
    revision: int
    sequence: int
    keys: tuple[int, int, int, int]
    distance: float
    event_only: bool = False


def _signature_center(image, x, estimate, tolerance, signatures):
    first = max(0, int(estimate) - tolerance)
    last = min(image.height - 1, ceil(estimate) + tolerance)
    for y in range(first, last + 1):
        color = image.pixel(x, y)
        if color not in signatures:
            continue
        end = y
        while end < last and image.pixel(x, end + 1) == color:
            end += 1
        if end > y:
            return (y + end) / 2
    return None


def _sample_column(image, frame, *, calibration=()):
    if not frame.ok or frame.protocol != 'old' or frame.version_code != DEV_VERSION:
        return None
    geometry = frame.geometry
    if geometry is None:
        return None
    x = int(geometry.anchor_x + geometry.pitch / 2)
    pitch = geometry.pitch
    if not 0 <= x < image.width:
        return None
    top = _signature_center(image, x, pitch / 2, max(2, ceil(pitch / 2)), (_SIGNATURE,))
    if top is not None:
        # 主色条的基准像素有取整误差。扩展列直接用相距最远的可见签名重估间距。
        for row, signatures in (*calibration, (70, (_RETARGET_SIGNATURE,)), (66, (_WAND_SIGNATURE,)),
                                (59, (_TARGET_SIGNATURE, _TARGET_WORLD_SIGNATURE)),
                                (43, (_NAVIGATION_SIGNATURE,)), (34, (_DEATH_SIGNATURE,))):
            nominal = (row + 0.5) * pitch
            center = _signature_center(image, x, nominal, max(2, ceil(nominal * 0.018) + 1), signatures)
            if center is None:
                continue
            measured = (center - top) / row
            if abs(measured - pitch) <= pitch * 0.022 and abs(center - top - row * pitch) >= 0.75:
                return lambda index: image.pixel(x, round(top + index * measured))
            break
    return lambda index: image.pixel(x, int((index + 0.5) * pitch))


def _valid_checksum(words, expected):
    checksum = 0
    for value in words:
        checksum = (checksum * 31 + value) % _CHECKSUM_MOD
    return checksum == expected


def decode_character_session(image, frame):
    word = _sample_column(image, frame)
    if word is None:
        return None
    try:
        if word(94) != _SESSION_SIGNATURE:
            return None
        token = word(95)
        if 0 <= token < _CHECKSUM_MOD and _valid_checksum((_SESSION_SIGNATURE, token), word(96)):
            return token
    except IndexError:
        return None
    return None


def decode_travel_identity(image, frame, session):
    if session is None:
        return None
    word = _sample_column(image, frame, calibration=((120, (_TRAVEL_IDENTITY_SIGNATURE,)),))
    if word is None:
        return None
    try:
        words = [word(row) for row in range(120, 124)]
        signature, token, first, second = words
        if (signature == _TRAVEL_IDENTITY_SIGNATURE and token == session
                and first < _CHECKSUM_MOD and second < _CHECKSUM_MOD and _valid_checksum(words, word(124))):
            return first, second
    except IndexError:
        pass
    return None


def decode_level_progress(image, frame, session):
    if session is None:
        return None
    word = _sample_column(image, frame, calibration=((125, (_PROGRESS_SIGNATURE,)),))
    if word is None:
        return None
    try:
        words = [word(row) for row in range(125, 131)]
        signature, token, level, current, maximum, notices = words
        if (signature != _PROGRESS_SIGNATURE or token != session or not 1 <= level <= 255
                or not _valid_checksum(words, word(131))):
            return None
    except IndexError:
        return None
    if (current, maximum) == (_NO_POSITION, _NO_POSITION):
        current = maximum = None
    elif not (0 < maximum < _CHECKSUM_MOD and 0 <= current <= maximum):
        return None
    if notices == _NO_POSITION:
        notices = None
    elif not 0 <= notices < 65536:
        return None
    return LevelProgress(level, current, maximum, notices)


def decode_cast_feedback(image, frame):
    word = _sample_column(image, frame, calibration=((97, (_CAST_FEEDBACK_SIGNATURE,)),))
    if word is None:
        return None
    try:
        words = [word(row) for row in range(97, 101)]
        signature, sequence, spell, stages = words
        base_checksum = word(101)
        if (signature != _CAST_FEEDBACK_SIGNATURE or sequence >= 65521
                or not 0 < spell < _CHECKSUM_MOD or not 0 < stages < 32
                or not _valid_checksum(words, base_checksum)):
            return None
    except IndexError:
        return None
    labels = tuple(label for bit, label in enumerate(_CAST_STAGES) if stages & (1 << bit))
    if stages & 9 == 9 and not stages & 20:
        try:
            reason = word(102)
            kind, code = divmod(reason, 65536)
            if code and 0 <= kind < len(_CAST_ERROR_KINDS) and _valid_checksum(
                    (*words, base_checksum, reason), word(103)):
                return CastFeedback(sequence, spell, labels, code, _CAST_ERROR_KINDS[kind])
        except IndexError:
            pass
    return CastFeedback(sequence, spell, labels)


def decode_combat_facing(image, frame, feedback):
    if feedback is None or feedback.error_kind != '朝向':
        return None
    fields = frame.values
    if (fields.get('player_in_combat') != 'ON' or fields.get('master_switch') != 'ON'
            or fields.get('player_valid') != 'ON' or fields.get('target_valid') != 'ON'
            or fields.get('player_moving') != 'OFF' or fields.get('player_casting') != '空闲'):
        return None
    signatures = _COMBAT_FACING_SIGNATURE, _COMBAT_FACING_ACTION_SIGNATURE
    word = _sample_column(image, frame, calibration=((104, signatures),))
    if word is None:
        return None
    try:
        words = [word(row) for row in range(104, 110)]
        signature, sequence, revision, bindings, heading, target_heading = words
        if signature not in signatures or sequence != feedback.sequence or revision >= 65521:
            return None
        action_spell = None
        if signature == _COMBAT_FACING_ACTION_SIGNATURE:
            action_spell = word(110)
            if not 0 < action_spell < _CHECKSUM_MOD:
                return None
            words.append(action_spell)
        if not _valid_checksum(words, word(104 + len(words))):
            return None
    except IndexError:
        return None
    keys = bindings >> 16, (bindings >> 8) & 255, bindings & 255
    if len(set(keys)) != 3 or not all(0x25 <= key <= 0x28 or 0x41 <= key <= 0x5A for key in keys):
        return None
    if heading == target_heading == 65535:
        return CombatFacingSample(revision, keys, action_spell=action_spell)
    if heading <= 6283 and target_heading <= 6283:
        return CombatFacingSample(revision, keys, heading / 1000, target_heading / 1000, action_spell)
    return None


def decode_nova_spacing(image, frame, feedback):
    if feedback is None or feedback.spell not in (122, 865, 6131, 10230) or '成功' not in feedback.stages:
        return None, ()
    fields = frame.values
    if (any(fields.get(key) != 'ON' for key in ('player_in_combat', 'master_switch', 'player_valid', 'target_valid', 'gcd'))
            or fields.get('player_moving') != 'OFF' or fields.get('player_casting') != '空闲'
            or fields.get('active_enemies') not in (1, '1')
            or fields.get('enemies_8yd') not in (0, 1, '0', '1')):
        return None, ()
    ready_signatures = _NOVA_SPACING_SIGNATURE, _NOVA_SPACING_EVENT_SIGNATURE
    signatures = *ready_signatures, _NOVA_SPACING_BLOCKED_SIGNATURE
    word = _sample_column(image, frame, calibration=((112, signatures),))
    if word is None:
        return None, ()
    try:
        signature, cast, status = (word(row) for row in range(112, 115))
        if signature == _NOVA_SPACING_BLOCKED_SIGNATURE:
            base_checksum = word(115)
            if (cast != feedback.sequence or not 0 < status < 256
                    or not _valid_checksum((signature, cast, status), base_checksum)):
                return None, ()
            reasons = list(_NOVA_SPACING_BLOCKERS)
            try:
                details = word(116)
                if _valid_checksum((signature, cast, status, base_checksum, details), word(117)):
                    direction, root = divmod(details, 256)
                    if 0 < direction < len(_NOVA_DIRECTION_ISSUES):
                        reasons[5] = _NOVA_DIRECTION_ISSUES[direction]
                    if 0 < root < len(_NOVA_ROOT_ISSUES):
                        reasons[7] = _NOVA_ROOT_ISSUES[root]
            except IndexError:
                pass
            return None, tuple(reason for bit, reason in enumerate(reasons) if status & (1 << bit))
        words = [word(row) for row in range(112, 119)]
        signature, cast, revision, sequence, backward, bindings, distance = words
        if (signature not in ready_signatures or cast != feedback.sequence or revision >= 65521
                or sequence > 255 or not 100 <= distance <= 850 or not _valid_checksum(words, word(119))):
            return None, ()
    except IndexError:
        return None, ()
    keys = backward, bindings >> 16, (bindings >> 8) & 255, bindings & 255
    if len(set(keys)) == 4 and all(0x25 <= key <= 0x28 or 0x41 <= key <= 0x5A for key in keys):
        return NovaSpacingSample(revision, sequence, keys, distance / 100, signature == _NOVA_SPACING_EVENT_SIGNATURE), ()
    return None, ()


def _auberdine_elevation(word, map_id, px, py):
    if map_id != 1439 or not (3600 <= px <= 3750 and 4480 <= py <= 4620):
        return None
    try:
        data = [word(index) for index in range(150, 155)]
        signature, nav_sequence, death_sequence, height_map, value = data
        if (signature == _ELEVATION_SIGNATURE and height_map == map_id
                and word(43) == _NAVIGATION_SIGNATURE and word(34) == _DEATH_SIGNATURE
                and word(45) == map_id and (word(46), word(47)) == (px, py)
                and nav_sequence == word(44) % 256 and death_sequence == (word(35) >> 8) % 256
                and value <= 1024000 and _valid_checksum(data, word(155))):
            return (value - 204800) / 100
    except IndexError:
        pass
    return None


def decode_character_state(image, frame):
    word = _sample_column(image, frame, calibration=((150, (_ELEVATION_SIGNATURE,)),))
    if word is None:
        return None
    try:
        if word(0) != _SIGNATURE:
            return None
        length = word(5)
        if not 0 <= length <= 72:
            return None
        end = 6 + (length + 2) // 3
        words = [word(index) for index in range(end)]
        if not _valid_checksum(words, word(end)):
            return None
    except IndexError:
        return None

    _, flags, map_id, px, py, _ = words[:6]
    state, faction, level = flags >> 16, (flags >> 8) & 255, flags & 255
    if state > 15 or faction >= len(_FACTIONS) or map_id >= 0xFF0000:
        return None
    if (px, py) == (_NO_POSITION, _NO_POSITION):
        map_x = map_y = None
    elif map_id and px <= 10000 and py <= 10000:
        map_x, map_y = px / 100, py / 100
    else:
        return None
    raw_name = b''.join(value.to_bytes(3, 'big') for value in words[6:])
    if any(raw_name[length:]) or (length and not map_id):
        return None
    try:
        zone = raw_name[:length].decode('utf8')
    except UnicodeDecodeError:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in zone):
        return None
    return CharacterState(_LIFE_STATES[state & 3], bool(state & 4), bool(state & 8), _FACTIONS[faction],
                          level or None, map_id or None, zone or None, map_x, map_y,
                          _auberdine_elevation(word, map_id, px, py))


def decode_death_state(image, frame):
    word = _sample_column(image, frame)
    if word is None:
        return None
    try:
        if word(34) != _DEATH_SIGNATURE:
            return None
        words = [word(index) for index in range(34, 41)]
        if not _valid_checksum(words, word(41)):
            return None
    except IndexError:
        return None

    _, flags, bx, by, map_id, cx, cy = words
    phase, sequence, status = flags >> 16, (flags >> 8) & 255, flags & 255
    popup, hovered, estimated = (status >> 1) & 7, bool(status & 1), bool(status & 16)
    if (phase > 3 or status > 31 or popup >= len(_POPUP_STATES) or (status and phase not in (1, 2))
            or (phase != 3 and frame.values.get('player_valid') != ('ON' if phase == 0 else 'OFF'))):
        return None
    actionable = phase in (1, 2) and frame.values.get('player_valid') == 'OFF' and frame.values.get('player_in_combat') == 'OFF'
    button = None
    has_point = (bx, by) != (_NO_POSITION, _NO_POSITION)
    if has_point:
        if not (phase in (1, 2) and popup in (0, 5) and 0 < bx < 10000 and 0 < by < 10000):
            return None
        if actionable:
            button = bx, by
    elif hovered or popup == 5:
        return None
    corpse = None
    if map_id:
        if not (phase in (1, 2) and map_id < 0xFF0000 and cx <= 10000 and cy <= 10000):
            return None
        corpse = map_id, cx / 100, cy / 100
    elif estimated or (cx, cy) != (_NO_POSITION, _NO_POSITION):
        return None
    return DeathState(('alive', 'dead', 'ghost', 'unknown')[phase], sequence,
                      button, hovered and button is not None, corpse, _POPUP_STATES[popup], estimated)


def decode_target_rejection(image, frame):
    if frame.values.get('target_valid') != 'ON':
        return None
    word = _sample_column(image, frame)
    if word is None:
        return None
    try:
        if word(89) != _TARGET_REJECTION_SIGNATURE:
            return None
        words = [word(index) for index in range(89, 93)]
        if not _valid_checksum(words, word(93)):
            return None
    except IndexError:
        return None
    _, sequence, revision, reason = words
    death = decode_death_state(image, frame)
    if death is None or death.life != 'alive' or sequence != death.sequence or revision >= 65521:
        return None
    position = decode_navigation_state(image, frame)
    if position is not None and position.target_revision not in (None, revision):
        return None
    if reason == 1:
        return '当前目标是玩家或玩家控制的单位'
    if reason == 2:
        return '当前怪物已被其他玩家占有'
    if reason == 3:
        return '当前怪物等级过低'
    if reason == 4 and frame.values.get('player_in_combat') == 'OFF':
        return '当前目标是精英怪或世界首领'
    # 旧插件仍可能报告 5（等级差不等于四级），由客户端忽略。
    return None


@dataclass(frozen=True, slots=True)
class MobState:
    sequence: int
    revision: int
    state: int
    key: str
    loot_generation: int
    loot_open: bool
    bearing: TargetBearing | None = None
    reacquired: bool = False
    loot_block: int = 0
    soft_corpse: bool = False
    loot_id: int = 0


@dataclass(frozen=True, slots=True)
class VendorState:
    sequence: int
    free: int
    junk: int
    selected: bool
    merchant_open: bool
    matched: bool
    hovered: bool
    select_key: str
    interact_vk: int
    sell_point: tuple[int, int] | None
    confirming: bool = False
    popup_blocked: bool = False
    catalog: bool = False
    repair_needed: bool | None = None
    repair_status: int = 0


@dataclass(frozen=True, slots=True)
class QuestTurnInPin:
    quest_id: int
    map_id: int
    x: float
    y: float


def decode_quest_turn_in_pin(image, frame):
    first = 177
    word = _sample_column(image, frame, calibration=((first, (_QUEST_SIGNATURE,)),))
    if word is None:
        return None
    try:
        words = [word(index) for index in range(first, first + 6)]
        if words[0] != _QUEST_SIGNATURE or not _valid_checksum(words, word(first + 6)):
            return None
    except IndexError:
        return None
    _, sequence, quest_id, map_id, x, y = words
    death = decode_death_state(image, frame)
    if (death is None or death.life != 'alive' or death.sequence != sequence
            or not 0 < quest_id < _CHECKSUM_MOD or not 0 < map_id < _CHECKSUM_MOD
            or not 0 < x < _POSITION_STEPS or not 0 < y < _POSITION_STEPS):
        return None
    return QuestTurnInPin(quest_id, map_id, x / 100, y / 100)


@dataclass(frozen=True, slots=True)
class QuestDialogState:
    sequence: int
    quest_id: int
    stage: int
    hovered: bool
    interact_vk: int
    unit_token: int
    button: tuple[int, int] | None
    receipt_quest: int
    receipt_generation: int
    clear_key: str = ''


def decode_quest_dialog(image, frame):
    first = 184
    word = _sample_column(image, frame, calibration=((first, (_QUEST_DIALOG_SIGNATURE,)),))
    if word is None:
        return None
    try:
        words = [word(index) for index in range(first, first + 10)]
        if words[0] != _QUEST_DIALOG_SIGNATURE or not _valid_checksum(words, word(first + 10)):
            return None
    except IndexError:
        return None
    _, sequence, quest_id, flags, vk, unit_token, x, y, receipt_quest, generation = words
    stage, hovered = divmod(flags, 2)
    death = decode_death_state(image, frame)
    if (death is None or death.life != 'alive' or death.sequence != sequence
            or not 0 <= quest_id < _CHECKSUM_MOD or not 0 <= receipt_quest < _CHECKSUM_MOD
            or generation > 65535 or (not receipt_quest and generation)
            or stage > 8 or (not quest_id and stage)):
        return None
    if stage == 1:
        if not (0 < unit_token < _CHECKSUM_MOD
                and (0x41 <= vk <= 0x5A or 0x70 <= vk <= 0x7B or 0x25 <= vk <= 0x28)):
            return None
    elif stage == 8:
        if not (0 < unit_token < _CHECKSUM_MOD and 1 <= vk <= 81):
            return None
    elif vk or unit_token:
        return None
    button = None
    if 2 <= stage <= 4:
        if not (0 < x < _POSITION_STEPS and 0 < y < _POSITION_STEPS):
            return None
        button = x, y
    elif hovered or (x, y) != (_NO_POSITION, _NO_POSITION):
        return None
    clear_key = key_for_index(vk) if stage == 8 else ''
    return QuestDialogState(sequence, quest_id, stage, bool(hovered), vk if stage == 1 else 0,
                            unit_token, button, receipt_quest, generation, clear_key)


def decode_vendor_state(image, frame, *, repair=False):
    signature, first, count = (0x574272, 165, 11) if repair else (0x574273, 140, 9)
    word = _sample_column(image, frame, calibration=((first, (signature,)),))
    if word is None:
        return None
    try:
        words = [word(index) for index in range(first, first + count)]
        if words[0] != signature or not _valid_checksum(words, word(first + count)):
            return None
    except IndexError:
        return None
    _, sequence, free, junk, flags, index, vk, x, y = words[:9]
    red, repair_status = words[9:] if repair else (2, 0)
    merchant_open, matched = bool(flags & 2), bool(flags & 4)
    confirming, popup_blocked = bool(flags & 16), bool(flags & 32)
    death = decode_death_state(image, frame)
    if (death is None or death.life != 'alive' or sequence != death.sequence or free > 1023
            or junk > 1023 or flags > 127 or index > 81 or red > 2 or repair_status > 3
            or (confirming and (not merchant_open or not matched or popup_blocked))
            or (repair_status and (red != 1 or not matched or not merchant_open or confirming or popup_blocked))
            or (vk and not (0x41 <= vk <= 0x5A or 0x70 <= vk <= 0x7B or 0x25 <= vk <= 0x28))):
        return None
    point = (x, y) if 0 < x < 10000 and 0 < y < 10000 else None
    return VendorState(sequence, free, junk, bool(flags & 1), merchant_open, matched,
                       bool(flags & 8), key_for_index(index) if index else '', vk, point,
                       confirming, popup_blocked, bool(flags & 64), None if red == 2 else bool(red), repair_status)


@dataclass(frozen=True, slots=True)
class TaxiState:
    sequence: int
    map_id: int
    riding: bool
    selected: bool
    panel_open: bool
    hovered: bool
    blocked: bool
    select_key: str
    interact_vk: int
    button: tuple[int, int] | None


def decode_taxi_state(image, frame):
    word = _sample_column(image, frame, calibration=((156, (_TAXI_SIGNATURE,)),))
    if word is None:
        return None
    try:
        words = [word(index) for index in range(156, 164)]
        if words[0] != _TAXI_SIGNATURE or not _valid_checksum(words, word(164)):
            return None
    except IndexError:
        return None
    _, sequence, map_id, flags, index, vk, x, y = words
    death = decode_death_state(image, frame)
    if (death is None or death.life != 'alive' or death.sequence != sequence
            or map_id >= 0xFF0000 or flags > 31 or index > 81
            or (vk and not (0x41 <= vk <= 0x5A or 0x70 <= vk <= 0x7B or 0x25 <= vk <= 0x28))):
        return None
    riding, selected, panel_open, hovered, blocked = (bool(flags & bit) for bit in (1, 2, 4, 8, 16))
    button = None
    if (x, y) != (_NO_POSITION, _NO_POSITION):
        if not (selected and panel_open and not blocked and 0 < x < 10000 and 0 < y < 10000):
            return None
        button = x, y
    if (hovered and button is None or (riding and flags != 1)
            or (not riding and map_id not in (1438, 1439)) or (map_id == 1439 and flags & ~1)
            or ((riding or panel_open or blocked or map_id == 1439) and (index or vk))):
        return None
    return TaxiState(sequence, map_id, riding, selected, panel_open, hovered, blocked,
                     key_for_index(index) if index else '', vk, button)


def decode_mob_state(image, frame):
    word = _sample_column(image, frame, calibration=((132, (_MOB_SIGNATURE,)),))
    if word is None:
        return None
    try:
        words = [word(index) for index in range(132, 139)]
        if words[0] != _MOB_SIGNATURE or not _valid_checksum(words, word(139)):
            return None
    except IndexError:
        return None
    _, sequence, revision, state, vk, loot, direction = words
    soft_corpse, loot = divmod(loot, 0x200000)
    loot_id = 0
    if soft_corpse or state == 6:
        loot_id, direction = direction, 0
    loot_block, loot = divmod(loot, 0x40000)
    reacquired, loot = divmod(loot, 0x20000)
    death = decode_death_state(image, frame)
    if (death is None or death.life != 'alive' or sequence != death.sequence or revision >= 65521
            or state > 7 or loot >= 65521 * 2 or loot_block > 5 or (state == 7 and loot_block)
            or (reacquired and state not in (0, 3, 4, 5))
            or loot_id > 65536
            or (soft_corpse and (soft_corpse != 1 or state != 3 or not vk or reacquired or loot_block))
            or (vk and state not in (3, 6)) or (direction and state != 3) or (state == 6 and not vk)):
        return None
    key = ''
    if state == 6 and 0x101 <= vk <= 0x151:
        key = key_for_index(vk - 0x100)
    elif 0x41 <= vk <= 0x5A:
        key = chr(vk)
    elif 0x70 <= vk <= 0x7B:
        key = f'F{vk - 0x6F}'
    elif vk:
        key = {0x25: 'LEFT', 0x26: 'UP', 0x27: 'RIGHT', 0x28: 'DOWN'}.get(vk)
        if key is None:
            return None
    bearing = None
    if direction:
        heading, distance = divmod(direction, 1024)
        if vk or heading > 6283 or not 18 <= distance <= 160:
            return None
        bearing = TargetBearing(revision, None, distance / 4, heading=heading / 1000)
    return MobState(sequence, revision, state, key, loot // 2, bool(loot % 2), bearing,
                    bool(reacquired), loot_block, bool(soft_corpse), loot_id)


class CharacterFrameFreshness:
    """用每约 200 毫秒更新的角色状态序号识别重复抓到的旧画面。"""

    timeout_ms = 1000

    def __init__(self):
        self._reset(None)

    @property
    def sample(self):
        if self._sequence is not None:
            return self._session, self._backend, self._sequence

    def _reset(self, session):
        self._session = session
        self._backend = None
        self._sequence = None
        self._changed_ms = 0
        self._confirmed = False

    def hold_reason(self, session, capture, frame, now_ms, *, require_sequence=False):
        if session != self._session:
            self._reset(session)
        reading = decode_death_state(capture.image, frame)
        if reading is None:
            # 早期插件没有这个扩展。当前会话读到过序号时，缺失才表示读数中断。
            self._confirmed = False
            if require_sequence or self._sequence is not None:
                return '角色状态读数暂不可用，已暂停游戏输入'
            return None
        if self._backend != capture.backend:
            # 两种抓屏来源可能各自缓存了不同的旧帧。先等新来源的序号变化。
            self._backend = capture.backend
            self._sequence = None
        if reading.sequence != self._sequence:
            self._confirmed = self._sequence is not None
            self._sequence = reading.sequence
            self._changed_ms = now_ms
        if now_ms - self._changed_ms >= self.timeout_ms:
            return STALE_FRAME
        if not self._confirmed:
            return '等待游戏画面更新'
        return None


def route_character(image, frame):
    if frame.values.get('player_valid') != 'ON' or frame.values.get('player_in_combat') != 'OFF':
        return None
    state = decode_character_state(image, frame)
    if state and state.life == 'alive' and state.outdoors and state.faction and state.level and state.zone:
        return state
    return None


def decode_navigation_state(image, frame, *, for_target=False, for_revival=False):
    word = _sample_column(image, frame, calibration=((150, (_ELEVATION_SIGNATURE,)),))
    combat = frame.values.get('player_in_combat')
    if (word is None or (combat != 'OFF' and not (for_target and combat == 'ON'))
            or frame.values.get('player_casting') != '空闲'):
        return None
    try:
        if word(43) != _NAVIGATION_SIGNATURE:
            return None
        words = [word(index) for index in range(43, 52)]
        if not _valid_checksum(words, word(52)):
            return None
    except IndexError:
        return None
    _, identity, map_id, px, py, facing, width, height, bindings = words
    motion, sequence = divmod(identity, 256)
    phase = motion & 0x1F
    revive_dialog = bool(motion & 0x20)
    continuous, moving = bool(motion & 0x40), bool(motion & 0x80)
    keys = bindings >> 16, (bindings >> 8) & 255, bindings & 255
    if (motion > 255 or (moving and not continuous) or phase not in (1, 3)
            or (revive_dialog and (phase != 3 or not for_revival))
            or (for_target and phase != 1)
            or frame.values.get('player_valid') != ('ON' if phase == 1 else 'OFF')
            or not 0 < map_id < 0xFF0000 or px > 10000 or py > 10000 or facing > 6283
            or not 1 <= width <= 100000 or not 1 <= height <= 100000
            or len(set(keys)) != 3 or not all(0x25 <= key <= 0x28 or 0x41 <= key <= 0x5A for key in keys)):
        return None
    idle_key_index = 0
    if combat == 'OFF' and phase == 1 and not moving:
        try:
            pull = [word(index) for index in range(54, 57)]
            if (pull[0] == _PULL_SIGNATURE and pull[1] == sequence and 1 <= pull[2] <= 81
                    and _valid_checksum(pull, word(57))):
                idle_key_index = pull[2]
        except IndexError:
            pass
    revision, retarget_key, discard_key, sight_blocked = None, 0, 0, False
    if combat == 'OFF' and phase == 1:
        try:
            retarget = [word(index) for index in range(70, 74)]
            signature, retarget_sequence, target_revision, key = retarget
            if (signature == _RETARGET_SIGNATURE and retarget_sequence == sequence
                    and target_revision < 65521 and _valid_checksum(retarget, word(74))):
                revision = target_revision
                if not moving and (key == 9 or 0x25 <= key <= 0x28 or 0x41 <= key <= 0x5A) and key not in keys:
                    retarget_key = key
        except IndexError:
            pass
        if revision is not None and not moving:
            try:
                discard = [word(index) for index in range(75, 78)]
                signature, discard_sequence, index = discard
                if (signature == _DISCARD_SIGNATURE and discard_sequence == sequence and 1 <= index <= 27
                        and _valid_checksum(discard, word(78))):
                    binding = parse_keybinding(key_for_index(index))
                    if binding.valid and not binding.modifiers and binding.vk not in (*keys, retarget_key):
                        discard_key = binding.vk
            except IndexError:
                pass
            if retarget_key or discard_key:
                try:
                    sight = [word(index) for index in range(79, 82)]
                    sight_blocked = (sight == [_SIGHT_SIGNATURE, sequence, revision]
                                     and _valid_checksum(sight, word(82)))
                except IndexError:
                    pass
    elif for_target and combat == 'ON' and (mob := decode_mob_state(image, frame)) and mob.state == 1:
        revision = mob.revision
    elevation = _auberdine_elevation(word, map_id, px, py)
    position_steps = _POSITION_STEPS
    try:
        precise = [word(index) for index in range(83, 88)]
        signature, precise_sequence, precise_map, fine_x, fine_y = precise
        scale = _PRECISE_POSITION_STEPS // _POSITION_STEPS
        if (signature == _PRECISE_POSITION_SIGNATURE and precise_sequence == sequence and precise_map == map_id
                and fine_x <= _PRECISE_POSITION_STEPS and fine_y <= _PRECISE_POSITION_STEPS
                and abs(fine_x - px * scale) <= scale // 2 and abs(fine_y - py * scale) <= scale // 2
                and _valid_checksum(precise, word(88))):
            px, py, position_steps = fine_x, fine_y, _PRECISE_POSITION_STEPS
    except IndexError:
        pass
    return NavigationState(_LIFE_STATES[phase], sequence, map_id, px * 100 / position_steps,
                           py * 100 / position_steps, facing / 1000,
                           width, height, keys, idle_key_index, continuous, moving, revision, retarget_key, discard_key,
                           sight_blocked, position_steps, elevation)


def decode_target_bearing(image, frame, position):
    if position is None or position.life != 'alive' or frame.values.get('target_valid') != 'ON':
        return None
    word = _sample_column(image, frame)
    if word is None:
        return None
    try:
        if word(59) not in (_TARGET_SIGNATURE, _TARGET_WORLD_SIGNATURE):
            return None
        words = [word(index) for index in range(59, 64)]
        if not _valid_checksum(words, word(64)):
            return None
    except IndexError:
        return None
    signature, sequence, revision, x, y = words
    if (sequence != position.sequence or revision >= 65521
            or position.target_revision not in (None, revision)
            or getattr(frame, 'target_revision', None) not in (None, revision)):
        return None
    if signature == _TARGET_WORLD_SIGNATURE:
        if x <= 6283 and 100 <= y <= 10000:
            return TargetBearing(revision, None, y / 100, continuous=True, heading=x / 1000)
        return None
    if not (0 < x < 10000 and 0 < y < 10000):
        return None
    try:
        capability = word(65)
    except IndexError:
        capability = 0
    estimated = capability == _ESTIMATED_TARGET_SIGNATURE
    continuous = capability in (_MOVING_TARGET_SIGNATURE, _ESTIMATED_TARGET_SIGNATURE)
    raw_distance = frame.values.get('distance')
    if estimated and raw_distance == '—':
        distance = None
    else:
        try:
            distance = float(raw_distance)
        except (TypeError, ValueError):
            return None
        if not 4 <= distance <= (100 if continuous else 65):
            return None
    return TargetBearing(revision, x / 10000, distance, continuous, estimated)


def decode_wand_key(image, frame):
    word = _sample_column(image, frame)
    if word is None:
        return ''
    try:
        words = [word(66), word(67)]
        if words[0] == _WAND_SIGNATURE and _valid_checksum(words, word(68)):
            return key_for_index(words[1])
    except IndexError:
        pass
    return ''


def read_live_character(assets_dir):
    """只读当前唯一游戏窗口，连续观察稳定的角色身份后返回。"""
    from .assets import Assets
    from .capture import make_win32_capture
    from .game_windows import CtypesWindowBackend, GAME_EXECUTABLES, enumerate_windows

    windows = [item for item in enumerate_windows(CtypesWindowBackend()).windows
               if item.executable.casefold() in GAME_EXECUTABLES]
    if len(windows) != 1:
        raise ValueError('自动读取练级状态需要打开一个游戏窗口，并进入角色')
    pipeline = Assets.load(assets_dir).pipeline()
    capture = make_win32_capture()
    try:
        end = time.monotonic() + 2.5
        previous = None
        while time.monotonic() < end:
            result = capture.capture(windows[0].hwnd)
            if result.image is not None:
                frame, _ = pipeline.decode(result.image)
                state = route_character(result.image, frame)
                if state:
                    if not state.simplified_chinese:
                        raise ValueError('当前练级指南按简体中文地图名匹配，请使用简体中文客户端或手动填写地图')
                    identity = state.route_key
                    if identity == previous:
                        return state
                    previous = identity
                else:
                    previous = None
            else:
                previous = None
            time.sleep(0.25)
    finally:
        capture.dxgi.backend.close()
    raise ValueError('未读取到稳定的角色状态，请确认配套插件已加载、色条可见，角色存活且已脱战并在野外地图')
