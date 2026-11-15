"""覆盖隐藏的主窗口接受关闭后仍需退出事件循环。"""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HiddenWindowCloseTests(unittest.TestCase):
    def test_close_hidden_development_window_exits(self):
        script = '''
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from run_dev import launch

app = QApplication(['WowBuddyDev'])
def hide_and_close():
    window = next(w for w in app.topLevelWidgets() if w.windowTitle().startswith('WowBuddyDev'))
    assert window.isVisible()
    window.hide()
    assert not window.isVisible()
    assert window.close()
    print('hidden close accepted', flush=True)

QTimer.singleShot(0, hide_and_close)
QTimer.singleShot(2000, lambda: app.exit(42))
sys.exit(launch(Path(sys.argv[1]), hub_online=False, client_online=False, addon_online=False))
'''
        with TemporaryDirectory() as data_dir:
            result = subprocess.run([sys.executable, '-c', script, data_dir], cwd=ROOT,
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen'), capture_output=True, timeout=15)
        self.assertIn(b'hidden close accepted', result.stdout, result.stderr)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))


if __name__ == '__main__':
    unittest.main()
