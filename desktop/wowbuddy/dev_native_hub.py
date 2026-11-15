"""060ab0命令适配；不填充缓存，返回原规则可用性判定。"""
from pathlib import Path
from .cli_hub import run_local_hub_command
from .native_cli import parse_native_cli
from .dev_hub_online import HUB_URL,BackupHubFiles


def hub_command_result(data_dir,report_dir,*,fetch_online=False,fetch=None):
    """以独立环境（WOWBUDDY_HOME=data_dir、本工程循环库地址）执行原 --hub-selftest，可选 --hub-fetch。

    不继承历史 WOWBUDDY_HOME 或服务器地址；联网时按需建立 QCoreApplication 并在执行期间保持引用。
    """
    data_dir=Path(data_dir).resolve()
    arguments=['WowBuddyDev','--hub-selftest']
    app=None
    if fetch_online:
        from PySide6.QtCore import QCoreApplication
        app=QCoreApplication.instance() or QCoreApplication(['WowBuddyDev'])
        arguments.append('--hub-fetch')
    return run_local_hub_command(parse_native_cli(arguments),files=BackupHubFiles(),fetch=fetch,
        application_dir=report_dir,
        environment={'WOWBUDDY_HOME':str(data_dir),'WOWBUDDY_HUB_URL':HUB_URL})


def run_native_hub(data_dir,report_dir,*,fetch_online=False,fetch=None):
    return hub_command_result(data_dir,report_dir,fetch_online=fetch_online,fetch=fetch).exit_code
