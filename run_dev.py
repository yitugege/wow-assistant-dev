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


def launch(data_dir, *, selftest=False, real_backends=False, auto_start=False, watch=False, dump_ui=None):
    if selftest and (auto_start or watch):
        raise ValueError('自检不能同时自动开始监控')
    if dump_ui is not None and (selftest or auto_start or watch):
        raise ValueError('界面诊断不能与自检或自动监控同时使用')
    if selftest or dump_ui is not None:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QUrl, QTimer
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QFileDialog
    from wowbuddy.assets import Assets
    from wowbuddy.settings import open_ini_settings
    from wowbuddy.qt_app import AssistantWindow
    from wowbuddy.ui_layout import NATIVE_STYLESHEET
    from wowbuddy.dev_library import seed_library, profile_action_gaps, read_local_library

    class DevWindow(AssistantWindow):
        def _install_shell(self, tray_enabled):
            available = tray_enabled and QSystemTrayIcon.isSystemTrayAvailable()
            super()._install_shell(available)
            self.shell.tray_available = bool(self.tray)
            self.shell.notice_title = 'WowBuddyDev'
            self.shell.on_quit = self._quit_development_app
            if self.tray:
                self.tray.setToolTip('WowBuddyDev（运行中）')

        def _quit_development_app(self):
            self.shutdown()
            QApplication.quit()

        def _configure_unfinished_controls(self):
            super()._configure_unfinished_controls()
            self.ui.hub_pull_button.setEnabled(True)
            self.ui.hub_pull_button.setText('重载本地方案')
            self.ui.hub_pull_button.setToolTip(str(Path(data_dir)/'hub/rotations.json'))

        def refresh_hub(self):
            try:
                loaded = read_local_library(Path(data_dir)/'hub/rotations.json', self.hub.hub)
            except (OSError, ValueError) as error:
                self.logger.append('本地方案重载失败，保留当前方案：' + str(error))
                return False
            status = f'本地方案已重载：{len(loaded.profiles)} 套'
            self.hub.hub = self._hub_changed(loaded, status)
            self.hub.status = status
            self.logger.append(status)
            return True

        def _render_hub_status(self):
            super()._render_hub_status()
            # 此入口无网络客户端，不能显示旧版的联网检查状态。
            label = self.ui.hub_status
            label.setText(label.text().replace('正在联网检查更新…', '离线开发版')
                          .replace('联网检查中', '离线开发版'))
            profile = self.controller.selection.active_profile
            missing = profile_action_gaps(profile, self.assets.rules, self.assets.readable_rules)
            label.setToolTip('')
            if missing:
                detail = '方案含未注册动作，这些规则不会执行：' + '、'.join(missing)
                label.setText(label.text() + '　⚠ 部分动作未注册')
                label.setToolTip(detail)
                label.setStyleSheet('color:#ffb02e;')
                key = (profile.key, missing)
                if getattr(self, '_last_profile_gap', None) != key:
                    self.logger.append(detail)
                self._last_profile_gap = key
            else:
                self._last_profile_gap = None

        def _install_addon_actions(self, windows, environment, files, dialogs):
            # 仅安装本工程固定包；不连接旧随机目录安装器或清理入口。
            self.addon_files = None
            self.addons = None
            self.ui.addon_path.setText(self.settings.snapshot().addon_last_dir)
            self.ui.addon_path.setReadOnly(True)
            self.ui.addon_status.setText('选择客户端后安装WowBuddyDev；请先退出游戏，测试前禁用旧插件。')
            self.ui.addon_clean_button.setEnabled(False)
            self.ui.addon_detect_button.setText('GitHub下载更新')
            self.ui.addon_detect_button.clicked.connect(self._download_github_addon)
            self.ui.addon_browse_button.setEnabled(True)
            self.ui.addon_browse_button.clicked.connect(self._browse_development_client)
            self.ui.addon_install_button.setText('安装/更新开发插件')
            self.ui.addon_install_button.clicked.connect(self._install_development_addon)

        def _download_github_addon(self):
            if self.session.is_active() or not self.ui.addon_path.text():
                self.ui.addon_status.setText('请先停止监控、退出游戏并选择客户端目录。')
                return
            from concurrent.futures import ThreadPoolExecutor
            from wowbuddy.github_addon import download_latest
            self._download_client = self.ui.addon_path.text()
            self._download_executor = ThreadPoolExecutor(max_workers=1)
            self._download_future = self._download_executor.submit(download_latest, data_dir)
            for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button):
                button.setEnabled(False)
            self.ui.addon_status.setText('正在从GitHub下载并校验插件…')
            self._download_timer = QTimer(self)
            self._download_timer.timeout.connect(self._finish_github_download)
            self._download_timer.start(150)

        def _finish_github_download(self):
            if not self._download_future.done():
                return
            self._download_timer.stop()
            self._download_executor.shutdown(wait=False)
            try:
                from wowbuddy.dev_addon_install import install_package
                release = self._download_future.result()
                if self.session.is_active():
                    raise ValueError('下载期间监控已启动；请停止监控后重新安装')
                result = install_package(release['package'],self._download_client)
                status = f"GitHub {release['tag']} 已安装：{result['target']}；请重新加载游戏插件列表。"
            except Exception as error:
                status = 'GitHub插件更新失败：' + str(error)
            self.ui.addon_status.setText(status)
            self.logger.append(status)
            for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button):
                button.setEnabled(True)

        def _browse_development_client(self):
            selected = QFileDialog.getExistingDirectory(self, '选择包含Wow.exe的客户端目录', self.ui.addon_path.text())
            if not selected:
                return
            from wowbuddy.dev_addon_install import client_directory
            try:
                directory = str(client_directory(selected))
                self.settings.save_addon_dir(directory)
                self.ui.addon_path.setText(directory)
            except (ValueError, OSError) as error:
                self.ui.addon_status.setText(str(error))

        def _install_development_addon(self):
            from wowbuddy.dev_addon_install import install_package
            from zipfile import BadZipFile
            if self.session.is_active():
                self.ui.addon_status.setText('请先停止监控并退出游戏，再安装插件。')
                return
            if not self.ui.addon_path.text():
                self.ui.addon_status.setText('请先浏览选择客户端目录。')
                return
            try:
                result = install_package(PACKAGE_DIR/'WowBuddyDev-dev.zip', self.ui.addon_path.text())
                status = f"已安装{result['files']}个文件：{result['target']}"
                if result['backup']:
                    status += f"；旧开发版备份：{result['backup']}"
                self.ui.addon_status.setText(status)
                self.logger.append(status)
            except (OSError, ValueError, KeyError, BadZipFile) as error:
                self.ui.addon_status.setText('安装失败：' + str(error))
                self.logger.append('开发插件安装失败：' + str(error))

    app = QApplication.instance() or QApplication(['WowBuddyDev'])
    app.setApplicationName('WowBuddyDev')
    app.setOrganizationName('WowBuddyDev')
    app.setStyleSheet(NATIVE_STYLESHEET)
    if (selftest and not real_backends) or dump_ui is not None:
        from wowbuddy.desktop import NoSystemBackend
        windows = capture = keys = NoSystemBackend()
    else:
        from wowbuddy.game_windows import CtypesWindowBackend
        from wowbuddy.capture import make_win32_capture
        from wowbuddy.windows_keys import CtypesWin32Backend
        windows, capture, keys = CtypesWindowBackend(), make_win32_capture(), CtypesWin32Backend()
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_library(ROOT/'assets', data_dir)
    settings = open_ini_settings(str(data_dir/'settings.ini'))
    window = DevWindow(Assets.load(ROOT/'assets'), settings,
        window_backend=windows, capture=capture, key_backend=keys,
        application_dir=data_dir, environment={'WOWBUDDY_HOME':str(data_dir),'WOWBUDDY_NO_GAME_SCAN':''},
        network_enabled=False, automatic=watch, tray_enabled=not selftest and dump_ui is None)
    window.setWindowTitle('WowBuddyDev — 独立开发版')
    window.ui.auto_update_check.setChecked(False)
    window.ui.auto_update_check.setEnabled(False)
    window.ui.update_status.setText('插件更新：在插件页点击“GitHub下载更新”；客户端请下载配套Release。')
    window.show()
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
                            if profile_action_gaps(p, window.assets.rules, window.assets.readable_rules)), None)
        warning_verified = gap_profile is None
        if gap_profile is not None:
            window.controller.select(gap_profile.key)
            window._render_hub_status()
            warning_verified = ('部分动作未注册' in window.ui.hub_status.text()
                                and all(name in window.ui.hub_status.toolTip() for name in
                                        profile_action_gaps(gap_profile, window.assets.rules, window.assets.readable_rules)))
            complete_profile = next(p for p in window.controller.hub.profiles
                                    if not profile_action_gaps(p, window.assets.rules, window.assets.readable_rules))
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


