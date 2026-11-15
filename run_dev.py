"""自有工程桌面入口：独立INI、本地资源、无旧更新服务器。"""
import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, 'frozen', False))
APP_ROOT = Path(sys.executable).resolve().parent if FROZEN else ROOT
PACKAGE_DIR = APP_ROOT/'packages' if FROZEN else ROOT/'dist'
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.dev_startup import record as startup_record
from wowbuddy.dev_paths import default_data_dir


def launch(data_dir, *, selftest=False, real_backends=False, auto_start=False, watch=False, dump_ui=None,
           hub_online=True, client_online=True, addon_online=True, no_update=False, staged=False,
           native_dump=None, auto_leveling=False, auto_revive=False,
           auto_navigate=False, auto_grind=False):
    if selftest and (auto_start or watch):
        raise ValueError('自检不能同时自动开始监控')
    if dump_ui is not None and (selftest or auto_start or watch):
        raise ValueError('界面诊断不能与自检或自动监控同时使用')
    if selftest or dump_ui is not None:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    from wowbuddy.engine.assets import Assets
    from wowbuddy.settings import open_ini_settings
    from wowbuddy.app.ui_layout import NATIVE_STYLESHEET
    from wowbuddy.dev_library import seed_library, profile_action_gaps
    from wowbuddy.app.dev_window import DevLaunchOptions, DevWindow


    startup_record('复用已初始化的 QApplication' if QApplication.instance() is not None else '准备构造 QApplication')
    app = QApplication.instance() or QApplication(['WowBuddyDev'])
    from wowbuddy.dev_startup import qt_ready,log_path,STYLE_READY
    if not getattr(app,'_wowbuddy_bootstrap_ready',False):
        qt_ready()
        app.setStyleSheet(NATIVE_STYLESHEET + '\nQInputDialog { background-color: #111724; }\n')
        startup_record(STYLE_READY)
        app._wowbuddy_bootstrap_ready=True
    app.setApplicationName('WowBuddyDev')
    from wowbuddy.dev_version import VERSION
    app.setApplicationVersion(VERSION)
    startup_record(f'独立助手版本 v{VERSION}')
    app.setOrganizationName('WowBuddyDev')
    if (selftest and not real_backends) or dump_ui is not None:
        from wowbuddy.desktop import NoSystemBackend
        windows = capture = keys = NoSystemBackend()
    else:
        from wowbuddy.win32.game_windows import CtypesWindowBackend
        from wowbuddy.dev_game_windows import AssistantWindowFilter
        from wowbuddy.win32.capture import make_win32_capture
        from wowbuddy.win32.windows_keys import CtypesWin32Backend
        windows = AssistantWindowFilter(CtypesWindowBackend(),current_executable=sys.executable if FROZEN else None)
        capture, keys = make_win32_capture(), CtypesWin32Backend()
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_library(ROOT/'assets', data_dir)
    startup_record('独立循环库种子快照就绪')
    settings = open_ini_settings(str(data_dir/'settings.ini'))
    def construct_window(assets):
        options = DevLaunchOptions(data_dir=data_dir, app_root=APP_ROOT, package_dir=PACKAGE_DIR, frozen=FROZEN,
            selftest=selftest, dump_ui=dump_ui, auto_leveling=auto_leveling, auto_revive=auto_revive,
            auto_navigate=auto_navigate, auto_grind=auto_grind)
        window = DevWindow(assets, settings, launch_options=options,
            window_backend=windows, capture=capture, key_backend=keys,
            application_dir=data_dir, environment={'WOWBUDDY_HOME':str(data_dir),'WOWBUDDY_NO_GAME_SCAN':''},
            network_enabled=False, automatic=watch, tray_enabled=False, game_windows_only=True,
            startup_record=startup_record,startup_log_path=log_path())
        startup_record('独立主窗口构造完成')
        from wowbuddy.release_identity import validated_outer_target
        window._outer_update_target=(validated_outer_target(os.environ.get('WOWBUDDY_EXE',''),Path(sys.executable))
                                     if FROZEN else None)
        from wowbuddy.update.github_addon import REPOSITORY
        project_url='https://github.com/'+REPOSITORY
        window.setWindowTitle(f'WowBuddyDev v{VERSION} — 独立开发版')
        window.ui.title_label.setText(f'WowBuddyDev v{VERSION}')
        window.ui.website_button.setText('GitHub 项目')
        window.ui.website_button.setToolTip('打开 '+project_url)
        window.shell.website_url=project_url
        window._configure_automatic_client_update(client_online and not selftest and dump_ui is None,no_update)
        configure_addon_refresh = addon_online and not selftest and dump_ui is None
        allow_addon_refresh = configure_addon_refresh and settings.automatic_addon_update_enabled()
        window._configure_addon_refresh(allow_addon_refresh)
        if configure_addon_refresh and not allow_addon_refresh:
            startup_record('已关闭 GitHub 插件自动更新，保留当前安装版本')
        window.ui.update_status.setText(f'当前 v{VERSION} · GitHub 客户端更新')
        if not selftest and dump_ui is None:window._restore_update_notice()
        if hub_online and not selftest and dump_ui is None:
            from wowbuddy.qt_network import QtHubClient
            from wowbuddy.dev_hub_online import BackupHubFiles
            window.hub.files=BackupHubFiles()
            window.hub_client=QtHubClient(window.hub,window)
            window.ui.hub_online_button.setVisible(True)
            window.ui.hub_online_button.setToolTip('从自有GitHub仓库刷新；替换前快照备份在 hub/backups 中。')
            window.ui.hub_online_button.clicked.connect(window._refresh_online_library)
            window._refresh_online_library()
            window.hub_timer.start()
        return window

    def after_main(window):
        if native_dump is not None:
            from wowbuddy.dev_dump_ui import NativeDumpSession
            options,output_dir=native_dump
            window._native_dump_session=NativeDumpSession(window,options,output_dir)

    if staged and not selftest and dump_ui is None:
        from wowbuddy.dev_staged_startup import create_staged_startup
        def cleanup_after_authorization():
            if FROZEN:
                from wowbuddy.cache_cleanup_host import cleanup_source_release
                cleanup_source_release(Path(sys.executable),os.environ.get('WOWBUDDY_EXE',''),record=startup_record)
        startup=create_staged_startup(app,ROOT/'assets',windows,construct_window,startup_record,
            auto_start=auto_start,after_main=after_main,after_authorization=cleanup_after_authorization)
        try:
            startup.start()
            return app.exec()
        finally:
            startup.close()
            if startup.stages.main_window is not None:
                startup.stages.main_window.shutdown()
                startup.stages.main_window.close()
            else:
                startup.splash.close()
                startup.splash.deleteLater()

    startup_record('准备加载契约和规则资源')
    assets=Assets.load(ROOT/'assets')
    startup_record('契约和规则资源加载完成，准备构造主窗口')
    window=construct_window(assets)
    window.show()
    startup_record('独立主窗口已显示')
    after_main(window)
    if dump_ui is not None:
        from wowbuddy.dev_dump_ui import run_dump
        try:
            return run_dump(app, window, dump_ui, data_dir)
        finally:
            window.shutdown()
            window.close()
    if selftest:
        app.processEvents()
        gap_profile = next((p for p in window.controller.hub.profiles
                            if profile_action_gaps(p, window.pipeline.engine.document, window.assets.readable_rules)), None)
        warning_verified = gap_profile is None
        if gap_profile is not None:
            window.controller.select(gap_profile.key)
            window._render_hub_status()
            warning_verified = ('部分动作未注册' in window.ui.hub_status.text()
                                and all(name in window.ui.hub_status.toolTip() for name in
                                        profile_action_gaps(gap_profile, window.pipeline.engine.document, window.assets.readable_rules)))
            complete_profile = next(p for p in window.controller.hub.profiles
                                    if not profile_action_gaps(p, window.pipeline.engine.document, window.assets.readable_rules))
            window.controller.select(complete_profile.key)
            window._render_hub_status()
            warning_verified = warning_verified and window.ui.hub_status.toolTip() == ''
        local_path = data_dir/'hub/rotations.json'
        local_payload = json.loads(local_path.read_text('utf8'))
        local_payload['rotations'][0]['rules'][0]['reason'] = '自检本地重载'
        local_path.write_text(json.dumps(local_payload,ensure_ascii=False),'utf8')
        window.ui.hub_pull_button.click()
        reload_verified = window.controller.hub.profiles[0].rules[0].reason == '自检本地重载'
        retained_hub = window.controller.hub
        local_path.write_text('{broken','utf8')
        window.ui.hub_pull_button.click()
        reload_verified = reload_verified and window.controller.hub is retained_hub
        report = {
            'title':window.windowTitle(),
            'settings_file':settings.qsettings.fileName(),
            'assets':str(window.assets.directory),
            'plugin_package':str(PACKAGE_DIR/'WowBuddyDev-dev.zip'),
            'plugin_package_present':(PACKAGE_DIR/'WowBuddyDev-dev.zip').is_file(),
            'frozen':FROZEN,
            'local_profiles':len(window.controller.hub.profiles),
            'profile_warning_verified':warning_verified,
            'local_reload_verified':reload_verified,
            'network_clients_absent':all(x is None for x in (window.update_client,window.addon_update_client,window.hub_client)),
            'monitor_active':window.session.is_active(),
            'watch_timer_active':window.watch_timer.isActive(),
            'legacy_installer_disconnected':window.addons is None,
            'real_system_backends_created':real_backends,
            'backend_types':{'windows':type(windows).__name__,
                             'capture':type(capture).__name__, 'keys':type(keys).__name__},
        }
        report['passed'] = report['network_clients_absent'] and not report['monitor_active'] and not report['watch_timer_active'] and report['legacy_installer_disconnected'] and report['local_profiles'] > 0 and warning_verified and reload_verified
        window.close()
        app.processEvents()
        report['window_closed']=window._closed
        return report
    try:
        if auto_start:
            window.auto_start_once()
        return app.exec()
    finally:
        window.shutdown()


