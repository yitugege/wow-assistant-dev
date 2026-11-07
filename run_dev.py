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


def launch(data_dir, *, selftest=False, real_backends=False, auto_start=False, watch=False, dump_ui=None, hub_online=True, client_online=True, addon_online=True, no_update=False, staged=False, native_dump=None, native_identity_enabled=False):
    if selftest and (auto_start or watch):
        raise ValueError('自检不能同时自动开始监控')
    if dump_ui is not None and (selftest or auto_start or watch):
        raise ValueError('界面诊断不能与自检或自动监控同时使用')
    if selftest or dump_ui is not None:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QUrl, QTimer, Qt
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QFileDialog, QMenu, QPushButton
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
            self.ui.update_check_button.setEnabled(True)
            self.ui.hub_pull_button.setEnabled(True)
            self.ui.hub_pull_button.setText('重载本地方案')
            self.ui.hub_pull_button.setToolTip(str(Path(data_dir)/'hub/rotations.json'))

        def check_update(self, checked=False, *, manual=True):
            if getattr(self,'_handoff',None):return
            timer=getattr(self,'_client_update_timer',None)
            if timer is not None and timer.isActive():return
            if not manual and not getattr(self,'_automatic_client_enabled',False):return
            self._client_update_manual=manual
            self._client_auto_chain=False
            self._client_update_staged=None
            from wowbuddy.github_client import check_latest
            self._start_client_update_task(check_latest,'正在检查GitHub客户端版本…','check')

        def _configure_automatic_client_update(self, enabled, suppress):
            self._automatic_client_enabled=enabled
            self.ui.auto_update_check.setEnabled(enabled)
            self.update_timer.stop()
            if enabled and not suppress:
                delay=self.settings.snapshot().automatic_update_delay_ms(self.clock_ms())
                if delay is not None:self.update_timer.start(delay)

        def download_update(self, checked=False):
            if getattr(self,'_client_update_staged',None):
                self._begin_update_handoff()
                return
            if not getattr(self,'_client_update_info',{}).get('has_update'):return
            if self.session.is_active():self.toggle_monitor()
            from wowbuddy.github_client import download_checked
            from queue import SimpleQueue
            progress=SimpleQueue()
            self._client_download_progress=progress
            workspace=APP_ROOT.parent/'WowBuddyDev-updates'
            self._start_client_update_task(lambda:download_checked(self._client_update_info,workspace,progress=lambda received,total:progress.put((received,total))),
                                           '正在下载并校验客户端更新包…','download')

        def _start_client_update_task(self, operation, status, phase):
            if getattr(self,'_client_update_future',None) is not None and not self._client_update_future.done():return
            from concurrent.futures import ThreadPoolExecutor
            self._client_update_phase=phase
            self._client_update_executor=ThreadPoolExecutor(max_workers=1)
            self._client_update_future=self._client_update_executor.submit(operation)
            self.ui.update_check_button.setEnabled(False)
            self.ui.update_apply_button.setEnabled(False)
            self.ui.update_status.setText(status)
            self.ui.update_progress.setVisible(phase=='download')
            if phase=='download':self.ui.update_progress.setRange(0,0)
            self._client_update_timer=QTimer(self)
            self._client_update_timer.timeout.connect(self._finish_client_update_task)
            self._client_update_timer.start(100)

        def _finish_client_update_task(self):
            if self._client_update_phase=='download':
                from queue import Empty
                progress=getattr(self,'_client_download_progress',None)
                latest=None
                if progress is not None:
                    while True:
                        try:latest=progress.get_nowait()
                        except Empty:break
                if latest is not None:
                    received,total=latest
                    if total>0 and received<=total:
                        self.ui.update_progress.setRange(0,100)
                        self.ui.update_progress.setValue(received*100//total)
                        status=f'已下载 {received/1048576:.1f} / {total/1048576:.1f} MiB'
                        if received==total:status+='，正在校验…'
                    else:
                        self.ui.update_progress.setRange(0,0)
                        status=f'已下载 {received/1048576:.1f} MiB（总大小未知）'
                    self.ui.update_status.setText(status)
            if not self._client_update_future.done():return
            self._client_update_timer.stop()
            self._client_update_executor.shutdown(wait=False)
            self.ui.update_progress.hide()
            try:
                result=self._client_update_future.result()
                if self._client_update_phase=='check':
                    self._client_update_info=result
                    self.settings.save_last_check_ms(self.clock_ms())
                    status=f"当前 {result['current_version']} / GitHub {result['version']}："+('发现新版本' if result['has_update'] else '没有更新')
                    self.ui.update_apply_button.setText('下载更新包')
                    self.ui.update_apply_button.setVisible(result['has_update'])
                    self.ui.update_apply_button.setEnabled(result['has_update'])
                    self.ui.update_apply_button.setToolTip('下载并校验完整客户端，完成后可安装并重启')
                    self._client_auto_chain=(result['has_update'] and not self._client_update_manual
                                             and self.ui.auto_update_check.isChecked() and FROZEN)
                    if self._client_auto_chain:QTimer.singleShot(0,self.download_update)
                elif self._client_update_phase=='handoff':
                    from wowbuddy.dev_update_notice import remember_handoff
                    remember_handoff(data_dir,APP_ROOT,result)
                    self._handoff=result
                    import time
                    self._handoff_deadline=time.monotonic()+30
                    self._handoff_timer=QTimer(self)
                    self._handoff_timer.timeout.connect(self._poll_update_handoff)
                    self._handoff_timer.start(100)
                    status='等待更新交接进程就绪…'
                else:
                    self._client_update_staged=result
                    status='更新包已校验并暂存：'+result['staged']
                    if FROZEN:
                        self.ui.update_apply_button.setText('安装并重启')
                        self.ui.update_apply_button.setToolTip('退出当前助手后替换整个客户端目录，并保留本地设置')
                        self.ui.update_apply_button.setEnabled(True)
                        if getattr(self,'_client_auto_chain',False):QTimer.singleShot(0,self._begin_update_handoff)
                    else:status+='；源码模式请使用打包后的客户端安装更新'
            except Exception as error:
                status='客户端更新失败：'+str(error)
                self._client_auto_chain=False
                if self._client_update_phase=='check':
                    self._client_update_info={}
                    self.ui.update_apply_button.hide()
                elif self._client_update_phase=='download':
                    self.ui.update_apply_button.setText('重试下载')
                    self.ui.update_apply_button.setEnabled(bool(getattr(self,'_client_update_info',{}).get('has_update')))
            self.ui.update_status.setText(status)
            self.logger.append(status)
            self.ui.update_check_button.setEnabled(not bool(getattr(self,'_handoff',None)))

        def _begin_update_handoff(self):
            if not FROZEN:return
            if self.session.is_active():self.toggle_monitor()
            self.watch_timer.stop()
            from wowbuddy.dev_update_handoff import prepare_handoff
            self._start_client_update_task(lambda:prepare_handoff(self._client_update_staged['staged'],APP_ROOT,sys.argv[1:]),
                                           '正在准备退出后的更新交接…','handoff')

        def _poll_update_handoff(self):
            import time
            job=Path(self._handoff['job'])
            if job.with_suffix('.ready.json').is_file() and self._handoff['process'].poll() is None:
                self._handoff_timer.stop()
                self._quit_development_app()
                return
            if self._handoff['process'].poll() is not None or time.monotonic()>self._handoff_deadline:
                self._handoff_timer.stop()
                from wowbuddy.dev_update_handoff import cancel_handoff
                cancel_handoff(self._handoff,'界面等待交接失败')
                detail='交接进程未就绪，当前助手保持运行；未替换程序。'
                result=job.with_suffix('.result.json')
                if result.is_file():detail+=' '+json.loads(result.read_text('utf8')).get('error','')
                self.ui.update_status.setText(detail)
                self.logger.append(detail)
                self._handoff=None
                self.ui.update_check_button.setEnabled(True)

        def shutdown(self):
            if getattr(self,'_native_dump_session',None) is not None:
                self._native_dump_session.close()
            notice_timer=getattr(self,'_update_notice_timer',None)
            if notice_timer is not None:notice_timer.stop()
            addon_timer=getattr(self,'_addon_refresh_timer',None)
            if addon_timer is not None:addon_timer.stop()
            for name in ('_addon_refresh_executor','_download_executor'):
                executor=getattr(self,name,None)
                if executor is not None:executor.shutdown(wait=False,cancel_futures=True)
            download_timer=getattr(self,'_download_timer',None)
            if download_timer is not None:download_timer.stop()
            handoff_timer=getattr(self,'_handoff_timer',None)
            if handoff_timer is not None:handoff_timer.stop()
            timer=getattr(self,'_client_update_timer',None)
            if timer is not None:timer.stop()
            executor=getattr(self,'_client_update_executor',None)
            if executor is not None:executor.shutdown(wait=False,cancel_futures=True)
            super().shutdown()

        def _restore_update_notice(self):
            from wowbuddy.dev_update_notice import poll_notice
            notice=poll_notice(data_dir,APP_ROOT)
            timer=getattr(self,'_update_notice_timer',None)
            if notice is None:
                if timer is not None:timer.stop()
                return
            self.ui.update_status.setText(notice['text'])
            if notice['complete']:
                self.logger.append(notice['text'])
                if timer is not None:timer.stop()
            elif timer is None:
                self._update_notice_attempts=0
                self._update_notice_timer=QTimer(self)
                self._update_notice_timer.timeout.connect(self._restore_update_notice)
                self._update_notice_timer.start(200)
            else:
                self._update_notice_attempts+=1
                if self._update_notice_attempts>=150:
                    timer.stop()
                    status='上次更新结果尚未返回，记录保留供下次启动检查。'
                    self.ui.update_status.setText(status)
                    self.logger.append(status)

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

        def _periodic_library_refresh(self):
            self._refresh_online_library()
            self._refresh_addon_release()

        def _configure_addon_refresh(self,enabled):
            self._addon_online=enabled
            if enabled:
                self.addon_startup_timer.timeout.connect(self._refresh_addon_release)
                self.addon_startup_timer.start()
                self.hub_timer.start()

        def _refresh_addon_release(self):
            if not getattr(self,'_addon_online',False):return
            for name in ('_download_timer','_addon_refresh_timer'):
                timer=getattr(self,name,None)
                if timer is not None and timer.isActive():return
            from concurrent.futures import ThreadPoolExecutor
            from wowbuddy.dev_addon_update import refresh_package
            self._addon_refresh_executor=ThreadPoolExecutor(max_workers=1)
            self._addon_refresh_future=self._addon_refresh_executor.submit(refresh_package,data_dir)
            for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button,self.ui.addon_clean_button):button.setEnabled(False)
            self._addon_refresh_timer=QTimer(self)
            self._addon_refresh_timer.timeout.connect(self._finish_addon_refresh)
            self._addon_refresh_timer.start(100)

        def _addon_game_snapshot(self):
            from wowbuddy.dev_game_paths import discover_clients,common_roots
            from wowbuddy.addon_games import selected_executable
            from wowbuddy.addon_update import AddonGame
            from wowbuddy.dev_addon_update import installed_name
            running=selected_executable(self._addon_windows)
            paths=discover_clients(self.settings,running_executable=running,search_roots=common_roots(),environment=os.environ)
            running_dir=str(Path(running).absolute().parent).casefold() if running else ''
            return tuple(AddonGame(path.name,str(path/'Interface/AddOns'),
                         self.session.is_active() or str(path).casefold()==running_dir,
                         installed_name(path/'Interface/AddOns')) for path in paths)

        def _finish_addon_refresh(self):
            if not self._addon_refresh_future.done():return
            self._addon_refresh_timer.stop()
            self._addon_refresh_executor.shutdown(wait=False)
            try:
                from wowbuddy.dev_addon_update import apply_release,installed_name
                from wowbuddy.addon_update import SettingsPendingAddons
                release=self._addon_refresh_future.result()
                state=apply_release(release,SettingsPendingAddons(self.settings),games=self._addon_game_snapshot,
                                    installed_name=installed_name,on_log=self.logger.append)
                status=f"GitHub插件检查完成；待补装 {len(state.pending)} 个客户端。"
            except Exception as error:status='GitHub插件自动更新失败：'+str(error)
            self.ui.addon_status.setText(status)
            self.logger.append(status)
            for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button,self.ui.addon_clean_button):button.setEnabled(True)

        def _refresh_online_library(self):
            if self.hub_client is not None:
                from wowbuddy.dev_hub_online import HUB_URL
                self.hub_client.refresh(HUB_URL)

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
            self._addon_windows = windows
            self.ui.addon_clean_button.setText('自动检测')
            self.ui.addon_clean_button.setEnabled(True)
            self.ui.addon_clean_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.ui.addon_clean_button.setToolTip('检测游戏客户端；右键选择最近目录')
            self.ui.addon_clean_button.clicked.connect(self._detect_development_client)
            self.ui.addon_clean_button.customContextMenuRequested.connect(self._recent_development_clients)
            self.ui.addon_detect_button.setText('GitHub下载更新')
            self.ui.addon_detect_button.setToolTip('从自有GitHub仓库下载并安装配套插件')
            self.ui.addon_detect_button.clicked.connect(self._download_github_addon)
            self.ui.addon_browse_button.setEnabled(True)
            self.ui.addon_browse_button.clicked.connect(self._browse_development_client)
            self.ui.addon_install_button.setText('安装/更新开发插件')
            self.ui.addon_install_button.clicked.connect(self._install_development_addon)
            self._addon_cleanup_button=QPushButton('清理旧插件')
            self._addon_cleanup_button.setObjectName('Dim')
            self._addon_cleanup_button.setMinimumHeight(30)
            self._addon_cleanup_button.setToolTip('清理所选客户端内含原插件特征文件的目录，保留当前独立插件')
            self.ui.addon_install_button.parentWidget().layout().addWidget(self._addon_cleanup_button)
            self._addon_cleanup_button.clicked.connect(self._cleanup_development_addons)

        def _cleanup_development_addons(self):
            if self.session.is_active():
                self.ui.addon_status.setText('请先停止监控并退出游戏，再清理旧插件。')
                return
            for name in ('_download_timer','_addon_refresh_timer'):
                timer=getattr(self,name,None)
                if timer is not None and timer.isActive():
                    self.ui.addon_status.setText('插件更新进行中，请完成后再清理。')
                    return
            try:
                from wowbuddy.dev_addon_cleanup import cleanup_old_addons
                from wowbuddy.addon_games import selected_executable
                from wowbuddy.dev_addon_install import client_directory
                selected=client_directory(self.ui.addon_path.text())
                running=selected_executable(self._addon_windows)
                if running and str(Path(running).absolute().parent).casefold()==str(selected).casefold():
                    raise ValueError('所选游戏正在运行，请退出游戏后再清理')
                result=cleanup_old_addons(selected)
                status=f'清理完成：删除 {result.deleted} 个旧插件目录。\n{result.notes}'
            except (OSError,ValueError) as error:status='插件清理失败：'+str(error)
            self.ui.addon_status.setText(status)
            self.logger.append(status)

        def _select_development_client(self, selected):
            from wowbuddy.dev_game_paths import normalize_client
            try:
                directory=str(normalize_client(selected))
                self.settings.save_addon_dir(directory)
                self.ui.addon_path.setText(directory)
                self.ui.addon_status.setText('已选择客户端：'+directory)
            except (ValueError,OSError) as error:
                self.ui.addon_status.setText(str(error))

        def _detect_development_client(self):
            if 'WOWBUDDY_NO_GAME_SCAN' in os.environ:
                self.ui.addon_status.setText('当前环境已禁用游戏目录扫描。')
                return
            from wowbuddy.dev_game_paths import discover_clients, common_roots
            from wowbuddy.addon_games import selected_executable
            try:
                paths=discover_clients(self.settings,running_executable=selected_executable(self._addon_windows),
                                       search_roots=common_roots(),environment=os.environ)
                if paths:self._select_development_client(paths[0])
                else:self.ui.addon_status.setText('未检测到游戏客户端，请手动选择目录。')
            except (OSError,ValueError) as error:
                self.ui.addon_status.setText('检测失败：'+str(error))

        def _recent_development_clients(self, position):
            menu=QMenu(self)
            for path in self.settings.snapshot().addon_history:
                action=menu.addAction(path)
                action.triggered.connect(lambda checked=False,p=path:self._select_development_client(p))
            if menu.actions():menu.addSeparator()
            menu.addAction('清空最近目录').triggered.connect(self.settings.clear_addon_history)
            menu.exec(self.ui.addon_clean_button.mapToGlobal(position))

        def _download_github_addon(self):
            if self.session.is_active() or not self.ui.addon_path.text():
                self.ui.addon_status.setText('请先停止监控、退出游戏并选择客户端目录。')
                return
            from concurrent.futures import ThreadPoolExecutor
            from wowbuddy.github_addon import download_latest
            self._download_client = self.ui.addon_path.text()
            self._download_executor = ThreadPoolExecutor(max_workers=1)
            self._download_future = self._download_executor.submit(download_latest, data_dir)
            for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button,self.ui.addon_clean_button):
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
                status += f"\n清理旧目录：{result['cleanup_deleted']} 个；{result['cleanup_notes']}"
            except Exception as error:
                status = 'GitHub插件更新失败：' + str(error)
            self.ui.addon_status.setText(status)
            self.logger.append(status)
            for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button,self.ui.addon_clean_button):
                button.setEnabled(True)

        def _browse_development_client(self):
            selected = QFileDialog.getExistingDirectory(self, '选择包含Wow.exe的客户端目录', self.ui.addon_path.text())
            if not selected:
                return
            self._select_development_client(selected)

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
                status += f"\n清理旧目录：{result['cleanup_deleted']} 个；{result['cleanup_notes']}"
                self.ui.addon_status.setText(status)
                self.logger.append(status)
            except (OSError, ValueError, KeyError, BadZipFile) as error:
                self.ui.addon_status.setText('安装失败：' + str(error))
                self.logger.append('开发插件安装失败：' + str(error))

    startup_record('复用已初始化的 QApplication' if QApplication.instance() is not None else '准备构造 QApplication')
    app = QApplication.instance() or QApplication(['WowBuddyDev'])
    from wowbuddy.dev_startup import qt_ready,log_path,STYLE_READY
    if not getattr(app,'_wowbuddy_bootstrap_ready',False):
        qt_ready()
        app.setStyleSheet(NATIVE_STYLESHEET)
        startup_record(STYLE_READY)
    app.setApplicationName('WowBuddyDev')
    app.setOrganizationName('WowBuddyDev')
    if (selftest and not real_backends) or dump_ui is not None:
        from wowbuddy.desktop import NoSystemBackend
        windows = capture = keys = NoSystemBackend()
    else:
        from wowbuddy.game_windows import CtypesWindowBackend
        from wowbuddy.dev_game_windows import AssistantWindowFilter
        from wowbuddy.capture import make_win32_capture
        from wowbuddy.windows_keys import CtypesWin32Backend
        windows, capture, keys = AssistantWindowFilter(CtypesWindowBackend()), make_win32_capture(), CtypesWin32Backend()
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_library(ROOT/'assets', data_dir)
    startup_record('独立循环库种子快照就绪')
    settings = open_ini_settings(str(data_dir/'settings.ini'))
    def construct_window(assets):
        from wowbuddy.window_identity import NativeWindowIdentity
        window = DevWindow(assets, settings,
            window_backend=windows, capture=capture, key_backend=keys,
            application_dir=data_dir, environment={'WOWBUDDY_HOME':str(data_dir),'WOWBUDDY_NO_GAME_SCAN':''},
            network_enabled=False, automatic=watch, tray_enabled=not selftest and dump_ui is None,
            startup_record=startup_record,startup_log_path=log_path(),
            native_window_identity=NativeWindowIdentity(native_identity_enabled))
        startup_record('独立主窗口构造完成')
        from wowbuddy.dev_version import VERSION
        from wowbuddy.github_addon import REPOSITORY
        project_url='https://github.com/'+REPOSITORY
        window.setWindowTitle('WowBuddyDev — 独立开发版')
        window.ui.title_label.setText('WowBuddyDev')
        window.ui.website_button.setText('GitHub 项目')
        window.ui.website_button.setToolTip('打开 '+project_url)
        window.shell.website_url=project_url
        window._configure_automatic_client_update(client_online and not selftest and dump_ui is None,no_update)
        window._configure_addon_refresh(addon_online and not selftest and dump_ui is None)
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
        startup=create_staged_startup(app,ROOT/'assets',windows,construct_window,startup_record,auto_start=auto_start,after_main=after_main)
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


