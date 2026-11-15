"""候选和诊断日志的占位符行为，与原包 Qt 格式化函数对照。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import unittest

from PySide6.QtCore import QLocale
from test_availability_display_native import QString
from wowbuddy.aura_probe import ProbeEvent, ProbeResult, Receipt
from wowbuddy.candidates import Candidate
from wowbuddy.capture_backend_text import CaptureBackendState, backend_status_text
from wowbuddy.dispatch import DispatchResult
from wowbuddy.presentation import candidate_text, field_change_text, probe_event_text, send_display


class StringView(C.Structure):
    _fields_ = [('ptr', C.c_void_p), ('size', C.c_size_t)]


class StringArg(C.Structure):
    _fields_ = [('type', C.c_uint8), ('view', StringView)]


def string_view(text):
    raw = text.encode('utf-16-le', 'surrogatepass')
    buffer = C.create_string_buffer(raw + b'\0\0')
    return buffer, StringView(C.addressof(buffer), len(raw) // 2 | (1 << 63))


class NativePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path('D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll')
        if os.name != 'nt' or not path.is_file():
            raise unittest.SkipTest('需要原 Windows Qt DLL')
        assert hashlib.sha256(path.read_bytes()).hexdigest() == 'b712b4754588e89f855dc0aa087d6304b2fd21b0e0639d1cdeb9cb969bd5fb72'
        with os.add_dll_directory(str(path.parent)):
            cls.dll = C.CDLL(str(path))

    @classmethod
    def bind(cls, name, result, *args):
        function = getattr(cls.dll, name)
        function.restype, function.argtypes = result, list(args)
        return function

    def read_result(self, result):
        try:
            return C.string_at(result.ptr, result.size * 2).decode('utf-16-le', 'surrogatepass')
        finally:
            self.bind('??1QString@@QEAA@XZ', None, C.POINTER(QString))(C.byref(result))

    def single(self, text, value, width=0):
        buffer, view = string_view(text)
        source = QString(None, view.ptr, len(buffer.raw) // 2 - 1)
        result = QString()
        signature = (C.POINTER(QString), C.POINTER(QString))
        if isinstance(value, str):
            replacement, value_view = string_view(value)
            function = self.bind('?arg_impl@QString@@AEBA?AV1@VQAnyStringView@@HVQChar@@@Z', C.c_void_p,
                                 *signature, C.POINTER(StringView), C.c_int, C.c_uint16)
            function(C.byref(source), C.byref(result), C.byref(value_view), width, 32)
        elif isinstance(value, int):
            function = self.bind('?arg_impl@QString@@AEBA?AV1@_JHHVQChar@@@Z', C.c_void_p,
                                 *signature, C.c_int64, C.c_int, C.c_int, C.c_uint16)
            function(C.byref(source), C.byref(result), value, width, 10, 32)
        else:
            function = self.bind('?arg_impl@QString@@AEBA?AV1@NHDHVQChar@@@Z', C.c_void_p,
                                 *signature, C.c_double, C.c_int, C.c_char, C.c_int, C.c_uint16)
            function(C.byref(source), C.byref(result), value, width, b'f', 1, 32)
        return self.read_result(result)

    def multi(self, text, *values):
        buffer, view = string_view(text)
        buffers, views = zip(*(string_view(value) for value in values))
        args = [StringArg(1, value_view) for value_view in views]
        pointers = (C.POINTER(StringArg) * len(args))(*(C.pointer(arg) for arg in args))
        result = QString()
        function = self.bind('?argToQString@QtPrivate@@YA?AVQString@@VQAnyStringView@@_KPEAPEBUArgBase@1@@Z',
                             C.c_void_p, C.POINTER(QString), C.POINTER(StringView), C.c_size_t,
                             C.POINTER(C.POINTER(StringArg)))
        function(C.byref(result), C.byref(view), len(args), pointers)
        return self.read_result(result)

    def chain(self, text, *values):
        for value in values:
            text = self.single(text, value)
        return text

    def use_german_locale(self):
        constructor = self.bind('??0QLocale@@QEAA@XZ', C.c_void_p, C.c_void_p)
        named_constructor = self.bind('??0QLocale@@QEAA@AEBVQString@@@Z', C.c_void_p,
                                      C.c_void_p, C.POINTER(QString))
        set_default = self.bind('?setDefault@QLocale@@SAXAEBV1@@Z', None, C.c_void_p)
        destroy = self.bind('??1QLocale@@QEAA@XZ', None, C.c_void_p)
        previous, current = C.create_string_buffer(32), C.create_string_buffer(32)
        locale_text, view = string_view('de_DE')
        name = QString(None, view.ptr, 5)
        constructor(previous)
        named_constructor(current, C.byref(name))
        self.addCleanup(destroy, previous)
        self.addCleanup(destroy, current)
        self.addCleanup(set_default, previous)
        set_default(current)
        self.addCleanup(QLocale.setDefault, QLocale())
        QLocale.setDefault(QLocale('de_DE'))
        self.assertEqual(self.single('%L1', 1234.5), '1.234,5')

    def test_candidate_rescans_key_and_label_then_inserts_reason_and_hold_together(self):
        for token in ('', '%0', '%01', '%L3', '%L04', '%5', '%10', '%100', '%%3', '%３', '%٣', '%𝟛'):
            for key, label in ((f'F1{token}', '寒冰箭'), ('F1', f'寒冰箭{token}')):
                with self.subTest(key=key, label=label):
                    candidate = Candidate(key=key, label=label, reason='技能%5', priority=12, hold_ms=2000)
                    native = self.single('  [%1] %2  %3  %4%5', 12)
                    native = self.single(native, key, -10)
                    native = self.single(native, label, -14)
                    native = self.multi(native, '技能%5', '  压制2s')
                    self.assertEqual(candidate_text([candidate]), native)

    def test_field_change_rescans_label_and_value(self):
        for token in ('', '%0', '%01', '%L0', '%L04', '%5', '%10', '%100', '%%2', '%２', '%٢'):
            for label, value in ((f'生命{token}', '可用'), ('生命', f'可用{token}')):
                with self.subTest(label=label, value=value):
                    native = self.chain('#%1 %2：%3  (rgb=%4,%5,%6)', 9, label, value, 123, 145, 167)
                    self.assertEqual(field_change_text(8, label, value, (123, 145, 167)), native)

    def test_probe_log_keeps_numeric_locale_after_rescanning_action(self):
        self.use_german_locale()
        template = '⚠ %1 按出去了但光环没出现（施法被打断？）→ 压制期从 %2s 缩到 %3s，重试'
        for token in ('', '%0', '%L1', '%L2', '%L03', '%L4'):
            with self.subTest(token=token):
                action = 'renew' + token
                event = ProbeEvent(action, ProbeResult.MISSED, Receipt.INVALID, 1235500, 2000, 1)
                expected = self.chain(template, action, 1234.5, 1.0)
                self.assertEqual(probe_event_text(event, now_ms=1000), expected)

    def test_send_status_and_log_do_not_rescan_inserted_strings(self):
        candidate = Candidate(key='F1', label='技能%L0', tag='目标%3')
        result = DispatchResult('sent', True, channel_status='已发送%0', channel_path='后台投递%01')
        display = send_display(candidate, result, prefix='自动%2')
        self.assertEqual(display.status, self.multi('%1 %2 → %3（%4）', '✓', '技能%L0', 'F1', '已发送%0'))
        self.assertEqual(display.log, self.multi('%1发送 %2 键=%3%4 结果=%5 %6%7%8', '自动%2', '技能%L0', 'F1',
                                                ' 标签=目标%3', '成功', '已发送%0', '  路径=后台投递%01', ''))

    def test_capture_backend_rechecks_placeholders_only_in_retry_message(self):
        self.use_german_locale()
        retry_template = 'GDI PrintWindow（%1，%2 秒后重试 DXGI）'
        permanent_template = 'GDI PrintWindow（%1）'
        for reason in ('DuplicateOutput 失败', '故障%0', '故障%01', '故障%L02', '故障%100', '故障%２'):
            for remaining, seconds in ((-1, 1), (0, 1), (999, 1), (1000, 2), (1233000, 1234),
                                       (2147483647000, -2147483648)):
                with self.subTest(reason=reason, remaining=remaining):
                    state = CaptureBackendState(last_error=reason, retry_after_ms=10+remaining)
                    self.assertEqual(backend_status_text(state, 10), self.chain(retry_template, reason, seconds))
            for flag in ('permanent_format_failure', 'permanent_factory_failure'):
                state = CaptureBackendState(last_error=reason, **{flag: True})
                self.assertEqual(backend_status_text(state, 10), self.single(permanent_template, reason))
        self.assertEqual(backend_status_text(CaptureBackendState(), 10), 'GDI PrintWindow')
        active = CaptureBackendState(duplication_active=True, frame_count=123, last_error='故障%0',
                                     permanent_factory_failure=True)
        self.assertEqual(backend_status_text(active, 10), self.single('DXGI 桌面复制（已取 %1 帧新桌面帧）', 123))
        counter = CaptureBackendState(duplication_active=True, frame_count=2**64 + 2)
        self.assertEqual(backend_status_text(counter, 10), self.single('DXGI 桌面复制（已取 %1 帧新桌面帧）', 2))


if __name__ == '__main__':
    unittest.main()
