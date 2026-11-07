"""将0624b0命令编排接到独立ZIP安装器；不创建主窗或抓屏/发键后端。"""
from pathlib import Path
import os
import sys
from zipfile import BadZipFile
from .cli_install import (AddonPreparation,CliAddonInstallOutcome,run_install_command,
                          write_local_report)
from .dev_addon_install import read_package,install_addons_directory
from .native_cli import parse_native_cli


def run_development_install(arguments,package,data_dir,*,detect=None):
    package=Path(package);data_dir=Path(data_dir)
    data_dir.mkdir(parents=True,exist_ok=True)
    if detect is None:
        def detect():
            if 'WOWBUDDY_NO_GAME_SCAN' in os.environ:
                return ()
            from .addon_games import selected_executable
            from .dev_game_paths import discover_clients,common_roots
            from types import SimpleNamespace
            from .game_windows import CtypesWindowBackend
            from .settings import open_ini_settings
            settings=open_ini_settings(str(data_dir/'settings.ini'))
            paths=discover_clients(settings,running_executable=selected_executable(CtypesWindowBackend()),
                                   search_roots=common_roots(),environment=os.environ)
            return tuple(SimpleNamespace(addons_path=str(p/'Interface/AddOns')) for p in paths)
    def prepare():
        try:
            read_package(package)
            return AddonPreparation(True)
        except (OSError,ValueError,KeyError,BadZipFile) as error:
            return AddonPreparation(False,str(error))
    def install(target):
        try:
            result=install_addons_directory(package,target)
            detail=f"已写入 {result['files']} 个文件 → {result['target']}\n"
            if result['backup']:detail+=f"旧开发插件备份：{result['backup']}\n"
            detail+=f"清理旧目录：{result['cleanup_deleted']} 个\n{result['cleanup_notes']}\n"
            return CliAddonInstallOutcome(True,result['addon_directory'],detail)
        except (OSError,ValueError,KeyError,BadZipFile) as error:
            return CliAddonInstallOutcome(False,error=str(error))
    def warn(text):
        if sys.stderr is not None:print(text,file=sys.stderr)
    result=run_install_command(parse_native_cli(arguments),application_dir=data_dir,
        detect=detect,prepare=prepare,install=install,write_report=write_local_report,warn=warn)
    if result.report_text and sys.stdout is not None:print(result.report_text)
    return result.exit_code
