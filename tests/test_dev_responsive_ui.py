from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from run_dev import launch
from wowbuddy.cli_dump_ui import DumpUiOptions
from wowbuddy.app.window_shell import ScreenRect, clamp_drag_position


class ResponsiveUiTests(unittest.TestCase):
    def test_window_stays_in_work_area(self):
        screen = ScreenRect(-1280, 40, 1280, 700)
        self.assertEqual(clamp_drag_position((-300, 500), (920, 600), screen), (-920, 140))
        self.assertEqual(clamp_drag_position((-1500, 0), (920, 600), screen), (-1280, 40))

    def test_compact_tabs_and_wide_columns_keep_controls_reachable(self):
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtWidgets import QInputDialog, QPushButton

        def check_layout(app, window, options, output_dir):
            app.processEvents()
            self.assertTrue(window.screen().availableGeometry().contains(window.frameGeometry()))
            ui = window.ui
            route = window.findChild(QPushButton, 'ManualCampRoutes')
            record_corpse = next(action for action in route.menu().actions()
                                 if action.text() == '录制跑尸路线')
            self.assertFalse(record_corpse.isChecked())
            record_corpse.trigger()
            self.assertTrue(window.settings.corpse_recording_enabled())
            import_route = next(action for action in route.menu().actions()
                                if action.text() == '导入游戏路线…')
            exported = 'WBDROUTE2|1429|艾尔文森林|4000,5000|4200,5100'
            with patch('PySide6.QtWidgets.QInputDialog.getText', return_value=(exported, True)):
                import_route.trigger()
            self.assertEqual(list(window.settings.manual_routes()), [exported])
            other = 'WBDROUTE2|1440|灰谷|3182,2084|1330,2592'
            window.settings.save_manual_routes([exported, other])
            with patch.object(QInputDialog, 'getItem', side_effect=lambda *args: (args[3][0], True)):
                window._edit_patrol_route()
            window.session.start(123)
            delete_route = next(action for action in route.menu().actions()
                                if action.text() == '删除路线（含当前循环）…')
            with patch.object(QInputDialog, 'getItem', return_value=('', False)):
                delete_route.trigger()
            self.assertTrue(window.session.is_active())
            self.assertEqual(window.settings.patrol_route(), exported)
            with patch.object(QInputDialog, 'getItem', side_effect=lambda *args: (
                    next(label for label in args[3] if '当前循环' in label), True)):
                delete_route.trigger()
            self.assertFalse(window.session.is_active())
            self.assertTrue(window._monitor_paused_by_user)
            self.assertIsNone(window._patrol_route)
            self.assertEqual(window.settings.patrol_route(), '')
            self.assertEqual(window.settings.manual_routes(), [other])
            dialog = QInputDialog(window)
            dialog.setLabelText('粘贴世界地图导出的固定打怪点。')
            dialog.show()
            app.processEvents()
            rendered = dialog.grab().toImage()
            self.assertEqual(rendered.pixelColor(3, 3).name(), '#111724')
            dialog.close()
            ui.hub_online_button.show()
            ui.monitor_button.setText('停止监控')
            tabs = ui.workspace.tabs

            def verify_in_view(button, scroll):
                viewport = scroll.viewport()
                rect = QRect(button.mapTo(viewport, QPoint()), button.size())
                self.assertTrue(button.isVisible())
                self.assertTrue(viewport.rect().contains(rect), button.text())
                self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())

            def capture(name):
                path = os.environ.get('WOWBUDDY_UI_SCREENSHOTS')
                if path:
                    window.grab().save(str(Path(path) / name))

            for width, height, compact in ((1330, 830, False), (410, 520, True),
                                           (1160, 610, False), (410, 520, True)):
                window.resize(width, height)
                app.processEvents()
                self.assertEqual(tabs.isVisible(), compact)
                if compact:
                    self.assertEqual(tabs.count(), 3)
                    tabs.setCurrentIndex(0)
                    app.processEvents()
                else:
                    self.assertEqual(tabs.count(), 0)
                    self.assertTrue(ui.center_panel.isVisible())
                    self.assertTrue(ui.right_panel.isVisible())
                ui.left_scroll.verticalScrollBar().setValue(0)
                verify_in_view(ui.monitor_button, ui.left_scroll)
                verify_in_view(route, ui.left_scroll)
                self.assertEqual(ui.left_scroll.horizontalScrollBar().maximum(), 0)
                capture(f'assistant-{width}.png')
                for button in (ui.hub_pull_button, ui.hub_online_button, ui.addon_install_button,
                               ui.addon_clean_button, ui.update_check_button):
                    ui.left_scroll.ensureWidgetVisible(button, 4, 4)
                    verify_in_view(button, ui.left_scroll)
                if compact:
                    tabs.setCurrentIndex(1)
                    app.processEvents()
                    self.assertTrue(ui.show_all_check.isVisible())
                    tabs.setCurrentIndex(2)
                    app.processEvents()
                    self.assertTrue(ui.suggestions.isVisible())
                    activity_scroll = tabs.widget(2)
                    activity_scroll.ensureWidgetVisible(ui.clear_log_button)
                    verify_in_view(ui.clear_log_button, activity_scroll)
                    capture(f'activity-{width}.png')
            return 0

        with tempfile.TemporaryDirectory() as data_dir:
            with patch('wowbuddy.dev_dump_ui.run_dump', side_effect=check_layout):
                self.assertEqual(launch(data_dir, dump_ui=DumpUiOptions()), 0)
