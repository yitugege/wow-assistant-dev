"""独立入口参数与原有单次自动监控回调；系统调用全部替换。"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
import run_dev
from wowbuddy.qt_app import AssistantWindow


class AutoStartTests(unittest.TestCase):
    def invoke(self,handle,active=False,index=2):
        window=Mock()
        window.session.is_active.return_value=active
        window.ui.window_combo.findData.return_value=index
        with patch('wowbuddy.qt_app.find_game_window',return_value=handle):
            AssistantWindow.auto_start_once(window)
        return window

    def test_no_game_does_not_start_or_select(self):
        window=self.invoke(0)
        window.toggle_monitor.assert_not_called()
        window.ui.window_combo.setCurrentIndex.assert_not_called()
        self.assertIn('未找到魔兽窗口',window.logger.append.call_args.args[0])

    def test_game_selects_matching_window_and_starts_once(self):
        window=self.invoke(123)
        window.ui.window_combo.setCurrentIndex.assert_called_once_with(2)
        window.toggle_monitor.assert_called_once_with()

    def test_running_monitor_not_toggled_off(self):
        window=self.invoke(123,active=True)
        window.toggle_monitor.assert_not_called()

    def test_missing_combo_entry_keeps_native_current_selection_behavior(self):
        window=self.invoke(123,index=-1)
        window.ui.window_combo.setCurrentIndex.assert_not_called()
        window.toggle_monitor.assert_called_once_with()

    def test_cli_auto_is_forwarded_without_launching_real_gui(self):
        with patch.object(sys,'argv',['run_dev.py','--auto']),patch.object(run_dev,'launch',return_value=0) as launch:
            self.assertEqual(run_dev.main(),0)
            self.assertTrue(launch.call_args.kwargs['auto_start'])

    def test_independent_selftest_combinations_rejected(self):
        for tail in (['--auto','--desktop-selftest'],['--auto','--selftest-backends'],['--watch','--desktop-selftest'],['--watch','--selftest-backends']):
            with self.subTest(tail=tail),patch.object(sys,'argv',['run_dev.py',*tail]),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:run_dev.main()
                self.assertEqual(raised.exception.code,2)

    def test_watch_parameter_and_selftest_guard(self):
        with patch.object(sys,'argv',['run_dev.py','--watch']),patch.object(run_dev,'launch',return_value=0) as launch:
            self.assertEqual(run_dev.main(),0)
            self.assertTrue(launch.call_args.kwargs['watch'])
        with self.assertRaises(ValueError):run_dev.launch('unused',selftest=True,watch=True)

    def test_normal_launch_restores_native_watch_default_and_explicit_opt_out(self):
        for arguments,expected in (([],True),(['--no-watch'],False),(['--auto'],True)):
            with self.subTest(arguments=arguments),patch.object(sys,'argv',['run_dev.py',*arguments]),patch.object(run_dev,'launch',return_value=0) as launch:
                self.assertEqual(run_dev.main(),0)
                self.assertEqual(launch.call_args.kwargs['watch'],expected)
        with patch.object(sys,'argv',['run_dev.py','--watch','--no-watch']),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:run_dev.main()
            self.assertEqual(raised.exception.code,2)
