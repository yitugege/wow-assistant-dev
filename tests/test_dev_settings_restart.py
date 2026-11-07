"""使用同一临时INI重新构造主窗，验证临时控件和方案阈值保存边界。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import json
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'desktop'),str(ROOT/'tests/core')]
from PySide6.QtWidgets import QApplication
from wowbuddy.desktop import NoSystemBackend
from test_old_protocol import render_old
import run_dev


class RestartSettingsTests(unittest.TestCase):
    def window(self,directory,exercise):
        app=QApplication.instance() or QApplication([])
        def loop():
            window=next(w for w in app.topLevelWidgets()
                        if w.windowTitle()=='WowBuddyDev — 独立开发版' and not getattr(w,'_closed',True))
            exercise(window)
            return 0
        with patch('wowbuddy.game_windows.CtypesWindowBackend',return_value=NoSystemBackend()),patch('wowbuddy.capture.make_win32_capture',return_value=NoSystemBackend()),patch('wowbuddy.windows_keys.CtypesWin32Backend',return_value=NoSystemBackend()),patch('PySide6.QtWidgets.QSystemTrayIcon.isSystemTrayAvailable',return_value=False),patch.object(QApplication,'exec',side_effect=loop):
            self.assertEqual(run_dev.launch(directory,hub_online=False,client_online=False,addon_online=False),0)

    def identify(self,window,spec):
        frame=window.controller.prepare(render_old(spec)[0]).frame
        self.assertTrue(frame.ok,frame.status)
        window._render_selection()

    def test_intervals_reset_but_auto_update_preference_survives(self):
        def first(window):
            window.poll_timer.start()
            window.ui.poll_interval_spin.setValue(80)
            window.ui.send_interval_spin.setValue(350)
            self.assertTrue(window.poll_timer.isActive())
            self.assertEqual(window.poll_timer.interval(),80)
            self.assertEqual(window.loop.send_interval_ms(),350)
            window.poll_timer.stop()
            window.ui.auto_update_check.setChecked(False)
            window.ui.show_all_check.setChecked(True)
        def second(window):
            self.assertEqual(window.ui.poll_interval_spin.value(),25)
            self.assertEqual(window.ui.send_interval_spin.value(),100)
            self.assertEqual(window.poll_timer.interval(),25)
            self.assertFalse(window.ui.auto_update_check.isChecked())
            self.assertFalse(window.ui.show_all_check.isChecked())
        with TemporaryDirectory() as directory:
            self.window(directory,first)
            self.window(directory,second)

    def test_every_snapshot_profile_and_threshold_group_restores(self):
        profiles=json.loads((ROOT/'assets/rotations.json').read_text('utf8'))['rotations']
        checked_profiles=0;checked_groups=0;persisted_expected={}
        with TemporaryDirectory() as root:
            for ordinal,profile in enumerate(profiles):
                spec=profile['specId'];saved={};selected=[]
                directory=str(Path(root)/str(ordinal))
                def first(window):
                    nonlocal checked_groups
                    self.identify(window,spec)
                    matching=[i for i in range(1,window.ui.rotation_combo.count())
                              if window.ui.rotation_combo.itemData(i)==
                              f"{spec}|{profile['subKey']}|{profile['profileName']}"]
                    self.assertTrue(matching,profile['profileName'])
                    # 原选择键不含ID；重名条目仍按快照首项恢复。
                    window.ui.rotation_combo.setCurrentIndex(matching[-1] if profile['id']==131 else matching[0])
                    selected.append(window.ui.rotation_combo.currentData())
                    self.assertEqual(window.controller.selection.active_profile.key,selected[0])
                    first_match=next(p for p in profiles if (p['specId'],p['subKey'],p['profileName'])==
                                     (spec,profile['subKey'],profile['profileName']))
                    self.assertEqual(window.controller.selection.active_profile.id,first_match['id'])
                    self.assertEqual(len(window.threshold_panel.rows),len(window.controller.groups))
                    for index,(row,group) in enumerate(zip(window.threshold_panel.rows,window.controller.groups)):
                        for value in (0,row.slider.maximum(),0):
                            row.slider.setValue(value)
                            for key in group.keys:
                                self.assertEqual(window.controller.switch_settings[key],value)
                        final=row.slider.maximum() if index%2 else 0
                        row.slider.setValue(final)
                        saved[group.keys]=final
                        checked_groups+=1
                def second(window):
                    self.identify(window,spec)
                    self.assertEqual(window.controller.selection.active_profile.key,selected[0])
                    self.assertEqual(window.ui.rotation_combo.currentData(),selected[0])
                    self.assertEqual(set(saved),{group.keys for group in window.controller.groups})
                    for row,group in zip(window.threshold_panel.rows,window.controller.groups):
                        self.assertEqual(row.slider.value(),saved[group.keys])
                        for key in group.keys:
                            self.assertEqual(window.controller.switch_settings[key],saved[group.keys])
                with self.subTest(profile=profile['profileName'],spec=spec):
                    self.window(directory,first)
                    self.window(directory,second)
                    persisted_expected[str(ordinal)]={'hub/by-spec/'+str(spec):selected[0],
                        **{'switch/'+key:value for keys,value in saved.items() for key in keys}}
                    checked_profiles+=1
            script="from PySide6.QtCore import QSettings; import sys,json; from pathlib import Path; result={}; root=Path(sys.argv[1]); exec('for p in root.iterdir():\\n q=QSettings(str(p/\"settings.ini\"),QSettings.IniFormat)\\n result[p.name]={k:q.value(k) for k in q.allKeys()}'); print(json.dumps(result))"
            loaded=subprocess.run([sys.executable,'-c',script,root],capture_output=True,timeout=15)
            self.assertEqual(loaded.returncode,0,loaded.stderr)
            actual=json.loads(loaded.stdout)
            for ordinal,values in persisted_expected.items():
                for key,value in values.items():
                    got=actual[ordinal][key]
                    self.assertEqual(int(got) if key.startswith('switch/') else got,value)
            self.assertEqual(checked_profiles,41)
            self.assertGreater(checked_groups,41)
            print(f'方案条目={checked_profiles}，唯一选择键=40，阈值组检查={checked_groups}')

    def test_saved_profiles_restore_on_fresh_start_and_preserve_native_switch_edge(self):
        selected={};disabled={}
        specs=(1482,1484,1485,1486,1487,1488,1489,1490,1491)
        def first(window):
            for spec in specs:
                self.identify(window,spec)
                self.assertGreater(window.ui.rotation_combo.count(),1)
                window.ui.rotation_combo.setCurrentIndex(1)
                selected[spec]=window.ui.rotation_combo.currentData()
                self.assertEqual(window.controller.selection.active_profile.key,selected[spec])
                self.assertTrue(window.threshold_panel.rows)
                group=window.controller.groups[0]
                window.threshold_panel.rows[0].slider.setValue(0)
                disabled[spec]=group.keys
                for key in group.keys:
                    self.assertEqual(window.settings._read('switch/'+key,-1,'integer'),0)
        def second(window,spec):
            self.assertIsNone(window.controller.selection.active_profile)
            self.identify(window,spec)
            self.assertEqual(window.ui.rotation_combo.currentData(),selected[spec])
            self.assertEqual(window.controller.selection.active_profile.key,selected[spec])
            for key in disabled[spec]:
                self.assertEqual(window.controller.switch_settings[key],0)
            group_index=next(i for i,g in enumerate(window.controller.groups) if g.keys==disabled[spec])
            self.assertEqual(window.threshold_panel.rows[group_index].slider.value(),0)
        def live_switch(window):
            second(window,1482)
            self.identify(window,1484)
            # 原0999f0优先旧current，失配不回退pending；不擅自修复原行为。
            self.assertEqual(window.ui.rotation_combo.currentData(),'')
            self.assertEqual(window.controller.selection.pending_key,'')
            self.assertIsNone(window.controller.selection.active_profile)
            self.assertEqual(window.settings.load_spec_selection('1484'),selected[1484])
        with TemporaryDirectory() as directory:
            self.window(directory,first)
            # 独立进程读取落盘INI，避免仅由同进程QSettings缓存证明持久化。
            script="from PySide6.QtCore import QSettings; import sys,json; from pathlib import Path; q=QSettings(str(Path(sys.argv[1])/'settings.ini'),QSettings.IniFormat); print(json.dumps({k:q.value(k) for k in q.allKeys()}))"
            loaded=subprocess.run([sys.executable,'-c',script,directory],capture_output=True,timeout=15)
            self.assertEqual(loaded.returncode,0,loaded.stderr)
            persisted=json.loads(loaded.stdout)
            for spec in specs:
                self.assertEqual(persisted['hub/by-spec/'+str(spec)],selected[spec])
                for key in disabled[spec]:self.assertEqual(int(persisted['switch/'+key]),0)
            for spec in specs:
                self.window(directory,lambda window:second(window,spec))
            self.window(directory,live_switch)


if __name__=='__main__':unittest.main()