def main(arguments=None, *, native_arguments=None):
    arguments=list(sys.argv if arguments is None else arguments)
    if len(arguments)==3 and arguments[1]=='--apply-client-update':
        if not FROZEN:return 2
        from wowbuddy.dev_update_handoff import run_handoff
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
    parser.add_argument('--check-update',action='store_true',help='检查自有GitHub客户端版本；有更新返回10')
    parser.add_argument('--update-now',action='store_true',help='检查、下载并交接安装客户端更新')
    parser.add_argument('--no-update',action='store_true',help='不安排本次启动的EXE自动检查；不关闭循环库联网')
    parser.add_argument('--no-stealth',action='store_true',help='保留可读的系统窗口标题，不设置原版工具窗样式')
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
    strict_commands={'--desktop-selftest','--selftest-backends','--engine-selftest','--desktop-dump-ui','--desktop-hub-selftest','--help','-h'}
    if native.command=='gui' and not strict_commands.intersection(arguments[1:]):
        if '--watch' in arguments and '--no-watch' in arguments:
            parser.error('--watch 与 --no-watch 不能同时使用')
        try:
            data_dir=command_data_dir(arguments,default_data_dir(APP_ROOT,frozen=FROZEN))
        except ValueError as error:
            parser.error(str(error))
        extra={}
        if native.dump_ui is not None:
            from wowbuddy.cli_dump_ui import DumpUiOptions
            extra['native_dump']=(DumpUiOptions.parse(arguments),command_data_dir(arguments,APP_ROOT))
        return launch(data_dir,auto_start=native.auto_start,watch='--no-watch' not in arguments,
                      no_update=native.suppress_auto_update,staged=True,
                      native_identity_enabled=native.native_title_enabled,**extra)
    args=parser.parse_args(arguments[1:])
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
    if not (args.desktop_selftest or args.selftest_backends): return launch(args.data_dir,auto_start=args.auto,watch=not args.no_watch,no_update=args.no_update,staged=True)
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
