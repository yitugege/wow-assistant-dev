"""原 062cd0 的 off-GCD 整组静态输入执行器，不发送按键。"""
from dataclasses import dataclass
from .candidates import CandidateEngine, OFF_GCD_ACTIONS, OFF_GCD_SPELL_IDS
from .send_gates import local_gcd_allows, invalidate_local_gcd
from .selftest_inputs_off_gcd import GATE_CASES, LOCAL_CASES, LEDGER_CASES, END_TO_END_CASES


@dataclass(frozen=True)
class OffGcdSelftestResult:
    text: str
    passed: int
    total: int
    gate_passed: int
    registry_passed: int
    local_passed: int
    engine_passed: int
    ledger_passed: int


def _mark(passed):
    return '✓' if passed else '✗'


def run_off_gcd_selftest(rules):
    lines = ['\n\n== 无 GCD 动作（off_gcd.h）==']
    gate_passed = local_passed = engine_passed = ledger_passed = 0
    for case in GATE_CASES:
        actual = bool(case['data_off_gcd'] or case['spell_id'] in OFF_GCD_SPELL_IDS or case['action'] in OFF_GCD_ACTIONS)
        passed = actual == bool(case['expected_keep'])
        gate_passed += passed
        lines.append(f'  {_mark(passed)} 闸门3 {case["label"]} → {"保留" if actual else "砍掉"}（期望{"保留" if case["expected_keep"] else "砍掉"}）')
    ids = tuple(OFF_GCD_SPELL_IDS)
    duplicates = sum(a == b for i,a in enumerate(ids) for b in ids[i+1:])
    nonpositive = sum(i <= 0 for i in ids)
    registry_passed = int(len(ids) >= 23 and duplicates == 0 and nonpositive == 0)
    lines.append(f'  {_mark(registry_passed)} 登记表 {len(ids)} 个 ID（期望 ≥23）、重复 {duplicates}、非正 {nonpositive}')
    for case in LOCAL_CASES:
        actual = local_gcd_allows(case['action'],off_gcd=bool(case['off_gcd']))
        passed = actual == bool(case['expected_allow'])
        local_passed += passed
        lines.append(f'  {_mark(passed)} 本地GCD窗 {case["label"]} → {"放行" if actual else "拦住"}（期望{"放行" if case["expected_allow"] else "拦住"}）')
    engine = CandidateEngine(rules)
    for case in END_TO_END_CASES:
        candidates = engine.generate(case['spec'],dict(case['fields']),selected_rules=case['selected_rules'])
        revenge = any(c.action == 'spell_6572' for c in candidates)
        block_candidates = [c for c in candidates if c.action == 'spell_2565']
        block = bool(block_candidates)
        # 原循环记录最后一个同名候选的标志；presence 不过滤 stop，显示过滤。
        off_gcd = block_candidates[-1].off_gcd if block else False
        passed = revenge == case['expected_revenge'] and block == case['expected_block'] and bool(off_gcd)
        engine_passed += passed
        names = ', '.join(c.action for c in candidates if not c.stop) or '(空)'
        lines.append(f'  {_mark(passed)} {case["label"]} → 表里 {names}（格挡标记 offGcd={"是" if off_gcd else "否"}，期望{"留复仇" if case["expected_revenge"] else "砍复仇"}/{"留格挡" if case["expected_block"] else "砍格挡"}）')
    for case in LEDGER_CASES:
        actual = invalidate_local_gcd(active=bool(case['ledger_pending']),plugin_gcd=case['gcd'],casting=bool(case['casting']))
        passed = actual == bool(case['expected_invalidate'])
        ledger_passed += passed
        lines.append(f'  {_mark(passed)} 换目标账本 {case["label"]} → {"作废" if actual else "保留"}（期望{"作废" if case["expected_invalidate"] else "保留"}）')
    lines.append(f'  小结：判据 {gate_passed}/13、登记表 {registry_passed}/1、本地窗 {local_passed}/5、端到端 {engine_passed}/3、换目标账本 {ledger_passed}/6，kGcdModelMs = 1500 ms')
    passed = gate_passed+registry_passed+local_passed+engine_passed+ledger_passed
    if passed != 28:
        lines.append('  ★ 有用例失败：无 GCD 判据或闸门 3 已跑偏，别发这套 EXE')
    return OffGcdSelftestResult('\n'.join(lines),passed,28,gate_passed,registry_passed,
                                local_passed,engine_passed,ledger_passed)
