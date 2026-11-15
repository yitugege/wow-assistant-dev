"""原0b48d0取消优先分支；Qt信号和真实临时文件，不访问网络或替换EXE。"""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
from PySide6.QtCore import QCoreApplication, QObject, Signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.qt_updater import QtUpdaterClient
from wowbuddy.updater import UpdateInfo


class Reply(QObject):
    readyRead = Signal()
    downloadProgress = Signal(int, int)
    finished = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.body = b''
        self.reads = 0
        self.code = 0
        self.aborts = 0

    def readAll(self):
        self.reads += 1
        result, self.body = self.body, b''
        return result

    def error(self): return self.code
    def errorString(self): return '测试网络错误'
    def isRunning(self): return True
    def abort(self): self.aborts += 1  # 模拟取消后已有成功finished排队。


class Manager(QObject):
    def get(self, request):
        self.reply = Reply(self)
        return self.reply


class UpdateFinishOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_completion_priority_and_residual_bytes(self):
        for scenario in ('success', 'cancel_success', 'cancel_error', 'network_error', 'error5'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)/'fixture.exe'
                target.write_bytes(b'untouched target')
                managers = []
                def factory(parent):
                    manager = Manager(parent)
                    managers.append(manager)
                    return manager
                client = QtUpdaterClient(env={'WOWBUDDY_EXE':str(target)},
                    application_dir=directory, manager_factory=factory)
                verified, logs = [], []
                client.verified.connect(verified.append)
                client.log_message.connect(logs.append)
                payload = b'head-tail'
                client.updater.info = UpdateInfo(ok=True, version='99.0.0',
                    download_url='https://invalid.test/never-requested', size=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest())
                try:
                    self.assertIsNotNone(client.download())
                    reply = managers[0].reply
                    reply.body = b'head-'
                    reply.readyRead.emit()
                    self.assertEqual(reply.reads, 1)
                    part = Path(client.updater.part_path)
                    if scenario.startswith('cancel'):
                        client.cancel()
                        self.assertEqual(reply.aborts, 1)
                    reply.code = 99 if scenario in ('cancel_error','network_error') else 5 if scenario=='error5' else 0
                    reply.body = b'tail'
                    reply.finished.emit()
                    self.assertEqual(client.pending_ids, ())
                    self.assertFalse(client.updater.busy)
                    self.assertEqual(target.read_bytes(), b'untouched target')
                    if scenario == 'success':
                        self.assertEqual(reply.reads, 2)
                        self.assertEqual(part.read_bytes(), payload)
                        self.assertEqual(len(verified), 1)
                        self.assertEqual(verified[0].actual_sha256, hashlib.sha256(payload).hexdigest())
                    else:
                        self.assertEqual(reply.reads, 1, '取消或错误优先于读取尾部数据')
                        self.assertEqual(verified, [])
                        self.assertFalse(part.exists())
                        expected = '下载失败：测试网络错误' if scenario=='network_error' else '已取消更新'
                        self.assertEqual(client.ui.text, expected)
                        self.assertEqual(logs, ['自动更新未完成：'+expected])
                    reply.finished.emit()  # 已断开信号，不重复发布结果。
                    self.assertEqual(len(verified), int(scenario=='success'))
                finally:
                    client.close()
                    client.deleteLater()


if __name__ == '__main__': unittest.main()
