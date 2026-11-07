"""原 --selftest 命令适配；GUI构建自检使用单独参数。"""
from pathlib import Path
from .cli_selftest import run_local_selftest_command
from .native_assets import read_qt_json


def run_native_selftest(assets_dir,output_dir,arguments):
    assets_dir=Path(assets_dir)
    # 资源键顺序用于确定性输出，不冒充原Qt进程的QHash遍历顺序。
    rules=read_qt_json(str(assets_dir/'rules.json')).document
    if not isinstance(rules,dict):rules={}
    order=tuple(rules.get('specs',{}))
    return run_local_selftest_command(arguments,application_dir=output_dir,
        current_dir=Path.cwd(),resource_dir=assets_dir,spec_order=order).exit_code
