"""原 0ab770 和 0ab270 的离线对照，不调用系统输入。"""
from copy import deepcopy
import ctypes as C
import hashlib
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path('D:/reverse-analysis')
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.core.keybindings import KEY_VKS, KeyBinding
from wowbuddy.win32.windows_keys import CtypesWin32Backend, KeyboardInput, activate_and_send, send_input
from tests.core.test_windows_keys import FakeWin32


_WINDOW_CALLS = {
    b'IsWindow': 1, b'GetForegroundWindow': 0, b'GetAncestor': 2,
    b'GetCurrentThreadId': 0, b'GetWindowThreadProcessId': 1,
    b'AttachThreadInput': 3, b'IsIconic': 1, b'ShowWindow': 2,
    b'BringWindowToTop': 1, b'SetForegroundWindow': 1, b'SetActiveWindow': 1, b'SetFocus': 1,
}


class SendInputNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = REFERENCE / 'wow-assistant/unpacked/WOW战斗助手.exe'
        if not source.is_file():
            raise unittest.SkipTest('需要原业务 EXE')
        sys.path.insert(0, str(REFERENCE / 'native-emulation-runtime'))
        try:
            import pefile
            from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
            from unicorn import x86_const as reg
        except ImportError as exc:
            raise unittest.SkipTest(f'缺少原程序模拟依赖：{exc}') from exc
        payload = source.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == '7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488'
        pe = pefile.PE(data=payload)
        cls.base = pe.OPTIONAL_HEADER.ImageBase
        cls.reg = reg
        cls.vm = Uc(UC_ARCH_X86, UC_MODE_64)
        image = pe.get_memory_mapped_image()
        cls.vm.mem_map(cls.base, (len(image) + 4095) & ~4095)
        cls.vm.mem_write(cls.base, image)
        cls.vm.mem_map(0x20000000, 0x10000)
        cls.vm.mem_map(0x30000000, 0x1000)

        imports = {}
        for library in pe.DIRECTORY_ENTRY_IMPORT:
            for entry in library.imports:
                name = entry.name or b'<ordinal>'
                address = 0x30000000 + len(imports)
                imports[address] = name
                cls.vm.mem_write(entry.address, struct.pack('<Q', address))

        def hook(vm, address, size, _):
            vm_case = cls.case
            arguments = [vm.reg_read(register) for register in
                         (reg.UC_X86_REG_RCX, reg.UC_X86_REG_RDX, reg.UC_X86_REG_R8)]
            name = imports[address]
            first, second, third = arguments
            result = 0
            if name == b'MapVirtualKeyW':
                result = vm_case.scan(first, second)
            elif name == b'SendInput':
                assert first <= 4 and third == 40
                result = vm_case.record_input(first, second, third,
                                              read=lambda ptr, length: bytes(vm.mem_read(ptr, length)))
            elif name == b'Sleep':
                vm_case.trace.append(('Sleep', first))
            elif vm_case.window_backend is not None and name in _WINDOW_CALLS:
                if name == b'GetWindowThreadProcessId':
                    assert second == 0
                if name == b'AttachThreadInput':
                    assert third in (0, 1)
                    arguments[2] = bool(third)
                result = int(getattr(vm_case.window_backend, name.decode('ascii'))(*arguments[:_WINDOW_CALLS[name]]))
            elif vm_case.window_backend is not None and name == b'??0QString@@QEAA@$$QEAU?$QArrayDataPointer@_S@@@Z':
                owner, pointer, length = struct.unpack('<QQQ', vm.mem_read(second, 24))
                assert owner == 0 and 0 < length <= 64
                vm_case.strings[first] = bytes(vm.mem_read(pointer, length * 2)).decode('utf-16le')
                result = first
            elif vm_case.window_backend is not None and name == b'??4QString@@QEAAAEAV0@$$QEAV0@@Z':
                vm_case.strings[first], vm_case.strings[second] = (
                    vm_case.strings[second], vm_case.strings[first],
                )
                result = first
            elif vm_case.window_backend is not None and name == b'??1QString@@QEAA@XZ':
                del vm_case.strings[first]
            elif name.startswith(b'?allocate@QArrayData@@'):
                assert (second, third) == (40, 8)
                # 固定容量足以容纳支持的四个键，保留原 append 和引用计数路径。
                block = vm_case.next_block
                vm_case.next_block += 0x200
                vm_case.allocations.add(block)
                vm.mem_write(block, struct.pack('<iiq', 1, 0, 8))
                vm.mem_write(first, struct.pack('<Q', block))
                result = block + 16
            elif name.startswith(b'?deallocate@QArrayData@@'):
                assert (second, third) == (40, 8)
                assert vm.mem_read(first, 4) == bytes(4)
                vm_case.allocations.remove(first)
            else:
                raise AssertionError(f'原函数触及未接管的导入 {name!r}')
            stack = vm.reg_read(reg.UC_X86_REG_RSP)
            return_address = struct.unpack('<Q', vm.mem_read(stack, 8))[0]
            vm.reg_write(reg.UC_X86_REG_RAX, result)
            vm.reg_write(reg.UC_X86_REG_RSP, stack + 8)
            vm.reg_write(reg.UC_X86_REG_RIP, return_address)

        cls.vm.hook_add(UC_HOOK_CODE, hook, begin=min(imports), end=max(imports))

    def run_native(self, binding, hold, results):
        case = InputTrace(results)
        ok = self.execute_native(case, binding, hold)
        return ok, case.trace

    def execute_native(self, case, binding, hold, *, hwnd=None):
        type(self).case = case
        vm, reg = self.vm, self.reg
        scratch, stack, stop = 0x20000000, 0x2000f008, 0x2000ff00
        vm.mem_write(scratch, struct.pack('<QQQ', 0, scratch + 24, len(binding.modifiers))
                     + b''.join(struct.pack('<I', key) for key in binding.modifiers))
        vm.mem_write(stack, struct.pack('<Q', stop))
        vm.reg_write(reg.UC_X86_REG_RSP, stack)
        if hwnd is None:
            entry = 0xab770
            vm.reg_write(reg.UC_X86_REG_RCX, binding.vk)
            vm.reg_write(reg.UC_X86_REG_RDX, scratch)
            vm.reg_write(reg.UC_X86_REG_R8, hold & 0xffffffff)
        else:
            entry = 0xab270
            case.output = scratch + 0x100
            case.strings[case.output] = ''
            vm.mem_write(stack + 40, struct.pack('<Q', case.output))
            vm.reg_write(reg.UC_X86_REG_RCX, hwnd)
            vm.reg_write(reg.UC_X86_REG_RDX, binding.vk)
            vm.reg_write(reg.UC_X86_REG_R8, scratch)
            vm.reg_write(reg.UC_X86_REG_R9, hold & 0xffffffff)
        vm.emu_start(self.base + entry, stop, count=20000)
        self.assertEqual(vm.reg_read(reg.UC_X86_REG_RIP), stop)
        self.assertFalse(case.allocations)
        return bool(vm.reg_read(reg.UC_X86_REG_RAX) & 0xff)

    def compare(self, binding, hold, results):
        case = InputTrace(results)
        backend = object.__new__(CtypesWin32Backend)
        backend.MapVirtualKeyW = case.scan
        backend.Sleep = lambda ms: case.trace.append(('Sleep', ms))
        backend._send = case.record_input
        rebuilt = send_input(backend, binding, hold)
        self.assertEqual((rebuilt, case.trace), self.run_native(binding, hold, results))

    def test_original_input_bytes_for_every_key_and_modifier_combination(self):
        for vk in sorted(set(KEY_VKS.values())):
            for mask in range(8):
                with self.subTest(vk=vk, modifiers=mask):
                    modifiers = tuple(key for bit, key in enumerate((18, 17, 16)) if mask & (1 << bit))
                    self.compare(KeyBinding(vk, modifiers, True), 45, ())

    def test_original_signed_hold_and_partial_result_boundaries(self):
        binding = KeyBinding(0x6f, (18, 17, 16), True)
        for hold in (-1, 0, 19, 20, 21, 119, 120, 121, 0x7fffffff, 0x80000000, 0xffffffff):
            for results in ((), (0,), (3,), (4, 0), (4, 3), (4, 4), (4, 5), (5,)):
                with self.subTest(hold=hold, results=results):
                    self.compare(binding, hold, results)

    def test_original_activation_matches_status_focus_and_thread_cleanup(self):
        binding = KeyBinding(0x41, (0x11,), True)
        cases = (
            ('temporary focus', 10, {}),
            ('already foreground', 10, {'foreground': 10}),
            ('foreground child', 10, {'roots': {20: 10}}),
            ('minimized', 10, {'iconic': True}),
            ('activation denied', 10, {'activate': False}),
            ('target attach denied', 10, {'attach_fail': {2}}),
            ('old window attach denied', 10, {'attach_fail': {3}}),
            ('shared input thread', 10, {'threads': {10: 2, 20: 2}}),
            ('no previous window', 10, {'foreground': 0}),
            ('previous window invalid at restore', 10, {'valid': {10, 30}}),
            ('foreground changed during input', 10, {'switch_during_input': 30}),
            ('partial key down', 10, {'input_results': [1]}),
            ('partial key up', 10, {'input_results': [2, 1]}),
            ('foreground send failed', 10, {'foreground': 10, 'input_results': [0]}),
            ('invalid target', 99, {}),
            ('null target', 0, {}),
        )
        for label, hwnd, state in cases:
            with self.subTest(label=label):
                rebuilt = ActivationTrace(state)
                expected = activate_and_send(rebuilt.window_backend, hwnd, binding, 45)
                native = ActivationTrace(state)
                ok = self.execute_native(native, binding, 45, hwnd=hwnd)
                self.assertEqual(ok, expected[0])
                self.assertEqual(native.strings, {native.output: expected[1]})
                self.assertEqual(native.trace, rebuilt.trace)


class InputTrace:
    def __init__(self, results):
        self.results = iter(results)
        self.trace = []
        self.next_block = 0x20001000
        self.allocations = set()
        self.window_backend = None
        self.strings = {}

    def scan(self, vk, mode):
        self.trace.append(('MapVirtualKeyW', vk, mode))
        # 两个批次均需映射，且只能保留返回值的低 16 位。
        return 0xa5a50000 + (vk << 2) + len(self.trace)

    def record_input(self, count, data, size, *, read=C.string_at):
        self.trace.append(('SendInput', count, size, read(data, count * size)))
        return next(self.results, count)


class ActivationTrace(InputTrace):
    def __init__(self, state):
        super().__init__(())
        self.window_backend = FakeWin32()
        self.window_backend.__dict__.update(deepcopy(state))
        self.trace = self.window_backend.calls

    def scan(self, vk, mode):
        return self.window_backend.MapVirtualKeyW(vk, mode)

    def record_input(self, count, data, size, *, read):
        inputs = read(data, count * size)
        events = tuple(KeyboardInput(*struct.unpack_from('<HHI', inputs, index * size + 8))
                       for index in range(count))
        return self.window_backend.SendInput(events)


if __name__ == '__main__':
    unittest.main()
