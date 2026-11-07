"""062CD0 绑定解析与阈值提升展示；动态数据计数，不是通过/失败断言组。"""
from dataclasses import dataclass
from typing import Mapping, Sequence
from .candidates import Action, _array, _object
from .expressions import _string
from .keybindings import parse_keybinding
from .thresholds import Threshold, parse_switch_fields, promote_builtin_rotations


# 只读PE UTF16常量；展示原样保留空格/换行，不能把43键/0滑条硬编码进结果。
TEMPLATES = {
    'bindings': (0x1400D60B8, '\n\n== 绑定键解析（共 %1 个）=='),
    'key': (0x1400D60E8, '%1 -> vk=%2 mods=[%3] %4'),
    'error': (0x1400D6120, 'ERR:%1'),
    'thresholds': (0x1400D6130, '\n\n== 阈值滑条（提升结果，%1 个可调字段）=='),
    'field': (0x1400D6168, '字段 %1 (%2) 上限 %3 单位 %4'),
    'spec': (0x1400D6198, '\n-- 专精 %1（%2 条）'),
    'threshold': (0x1400D61C0, '  [%1] %2 默认=%3 max=%4 字段=%5 %6 技能=%7 类别=%8'),
    'direct': (0x1400D6218, '直挂'),
    'at_least': (0x1400D6220, '>='),
    'below': (0x1400D2E68, '<'),
    'missing': (0x1400D2DE4, '-'),
    'total': (0x1400D6228, '\n滑条合计 %1 条'),
}


@dataclass(frozen=True)
class BindingsThresholdsSelftestResult:
    text: str
    key_count: int
    binding_error_count: int
    field_count: int
    threshold_count: int


def _utf16_key(value: str):
    return value.encode('utf-16-be','surrogatepass')


def _left(value: str, width: int):
    return value + ' '*max(0,width-len(value.encode('utf-16-le','surrogatepass'))//2)


def _fmt(key,*values):
    text=TEMPLATES[key][1]
    for i in range(len(values),0,-1):
        text=text.replace(f'%{i}',str(values[i-1]))
    return text


def run_bindings_thresholds_selftest(rules: Mapping, *, spec_order: Sequence[str] | None = None,
        thresholds_by_spec: Mapping[str,Sequence[Threshold]] | None = None):
    """复用实际解析/提升。多个非空spec需调用者给原QHash迭代次序，未知不猜。

    thresholds_by_spec可注入已由041E00加载等价层生成的阈值；默认调用已有提升器。
    原生此处不对显示结果另作断言，因此不制造passed/total。
    """
    specs=_object(rules.get('specs'))
    keys=set()
    for spec in specs.values():
        for raw in _array(_object(spec).get('actions')):
            action=Action.from_json(raw)
            if action.key:
                keys.add(action.key)
    keys=sorted(keys,key=_utf16_key)
    lines=[_fmt('bindings',len(keys)).removeprefix('\n\n')]
    errors=0
    for key in keys:
        parsed=parse_keybinding(key)
        errors+=not parsed.valid
        lines.append(_fmt('key',_left(key,22),parsed.vk,
            ','.join(str(v) for v in parsed.modifiers),
            '' if parsed.valid else _fmt('error',parsed.error)))
    fields=parse_switch_fields(rules)
    lines.append(_fmt('thresholds',len(fields)))
    for key in sorted(fields,key=_utf16_key):
        field=fields[key]
        lines.append(_fmt('field',key,field.label,field.maximum,field.unit))
    if thresholds_by_spec is None:
        thresholds_by_spec={key:tuple(item for promotion in promote_builtin_rotations(rules,key).values()
                                     for item in promotion.thresholds) for key in specs}
    active=[key for key in specs if thresholds_by_spec.get(key)]
    if spec_order is None:
        if len(active)>1:
            raise ValueError('多个非空专精的原QHash遍历顺序未知；请显式提供spec_order')
        spec_order=active
    elif (len(set(spec_order)) != len(spec_order)
          or any(key not in specs for key in spec_order)
          or not set(active).issubset(spec_order)):
        raise ValueError('spec_order必须不重复且覆盖全部非空专精，只能包含已载入专精')
    total=0
    for key in spec_order:
        rows=thresholds_by_spec.get(key,())
        if not rows:
            continue
        lines.append(_fmt('spec',_string(_object(specs[key]).get('title')),len(rows)))
        for row in rows:
            lines.append(_fmt('threshold',_left(row.group or _fmt('direct'),8),_left(row.key,34),
                row.default,row.maximum,row.field,
                _fmt('at_least') if row.direction=='at_least' else _fmt('below'),
                '/'.join(row.skills) or _fmt('missing'),row.tag or _fmt('missing')))
            total+=1
    lines.append(_fmt('total',total))
    return BindingsThresholdsSelftestResult('\n'.join(lines),len(keys),errors,len(fields),total)
