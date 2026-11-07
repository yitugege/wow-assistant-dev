"""原早期命令分支的执行桥；先选命令，再处理独立data-dir扩展。"""
from pathlib import Path
from .native_cli import parse_native_cli


def command_data_dir(arguments,default):
    value=Path(default)
    for index,arg in enumerate(arguments[1:],1):
        if arg.startswith('--data-dir='):value=Path(arg.split('=',1)[1])
        elif arg=='--data-dir':
            if index+1>=len(arguments):raise ValueError('--data-dir缺少路径')
            value=Path(arguments[index+1])
    return value


def dispatch_native_command(arguments,*,assets,application,packages,frozen):
    options=parse_native_cli(arguments)
    if options.command not in ('selftest','install_addon','check_update','update_now','hub_selftest'):
        return None
    default=application if options.command=='selftest' else Path(application)/'.local'
    data=command_data_dir(arguments,default)
    data.mkdir(parents=True,exist_ok=True)
    if options.command=='selftest':
        from .dev_native_selftest import run_native_selftest
        return run_native_selftest(assets,data,arguments)
    if options.command=='install_addon':
        from .dev_cli_install import run_development_install
        package=Path(packages)/'WowBuddyDev-addon.zip'
        if not package.exists():package=Path(packages)/'WowBuddyDev-dev.zip'
        return run_development_install(arguments,package,data)
    if options.command=='check_update':
        from .github_client import run_check_command
        return run_check_command(data)
    if options.command=='update_now':
        from .dev_cli_update import run_update_now
        return run_update_now(data,application,arguments[1:],frozen=frozen)
    from .dev_native_hub import run_native_hub
    return run_native_hub(data,command_data_dir(arguments,application),fetch_online=options.hub_fetch)
