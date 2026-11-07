"""059020/05acb0/05bb60/05c6a0焦点自测共用构图与原断言。"""
from dataclasses import dataclass
import re
from .candidates import CandidateEngine, _array, _object, _decimal_int
from .expressions import _int, _string, _trim
from .thresholds import promote_profile, apply_thresholds
from .selftest_inputs_focus import BASE_FIELDS, AURAS_12, AURAS_34, HEALTH_UNITS, MINIMUM_CASES
from .selftest_engine import NativeSelftestEngine


@dataclass(frozen=True)
class InjuredResult:
    text: str
    candidate_count: int
    pre_count: int
    missing_key_count: int


@dataclass(frozen=True)
class MinimumResult:
    text: str
    status: str
    actual_pre: str | None
    expected_pre: str
    diagnostic_min: str | None


@dataclass(frozen=True)
class FocusSelftestResult:
    text: str
    checked: int
    mismatches: int
    skipped: int


def build_injured_fields(rules, spec, talents, overrides=None):
    fields = dict(BASE_FIELDS)
    fields.update(friendly_party1='ON',friendly_party2='ON')
    fields.update({name:'OFF' for name in AURAS_12})
    config = _object(_object(rules.get('specs')).get(str(spec)))
    count = len(_array(config.get('actionAvailSpellIDs')))
    mask = (1 << min(count+1,32))-1
    fields['action_avail'] = str(mask if mask < 0x80000000 else mask-0x100000000)
    for action in _array(config.get('actions')):
        spell_id = _int(_object(action).get('spellId'))
        if spell_id > 0:
            fields['ready_'+str(spell_id)] = 'ON'
    if overrides is not None:
        fields.update(friendly_party3='ON',friendly_party4='ON')
        fields.update({name:'OFF' for name in AURAS_34})
        for unit in HEALTH_UNITS:
            fields['health_'+unit] = overrides.get(unit,'100')
        fields['player_health_pct'] = overrides.get('player','100')
    token = _string(_object(_object(rules.get('roles')).get(str(spec))).get('token'))
    if token and talents:
        fields[token+'_talents'] = talents
    return fields


def _generate(rules, profile, spec, fields):
    return NativeSelftestEngine(rules).generate(str(spec),fields,section='focus',profile=profile)


def _left(text, width):
    return text+' '*max(0,width-len(text.encode('utf-16-le',errors='surrogatepass'))//2)


def evaluate_injured(rules, profile, spec, talents, label):
    candidates = _generate(rules,profile,spec,build_injured_fields(rules,spec,talents))
    lines = [f'\n{label} 受伤帧 → {len(candidates)} 条建议']
    count = pre_count = missing_key_count = omitted = 0
    for candidate in candidates:
        if candidate.stop:
            lines.append('   [停发] '+candidate.label)
            continue
        pre_count += bool(candidate.pre_action)
        missing_key_count += bool(candidate.pre_action) and not candidate.pre_key
        count += 1
        if count <= 8:
            lines.append(f'   {_left(candidate.action,26)} 键={_left(candidate.key,18)} 先行={candidate.pre_action or "-"}({candidate.pre_key or "-"})')
        else:
            omitted += 1
    if omitted:
        lines.append(f'   …（其余 {omitted} 条省略）')
    lines.append(f'   => 先行 {pre_count} 条 / 其中查不到键 {missing_key_count} 条')
    return InjuredResult('\n'.join(lines),len(candidates),pre_count,missing_key_count)


def _health(fields, pre):
    if pre == 'focus_player':
        unit = 'player'
    elif re.fullmatch(r'focus_party[1-4]',pre):
        unit = pre[6:]
    else:
        return -1
    # 原05c150直接toInt，不先Unicode trimmed，也不拆字段尾注。
    value = _decimal_int(fields.get('health_'+unit,''))
    return value if value is not None else -1


def evaluate_minimum(rules, profile, spec, talents, label, case):
    fields = build_injured_fields(rules,spec,talents,case['health_overrides'])
    eligible = [c for c in _generate(rules,profile,spec,fields) if not c.stop and c.pre_action]
    first = eligible[0] if eligible else None
    groups = {}
    for candidate in eligible:
        if _health(fields,candidate.pre_action) >= 0:
            groups.setdefault(candidate.action+'\x1f'+candidate.tag,set()).add(candidate.pre_action)
    multiple = any(len(group)>=2 for group in groups.values())
    expected = case['expected_pre']
    if first is None or case['require_multi'] and not multiple:
        return MinimumResult(f'  — {label}：本帧无「同档多人」决策，跳过（不计入核对）','skipped',None,expected,None)
    best, best_hp = '',1000
    for candidate in eligible:
        health = _health(fields,candidate.pre_action)
        if candidate.action == first.action and candidate.tag == first.tag and 0 <= health < best_hp:
            best,best_hp = candidate.pre_action,health
    passed = first.pre_action == expected
    text = f'  {"✓" if passed else "✗"} {label}：选中 {first.pre_action} / 期望 {expected}（同档最低 {best or "-"}）'
    return MinimumResult(text,'pass' if passed else 'mismatch',first.pre_action,expected,best or None)


def run_focus_selftest(rules, rotations=None):
    profile = next((p for p in _array(_object(rotations).get('rotations')) if
                    _int(_object(p).get('specId')) == 1486 and '神圣' in _string(_object(p).get('subKey'))),None)
    lines = ['== 焦点治疗先行键（合成受伤帧）==']
    if profile is not None:
        lines.append('(圣骑-神圣 用例改用循环库方案「'+_string(profile.get('profileName'))+'」)')
        lines.append('')
    lines.append(evaluate_injured(rules,profile,'1486','10/0/0','圣骑-神圣').text)
    lines.append('\n== 同档最低血裁决（每帧都标出期望值，期望来自用例而非引擎输出）==')
    cases = [evaluate_minimum(rules,profile,'1486','10/0/0','圣骑-神圣 · '+case['label'],case) for case in MINIMUM_CASES]
    lines.extend(case.text for case in cases)
    return FocusSelftestResult('\n'.join(lines),sum(c.status!='skipped' for c in cases),
                               sum(c.status=='mismatch' for c in cases),sum(c.status=='skipped' for c in cases))
