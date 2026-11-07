"""062cd0 中 067c35–069c41 循环库自测；输入由调用者读取，不访问文件。"""
from dataclasses import dataclass
from .candidates import _array, _object
from .expressions import _int, _string
from .thresholds import promote_profile
from .selftest_focus import evaluate_injured, evaluate_minimum, MINIMUM_CASES


@dataclass(frozen=True)
class HubSelftestResult:
    text: str
    checked: int
    mismatches: int
    skipped: int
    profile_count: int
    threshold_count: int
    pre_action_count: int
    pre_action_failures: int
    pre_profile_count: int


def profile_talents(rules, spec, sub_key):
    """0696xx 的 SkipEmptyParts 首段 + 05a3d0 的前 3 组精确匹配。"""
    first = next((part for part in _string(sub_key).split('/') if part), '')
    if not first:
        return ''
    groups = _array(_object(_object(rules.get('roles')).get(str(spec))).get('groups'))
    for index, group in enumerate(groups[:3]):
        if _string(group) == first:
            values = ['0', '0', '0']
            values[index] = '10'
            return '/'.join(values)
    return ''


def _left(text, width):
    return text + ' ' * max(0, width - len(text.encode('utf-16-le', errors='surrogatepass')) // 2)


def run_hub_selftest(rules, rotations=None, *, snapshot_path='', snapshot_readable=True,
                     initial_checked=0, initial_mismatches=0, initial_skipped=0):
    """返回此子组计数；末行显示加上 initial_* 后的原版累计数。

    snapshot_path 为空即原版未找到快照分支；非空而 unreadable 为打开失败。
    成功打开但 JSON 非对象/无 rotations，由调用者传 None/相应值，原版当空库。
    text 含原版段首换行、无段尾换行，可与其他子组用一个 LF 连接。
    """
    lines = []
    checked = mismatches = skipped = threshold_count = 0
    pre_action_count = pre_action_failures = pre_profile_count = profile_count = 0
    if snapshot_path:
        lines.append(f'\n\n== 循环库方案滑条（提升结果，{snapshot_path}）==')
        if not snapshot_readable:
            lines.append(f'  打不开快照：{snapshot_path}')
        else:
            profiles = [_object(p) for p in _array(_object(rotations).get('rotations'))]
            profile_count = len(profiles)
            for profile in profiles:
                spec = str(_int(profile.get('specId')))
                thresholds = promote_profile(rules, profile).thresholds
                threshold_count += len(thresholds)
                lines.append(f'  [{_int(profile.get("id"))}] spec={spec} {_string(profile.get("specName"))} {_string(profile.get("subKey"))}：{len(thresholds)} 条滑条')
                for item in thresholds:
                    lines.append(f'      {_left(item.key,34)} 默认={item.default} max={item.maximum} 技能={"/".join(item.skills) or "-"}')
            lines.append(f'\n循环库滑条合计 {threshold_count} 条（{profile_count} 套）')
            examples = []
            for profile in profiles:
                spec = str(_int(profile.get('specId')))
                actions = _array(_object(_object(rules.get('specs')).get(spec)).get('actions'))
                for rule in _array(profile.get('rules')):
                    pre = _string(_object(rule).get('pre'))
                    if not pre:
                        continue
                    pre_action_count += 1
                    # 原线性扫描命中即退出，重复 name 取首项，包括首项为空键。
                    action = next((_object(a) for a in actions if _string(_object(a).get('name')) == pre), {})
                    key = _string(action.get('key'))
                    if not key:
                        pre_action_failures += 1
                        examples.append(f'{spec}/{pre} 无键')
                    elif len(examples) < 4:
                        examples.append(f'{spec}/{pre}={key}')
            lines.append(f'\n循环库先行动作合计 {pre_action_count} 条，解析失败 {pre_action_failures} 条')
            lines.append('   '+(', '.join(examples) or '(无)'))
            lines.append('\n循环库方案 · 受伤帧先行键核对')
            for profile in profiles:
                if not any(_string(_object(r).get('pre')) for r in _array(profile.get('rules'))):
                    continue
                pre_profile_count += 1
                spec = str(_int(profile.get('specId')))
                sub_key = _string(profile.get('subKey'))
                label = f'[{_int(profile.get("id"))}] {_string(profile.get("specName"))}/{sub_key or "通用"}'
                talents = profile_talents(rules, spec, sub_key)
                lines.append(evaluate_injured(rules, profile, spec, talents, label).text)
                for case in MINIMUM_CASES:
                    result = evaluate_minimum(rules, profile, spec, talents, label+' · '+case['label'], case)
                    lines.append(result.text)
                    checked += result.status != 'skipped'
                    mismatches += result.status == 'mismatch'
                    skipped += result.status == 'skipped'
            lines.append(f'\n带先行键的方案 {pre_profile_count} 套（共核对 {profile_count} 套）')
    lines.append(f'\n同档最低血裁决：核对 {checked+initial_checked} 套，不符 {mismatches+initial_mismatches} 套，跳过 {skipped+initial_skipped} 套（本帧无同档多人决策）')
    return HubSelftestResult('\n'.join(lines),checked,mismatches,skipped,profile_count,
                             threshold_count,pre_action_count,pre_action_failures,pre_profile_count)
