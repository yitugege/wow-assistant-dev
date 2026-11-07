"""原QFile字节语义与主窗日志生命周期联测；仅临时文件和替身游戏后端。"""
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from PySide6.QtCore import QFile,QIODevice
from wowbuddy.session import FileLog


class SessionLogTests(unittest.TestCase):
    def test_bytes_and_write_counts_match_actual_qfile(self):
        cases=([b'a\nb\n'],[b'a\r\nb\r'],[b'a\r',b'\nb'],
               ['中文🙂\n'.encode('utf8')],[b'a\0b\n'],[b''],[b'\n\r\n\n'])
        with TemporaryDirectory() as directory:
            for index,chunks in enumerate(cases):
                with self.subTest(chunks=chunks):
                    qt_path=Path(directory)/f'qt-{index}.log'
                    source_path=Path(directory)/f'source-{index}.log'
                    qt=QFile(str(qt_path));source=FileLog(source_path)
                    # 0a2070:287传入0x14，QFile由Append隐含启用写入。
                    self.assertTrue(qt.open(QIODevice.Append|QIODevice.Text))
                    try:
                        for chunk in chunks:
                            self.assertEqual(source.write(chunk),qt.write(chunk))
                            self.assertTrue(qt.flush());self.assertTrue(source.flush())
                            self.assertEqual(source_path.read_bytes(),qt_path.read_bytes())
                    finally:source.close();qt.close()

    def test_clear_keeps_file_and_same_second_restart_appends(self):
        from test_dev_tray import TrayTests
        def exercise(window):
            window.logger.now=lambda:datetime(2026,11,7,12,34,56,123000)
            window.toggle_monitor()
            self.assertTrue(window.session.is_active())
            path=Path(window.logger.file.path)
            window.logger.append('清空前标记')
            before=path.read_bytes()
            window.logger.buffer='待清缓冲'
            handle=window.logger.file
            window.ui.clear_log_button.click()
            self.assertEqual(window.ui.log_view.toPlainText(),'')
            self.assertEqual(window.logger.buffer,'')
            self.assertIs(window.logger.file,handle)
            self.assertTrue(handle.is_open())
            self.assertEqual(path.read_bytes(),before)
            self.assertTrue(window.session.is_active())
            window.logger.append('清空后标记')
            window.toggle_monitor()
            stopped=path.read_bytes()
            self.assertTrue(stopped.startswith(before))
            self.assertEqual(stopped.count('已停止监控'.encode()),1)
            self.assertIsNone(window.logger.file)
            window.toggle_monitor()
            self.assertEqual(Path(window.logger.file.path),path)
            self.assertTrue(path.read_bytes().startswith(stopped))
            before_shutdown=path.read_bytes()
            window.shutdown()
            self.assertEqual(path.read_bytes(),before_shutdown)
            self.assertFalse(window.poll_timer.isActive())
            self.assertIsNone(window.logger.file)
        TrayTests.run_window(self,False,exercise)

    def test_log_open_failure_does_not_cancel_monitor(self):
        from test_dev_tray import TrayTests
        def exercise(window):
            logs=Path(window.session.application_dir)/'logs'
            logs.write_bytes(b'path-blocker')
            window.toggle_monitor()
            self.assertTrue(window.session.is_active())
            self.assertFalse(window.logger.file.is_open())
            self.assertIn('日志文件打不开',window.ui.log_view.toPlainText())
            self.assertEqual(logs.read_bytes(),b'path-blocker')
            window.toggle_monitor()
            self.assertFalse(window.session.is_active())
            self.assertIn('已停止监控',window.ui.log_view.toPlainText())
        TrayTests.run_window(self,False,exercise)


if __name__=='__main__':unittest.main()
