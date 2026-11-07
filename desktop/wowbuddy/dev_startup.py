"""独立入口启动取证桥；复用原日志格式、轮转和阶段记录。"""
import os
from pathlib import Path
import traceback
from .startup_log import open_local_startup_log,QT_READY,STYLE_READY
from .dev_native_commands import command_data_dir
from .dev_version import VERSION
from .dev_paths import default_data_dir

_active=None


def record(message):
    if _active is not None:_active.record(message)


def log_path():return _active.path if _active is not None else ''


def qt_ready():
    if _active is not None:
        try:_active.qt_environment()
        except Exception as error:record('Qt环境信息读取失败：'+str(error))
    record(QT_READY)


def prepare_qt_runtime(arguments):
    """原075960先构造Qt；使用Qt实际消费后的参数，不手写Qt选项表。"""
    from PySide6.QtWidgets import QApplication
    from .ui_layout import NATIVE_STYLESHEET
    record('main() 进入，准备构造 QApplication')
    if {'--desktop-selftest','--selftest-backends','--desktop-dump-ui'}.intersection(arguments[1:]):
        os.environ['QT_QPA_PLATFORM']='offscreen'
    app=QApplication.instance() or QApplication(list(arguments))
    qt_ready()
    app.setStyleSheet(NATIVE_STYLESHEET)
    record(STYLE_READY)
    app._wowbuddy_bootstrap_ready=True
    return app


def prepare_crash_runtime(arguments):
    return prepare_qt_runtime(arguments)


def run_logged(main,*,application,arguments,qt_runtime=False):
    global _active
    previous=_active;log=None;diagnostics=None
    directory=default_data_dir(application)
    try:
        try:
            directory=command_data_dir(arguments,directory)
            directory.mkdir(parents=True,exist_ok=True)
            # 仅已验证自有外层可改变默认位置；显式data-dir仍优先。
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
            # 日志单测等嵌入式调用可保持无Qt；真实可执行入口显式启用。
            # 目录更新辅助进程是独立扩展，不需要Qt窗口环境。
            use_qt=qt_runtime and not (len(arguments)==3 and arguments[1]=='--apply-client-update')
            qt_app=prepare_qt_runtime(arguments) if use_qt else None
            effective=tuple(qt_app.arguments()) if qt_app is not None else tuple(arguments)
            command=parse_native_cli(effective,native_arguments=arguments).command
            if command in ('crash_null','crash_throw'):
                from .crash_diagnostics import trigger_null_write,trigger_cpp_runtime_error
                crash_app=qt_app if qt_app is not None else prepare_crash_runtime(arguments)
                record('--crash-test：即将制造一次空指针解引用' if command=='crash_null'
                       else '--crash-test=throw：即将抛出未捕获异常')
                (trigger_null_write if command=='crash_null' else trigger_cpp_runtime_error)()
                raise RuntimeError('崩溃诊断意外返回')
            code=main(effective) if qt_runtime else main()
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
