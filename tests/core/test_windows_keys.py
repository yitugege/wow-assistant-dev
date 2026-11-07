"""所有 Win32 事件均由 fake 记录，绝不构造真实后端。"""
import ctypes
import unittest

from wowbuddy.keybindings import parse_keybinding
from wowbuddy.windows_keys import (
    CtypesWin32Backend, INPUT, KEYBDINPUT, KeyboardInput, KeySender,
    activate_and_send, is_foreground, post_message, send_input,
)


class FakeWin32:
    def __init__(self):
        self.calls = []
        self.foreground = 20
        self.valid = {10, 20, 30}
        self.roots = {}
        self.threads = {10: 2, 20: 3}
        self.current_thread = 1
        self.iconic = False
        self.activate = True
        self.attach_fail = set()
        self.input_results = []
        self.post_results = []
        self.input_exception = False
        self.switch_during_input = None
        self.clock = 1000

    def now_ms(self):
        self.calls.append(('now_ms',))
        return self.clock

    def __getattr__(self, name):
        def invoke(*args):
            self.calls.append((name, *args))
            if name == 'IsWindow': return args[0] in self.valid
            if name == 'GetForegroundWindow': return self.foreground
            if name == 'GetAncestor': return self.roots.get(args[0], args[0])
            if name == 'GetCurrentThreadId': return self.current_thread
            if name == 'GetWindowThreadProcessId': return self.threads.get(args[0], 0)
            if name == 'IsIconic': return self.iconic
            if name == 'AttachThreadInput': return args[1] not in self.attach_fail
            if name == 'SetForegroundWindow':
                if self.activate: self.foreground = args[0]
                return self.activate
            if name == 'MapVirtualKeyW': return args[0] + 0x100
            if name == 'SendInput':
                if self.input_exception: raise RuntimeError('fake failure')
                if self.switch_during_input: self.foreground = self.switch_during_input
                return self.input_results.pop(0) if self.input_results else len(args[0])
            if name == 'PostMessageW': return self.post_results.pop(0) if self.post_results else 1
            if name in ('Sleep', 'ShowWindow', 'BringWindowToTop', 'SetActiveWindow', 'SetFocus'):
                return 1
            raise AssertionError(f'unexpected backend call: {name}')
        return invoke

    def of(self, name):
        return [item for item in self.calls if item[0] == name]


class SendInputTests(unittest.TestCase):
    def test_modifier_order_scan_flags_and_batches(self):
        backend = FakeWin32()
        self.assertTrue(send_input(backend, parse_keybinding('ALT-CTRL-SHIFT-NUMPADDIVIDE'), 55))
        batches = backend.of('SendInput')
        self.assertEqual(batches[0][1], (
            KeyboardInput(18, 274, 0), KeyboardInput(17, 273, 0),
            KeyboardInput(16, 272, 0), KeyboardInput(111, 367, 1)))
        self.assertEqual(batches[1][1], (
            KeyboardInput(111, 367, 3), KeyboardInput(16, 272, 2),
            KeyboardInput(17, 273, 2), KeyboardInput(18, 274, 2)))
        self.assertEqual(backend.of('Sleep'), [('Sleep', 55)])
        names = [c[0] for c in backend.calls]
        self.assertEqual(names, ['MapVirtualKeyW'] * 8 + ['SendInput', 'Sleep', 'SendInput'])

    def test_hold_clamp_signed_dword(self):
        for hold, expected in [(-1, 20), (0, 20), (20, 20), (80, 80), (121, 120), (0xffffffff, 20)]:
            with self.subTest(hold=hold):
                backend = FakeWin32()
                send_input(backend, parse_keybinding('A'), hold)
                self.assertEqual(backend.of('Sleep'), [('Sleep', expected)])

    def test_partial_down_preserves_native_no_release(self):
        backend = FakeWin32()
        backend.input_results = [1]
        self.assertFalse(send_input(backend, parse_keybinding('CTRL-A'), 30))
        self.assertEqual(len(backend.of('SendInput')), 1)
        self.assertEqual(backend.of('Sleep'), [])

    def test_partial_up_failure(self):
        backend = FakeWin32()
        backend.input_results = [2, 1]
        self.assertFalse(send_input(backend, parse_keybinding('CTRL-A'), 30))
        self.assertEqual(len(backend.of('SendInput')), 2)

    def test_invalid_binding_has_no_backend_calls(self):
        backend = FakeWin32()
        self.assertFalse(send_input(backend, parse_keybinding('F99'), 30))
        self.assertEqual(backend.calls, [])

    def test_ctypes_input_layout_and_conversion_without_dll(self):
        self.assertEqual(ctypes.sizeof(INPUT), 40)
        self.assertEqual(INPUT.data.offset, 8)
        self.assertEqual(KEYBDINPUT.dwFlags.offset, 4)
        backend = object.__new__(CtypesWin32Backend)
        captured = []
        def fake_send(count, array, size):
            captured.append((count, size, [(v.type, v.ki.wVk, v.ki.wScan, v.ki.dwFlags,
                                            v.ki.time, v.ki.dwExtraInfo) for v in array]))
            return count
        backend._send = fake_send
        self.assertEqual(backend.SendInput((KeyboardInput(111, 53, 3),)), 1)
        self.assertEqual(captured, [(1, 40, [(1, 111, 53, 3, 0, 0)])])


