"""跨退出保存交接任务位置，下一次启动只展示已落盘的实际结果。"""
import json
import os
from pathlib import Path
from .dev_update_handoff import write_json,cancel_handoff

PENDING='client-update-pending.json'


def remember_handoff(data_dir,current,handoff):
    try:
        write_json(Path(data_dir)/PENDING,{'job':str(Path(handoff['job']).absolute()),
                   'current':str(Path(current).absolute())})
    except OSError:
        cancel_handoff(handoff,'无法保存下次启动的更新结果位置')
        raise


def poll_notice(data_dir,current):
    marker=Path(data_dir)/PENDING
    if not marker.exists():return None
    try:
        pending=json.loads(marker.read_text('utf8'))
        same=lambda p:os.path.normcase(os.path.abspath(p))==os.path.normcase(os.path.abspath(current))
        if not same(pending['current']):raise ValueError('更新记录不属于当前客户端')
        job=Path(pending['job'])
        task=json.loads(job.read_text('utf8'))
        if task.get('product')!='wowbuddy-update-job' or not same(task['current']):
            raise ValueError('更新交接任务身份不匹配')
        report=job.with_suffix('.result.json')
        if not report.exists():return {'complete':False,'text':'正在等待上次更新交接的最终结果…'}
        result=json.loads(report.read_text('utf8'))
        if not isinstance(result.get('ok'),bool) or not isinstance(result.get('replaced'),bool):
            raise ValueError('更新结果缺少有效完成状态')
        if not result['ok']:
            text=('新版文件已换入，但后续交接失败：' if result['replaced'] else '上次客户端更新未完成：')+str(result.get('error','未提供错误原因'))
        elif result['replaced']:
            text='上次客户端更新已完成目录替换。'
            text+=' 已发起新版重启。' if result.get('restarted') else ' 未自动重启。'
        else:raise ValueError('更新结果声称成功，但未确认目录替换')
        if result.get('backup'):text+=' 旧版备份：'+str(result['backup'])
        notice={'complete':True,'text':text,'result':result,'report':str(report)}
        write_json(Path(data_dir)/'client-update-last-result.json',notice)
        marker.unlink()
        return notice
    except (OSError,ValueError,KeyError,TypeError) as error:
        return {'complete':True,'text':'无法读取上次更新结果：'+str(error)}