def main():
    parser=argparse.ArgumentParser(description='WowBuddyDev源码开发入口',allow_abbrev=False)
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--selftest-backends', action='store_true',
                        help='验证真实Win32后端构造及GUI关闭，不开始监控或发键')
    parser.add_argument('--data-dir',type=Path,default=APP_ROOT/'.local')
    parser.add_argument('--auto',action='store_true',help='界面初始化后尝试一次开始监控')
    parser.add_argument('--watch',action='store_true',help='立即检查并每5秒自动连接游戏窗口；窗口关闭后停止监控')
    parser.add_argument('--install-addon',action='store_true',help='无主窗安装自有插件包并退出')
    parser.add_argument('--install-addon-dir',default=None,help='直接安装目标目录，原版格式为 --install-addon-dir=路径')
    parser.add_argument('--dump-ui',action='store_true',help='离屏导出界面诊断到data-dir后退出，不抓屏或发键')
    parser.add_argument('--hub-selftest',action='store_true',help='检查本地循环库并报告缺失动作，不联网')
    parser.add_argument('--engine-selftest',action='store_true',help='运行原引擎离线自检并记录失败/跳过计数')
    parser.add_argument('--spec',action='append',default=[],help='界面诊断的专精ID，可重复指定')
    parser.add_argument('--talent',default=None,help='界面诊断的天赋字符串')
    parser.add_argument('--rotations',default='',help='界面诊断的循环库JSON路径')
    parser.add_argument('--rotation',default='',help='界面诊断的专精ID|子分类|方案名')
    parser.add_argument('--toggle-showall',action='store_true',help='同时导出显示全部切换诊断')
    args=parser.parse_args()
    if args.install_addon:
        if (args.selftest or args.selftest_backends or args.dump_ui or args.auto or args.watch
                or args.hub_selftest or args.engine_selftest or args.spec or args.talent is not None
                or args.rotations or args.rotation or args.toggle_showall):
            parser.error('--install-addon 仅与 --install-addon-dir 和 --data-dir 配合使用')
        from wowbuddy.dev_cli_install import run_development_install
        package=PACKAGE_DIR/'WowBuddyDev-addon.zip'
        if not package.exists():package=PACKAGE_DIR/'WowBuddyDev-dev.zip'
        arguments=['WowBuddyDev','--install-addon']
        if args.install_addon_dir is not None:
            arguments.append('--install-addon-dir='+args.install_addon_dir)
        return run_development_install(arguments,package,args.data_dir)
    if args.install_addon_dir is not None:
        parser.error('--install-addon-dir 需要 --install-addon')
    if args.hub_selftest or args.engine_selftest:
        if (args.dump_ui or args.selftest or args.selftest_backends or args.auto or args.watch
                or args.spec or args.talent is not None or args.rotations or args.rotation or args.toggle_showall
                or (args.hub_selftest and args.engine_selftest)):
            parser.error('--hub-selftest / --engine-selftest 各自仅与 --data-dir 配合使用')
        if args.engine_selftest:
            from wowbuddy.dev_engine_diagnostics import run_engine_diagnostics
            return run_engine_diagnostics(ROOT/'assets',args.data_dir)
        from wowbuddy.dev_hub_diagnostics import run_hub_diagnostics
        return run_hub_diagnostics(ROOT/'assets',args.data_dir)
    if args.dump_ui:
        if args.selftest or args.selftest_backends or args.auto or args.watch:
            parser.error('--dump-ui 不能与自检或自动监控参数同时使用')
        from wowbuddy.cli_dump_ui import DumpUiOptions
        options=DumpUiOptions(args.rotations,args.rotation,tuple(args.spec),args.talent or '10/0/0',args.toggle_showall)
        return launch(args.data_dir,dump_ui=options)
    if args.spec or args.talent is not None or args.rotations or args.rotation or args.toggle_showall:
        parser.error('专精、天赋及方案诊断参数需要 --dump-ui')
    if (args.auto or args.watch) and (args.selftest or args.selftest_backends):
        parser.error('--auto / --watch 不能与自检参数同时使用')
    if not (args.selftest or args.selftest_backends): return launch(args.data_dir,auto_start=args.auto,watch=args.watch)
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
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        (APP_ROOT/'startup-error.log').write_text(traceback.format_exc(), 'utf8')
        raise SystemExit(1)