class PostMessageTests(unittest.TestCase):
    def test_fixed_lparam_and_continue_after_failure(self):
        backend = FakeWin32()
        backend.post_results = [0, 1, 1, 1, 1, 1]
        self.assertFalse(post_message(backend, 10, parse_keybinding('ALT-CTRL-UP')))
        self.assertEqual(backend.of('PostMessageW'), [
            ('PostMessageW', 10, 0x100, 18, 1), ('PostMessageW', 10, 0x100, 17, 1),
            ('PostMessageW', 10, 0x100, 38, 1), ('PostMessageW', 10, 0x101, 38, 0xc0000001),
            ('PostMessageW', 10, 0x101, 17, 0xc0000001), ('PostMessageW', 10, 0x101, 18, 0xc0000001)])
        self.assertEqual(backend.of('Sleep'), [('Sleep', 10)])
        self.assertFalse(backend.of('MapVirtualKeyW'))

    def test_invalid_window_does_not_post(self):
        for hwnd in (0, 99):
            backend = FakeWin32()
            self.assertFalse(post_message(backend, hwnd, parse_keybinding('A')))
            self.assertFalse(backend.of('PostMessageW'))


class ActivationTests(unittest.TestCase):
    def test_root_comparison_and_no_foreground(self):
        backend = FakeWin32()
        backend.roots = {10: 40, 20: 40}
        self.assertTrue(is_foreground(backend, 10))
        backend.foreground = 0
        self.assertFalse(is_foreground(backend, 10))

    def test_activation_and_restore_order(self):
        backend = FakeWin32()
        backend.iconic = True
        self.assertEqual(activate_and_send(backend, 10, parse_keybinding('A'), 30),
                         (True, '已临时激活游戏窗口并发送真实按键'))
        focus_names = {'AttachThreadInput', 'ShowWindow', 'BringWindowToTop',
                       'SetForegroundWindow', 'SetActiveWindow', 'SetFocus', 'Sleep'}
        self.assertEqual([c for c in backend.calls if c[0] in focus_names], [
            ('AttachThreadInput', 1, 2, True), ('AttachThreadInput', 1, 3, True),
            ('ShowWindow', 10, 9), ('BringWindowToTop', 10), ('SetForegroundWindow', 10),
            ('SetActiveWindow', 10), ('SetFocus', 10), ('Sleep', 15), ('Sleep', 30),
            ('BringWindowToTop', 20), ('SetForegroundWindow', 20),
            ('AttachThreadInput', 1, 3, False), ('AttachThreadInput', 1, 2, False)])
        self.assertEqual(backend.foreground, 20)

    def test_activation_failure_no_input_and_detaches(self):
        backend = FakeWin32()
        backend.activate = False
        self.assertEqual(activate_and_send(backend, 10, parse_keybinding('A'), 30),
                         (False, '无法把游戏窗口激活到前台'))
        self.assertFalse(backend.of('SendInput'))
        self.assertEqual(backend.of('SetForegroundWindow'), [('SetForegroundWindow', 10)])
        self.assertEqual(backend.of('AttachThreadInput')[-2:],
                         [('AttachThreadInput', 1, 3, False), ('AttachThreadInput', 1, 2, False)])

    def test_failed_attach_not_detached_and_duplicate_threads_not_attached(self):
        backend = FakeWin32()
        backend.threads[20] = 2
        backend.attach_fail = {2}
        self.assertTrue(activate_and_send(backend, 10, parse_keybinding('A'), 30)[0])
        self.assertEqual(backend.of('AttachThreadInput'), [('AttachThreadInput', 1, 2, True)])

    def test_user_switch_during_send_is_not_overridden(self):
        backend = FakeWin32()
        backend.switch_during_input = 30
        self.assertTrue(activate_and_send(backend, 10, parse_keybinding('A'), 30)[0])
        self.assertEqual(backend.foreground, 30)
        self.assertEqual(backend.of('SetForegroundWindow'), [('SetForegroundWindow', 10)])

    def test_input_failure_still_restores(self):
        backend = FakeWin32()
        backend.input_results = [0]
        self.assertEqual(activate_and_send(backend, 10, parse_keybinding('A'), 30),
                         (False, '激活成功但按键发送失败'))
        self.assertEqual(backend.foreground, 20)

    def test_python_backend_exception_restores_and_detaches(self):
        backend = FakeWin32()
        backend.input_exception = True
        with self.assertRaisesRegex(RuntimeError, 'fake failure'):
            activate_and_send(backend, 10, parse_keybinding('A'), 30)
        self.assertEqual(backend.foreground, 20)
        self.assertEqual(backend.calls[-1], ('AttachThreadInput', 1, 2, False))

    def test_foreground_short_path_and_invalid_window(self):
        backend = FakeWin32()
        backend.foreground = 10
        self.assertEqual(activate_and_send(backend, 10, parse_keybinding('A'), 30),
                         (True, '前台按键已发送'))
        self.assertFalse(backend.of('AttachThreadInput'))
        self.assertEqual(activate_and_send(backend, 99, parse_keybinding('A'), 30),
                         (False, '游戏窗口已失效'))


