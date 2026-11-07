"""原引擎自检的独立入口，保留文本并显式记录失败和跳过计数。"""
from dataclasses import asdict
import json
from pathlib import Path
from .assets import Assets
from .cli_selftest import run_local_selftest_command
from .dev_library import read_local_library, seed_library
from .rotation_selection import HubState


def run_engine_diagnostics(assets_dir, data_dir):
    assets_dir=Path(assets_dir)
    data_dir=Path(data_dir).resolve()
    data_dir.mkdir(parents=True,exist_ok=True)
    report={'checks_passed':False,'report_written':False,'errors':[],
            'checks_scope':'仅汇总原自检结果对象提供的断言、绑定错误、不符及先行动作失败计数；展示段落不是完整断言',
            'skip_reason':'合成帧没有同档多人决策的案例不计入核对，不算通过',
            'scope':'原062cd0离线自检的迁入实现；合成输入，不证明全部功能或游戏行为完成'}
    try:
        assets=Assets.load(assets_dir)
        seeded=seed_library(assets_dir,data_dir)
        snapshot=data_dir/'hub/rotations.json'
        read_local_library(snapshot,HubState())  # 原入口宽松解析前先明确拒绝损坏快照。
        order=tuple(assets.rules.get('specs',{}))
        result=run_local_selftest_command(['WowBuddyDev',f'--rotations={snapshot}'],
            application_dir=data_dir,current_dir=data_dir,resource_dir=assets_dir,spec_order=order)
        groups={name:{k:v for k,v in asdict(value).items() if k not in ('text','cases')}
                for name,value in result.report.groups.items()}
        failures=[]
        for name,values in groups.items():
            if 'total' in values and values['passed'] != values['total']:
                failures.append(name)
            if any(values.get(key,0) for key in ('mismatches','binding_error_count','pre_action_failures')):
                failures.append(name)
        report.update(checks_passed=not failures,failed_groups=sorted(set(failures)),
            report_written=result.report_written,report_error=result.write_error,
            groups=groups,skipped=sum(g.get('skipped',0) for g in groups.values()),
            initial_library_seeded=seeded,spec_order=order,
            spec_order_source='本地rules.json键顺序；不冒充原Qt QHash运行时遍历顺序',
            native_command_exit_code=result.exit_code)
    except (OSError,ValueError,KeyError) as error:
        report['errors'].append(str(error))
    report['command_succeeded']=report['checks_passed'] and report['report_written'] and not report['errors']
    (data_dir/'engine-selftest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    return int(not report['command_succeeded'])
