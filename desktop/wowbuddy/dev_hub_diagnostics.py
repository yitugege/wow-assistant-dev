"""独立版循环库本地诊断；原缓存报告与动作缺口分别记录。"""
import json
from pathlib import Path
from .cli_hub import run_local_hub_command
from .native_cli import parse_native_cli
from .dev_library import seed_library, profile_action_gaps


def run_hub_diagnostics(assets_dir, data_dir):
    assets_dir=Path(assets_dir)
    data_dir=Path(data_dir).resolve()
    data_dir.mkdir(parents=True,exist_ok=True)
    seeded=seed_library(assets_dir,data_dir)
    # 显式环境隔离，不能继承历史WOWBUDDY_HOME或服务器地址。
    result=run_local_hub_command(parse_native_cli(['WowBuddyDev','--hub-selftest']),
        application_dir=data_dir,environment={'WOWBUDDY_HOME':str(data_dir)})
    documents=[json.loads((assets_dir/name).read_text('utf8'))
               for name in ('rules.json','rules_readable.json')]
    gaps=[]
    for profile in result.hub.profiles:
        missing=profile_action_gaps(profile,*documents)
        if missing:
            gaps.append({'profile_key':profile.key,'spec_id':profile.spec_id,'missing_actions':missing})
    success=result.exit_code==0 and result.report_written
    report={'cache_check_passed':success,'native_cache_exit_code':result.exit_code,
            'report_written':result.report_written,'report_error':result.report_error,
            'initial_library_seeded':seeded,'profiles':len(result.hub.profiles),
            'status':result.status.replace('正在联网检查更新…','离线诊断，未联网'),
            'cache_error':result.hub.error,
            'profiles_with_missing_actions':len(gaps),'action_gaps':gaps,
            'network_used':False,
            'scope':'缓存读取与静态动作引用检查；PASS不证明宏可用、条件正确或游戏施法成功'}
    (data_dir/'hub-selftest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    return int(not success)
