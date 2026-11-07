"""060ab0命令适配；不填充缓存，返回原规则可用性判定。"""
from pathlib import Path
from .cli_hub import run_local_hub_command
from .native_cli import parse_native_cli
from .dev_hub_online import HUB_URL,BackupHubFiles


def run_native_hub(data_dir,report_dir,*,fetch_online=False,fetch=None):
    data_dir=Path(data_dir).resolve()
    arguments=['WowBuddyDev','--hub-selftest']
    if fetch_online:
        from PySide6.QtCore import QCoreApplication
        app=QCoreApplication.instance() or QCoreApplication(['WowBuddyDev'])
        arguments.append('--hub-fetch')
    result=run_local_hub_command(parse_native_cli(arguments),files=BackupHubFiles(),fetch=fetch,
        application_dir=report_dir,
        environment={'WOWBUDDY_HOME':str(data_dir),'WOWBUDDY_HUB_URL':HUB_URL})
    return result.exit_code
