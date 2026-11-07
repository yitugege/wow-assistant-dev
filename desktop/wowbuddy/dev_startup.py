"""独立入口启动取证桥；复用原日志格式、轮转和阶段记录。"""
import os
from pathlib import Path
import traceback
from .startup_log import open_local_startup_log,QT_READY,STYLE_READY
from .dev_native_commands import command_data_dir
from .dev_version import VERSION

_active=None


def record(message):
    if _active is not None:_active.record(message)


def log_path():return _active.path if _active is not None else ''


def qt_ready():
    record(QT_READY)
    if _active is not None:
        try:_active.qt_environment()
        except Exception as error:record('Qt环境信息读取失败：'+str(error))


def run_logged(main,*,application,arguments):
    global _active
    previous=_active;log=None;diagnostics=None
    directory=Path(application)/'.local'
    try:
        try:
            directory=command_data_dir(arguments,directory)
            directory.mkdir(parents=True,exist_ok=True)
            # 不继承旧产品HOME或LOCALAPPDATA位置，避免混写原程序日志。
            log=open_local_startup_log(VERSION,executable=str(Path(application)/Path(arguments[0]).name),
                environment={'WOWBUDDY_HOME':str(directory)},
                environment_fields=(('进程ID',str(os.getpid())),('独立程序目录',str(application))))
        except (OSError,ValueError):pass
        _active=log
        if log is not None and os.name=='nt':
            try:
                from .crash_diagnostics import CurrentProcessDiagnostics
                diagnostics=CurrentProcessDiagnostics(log).install()
                record('当前进程SEH/CRT异常处理器已注册')
            except (OSError,AttributeError) as error:
                record('原生异常处理器注册失败：'+str(error))
        record('main() 进入，准备分派独立入口')
        try:
            from .native_cli import parse_native_cli
            command=parse_native_cli(arguments).command
            if command in ('crash_null','crash_throw'):
                from .crash_diagnostics import trigger_null_write,trigger_cpp_runtime_error
                record('执行显式崩溃诊断：'+command)
                (trigger_null_write if command=='crash_null' else trigger_cpp_runtime_error)()
                raise RuntimeError('崩溃诊断意外返回')
            code=main()
        except SystemExit as exit_status:
            code=exit_status.code if isinstance(exit_status.code,int) else (0 if exit_status.code is None else 1)
        except Exception:
            detail=traceback.format_exc()
            if log is not None:log.write_event('异常',detail)
            try:(directory/'startup-error.log').write_text(detail,'utf8')
            except OSError:pass
            record('独立入口因Python异常退出，返回码 1')
            return 1
        if log is not None:log.finish(code)
        return code
    finally:
        if diagnostics is not None:diagnostics.close()
        _active=previous
        if log is not None:log.close()
