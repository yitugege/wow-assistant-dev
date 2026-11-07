"""源码桌面入口及不访问真实桌面的离屏启动核验。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


class NoSystemBackend:
    """仅用于--selftest-ui；任何意外系统操作都使自测失败。"""
    dxgi = None
    def enum_windows(self, visitor): pass
    def current_pid(self): return 0
    def is_window(self, hwnd): return False
    def capture(self, hwnd): raise AssertionError("离屏自测不应抓屏")
    def __getattr__(self, name):
        raise AssertionError(f"离屏自测不应调用系统后端：{name}")


def source_handoff():
    """冻结源码程序只为自身或经核验的源码外层建立更新范围。"""
    if not getattr(sys, "frozen", False):
        return None
    from .update_handoff import QtWin32HandoffBackend, TestProgramScope
    from .release_identity import validated_outer_target
    outer = validated_outer_target(os.environ.get("WOWBUDDY_EXE", ""), Path(sys.executable))
    target = outer or Path(sys.executable)
    return QtWin32HandoffBackend(TestProgramScope(str(target.parent), str(target)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="WOW战斗助手独立源码本地测试版", allow_abbrev=False)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--settings-file", type=Path)
    parser.add_argument("--offline", action="store_true", help="本地测试差异：不联网刷新循环库")
    parser.add_argument("--no-auto", action="store_true", help="本地测试差异：不自动寻找游戏窗口")
    parser.add_argument("--no-stealth", action="store_true", help="原版参数：不设置随机原生窗口标题和工具窗样式")
    parser.add_argument("--selftest-ui", action="store_true", help="离屏启动，不读注册表/真实窗口或发送按键")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--render", type=Path)
    raw_arguments = [sys.argv[0], *(argv if argv is not None else sys.argv[1:])]
    args, qt_tail = parser.parse_known_args(raw_arguments[1:])
    from .startup_log import open_local_startup_log, MAIN_ENTER
    from .updater import CURRENT_VERSION
    temporary = TemporaryDirectory(prefix="wowbuddy-ui-test-") if args.selftest_ui else None
    log_environment = dict(os.environ)
    if temporary or args.home:
        log_environment["WOWBUDDY_HOME"] = temporary.name if temporary else str(args.home)
    log = diagnostics = None
    try:
        log = open_local_startup_log(CURRENT_VERSION, environment=log_environment,
                                    environment_fields=[] if args.selftest_ui else None)
        if not args.selftest_ui:
            from .crash_diagnostics import CurrentProcessDiagnostics
            diagnostics = CurrentProcessDiagnostics(log).install()
            log.exception_handlers_installed = True
        log.record(MAIN_ENTER)
        result = _run(args, qt_tail, raw_arguments, log, temporary)
        log.finish(result)
        return result
    except Exception:
        if diagnostics is not None and diagnostics.installed:
            diagnostics.state.python_exception(*sys.exc_info())
        raise
    finally:
        if diagnostics is not None:
            diagnostics.close()
        if log is not None:
            log.close()
        if temporary:
            temporary.cleanup()


def _run(args, qt_tail, raw_arguments, log, temporary):
    if args.selftest_ui:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QTimer, qVersion
    from PySide6.QtWidgets import QApplication, QWidget
    from .settings import open_test_settings, open_ini_settings
    from .qt_app import AssistantWindow
    from .native_cli import parse_native_cli

    app = QApplication.instance()
    if app is None:
        app = QApplication([raw_arguments[0], *qt_tail])
        qt_arguments = app.arguments()
    else:
        # 嵌入调用已有QApplication时不能重新让Qt消费参数。
        qt_arguments = [raw_arguments[0], *qt_tail]
    from .startup_log import QT_READY, STYLE_READY
    from .ui_layout import NATIVE_STYLESHEET
    log.qt_environment()
    log.record(QT_READY)
    app.setApplicationName("WOW战斗助手-重建本地测试")
    app.setOrganizationName("wowbuddy.cn")
    app.setStyleSheet(NATIVE_STYLESHEET)
    log.record(STYLE_READY)
    native = parse_native_cli(qt_arguments, native_arguments=raw_arguments)
    if native.command not in ("gui", "install_addon", "check_update", "update_now", "hub_selftest",
                              "crash_null", "crash_throw", "selftest"):
        command = native.command if native.command != "gui" else "dump_ui"
        print(f"源码重建尚未接入此原生执行入口：{command}", file=sys.stderr)
        return 2
    if args.selftest_ui and native.command != "gui":
        print("离屏UI自测不能同时执行独立原生命令", file=sys.stderr)
        return 2
    if native.command == "crash_null":
        from .crash_diagnostics import trigger_null_write
        log.record("--crash-test：即将制造一次空指针解引用")
        trigger_null_write()
    if native.command == "crash_throw":
        from .crash_diagnostics import trigger_cpp_runtime_error
        log.record("--crash-test=throw：即将抛出未捕获异常")
        trigger_cpp_runtime_error()

    frozen = getattr(sys, "frozen", False)
    application_dir = Path(sys.executable).parent if frozen else Path(__file__).resolve().parents[1]
    default_assets = (Path(sys._MEIPASS) / "assets" if frozen
                      else Path(__file__).resolve().parents[2] / "unpacked")
    if frozen and (application_dir / "contract.json").is_file():
        # 完整发布包沿原生appDir读取旁置资源；缺项/损坏须报错，不能混用旧内嵌表。
        default_assets = application_dir
    if native.command == "selftest":
        from .cli_selftest import run_local_selftest_command
        # 源码及单文件包有明确资源目录；完整发布包保持原版五处查找。
        resources = args.assets or (default_assets if default_assets != application_dir else None)
        return run_local_selftest_command(qt_arguments,application_dir=application_dir,
                                          resource_dir=resources).exit_code
    if native.command in ("check_update", "update_now"):
        from .cli_update import run_local_update_command
        return run_local_update_command(native, application_dir=application_dir,
            application_arguments=qt_arguments, handoff=source_handoff()).exit_code
    if native.command == "hub_selftest":
        from .cli_hub import run_local_hub_command
        cli_environment = {**os.environ, **({"WOWBUDDY_HOME": str(args.home)} if args.home else {})}
        return run_local_hub_command(native, application_dir=application_dir,
                                     environment=cli_environment).exit_code
    if native.command == "install_addon":
        # CLI只需要插件包；不能因无关JSON缺失而提前改变原生退出码。
        if frozen and default_assets != application_dir:
            try:
                with (application_dir / "addon.bin").open("xb") as destination:
                    destination.write(((args.assets or default_assets) / "addon.bin").read_bytes())
            except FileExistsError:
                pass
        from .cli_install import run_local_install_command
        cli_settings = open_ini_settings(str(args.settings_file)) if args.settings_file else None
        return run_local_install_command(native, application_dir=application_dir,
                                         settings=cli_settings).exit_code
    resource_directory = args.assets or default_assets
    if args.selftest_ui:
        # Windows offscreen插件不枚举系统字体；只为渲染核验显式加载本机字体。
        # 不复制或随EXE分发字体，正常qwindows平台仍使用系统字体发现。
        from PySide6.QtGui import QFontDatabase, QFont
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "msyh.ttc", "msyhbd.ttc", "consola.ttf"):
            path = fonts / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
        app.setFont(QFont("Microsoft YaHei", 9))
    home = (Path(temporary.name) if temporary else args.home or
            Path(os.environ.get("WOWBUDDY_HOME", str(application_dir / "runtime-source-local-test"))))
    home.mkdir(parents=True, exist_ok=True)
    settings_path = home / "selftest.ini" if args.selftest_ui else args.settings_file
    settings = open_ini_settings(str(settings_path)) if settings_path else open_test_settings()
    if args.selftest_ui:
        windows = NoSystemBackend()
    else:
        from .game_windows import CtypesWindowBackend
        windows = CtypesWindowBackend()
    from .native_assets import NativeAssetStore
    from .startup_stages import ResourceStageLoader, find_resource
    from .game_windows import find_game_window
    from .qt_startup import QtStartup
    from .startup_splash import NeonSplash
    store = NativeAssetStore()
    def resolve_resource(name):
        from PySide6.QtCore import QFileInfo
        if args.assets is not None:
            path = QFileInfo(str(args.assets / name))
            return path.absoluteFilePath() if path.exists() else ""
        found = find_resource(name, application_dir=str(application_dir), current_dir=str(Path.cwd()))
        if found:
            return found
        # 仅源码运行/单文件内层扩展：无外部原路径时使用明确随包资源。
        path = QFileInfo(str(default_assets / name))
        return path.absoluteFilePath() if path.exists() else ""
    loader = ResourceStageLoader(resolve=resolve_resource,
        load_contract=store.load_contract,load_rules=store.load_rules,
        load_readable_contract=store.load_readable_contract,load_readable_rules=store.load_readable_rules,
        find_game_window=lambda:find_game_window(windows,on_diagnostic=log.record))
    window = assets = None
    def construct_main():
        nonlocal window, assets
        assets = store.to_assets(resource_directory)
        if not args.selftest_ui:
            addon_source = assets.directory / "addon.bin"
            if addon_source.is_file():
                # 初始包释放是单文件重建扩展；不覆盖热更文件，不要求包存在才能启动。
                try:
                    with (application_dir / "addon.bin").open("xb") as destination:
                        destination.write(addon_source.read_bytes())
                except FileExistsError:
                    pass
        handoff = identity = None
        if args.selftest_ui:
            capture = keys = windows
        else:
            from .capture import make_win32_capture
            from .windows_keys import CtypesWin32Backend
            from .window_identity import NativeWindowIdentity
            capture, keys = make_win32_capture(), CtypesWin32Backend()
            identity = NativeWindowIdentity(native.native_title_enabled)
            if frozen:
                handoff = source_handoff()
        window = AssistantWindow(assets, settings, window_backend=windows, capture=capture,
            key_backend=keys, application_dir=application_dir,
            environment={**os.environ, "WOWBUDDY_HOME": str(home),
                         **({"WOWBUDDY_NO_GAME_SCAN": ""} if args.selftest_ui else {})},
            network_enabled=not (args.offline or args.selftest_ui),
            automatic=not (args.no_auto or args.selftest_ui), tray_enabled=not args.selftest_ui,
            update_handoff=handoff, application_arguments=qt_arguments,
            native_window_identity=identity,startup_record=log.record,startup_log_path=log.path)
        return window
    dump_runner = dump_delay = None
    def after_main(shown_window):
        nonlocal dump_runner, dump_delay
        if native.dump_ui is not None:
            from .cli_dump_ui import make_runner_for_window
            dump_runner = make_runner_for_window(shown_window, qt_arguments,
                application_dir=home if args.selftest_ui else application_dir)
            dump_delay = QTimer(shown_window)
            dump_delay.setSingleShot(True)
            dump_delay.timeout.connect(dump_runner.start)
            dump_delay.start(2600)
        if args.selftest_ui:
            QTimer.singleShot(3500 if dump_runner is not None else 100, shown_window, finish)
    test_errors = []
    original_hook = sys.excepthook
    if args.selftest_ui:
        def qt_error(kind, value, traceback):
            test_errors.append(f"{kind.__name__}: {value}")
            original_hook(kind, value, traceback)
        sys.excepthook = qt_error
        def finish():
            try:
                report = {"schema": "wowbuddy-source-ui-smoke-v1", "qt_version": qVersion(),
                    "source_business_logic": True, "original_business_executable_loaded": False,
                    "real_system_backends_created": False,
                    "full_reconstruction_complete": False,
                    "size": [window.width(), window.height()],
                    "widgets": len(window.findChildren(QWidget)),
                    "poll_interval_ms": window.ui.poll_interval_spin.value(),
                    "send_interval_ms": window.ui.send_interval_spin.value(),
                    "monitor_active": window.session.is_active(),
                    "window_count": window.ui.window_combo.count()}
                report["runtime_executable"] = sys.executable
                report["process_id"] = os.getpid()
                report["working_directory"] = str(Path.cwd())
                report["application_directory"] = str(application_dir)
                report["assets_directory"] = str(assets.directory)
                report["launcher_home"] = os.environ.get("WOWBUDDY_HOME")
                report["launcher_executable"] = os.environ.get("WOWBUDDY_EXE")
                report["startup_phase"] = startup.stages.phase
                report["startup_warning"] = loader.warning
                report["startup_stage_index"] = startup.stages.index
                report["resource_paths"] = loader.paths
                report["resource_valid"] = {name:getattr(store,name).valid for name in
                    ("contract","rules","readable_contract","readable_rules")}
                if dump_runner is not None:
                    report["native_ui_dump_written"] = dump_runner.report_written
                    report["native_ui_dump"] = (home / "_ui.txt").read_text(encoding="utf-8")
                    if native.dump_ui.toggle_showall:
                        report["native_showall_dump"] = (home / "_showall.txt").read_text(encoding="utf-8")
                    if dump_runner.report_written is not True:
                        raise AssertionError("原生UI诊断尚未完成")
                if args.render:
                    args.render.parent.mkdir(parents=True, exist_ok=True)
                    if not window.grab().save(str(args.render)):
                        raise OSError(f"渲染保存失败：{args.render}")
                window.close()
                report["passed"] = not test_errors
                if args.report:
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(report, ensure_ascii=True))
            except Exception as exc:
                test_errors.append(str(exc))
                print(str(exc), file=sys.stderr)
            finally:
                app.quit()
    splash = NeonSplash()
    def cleanup_after_authorization():
        if frozen and not args.selftest_ui:
            from .cache_cleanup_host import cleanup_source_release
            cleanup_source_release(Path(sys.executable),os.environ.get("WOWBUDDY_EXE",""),record=log.record)
    startup = QtStartup(app,splash,loader,construct_main=construct_main,record=log.record,
        after_main=after_main,auto_start=native.auto_start and not args.selftest_ui,
        after_authorization=cleanup_after_authorization)
    startup.start()
    result = app.exec()
    startup.close()
    if dump_delay is not None:
        dump_delay.stop()
        dump_runner.close()
    if window is not None:
        window.shutdown()
    sys.excepthook = original_hook
    return 1 if test_errors else result


if __name__ == "__main__":
    raise SystemExit(main())
