"""062CD0 焦点去重子组的8项判据、9项动作映射；无输入或系统动作。"""
from dataclasses import dataclass
from . import send_gates
from .selftest_inputs_focus_dedup import INPUTS


@dataclass(frozen=True)
class FocusDedupSelftestResult:
    text: str
    passed: int
    total: int


def _evaluate_scalar(values):
    """窄适配原标量到现有动作API；字符串是适配载体，不是伪造原输入。"""
    desired=values['desired_focus']
    if desired == 2:
        action='focus_party2'
    elif desired == -1:
        action='spell_633_focus'
    else:
        raise ValueError('原8项只有desired_focus=2/-1；未支持额外标量输入')
    return send_gates.should_skip_focus(action,
        last_action=action if values['same_action'] else '', last_switch_ms=0,
        now_ms=values['elapsed_ms'], focus_known=bool(values['reading_known']),
        observed_index=values['observed_focus'])


def run_focus_dedup_selftest(*, inputs=None):
    data=INPUTS if inputs is None else inputs
    t={key:item['text'] for key,item in data['templates'].items()}
    def fmt(key,*values):
        text=t[key]
        for index in range(len(values),0,-1):
            text=text.replace(f'%{index}',str(values[index-1]))
        return text
    def sign(ok): return t['passed'] if ok else t['failed']
    def state(skip): return t['skip'] if skip else t['resend']
    lines=[t['header'].removeprefix('\n')]
    predicates=0
    mappings=0
    for case in data['scalar_table']['records']:
        actual=_evaluate_scalar(case['values'])
        expected=bool(case['values']['expected_skip'])
        passed=actual == expected
        predicates+=passed
        lines.append(fmt('case',sign(passed),case['label'],state(expected),state(actual)))
    for case in data['mappings']:
        actual=send_gates.focus_index(case['action'])
        passed=actual == case['expected']
        mappings+=passed
        lines.append(fmt('mapping',sign(passed),case['action'] or t['empty'],actual,case['expected']))
    lines.append(fmt('summary',predicates,8,mappings,9))
    if predicates != 8 or mappings != 9:
        lines.append(t['warning'])
    # 原06AB52的报告参数为立即数3000；不把运行时常量改变藏进期望。
    lines.append(fmt('keep',data['keep_ms']))
    return FocusDedupSelftestResult('\n'.join(lines),predicates+mappings,17)
