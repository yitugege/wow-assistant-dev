"""062cd0完整自动选目标自测子组；候选计算不发送按键。"""
from dataclasses import dataclass
from .auto_target import parse_auto_target, key_for_index
from .candidates import CandidateEngine, _object, _array
from .expressions import _string
from .selftest_inputs_auto_target import INPUTS


@dataclass(frozen=True)
class AutoTargetSelftestResult:
    text: str
    passed: int
    total: int


def run_auto_target_selftest(rules, contract, *, inputs=None):
    inputs=INPUTS if inputs is None else inputs
    lines=['== 自动选目标（合成 ttd 包）==']
    engine=CandidateEngine(rules)
    count=len(_array(_object(_object(rules.get('specs')).get('1491')).get('actionAvailSpellIDs')))
    # 原BTS使用64位寄存器；第63位后已全1，后续循环只重复置位。
    mask=(1 << min(count+1,64))-1
    fields0=dict(inputs['common_frame'],action_avail=str(mask))
    for field in _array(_object(_object(contract.get('specs')).get('1491')).get('fields')):
        if _string(_object(field).get('type'))=='cooldown':
            fields0[_string(field.get('id'))]='0.0'
    passed=0
    for case in inputs['valid']:
        fields=dict(fields0,gcd='ON' if case['gcd_busy'] else 'OFF',
                    player_casting=inputs['casting_text']['true' if case['casting'] else 'false'],ttd=str(case['packed_ttd']))
        matches=[row for row in engine.generate('1491',fields,allow_unknown_availability=False) if row.action=='auto_target']
        chosen=matches[0] if matches else None
        ok=bool(chosen)==bool(case['expected_hit'])
        if chosen and case['expected_hit']:
            ok=ok and (chosen.key,chosen.priority,chosen.hold_ms)==(case['expected_key'],case['expected_priority'],case['expected_hold_ms'])
        passed+=ok
        detail=f'命中 {chosen.key}（p{chosen.priority} 压制{chosen.hold_ms}ms）' if chosen else '未命中'
        lines.append(f'  {"✓" if ok else "✗"} {case["label"]} → {detail}')
    for case in inputs['invalid']:
        rejected=parse_auto_target(case['ttd']) is None
        passed+=rejected
        lines.append(f'  {"✓" if rejected else "✗"} {case["label"]} → {"拒绝（不按键）" if rejected else "误接受"}')
    last=max((i for i in range(1,201) if key_for_index(i)),default=0)
    ok=last==81;passed+=ok
    lines.append(f'  {"✓" if ok else "✗"} 键表覆盖 1..{last}（期望 81）')
    lines.append(f'  小结：自动选目标用例 {passed}/15')
    return AutoTargetSelftestResult('\n'.join(lines),passed,15)
