"""0x1400b1390 的暗色色块分支：通过真实 Qt 绘制检查中心填色。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from PySide6.QtWidgets import QApplication
from wowbuddy.swatch_strip import SwatchStrip, SwatchItem


class SwatchPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def center(self, rgb, value):
        widget = SwatchStrip()
        try:
            widget.resize(180, 14)
            widget.set_items([SwatchItem(rgb, '字段', value)])
            # QWidget.grab 实际触发 paintEvent，不替换 QPainter。
            rendered = widget.grab().toImage()
            color = rendered.pixelColor(7, 7)
            return color.red(), color.green(), color.blue()
        finally:
            widget.close()
            widget.deleteLater()

    def test_dark_unknown_and_known_values_are_distinct(self):
        for value in ('', '  ', '—', 'UNKNOWN', 'UNKNOWN detail', '光环无'):
            with self.subTest(value=value):
                self.assertEqual(self.center((0, 0, 0), value), (30, 39, 59))
        for value in ('0', 'OFF', 'unknown', '无效果', '已就绪'):
            with self.subTest(value=value):
                self.assertEqual(self.center((0, 0, 0), value), (12, 17, 27))

    def test_rgb_sum_boundary_is_strictly_below_twelve(self):
        self.assertEqual(self.center((4, 4, 3), 'UNKNOWN'), (30, 39, 59))
        self.assertEqual(self.center((4, 4, 4), 'UNKNOWN'), (4, 4, 4))
        self.assertEqual(self.center((220, 30, 90), 'UNKNOWN'), (220, 30, 90))


if __name__ == '__main__':
    unittest.main()