def main(arguments=None, *, native_arguments=None):
    arguments=list(sys.argv if arguments is None else arguments)
    if len(arguments)==3 and arguments[1]=='--apply-client-update':
        if not FROZEN:return 2
        from wowbuddy.update.dev_update_handoff import run_handoff
        return run_handoff(arguments[2])
    from wowbuddy.dev_native_commands import dispatch_native_command
    native_result=dispatch_native_command(arguments,assets=ROOT/'assets',application=APP_ROOT,packages=PACKAGE_DIR,frozen=FROZEN)
    if native_result is not None:return native_result
    parser=argparse.ArgumentParser(description='WowBuddyDev源码开发入口',allow_abbrev=False)
    parser.add_argument('--selftest', action='store_true',help='运行原引擎自检并追加_selftest.txt，不启动GUI')
    parser.add_argument('--desktop-selftest',action='store_true',help='独立离屏GUI构建自检')
    parser.add_argument('--selftest-backends', action='store_true',
                        help='验证真实Win32后端构造及GUI关闭，不开始监控或发键')
    parser.add_argument('--data-dir',type=Path,default=default_data_dir(APP_ROOT,frozen=FROZEN))
    parser.add_argument('--auto',action='store_true',help='界面初始化后尝试一次开始监控')
    watch_options=parser.add_mutually_exclusive_group()
    watch_options.add_argument('--watch',action='store_true',help='显式启用默认的5秒游戏窗口自动监视')
    watch_options.add_argument('--no-watch',action='store_true',help='本次启动不自动连接游戏窗口，改为手动开始监控')
    parser.add_argument('--install-addon',action='store_true',help='无主窗安装自有插件包并退出')
    parser.add_argument('--install-addon-dir',default=None,help='直接安装目标目录，原版格式为 --install-addon-dir=路径')
    parser.add_argument('--dump-ui',action='store_true',help='普通GUI启动后延迟写原界面报告，保持运行')
    parser.add_argument('--desktop-dump-ui',dest='dump_ui',action='store_true',help='独立离屏导出界面诊断并退出')
    parser.add_argument('--hub-selftest',action='store_true',help='按原语义检查现有循环库并写_hub.txt，默认不联网')
    parser.add_argument('--desktop-hub-selftest',action='store_true',help='独立循环库增强诊断：填充初始库、检查动作并输出JSON')
    parser.add_argument('--hub-fetch',action='store_true',help='与 --hub-selftest 合用，从自有GitHub拉取循环库')
    parser.add_argument('--engine-selftest',action='store_true',help='运行原引擎离线自检并记录失败/跳过计数')
    parser.add_argument('--export-diagnostics',action='store_true',
                        help='把日志、诊断文件与游戏中本插件的SavedVariables打包到 数据目录/diagnostics，结果写 diagnostics-export.json')
    parser.add_argument('--leveling-next',action='store_true',help='联网查找无限版下一处练级据点，写入 leveling-next.json')
    parser.add_argument('--auto-leveling',action='store_true',help='监控中根据游戏状态自动联网查询练级点，写入 leveling-auto.json')
    parser.add_argument('--auto-revive',action='store_true',help='在前台游戏监控中处理暴雪的释放灵魂与尸体复活弹窗')
    parser.add_argument('--auto-navigate',action='store_true',help='向同一地图的尸体或已选练级点移动')
    parser.add_argument('--auto-grind',action='store_true',help='本次启动勾选无人托管')
    parser.add_argument('--faction',choices=('alliance','horde'),help='练级查询的阵营')
    parser.add_argument('--level',type=int,help='练级查询的角色等级')
    parser.add_argument('--zone',help='练级查询的当前地图名称')
    parser.add_argument('--completed-point',default='',help='练级查询中已完成的当前地图据点')
    parser.add_argument('--check-update',action='store_true',help='检查自有GitHub客户端版本；有更新返回10')
    parser.add_argument('--update-now',action='store_true',help='检查、下载并交接安装客户端更新')
    parser.add_argument('--no-update',action='store_true',help='不安排本次启动的EXE自动检查；不关闭循环库联网')
    parser.add_argument('--no-stealth',action='store_true',help='兼容旧启动参数；独立版始终显示在任务栏')
    parser.add_argument('--spec',action='append',default=[],help='界面诊断的专精ID，可重复指定')
    parser.add_argument('--talent',default=None,help='界面诊断的天赋字符串')
    parser.add_argument('--rotations',default='',help='界面诊断的循环库JSON路径')
    parser.add_argument('--rotation',default='',help='界面诊断的专精ID|子分类|方案名')
    parser.add_argument('--toggle-showall',action='store_true',help='同时导出显示全部切换诊断')
    # 原GUI分支对完整参数列表做精确匹配，不拒绝无关项，也不把--当结束标记。
    # 独立构建诊断和帮助仍使用下面的严格解析器。
    from wowbuddy.native_cli import parse_native_cli
    from wowbuddy.dev_native_commands import command_data_dir
    native=parse_native_cli(arguments,native_arguments=native_arguments)
    strict_commands={'--desktop-selftest','--selftest-backends','--engine-selftest','--desktop-dump-ui','--desktop-hub-selftest','--leveling-next','--export-diagnostics','--help','-h'}
    if native.command=='gui' and not strict_commands.intersection(arguments[1:]):
        if '--watch' in arguments and '--no-watch' in arguments:
            parser.error('--watch 与 --no-watch 不能同时使用')
        try:
            data_dir=command_data_dir(arguments,default_data_dir(APP_ROOT,frozen=FROZEN))
        except ValueError as error:
            parser.error(str(error))
        extra={}
        if '--auto-leveling' in arguments[1:]:
            extra['auto_leveling']=True
        if '--auto-revive' in arguments[1:]:
            extra['auto_revive']=True
        if '--auto-navigate' in arguments[1:]:
            extra['auto_navigate']=True
        if '--auto-grind' in arguments[1:]:
            extra['auto_grind']=True
        if native.dump_ui is not None:
            from wowbuddy.cli_dump_ui import DumpUiOptions
            extra['native_dump']=(DumpUiOptions.parse(arguments),command_data_dir(arguments,APP_ROOT))
        return launch(data_dir,auto_start=native.auto_start,watch='--no-watch' not in arguments,
                      no_update=native.suppress_auto_update,staged=True,**extra)
    args=parser.parse_args(arguments[1:])
    if args.export_diagnostics:
        if (args.dump_ui or args.desktop_selftest or args.selftest_backends or args.engine_selftest or args.selftest
                or args.hub_selftest or args.desktop_hub_selftest or args.leveling_next or args.install_addon
                or args.auto or args.watch or args.check_update or args.update_now):
            parser.error('--export-diagnostics 仅与 --data-dir 配合使用')
        from wowbuddy.diagnostic_export import run_export_command
        return run_export_command(args.data_dir,running_executable=sys.executable if FROZEN else '')
    if args.leveling_next:
        from wowbuddy.automation.leveling_route import run_leveling_lookup
        manual = args.faction is not None, args.level is not None, args.zone is not None
        if any(manual) and not (all(manual) and args.zone.strip()):
            parser.error('手动查询请同时填写 --faction、--level 和 --zone，省略三项则从游戏读取')
        if all(manual):
            return run_leveling_lookup(args.data_dir,args.faction,args.level,args.zone,args.completed_point)
        from wowbuddy.engine.character_state import read_live_character
        return run_leveling_lookup(args.data_dir,None,None,None,args.completed_point,
                                   read_character=lambda: read_live_character(ROOT/'assets'))
    if args.hub_fetch and not (args.hub_selftest or args.desktop_hub_selftest):
        parser.error('--hub-fetch 需要 --hub-selftest')
    if args.install_addon_dir is not None:
        parser.error('--install-addon-dir 需要 --install-addon')
    if args.desktop_hub_selftest:
        if (args.dump_ui or args.desktop_selftest or args.selftest_backends or args.engine_selftest
                or args.auto or args.watch or args.spec or args.talent is not None
                or args.rotations or args.rotation or args.toggle_showall):
            parser.error('--desktop-hub-selftest 仅与 --data-dir / --hub-fetch 配合使用')
        from wowbuddy.dev_hub_diagnostics import run_hub_diagnostics
        return run_hub_diagnostics(ROOT/'assets',args.data_dir,fetch_online=args.hub_fetch)
    if args.engine_selftest:
        if (args.dump_ui or args.desktop_selftest or args.selftest_backends or args.auto or args.watch
                or args.spec or args.talent is not None or args.rotations or args.rotation or args.toggle_showall
                or (args.hub_selftest and args.engine_selftest)):
            parser.error('--hub-selftest / --engine-selftest 各自仅与 --data-dir 配合使用')
        from wowbuddy.dev_engine_diagnostics import run_engine_diagnostics
        return run_engine_diagnostics(ROOT/'assets',args.data_dir)
    if args.dump_ui:
        if args.desktop_selftest or args.selftest_backends or args.auto or args.watch:
            parser.error('--dump-ui 不能与自检或自动监控参数同时使用')
        from wowbuddy.cli_dump_ui import DumpUiOptions
        options=DumpUiOptions(args.rotations,args.rotation,tuple(args.spec),args.talent or '10/0/0',args.toggle_showall)
        return launch(args.data_dir,dump_ui=options)
    if args.spec or args.talent is not None or args.rotations or args.rotation or args.toggle_showall:
        parser.error('专精、天赋及方案诊断参数需要 --dump-ui')
    if (args.auto or args.watch) and (args.desktop_selftest or args.selftest_backends):
        parser.error('--auto / --watch 不能与自检参数同时使用')
    if not (args.desktop_selftest or args.selftest_backends):
        return launch(args.data_dir,auto_start=args.auto,watch=not args.no_watch,no_update=args.no_update,
                      staged=True,auto_leveling=args.auto_leveling,auto_revive=args.auto_revive,
                      auto_navigate=args.auto_navigate,auto_grind=args.auto_grind)
    with TemporaryDirectory(prefix='wowbuddy-dev-selftest-') as temporary:
        report=launch(temporary,selftest=True,real_backends=args.selftest_backends)
    report['temporary_removed']=not Path(temporary).exists()
    report_dir=APP_ROOT if FROZEN else ROOT/'dist'
    report_dir.mkdir(exist_ok=True)
    report_name='backend-selftest.json' if args.selftest_backends else 'desktop-selftest.json'
    (report_dir/report_name).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    if sys.stdout is not None:print(json.dumps(report,ensure_ascii=False))
    return int(not(report['passed'] and report['window_closed'] and report['temporary_removed']))


if __name__=='__main__':
    from wowbuddy.dev_startup import run_logged
    raw_arguments=tuple(sys.argv)
    raise SystemExit(run_logged(lambda arguments: main(arguments,native_arguments=raw_arguments),
                                application=APP_ROOT,arguments=raw_arguments,qt_runtime=True))