class RouterTests(unittest.TestCase):
    def make_sender(self, backend, force=False, activate=True):
        return KeySender(backend, hwnd=10, force_background=force,
                         allow_activation=activate, interval_ms=100, hold_ms=30)

    def test_route_matrix(self):
        for force, activate, foreground, channel in [
            (True, True, 10, '后台投递'), (False, True, 10, '前台真实按键'),
            (False, False, 20, '后台投递'), (False, True, 20, '临时激活（会闪）')]:
            with self.subTest(force=force, activate=activate, foreground=foreground):
                backend = FakeWin32()
                backend.foreground = foreground
                sender = self.make_sender(backend, force, activate)
                self.assertTrue(sender.send('A'))
                self.assertEqual(sender.channel, channel)
                self.assertEqual((sender.success_count, sender.failure_count, sender.last_send_ms),
                                 (1, 0, 1000))

    def test_rate_limit_parse_order_bypass_and_counters(self):
        backend = FakeWin32()
        sender = self.make_sender(backend, force=True)
        sender.send('A')
        backend.calls.clear()
        backend.clock = 1050
        self.assertFalse(sender.send('A'))
        self.assertEqual(backend.calls, [('now_ms',)])
        self.assertEqual(sender.status, '限速跳过（距上次 50ms < 100ms）')
        self.assertEqual((sender.success_count, sender.failure_count), (1, 0))
        self.assertFalse(sender.send('F99'))
        self.assertEqual(sender.failure_count, 1)
        self.assertEqual(sender.channel, '后台投递')
        self.assertEqual(backend.calls, [('now_ms',)])
        self.assertTrue(sender.send('A', bypass_interval=True))
        self.assertEqual(sender.last_send_ms, 1050)
        backend.clock = 1150
        self.assertTrue(sender.send('A'))  # 等于间隔时放行

    def test_failure_does_not_update_timestamp(self):
        backend = FakeWin32()
        backend.post_results = [0, 1]
        sender = self.make_sender(backend, force=True)
        self.assertFalse(sender.send('A'))
        self.assertEqual((sender.success_count, sender.failure_count, sender.last_send_ms), (0, 1, 0))
        self.assertEqual(sender.status, '后台按键发送失败')


if __name__ == '__main__':
    unittest.main()
