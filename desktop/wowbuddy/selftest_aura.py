"""原生062cd0完整光环自测子组；供统一离线自测入口调用。"""
from dataclasses import dataclass
from .aura_probe import probe, classify_receipt, spell_id_from_action, Receipt
from .candidates import CandidateEngine, collect_expect_off
from .selftest_inputs_aura import INPUTS


@dataclass(frozen=True)
class AuraSelftestResult:
    text: str
    passed: int
    total: int


def run_aura_selftest(rules, *, inputs=None):
    inputs = INPUTS if inputs is None else inputs
    lines = ['== 「按了但没生效」回查（aura_probe.h）==']
    names = ('未到点', '读条中', '已生效', '没生效', '免疫')
    receipt_names = ('作废', '没出手', '出手了', '别的技能')
    totals = dict(probe=0, receipt=0, collect=0, candidates=0)
    def sign(passed): return '✓' if passed else '✗'
    for case in inputs['probe_records']:
        fields = {key: {0:'OFF',1:'ON',-1:'—'}[value] for key,value in case['flag_readings'].items()}
        actual = int(probe(expect_off=case['expect_off'], fields=fields, now_ms=case['now_ms'],
            check_at_ms=case['check_at_ms'], casting=bool(case['casting']), failures=case['failures'],
            receipt=Receipt(case['receipt'])))
        passed = actual == case['expected']; totals['probe'] += passed
        lines.append(f"  {sign(passed)} {case['label']} → {names[actual]}（期望 {names[case['expected']]}）")
    for case in inputs['spell_records']:
        actual = spell_id_from_action(case['action'])
        passed = actual == case['expected']; totals['receipt'] += passed
        lines.append(f"  {sign(passed)} spellIdFromAction({case['action']}) = {actual}（期望 {case['expected']}）")
    for case in inputs['receipt_records']:
        action = 'unknown' if case['action_spell_id'] == -1 else f"spell_{case['action_spell_id']}"
        actual = int(classify_receipt(action, case['sent_generation'], case['current_generation'],case['current_spell_id']))
        passed = actual == case['expected']; totals['receipt'] += passed
        lines.append(f"  {sign(passed)} {case['label']} → {receipt_names[actual]}（期望 {receipt_names[case['expected']]}）")
    lines.append(f"  回执小计：{totals['receipt']}/17")
    for case in inputs['collect_records']:
        actual = list(collect_expect_off(case['expression']))
        passed = actual == case['expected']; totals['collect'] += passed
        lines.append(f"  {sign(passed)} {case['label']} → 收到 [{','.join(actual)}]（期望 [{','.join(case['expected'])}]）")
    engine = CandidateEngine(rules)
    for case in inputs['candidate_records']:
        matches = [row for row in engine.generate(inputs['candidate_spec'], inputs['candidate_fields'],
                   selected_rules=[case['rule']]) if row.action == case['action']]
        actual = list(matches[-1].expect_off) if matches else []
        passed = bool(matches) == case['expected_hit'] and actual == case['expected_expect_off']
        totals['candidates'] += passed
        hit = '命中' if matches else '未命中'
        lines.append(f"  {sign(passed)} {case['label']} → {hit}，expectOff=[{','.join(actual)}]（期望 [{','.join(case['expected_expect_off'])}]）")
    lines.append(f"  小结：判据 {totals['probe']}/21、收集 {totals['collect']}/9、端到端 {totals['candidates']}/3，回查 400ms、重试压制 1000ms（回查重试总窗口 400+1000=1400ms，必须 ≤ 本地 GCD 窗口 1500ms —— aura_probe.h 的 static_assert 钉死）")
    lines.append('  免疫预算：连续 2 次回查都判「没落地」⇒ 认这个目标免疫/抵抗（或够不着），压制期恢复成规则自己写的 holdMs（撕裂 8~9s、腐蚀术 30s），不再每 1400ms 空放一次')
    return AuraSelftestResult('\n'.join(lines), sum(totals.values()), 50)
