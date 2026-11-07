"""目录版 --update-now：退出前完成校验和交接，就绪后退出允许替换。"""
from pathlib import Path
import os
from .github_client import check_latest,download_checked
from .dev_update_handoff import prepare_handoff,wait_until_ready,cancel_handoff,write_json

def run_update_now(data_dir,current,arguments,*,frozen,check=check_latest,
                   download=download_checked,prepare=prepare_handoff,wait_ready=wait_until_ready):
    data_dir=Path(data_dir).absolute();data_dir.mkdir(parents=True,exist_ok=True)
    current=Path(current).absolute();handoff=None
    result={'ok':False,'installed':False,'handoff_ready':False}
    lines=['== 自动更新 ==']
    try:
        info=check();result['version']=info['version']
        lines.extend([f"当前版本 {info['current_version']}",f"线上版本 {info['version']}"])
        if not info['has_update']:
            lines.append('已是最新版本');result.update(ok=True,has_update=False);code=0
        else:
            result['has_update']=True
            if not frozen:raise ValueError('源码模式不能替换客户端，请使用构建后的EXE执行 --update-now')
            staged=download(info,current.parent/'WowBuddyDev-updates')
            lines.append('安装包已校验，准备退出后替换。')
            handoff=prepare(staged['staged'],current,arguments,restart='WOWBUDDY_UPDATE_NO_RESTART' not in os.environ)
            from .dev_update_notice import remember_handoff
            remember_handoff(data_dir,current,handoff)
            result['job']=handoff['job']
            result['final_report']=str(Path(handoff['job']).with_suffix('.result.json'))
            wait_ready(handoff)
            result.update(ok=True,handoff_ready=True)
            lines.extend(['交接已就绪；当前进程退出后安装，尚未宣称安装完成。','最终结果：'+result['final_report']])
            code=0
    except Exception as error:
        if handoff is not None:cancel_handoff(handoff,str(error))
        result['error']=str(error);lines.append('更新失败：'+str(error));code=1
    result['exit_code']=code
    try:
        write_json(data_dir/'update-now.json',result)
        (data_dir/'_update.txt').write_text('\n'.join(lines)+'\n','utf8')
    except OSError:
        if handoff is not None:cancel_handoff(handoff,'更新报告写入失败')
        raise
    return code
