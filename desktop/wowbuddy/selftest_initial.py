"""062cd0十四项初始引擎展示和四项治疗不攻击断言。"""
from dataclasses import dataclass
from .candidates import CandidateEngine, infer_role, parse_rules, _object, _array
from .expressions import EvaluationContext, _string
from .selftest_inputs_initial import INPUTS
from .selftest_engine import NativeSelftestEngine


@dataclass(frozen=True)
class InitialSelftestResult:
    text: str
    passed: int
    total: int


def build_initial_fields(rules,contract,case,*,common_fields=None):
    fields=dict(INPUTS['common_fields'] if common_fields is None else common_fields)
    spec=case['spec']
    actions=_object(_object(rules.get('specs')).get(spec))
    count=len(_array(actions.get('actionAvailSpellIDs')))
    fields['action_avail']=str((1 << min(count+1,64))-1)
    schema=_object(_object(contract.get('specs')).get(spec))
    for row in _array(contract.get('commonFields'))+_array(schema.get('fields'))+_array(schema.get('presenceFields')):
        if _string(_object(row).get('type'))=='cooldown':
            fields[_string(row.get('id'))]='0.0'
    token=_string(_object(_object(rules.get('roles')).get(spec)).get('token'))
    fields[token+'_talents' if token else '']=case['talents']
    return fields


def builtin_rule_count(rules,spec,fields):
    """0472a0→0472d0；本段尚未安装循环库外部覆盖。"""
    config=_object(_object(rules.get('specs')).get(spec))
    builtin=_object(config.get('rotations'))
    if not builtin: return 0
    if '' in builtin: return len(parse_rules(builtin['']))
    role_config=_object(_object(rules.get('roles')).get(spec))
    role=infer_role(role_config,EvaluationContext(fields))
    groups=[_string(x) for x in _array(role_config.get('groups'))]
    if role.status==2:
        for group in role.group.split('/'):
            if group in builtin: return len(parse_rules(builtin[group]))
    elif role.status!=0:
        roles=_object(role_config.get('roles'))
        unique={_string(roles.get(group)) for group in groups if _string(roles.get(group))}
        if len(unique)==1:
            return len(parse_rules(builtin.get(groups[0] if groups else '')))
    return 0


def run_initial_selftest(rules,contract,*,inputs=None):
    inputs=INPUTS if inputs is None else inputs
    engine=NativeSelftestEngine(rules)
    lines=[];passed=total=0
    for case in inputs['cases']:
        fields=build_initial_fields(rules,contract,case,common_fields=inputs['common_fields'])
        candidates=engine.generate(case['spec'],fields,section='initial',allow_unknown_availability=False)
        count=builtin_rule_count(engine.document,case['spec'],fields)
        lines.append(f'\n{case["label"]} 专精{case["spec"]} 天赋={case["talents"]} 规则{count} 条 → {len(candidates)} 条建议')
        shown=[]
        for candidate in candidates[:6]:
            if candidate.stop:
                shown.append('[停发]'+candidate.label)
            else:
                pre=f',先行={candidate.pre_action}/{candidate.pre_key}' if candidate.pre_key else ''
                shown.append(f'{candidate.action}({candidate.key},p{candidate.priority}{pre})')
        lines.append('   '+(', '.join(shown) if shown else '(空)'))
        if case['label'] in inputs['healer_labels']:
            attack=any(not c.stop and (c.action==inputs['forbidden_action'] or c.tag in inputs['forbidden_tags']) for c in candidates)
            total+=1;passed+=not attack
            lines.append(f'   治疗闸门：{"✗ 产出了攻击建议" if attack else "✓ 未产出攻击建议"}（共 {len(candidates)} 条建议）')
    verdict='✓ 通过（治疗不攻击）' if passed==total else '★ 治疗会去打怪，别发这套 EXE'
    lines.append(f'\n== 治疗兜底闸门：{passed}/{total} {verdict}')
    return InitialSelftestResult('\n'.join(lines),passed,total)
