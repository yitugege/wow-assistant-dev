"""图像→双协议→阈值字段→候选的无副作用运行链。

保留主窗身份与字段描述状态；窗口捕获、方案选择持久化、发送调度由上层负责。
原生 readable 资源只加载 name→key，不替换基础动作或规则。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Mapping

from .candidates import Candidate, CandidateEngine
from .dev_library import runtime_profile_action
from .expressions import UnsupportedSemantics, _int, _string
from .old_protocol import OldDecoder, OldFrame
from .pixel_geometry import RGBImage
from .readable_protocol import ReadableDecoder, ReadableFrame
from .thresholds import Threshold, apply_thresholds, promote_builtin_rotations, promote_profile
from .dev_protocol import (DEV_VERSION, RecoveryGate, disabled_recovery_ready, normalize_availability,
                           recovery_candidate)


Frame = OldFrame | ReadableFrame
_ATTACK_TAGS = frozenset(('输出', '填充', 'AOE', '起手', '主攻', '持续伤害', '仇恨', '群攻', '减益', '触发'))
_WAND_SPECS = frozenset(('1482', '1487', '1490'))
_OFFICIAL_FROST_LEVELING = '官方 · 练级（冰霜 · 单体+AOE）'
_OFFICIAL_ARCANE_LEVELING = '官方 · 练级（奥术）'
_ARCANE_SEQUENCE = (400574, 5143, 5143, 2136)
_ARCANE_REQUIRED_SPELLS = (400574, 5143)
_ARCANE_CAST_RANKS = {
    400574: {400574, 1239696, 1239697, 1239699, 1239700},
    5143: {5143, 5144, 5145, 8416, 8417, 10211, 10212, 25345},
    2136: {2136, 2137, 2138, 8412, 8413, 10197, 10199, 400616, 400618, 400619, 400620, 400621, 400622, 400623},
}
_MAGE_EMERGENCY_HEALTH = 45
# 单体、无伤害增益和治疗。未确认影响范围的动作不进入自动刷怪。
_SINGLE_TARGET_SPELLS = frozenset('''
    1126 467 5176 2912 8921 5570 24858 768 5487 9634 407995 1082 5221 1822 1079
    22568 6807 5217 417141 22812 1850 17056 8936 774 5185 18562 408120 17116 5229
    13163 13165 1130 1978 3044 75 5116 2973 1494 19574 1310687 19434 3045 19306 19263
    19577 136 1299346 1459 168 7302 6117 116 133 2136 5143 2948 11366 400574 1312002
    2139 12051 12042 11129 11426 12043 19740 465 7294 20163 20154 20375 20271 678 879
    24275 20925 633 498 853 635 19750 1311606 20216 1243 588 589 585 8092 2944 15407
    15473 15487 15286 17 139 2050 2060 2061 402174 401859 10060 14751 1752 2098 5171
    703 1943 53 8676 16511 1310707 14278 1766 5277 13750 14177 14183 1776 324 408510
    403 8042 8050 8056 17364 408490 331 8004 1064 408521 16188 16190 5675 687 706 688
    980 172 348 686 689 1454 18265 1316697 412758 1293817 6353 17877 19028 1293695 6789
    18288 100 6673 2687 6552 72 5308 7384 6572 402927 12294 23881 23922 1310222 12328
    772 1240193 78 871 12975 2565 7386 355
'''.split())


def _single_target_candidate(candidate):
    if candidate.stop or candidate.action in ('auto_target', 'start_attack', 'shoot_wand', 'pet_attack'):
        return True
    if candidate.action.startswith('focus_'):
        return True
    return (candidate.action.startswith('spell_') and candidate.tag not in ('AOE', '群攻')
            and candidate.action.split('_', 2)[1] in _SINGLE_TARGET_SPELLS)


def _add_frost_emergency_blast(rules, thresholds, settings):
    finisher = next((threshold for threshold in thresholds
                     if threshold.action == 'spell_2136' and threshold.field == 'target_health_pct'
                     and threshold.direction == 'below'), None)
    if finisher is None or settings.get(finisher.key, finisher.default) < 1:
        return
    cutoff = ['flag', finisher.key, True]
    for index, rule in enumerate(rules):
        when = rule['when']
        if (rule['action'] != 'spell_2136' or not isinstance(when, list) or not when
                or when[0] != 'and' or cutoff not in when[1:]):
            continue
        other_guards = [condition for condition in when[1:] if condition != cutoff]
        rules.insert(index + 1, dict(rule, reason='贴身战斗血量偏低，优先使用火焰冲击瞬发输出',
            when=['and', *other_guards, ['not', cutoff], ['flag', 'player_valid', True],
                  ['flag', 'player_in_combat', True], ['flag', 'range_2136', True],
                  ['num_below', 'distance', 8], ['num_below', 'player_health_pct', _MAGE_EMERGENCY_HEALTH]]))
        return


def _add_arcane_leveling_armor(rules):
    actions = {rule['action'] for rule in rules}
    armor = []
    for spell, name, extra in ((7302, '冰甲术', []),
                               (168, '霜甲术', [['flag', 'known_7302', False]])):
        action = f'spell_{spell}'
        if action in actions:
            continue
        armor.append({
            'action': action, 'tag': '增益', 'holdMs': 30000,
            'reason': f'尚未学会魔甲术，脱战时补{name}',
            'when': ['and', ['flag', 'player_valid', True], ['flag', 'player_in_combat', False],
                     ['flag', 'player_moving', False], ['flag', 'known_6117', False],
                     ['flag', f'known_{spell}', True], *extra, ['avail', spell],
                     *(['flag', aura, False] for aura in ('mage_armor', 'ice_armor', 'frost_armor'))],
        })
    # 护甲互斥，沿用方案的魔甲术优先级。
    index = next((i + 1 for i, rule in enumerate(rules) if rule['action'] == 'spell_6117'), 0)
    rules[index:index] = armor
    return armor


def readable_key_maps(document: Mapping) -> dict[str, dict[str, str]]:
    """0446a0：只接受非空字符串 name/key；同名最后一次有效值覆盖。"""
    specs = document.get("specs", {})
    result = {}
    for spec_id, spec in specs.items() if isinstance(specs, dict) else ():
        actions = spec.get("actions", []) if isinstance(spec, dict) else []
        keys = {}
        for action in actions if isinstance(actions, list) else []:
            if not isinstance(action, dict):
                continue
            name, key = _string(action.get("name")), _string(action.get("key"))
            if name and key:
                keys[name] = key
        if keys:
            result[spec_id] = keys
    return result


@dataclass(frozen=True)
class Decision:
    frame: Frame
    fields: Mapping[str, str]
    candidates: tuple[Candidate, ...]
    thresholds: tuple[Threshold, ...] = ()
    # 保留旧条失败原因，供上层解释为何走 readable；不复用失败帧字段。
    old_attempt: OldFrame | None = None
    recovery_ready: bool = False
    attack_blocked_by_range: bool = False
    recovery_disabled: bool = False
    attack_blocked_by_sight: bool = False
    target_rejection: str | None = None


@dataclass(frozen=True)
class PreparedFrame:
    frame: Frame
    fields: Mapping[str, str]
    thresholds: tuple[Threshold, ...] = ()
    selected_rules: list | None = None
    key_overrides: Mapping[str, str] | None = None
    old_attempt: OldFrame | None = None
    travel_buffs: list | None = None


class DecisionPipeline:
    def __init__(self, old_contract: Mapping, readable_contract: Mapping,
                 rules: Mapping, readable_rules: Mapping, *, legacy_descriptor_cache=False):
        # 固定一次资源加载快照；调用者改原 dict 不会偷偷改变运行中的表。
        self.rules = deepcopy(rules)
        self.old = OldDecoder(deepcopy(old_contract), additional_versions=(DEV_VERSION,))
        self.readable = ReadableDecoder(deepcopy(old_contract), deepcopy(readable_contract))
        # 原主窗098BE0在首帧前建立空身份通用表；None仅用于触发首次构建。
        self._descriptor_identity = None
        # 独立版修复：协议也参与缓存身份。旧行为仅供离线对比，不由GUI启用。
        self.legacy_descriptor_cache = legacy_descriptor_cache
        self._descriptor_protocol = None
        self._retained_descriptors: tuple[Mapping, ...] = ()
        self._old_descriptors("")
        self.readable_keys = readable_key_maps(readable_rules)
        compiled = deepcopy(self.rules)
        self.builtin_thresholds = {}
        for spec_id, spec in compiled.get("specs", {}).items():
            if spec_id in _WAND_SPECS:
                # 原资源保持原样。只有独立插件确实上报按键时，动作才有可用键。
                spec["actions"].append({"name": "shoot_wand", "label": "魔杖射击", "spellId": 5019})
            promotions = promote_builtin_rotations(self.rules, spec_id)
            spec["rotations"] = {group: item.json_rules() for group, item in promotions.items()}
            self.builtin_thresholds[spec_id] = tuple(
                threshold for item in promotions.values() for threshold in item.thresholds)
        self.engine = CandidateEngine(compiled)
        self.recovery = RecoveryGate()
        self.probe_attack_range = False
        self.skip_obstructed_targets = False
        self.unattended_grinding = False
        self.unattended_travel = False
        self.mob_policy_seen = False
        self._arcane_target = None
        self._arcane_receipt = None
        self._arcane_step = 0

    def evaluate(self, image: RGBImage, *, selected_profile: Mapping | None = None,
                 settings: Mapping[str, int] | None = None) -> Decision:
        return self.generate(self.prepare(image, selected_profile=selected_profile, settings=settings))

    def prepare(self, image: RGBImage, *, selected_profile: Mapping | None = None,
                settings: Mapping[str, int] | None = None) -> PreparedFrame:
        """selected_profile 是上层已为当前专精选择的循环库对象。

        settings 是去掉 switch/ 前缀后的整数配置；UI 迁移/夹紧单独执行。
        无图/失败帧返回空候选，不保留上帧动作。
        """
        frame, attempt = self.decode(image)
        return self.prepare_frame(frame, old_attempt=attempt, selected_profile=selected_profile, settings=settings)

    def decode(self, image: RGBImage) -> tuple[Frame, OldFrame | None]:
        """先取专精，再允许上层恢复方案；同一张图像无需重复解码。"""
        old_frame = self.old.decode(image, descriptor_resolver=self._old_descriptors)
        if old_frame.fallback_readable:
            frame = normalize_availability(self.readable.decode(image, descriptor_resolver=self._readable_descriptors))
            return self._apply_target_policy(image, frame), old_frame
        frame = normalize_availability(old_frame)
        if frame.ok and self.unattended_grinding and frame.version_code == DEV_VERSION:
            from .character_state import decode_vendor_state
            repair = decode_vendor_state(image, frame, repair=True)
            if repair is not None and repair.repair_needed:
                frame = replace(frame, values=dict(frame.values, equipment_red='ON'))
        if frame.ok and frame.version_code == DEV_VERSION and frame.spec_id in _WAND_SPECS:
            from .character_state import decode_wand_key
            if key := decode_wand_key(image, frame):
                frame = replace(frame, values=dict(frame.values, shoot_wand_key=key))
        prep = (self.unattended_grinding and frame.version_code == DEV_VERSION and frame.spec_id == '1482'
                and frame.values.get('target_valid') == 'OFF' and frame.values.get('target_health_pct') == '0'
                and frame.values.get('player_in_combat') == 'OFF' and frame.values.get('player_moving') == 'OFF')
        if prep or (self.skip_obstructed_targets and frame.values.get('target_valid') == 'ON'):
            from .character_state import decode_navigation_state
            position = decode_navigation_state(image, frame)
            if position is not None and position.sight_blocked:
                frame = replace(frame, values=dict(frame.values, target_sight_blocked='ON'))
            if prep and position is not None and position.idle_key_index:
                from .character_state import decode_vendor_state
                vendor = decode_vendor_state(image, frame)
                if vendor is None or not (vendor.merchant_open or vendor.popup_blocked):
                    # 站定时的寻怪就绪包已校验总开关、输入焦点和绑定。此处只允许自身护甲。
                    frame = replace(frame, values=dict(frame.values, mage_prep_ready='ON'))
        frame = self._apply_target_policy(image, frame)
        if frame.ok and frame.version_code == DEV_VERSION and frame.spec_id == '1482':
            from .character_state import decode_cast_feedback, decode_character_session
            token = decode_character_session(image, frame)
            target = ((token, frame.target_revision) if token is not None and frame.target_revision is not None
                      and frame.values.get('target_valid') == 'ON' and frame.values.get('player_valid') == 'ON'
                      else None)
            self._observe_arcane_sequence(target, decode_cast_feedback(image, frame))
        else:
            self._observe_arcane_sequence(None, None)
        return frame, None

    def _observe_arcane_sequence(self, target, feedback):
        if target is None or target != self._arcane_target:
            self._arcane_target = target
            self._arcane_step = 0
            self._arcane_receipt = feedback.sequence if feedback else None
            return
        if (feedback is not None and feedback.sequence != self._arcane_receipt
                and '成功' in feedback.stages):
            self._arcane_receipt = feedback.sequence
            expected = _ARCANE_SEQUENCE[self._arcane_step]
            if expected == 2136 and feedback.spell in _ARCANE_CAST_RANKS[400574]:
                self._arcane_step = 1
            elif expected == 2136 and feedback.spell in _ARCANE_CAST_RANKS[5143]:
                self._arcane_step = 0
            elif feedback.spell in _ARCANE_CAST_RANKS[expected]:
                self._arcane_step = (self._arcane_step + 1) % len(_ARCANE_SEQUENCE)

    def _apply_target_policy(self, image: RGBImage, frame: Frame) -> Frame:
        if not frame.ok:
            return frame
        mob, reason = None, None
        independent = frame.protocol == 'old' and frame.version_code == DEV_VERSION
        if independent:
            from .character_state import decode_mob_state, decode_target_rejection
            mob = decode_mob_state(image, frame)
            self.mob_policy_seen = self.mob_policy_seen or mob is not None
            if mob is not None and mob.state == 1 and frame.values.get('target_valid') == 'ON':
                frame = replace(frame, target_revision=mob.revision)
            if self.unattended_grinding or self.mob_policy_seen:
                reason = decode_target_rejection(image, frame)
        if self.mob_policy_seen:
            frame = replace(frame, values=dict(frame.values, mob_policy='ON'))
            if not independent:
                reason = '当前协议无法确认怪物归属，等待独立插件读数'
            elif frame.values.get('target_valid') == 'ON' and (mob is None or mob.state != 1):
                reason = reason or '游戏未确认当前怪物可由自己攻击和拾取'
        if reason:
            frame = replace(frame, values=dict(frame.values, target_rejection=reason))
        return frame

    def rebuild_old_descriptors(self, spec_id: str) -> tuple[Mapping, ...]:
        """08CFE0→098BE0：显式布局回调即使身份相同也重建旧契约表。"""
        return self._old_descriptors(spec_id, force=True)

    def _old_descriptors(self, spec_id: str, *, force: bool = False) -> tuple[Mapping, ...]:
        # 093A48：未知身份仅在先前身份非空时触发公共字段重建。
        if force or spec_id != self._descriptor_identity or (not self.legacy_descriptor_cache and self._descriptor_protocol != 'old'):
            common_count = len(self.old.contract.get("commonFields", []))
            class_only = self.old.contract.get("classOnlyFields", {})
            numeric_spec = int(spec_id) if spec_id else 0
            self._retained_descriptors = tuple(
                dict(field, applicable=(field["id"] not in class_only
                                       or numeric_spec in class_only[field["id"]]),
                     is_common=index < common_count)
                for index, field in enumerate(self.old.field_definitions(spec_id)))
            self._descriptor_identity = spec_id
            self._descriptor_protocol = 'old'
        return self._retained_descriptors

    def _readable_descriptors(self, spec_id: str) -> tuple[Mapping, ...]:
        # 095410：未知身份已提前返回；只有身份改变才重建，协议不参与比较。
        if spec_id != self._descriptor_identity or (not self.legacy_descriptor_cache and self._descriptor_protocol != 'readable'):
            self._retained_descriptors = tuple(
                {"id": key, "label": key, "type": kind, "applicable": True,
                 "is_common": False, "note": ""}
                for key, kind, _ in self.readable.field_definitions(spec_id))
            self._descriptor_identity = spec_id
            self._descriptor_protocol = 'readable'
        return self._retained_descriptors

    def prepare_frame(self, frame: Frame, *, old_attempt: OldFrame | None = None,
                      selected_profile: Mapping | None = None,
                      settings: Mapping[str, int] | None = None) -> PreparedFrame:
        attempt = old_attempt
        if not frame.ok:
            return PreparedFrame(frame, {}, old_attempt=attempt)
        thresholds = self.builtin_thresholds.get(frame.spec_id, ())
        selected_rules = None
        travel_buffs = None
        if selected_profile is not None:
            if str(_int(selected_profile.get("specId"))) != frame.spec_id:
                raise ValueError("上层必须传入当前专精的已选方案，不能跨专精套用")
            promotion = promote_profile(self.rules, selected_profile)
            selected_rules = promotion.json_rules()
            if (self.unattended_grinding and frame.version_code == DEV_VERSION and frame.spec_id == '1482'
                    and selected_profile.get('profileName') == _OFFICIAL_FROST_LEVELING
                    and selected_profile.get('author') == '官方'):
                if (frame.values.get('known_116') == 'OFF'
                        and not any(rule['action'] == 'spell_133' for rule in selected_rules)):
                    for index, rule in enumerate(selected_rules):
                        if rule['action'] == 'spell_116':
                            selected_rules[index] = {
                                'action': 'spell_133', 'tag': '输出', 'reason': '尚未学会寒冰箭，使用已学的火球术',
                                'when': ['and', ['flag', 'player_valid', True], ['flag', 'target_valid', True],
                                         ['flag', 'known_133', True], ['flag', 'range_133', True],
                                         ['flag', 'player_moving', False], ['avail', 133]],
                            }
                            break
                _add_frost_emergency_blast(selected_rules, promotion.thresholds, settings or {})
            if (frame.version_code == DEV_VERSION and frame.spec_id == '1482'
                    and selected_profile.get('profileName') == _OFFICIAL_ARCANE_LEVELING
                    and selected_profile.get('author') == '官方'):
                selected_rules = [rule for rule in selected_rules if rule['action'] != 'spell_2136']
                if self.unattended_grinding:
                    travel_buffs = _add_arcane_leveling_armor(selected_rules)
                if all(frame.values.get(f'known_{spell}') == 'ON' for spell in _ARCANE_REQUIRED_SPELLS):
                    spell = _ARCANE_SEQUENCE[self._arcane_step]
                    blast_blocked = frame.values.get('arcane_blast_debuff') == 'ON'
                    selected_rules = [rule for rule in selected_rules
                                      if rule['tag'] not in _ATTACK_TAGS and rule['action'] != 'spell_11366']
                    step_rules = [(spell, [], f'奥术循环第 {self._arcane_step + 1} 步')]
                    if spell == 400574 and blast_blocked:
                        step_rules = [(5143, [], '奥术冲击减益仍在，改用奥术飞弹')]
                    if spell == 2136:
                        fire_ready = ['and', ['flag', 'known_2136', True],
                                      ['flag', 'range_2136', True], ['avail', 2136]]
                        step_rules = [
                            (2136, [fire_ready], '第二次奥术飞弹后，火焰冲击在射程内且可用'),
                            (5143 if blast_blocked else 400574, [['not', fire_ready]],
                             '跳过当前不可用的火焰冲击，继续奥术循环'),
                        ]
                    for action_spell, guards, reason in step_rules:
                        selected_rules.append({
                            'action': f'spell_{action_spell}', 'tag': '输出', 'reason': reason,
                            'when': ['and', ['flag', 'player_valid', True], ['flag', 'target_valid', True],
                                     ['flag', 'player_moving', False], ['flag', f'range_{action_spell}', True],
                                     ['avail', action_spell], *guards],
                        })
            if frame.version_code == DEV_VERSION and frame.spec_id == '1490':
                profile_id = _int(selected_profile.get('id'))
                for rule in selected_rules:
                    rule['action'] = runtime_profile_action(1490, profile_id, rule['action'], rule['reason'])
            # 原引擎空外部规则仍回退到内置；相应保留内置阈值。
            if promotion.rules:
                thresholds = promotion.thresholds
        fields = apply_thresholds(thresholds, settings or {}, frame.values)
        keys = self.readable_keys.get(frame.spec_id) if frame.protocol == "readable" else None
        if (frame.protocol == 'old' and frame.version_code == DEV_VERSION and frame.spec_id in _WAND_SPECS
                and fields.get('player_valid') == 'ON' and fields.get('target_valid') == 'ON'
                and fields.get('player_moving') == 'OFF' and (wand_key := fields.get('shoot_wand_key'))):
            keys = {'shoot_wand': wand_key}
        return PreparedFrame(frame, fields, thresholds, selected_rules, keys, attempt, travel_buffs)

    def generate(self, prepared: PreparedFrame, *, engine_fields: Mapping[str, str] | None = None) -> Decision:
        """调度器在这里注入圣印回执覆盖；原字段仍保留用于光环回查。"""
        candidates = ()
        recovery_ready = False
        recovery_disabled = False
        attack_blocked_by_range = False
        attack_blocked_by_sight = False
        fields = prepared.fields
        if prepared.frame.ok:
            gate = self.recovery.evaluate(prepared.frame)
            if gate is None:
                disabled = disabled_recovery_ready(prepared.frame)
                recovery_disabled = disabled is not None
                recovery_ready = disabled is True
                handoff, recovery = self.recovery.post_kill_recovery(prepared.frame)
                if handoff or recovery_disabled:
                    fields = dict(fields, ttf="0")
                    if engine_fields is not None:
                        engine_fields = dict(engine_fields, ttf="0")
                else:
                    recovery = recovery_candidate(prepared.frame)
            else:
                normal_gate, recovery = gate
                fields = dict(fields, combat_time="0", ttf="0", master_switch="ON" if normal_gate else "OFF")
                if engine_fields is not None:
                    engine_fields = dict(engine_fields, combat_time="0", ttf="0", master_switch=fields["master_switch"])
            recovery_ready = recovery_ready or gate is not None
            if self.unattended_grinding and prepared.frame.version_code == DEV_VERSION:
                if fields.get('player_valid') != 'ON':
                    recovery = Candidate(label='等待角色存活', reason='游戏尚未确认角色存活，暂停战斗按键。',
                                         tag='恢复', stop=True)
                elif (recovery is None and not recovery_ready and fields.get('master_switch') == 'ON'
                      and fields.get('player_in_combat') != 'ON'):
                    reason = ('自动吃喝已关闭，等待血量和法力达到设置的开始阈值。' if recovery_disabled
                              else '等待游戏提供有效的恢复读数，再继续战斗。')
                    recovery = Candidate(label='等待恢复确认', reason=reason, tag='恢复', stop=True)
            if recovery is not None:
                self.engine.last_auto_packet = None
                return Decision(prepared.frame, fields, (recovery,), prepared.thresholds, prepared.old_attempt,
                                recovery_disabled=recovery_disabled)
            if fields.get('equipment_red') == 'ON' and fields.get('player_in_combat') == 'OFF':
                self.engine.last_auto_packet = None
                stop = Candidate(label='装备待修理', reason='装备耐久已变红，暂停主动开怪。', tag='补给', stop=True)
                return Decision(prepared.frame, fields, (stop,), prepared.thresholds, prepared.old_attempt,
                                recovery_ready=recovery_ready, recovery_disabled=recovery_disabled)
            if (self.unattended_grinding or fields.get('mob_policy') == 'ON') and (reason := fields.get('target_rejection')):
                self.engine.last_auto_packet = None
                stopped = (() if fields.get('player_in_combat') == 'OFF' else
                           (Candidate(label='已跳过目标', reason=reason, tag='选目标', stop=True),))
                return Decision(prepared.frame, fields, stopped, prepared.thresholds, prepared.old_attempt,
                                recovery_ready=recovery_ready, recovery_disabled=recovery_disabled,
                                target_rejection=reason)
            effective_fields = fields if engine_fields is None else engine_fields
            if (prepared.travel_buffs and recovery_ready and fields.get('mage_prep_ready') == 'ON'
                    and fields.get('target_valid') == 'OFF' and fields.get('player_casting') == '空闲'):
                # 复用候选引擎的可用性与公共冷却检查，只计算经过核对的自身护甲。
                buffs = tuple(self.engine.generate(
                    prepared.frame.spec_id, dict(effective_fields, master_switch='ON', ttd='0'),
                    selected_rules=prepared.travel_buffs, key_overrides=prepared.key_overrides,
                    allow_unknown_availability=False))
                if buffs:
                    return Decision(prepared.frame, fields, buffs, prepared.thresholds, prepared.old_attempt,
                                    recovery_ready=True, recovery_disabled=recovery_disabled)
            candidates = tuple(self.engine.generate(
                prepared.frame.spec_id, effective_fields,
                selected_rules=prepared.selected_rules, key_overrides=prepared.key_overrides,
                allow_unknown_availability=prepared.frame.allow_unknown_availability))
            if fields.get('mob_policy') == 'ON':
                candidates = tuple(candidate for candidate in candidates if _single_target_candidate(candidate))
            attack_blocked_by_sight = (self.skip_obstructed_targets and recovery_ready
                                      and fields.get('master_switch') == 'ON'
                                      and fields.get('player_in_combat') == 'OFF'
                                      and fields.get('target_sight_blocked') == 'ON')
            if attack_blocked_by_sight:
                candidates = tuple(candidate for candidate in candidates if candidate.tag not in _ATTACK_TAGS)
            elif (self.probe_attack_range and prepared.selected_rules
                    and not any(candidate.stop or candidate.tag in _ATTACK_TAGS for candidate in candidates)):
                # 增益等非攻击候选可能仍在压制期，不能据此认定目标已进入射程。
                attack_blocked_by_range = self._range_is_blocking_attack(prepared, effective_fields)
            travel_pause = (self.unattended_travel and prepared.frame.version_code == DEV_VERSION
                            and fields.get('player_in_combat') == 'OFF')
            if travel_pause:
                # 陆路尚未完成，保留恢复入口和停发诊断，暂停循环发键。
                candidates = tuple(candidate for candidate in candidates if candidate.stop)
            if (prepared.frame.version_code == DEV_VERSION and len(candidates) == 1
                    and candidates[0].stop and candidates[0].reason == self.engine.sentinel.get("stopReason")):
                reason = "插件暂停发键，请检查总开关、当前目标或游戏输入焦点。"
                if travel_pause:
                    reason = "无人托管正在执行陆路计划，脱战时暂停技能循环。"
                elif (prepared.fields.get("player_in_combat") == "OFF"
                        and prepared.fields.get("target_valid") == "OFF"):
                    reason = "已脱战且没有可攻击目标。请选中目标，或检查插件的「击杀后继续选怪」设置。"
                candidates = (replace(candidates[0], label="插件已暂停", reason=reason),)
        return Decision(prepared.frame, fields, candidates, prepared.thresholds, prepared.old_attempt,
                        recovery_ready=recovery_ready, attack_blocked_by_range=attack_blocked_by_range,
                        recovery_disabled=recovery_disabled, attack_blocked_by_sight=attack_blocked_by_sight)

    def _range_is_blocking_attack(self, prepared, fields):
        if (prepared.frame.version_code != DEV_VERSION or fields.get('master_switch') != 'ON'
                or fields.get('target_valid') != 'ON' or fields.get('player_valid') != 'ON'
                or fields.get('player_in_combat') not in ('ON', 'OFF') or fields.get('player_casting') != '空闲'):
            return False
        raw_distance = fields.get('distance')
        if raw_distance != '—':
            try:
                distance = float(raw_distance)
            except (TypeError, ValueError):
                return False
            if not 4 <= distance <= 100:
                return False

        # 仅试算已有循环。未知射程不补成可达，也不把试算候选交给调度器。
        range_changes = {key: 'ON' for key, value in fields.items() if key.startswith('range_') and value == 'OFF'}
        stopped = dict(fields, player_moving='OFF') if fields.get('player_moving') == 'ON' else fields
        closer = dict(stopped, **range_changes)
        if raw_distance == '—':
            if not range_changes:
                return False
            samples = (closer,)
        else:
            samples = (closer, *(dict(closer, distance=str(near)) for near in (20.0, 3.0) if near < distance))
        saved_packet = self.engine.last_auto_packet
        def has_attack(sample):
            return any(candidate.tag in _ATTACK_TAGS and candidate.key and not candidate.stop
                       and (sample.get('mob_policy') != 'ON' or _single_target_candidate(candidate))
                       for candidate in self.engine.generate(
                           prepared.frame.spec_id, sample, selected_rules=prepared.selected_rules,
                           key_overrides=prepared.key_overrides,
                           allow_unknown_availability=prepared.frame.allow_unknown_availability))
        try:
            if stopped is not fields and has_attack(stopped):
                return False
            return any(has_attack(sample) for sample in samples)
        except UnsupportedSemantics:
            return False
        finally:
            self.engine.last_auto_packet = saved_packet
