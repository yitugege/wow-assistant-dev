"""0b33a0读取循环边界；注入QFile返回，不替换程序、不访问网络。"""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PySide6.QtCore import QFileDevice

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.qt_updater import QtLocalUpdateFS


class ScriptedFile:
    def __init__(self, chunks, opens=True):
        self.chunks = iter(chunks)
        self.opens = opens
        self.closed = False
        self.sizes = []
        self.failed = False

    def open(self, mode): return self.opens
    def read(self, size):
        self.sizes.append(size)
        value = next(self.chunks)
        if value is None:
            self.failed = True
            return b''  # QByteArray重载将原read=-1表现为空结果。
        return value
    def error(self):
        return QFileDevice.FileError.ReadError if self.failed else QFileDevice.FileError.NoError
    def errorString(self): return 'injected read failure'
    def close(self): self.closed = True


class NativeHashReadTests(unittest.TestCase):
    def test_read_error_after_open_finishes_with_prefix_hash(self):
        for chunks, prefix in (([None],b''), ([b'prefix',None],b'prefix'),
                               ([b'a',b'b',b''],b'ab'), ([b''],b'')):
            with self.subTest(chunks=chunks):
                source = ScriptedFile(chunks)
                with patch('wowbuddy.qt_updater.QFile', return_value=source):
                    digest = hashlib.sha256()
                    for chunk in QtLocalUpdateFS().read_chunks('fixture',0x100000):
                        digest.update(chunk)
                self.assertEqual(digest.hexdigest(),hashlib.sha256(prefix).hexdigest())
                self.assertTrue(source.closed)
                self.assertTrue(all(size==0x100000 for size in source.sizes))

    def test_open_failure_still_reports_unreadable(self):
        source = ScriptedFile([], opens=False)
        with patch('wowbuddy.qt_updater.QFile', return_value=source):
            with self.assertRaises(OSError):
                list(QtLocalUpdateFS().read_chunks('fixture',0x100000))
        self.assertEqual(source.sizes,[])


if __name__=='__main__': unittest.main()
