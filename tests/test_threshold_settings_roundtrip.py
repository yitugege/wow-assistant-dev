"""真实INI与控制器联测；自定义规则输入，不采集游戏或发送按键。"""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QLabel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.controller import FrameController, SettingsChange
from wowbuddy.pipeline import DecisionPipeline
from wowbuddy.rotation_selection import HubState
from wowbuddy.settings import open_ini_settings
from wowbuddy.thresholds import apply_thresholds
from wowbuddy.expressions import EvaluationContext, evaluate
from wowbuddy.threshold_widgets import ThresholdPanel


class ThresholdSettingsRoundtripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel_for(self, controller):
        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        hint = QLabel(host)
        panel = ThresholdPanel(QGridLayout(host), hint, host, on_change=controller.change_slider)
        panel.render_controller(controller)
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.close)
        return panel

    def test_original_key_migrates_and_slider_persists_across_reopen(self):
        def asset(name):
            return json.loads((ROOT/'assets'/name).read_bytes())
        rules = asset('rules.json')
        field = 'health%1'
        rules['switchFields'] = [{'field': field, 'label': '生命', 'max': 100}]
        rules['specs']['1482']['rotations'] = {'': [
            {'action': 'cast', 'when': ['num_below', field, 30]}]}
        pipeline = DecisionPipeline(asset('contract.json'), asset('contract_readable.json'),
                                    rules, asset('rules_readable.json'))
        old_key, new_key = 'sw_health30_b%3', 'sw_cast~health30_b%4'
        with TemporaryDirectory() as temporary:
            path = str(Path(temporary)/'settings.ini')
            store = open_ini_settings(path)
            store.apply_change(SettingsChange({}, {old_key: 19, 'unrelated': 7}))
            store.qsettings.sync()

            def controller(settings):
                instance = FrameController(pipeline, HubState(), switch_settings=settings.load_switches(),
                                           persist=settings.apply_change, load_switches=settings.load_switches)
                instance.spec_id = '1482'
                instance.refresh_thresholds()
                return instance

            current = controller(store)
            self.assertEqual(current.slider_values, (19,))
            self.assertEqual(current.groups[0].keys, (new_key,))
            panel = self.panel_for(current)
            self.assertEqual(panel.rows[0].slider.value(), 19)
            panel.rows[0].slider.setValue(24)
            self.assertEqual(current.slider_values, (24,))
            store.qsettings.sync()
            reopened = open_ini_settings(path)
            self.assertEqual(reopened.load_switches(), {new_key: 24, 'unrelated': 7})
            restored = controller(reopened)
            self.assertEqual(restored.slider_values, (24,))
            threshold = restored.groups[0].thresholds
            for value, expected in (('23', True), ('24', False)):
                fields = apply_thresholds(threshold, restored.switch_settings, {field: value})
                self.assertEqual(evaluate(['flag', new_key, True], EvaluationContext(fields)), expected)
            restored_panel = self.panel_for(restored)
            self.assertEqual(restored_panel.rows[0].slider.value(), 24)
            restored_panel.rows[0].slider.setValue(0)
            self.assertEqual(restored_panel.rows[0].value_label.text(), '关闭')
            reopened.qsettings.sync()
            disabled = open_ini_settings(path).load_switches()
            fields = apply_thresholds(threshold, disabled, {field: '1'})
            self.assertEqual(fields[new_key], 'OFF')
            self.assertNotIn(old_key, disabled)
            self.assertEqual(disabled['unrelated'], 7)


if __name__ == '__main__': unittest.main()
