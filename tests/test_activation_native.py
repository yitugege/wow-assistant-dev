"""原激活/前台判据机器码；所有系统调用替换为记录器，无实际窗口操作。"""
import ctypes as C
import hashlib
import itertools
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
sys.path.insert(0, str(ROOT / 'tests/core'))
from test_windows_keys import FakeWin32
from wowbuddy.keybindings import parse_keybinding
from wowbuddy.windows_keys import activate_and_send


class ActivationNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path('D:/reverse-analysis/wow-assistant/unpacked/WOW战斗助手.exe')
        if os.name != 'nt' or not path.is_file():
            raise unittest.SkipTest('需要原 Windows x64 EXE')
        import pefile
        import capstone as cs
        payload = path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == '7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488'
        pe = pefile.PE(data=payload)
        base = 0xa99c0
        image_base = pe.OPTIONAL_HEADER.ImageBase
        image = bytearray(0xe0200 - base)
        imports = {i.address: i.name.decode() for d in pe.DIRECTORY_ENTRY_IMPORT
                   for i in d.imports if i.name}
        # 仅这两个函数可执行，其他间隙为零；保持原相对地址。
        referenced = {}
        decoder = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64)
        decoder.detail = True
        for rva, size in ((base, 0x4f), (0xab270, 0x4f9)):
            code = pe.get_data(rva, size)
            image[rva-base:rva-base+size] = code
            for ins in decoder.disasm(code, image_base + rva):
                for op in ins.operands:
                    if op.type == cs.x86.X86_OP_MEM and op.mem.base == cs.x86.X86_REG_RIP:
                        target = ins.address + ins.size + op.mem.disp
                        if ins.mnemonic == 'call':
                            referenced[target-image_base] = imports[target]
                        else:
                            assert ins.mnemonic == 'lea'  # 仅不执行的 Qt 文案分支
                    elif ins.mnemonic == 'call' and op.type == cs.x86.X86_OP_IMM:
                        assert op.imm-image_base in (base, 0xab770)

        ptr, integer = C.c_size_t, C.c_int32
        signatures = {
            'IsWindow': (integer, [ptr]), 'GetForegroundWindow': (ptr, []),
            'GetAncestor': (ptr, [ptr, C.c_uint32]),
            'GetCurrentThreadId': (C.c_uint32, []),
            'GetWindowThreadProcessId': (C.c_uint32, [ptr, ptr]),
            'AttachThreadInput': (integer, [C.c_uint32, C.c_uint32, integer]),
            'IsIconic': (integer, [ptr]), 'ShowWindow': (integer, [ptr, integer]),
            'BringWindowToTop': (integer, [ptr]), 'SetForegroundWindow': (integer, [ptr]),
            'SetActiveWindow': (ptr, [ptr]), 'SetFocus': (ptr, [ptr]),
            'Sleep': (None, [C.c_uint32]),
        }
        cls.callbacks = []
        cls.unexpected = []

        def callback(name):
            def invoke(*args):
                if name not in signatures:
                    cls.unexpected.append(name)
                    return 0
                if name == 'GetWindowThreadProcessId':
                    args = args[:1]
                return getattr(cls.backend, name)(*args)
            return invoke

        for rva, name in referenced.items():
            result, args = signatures.get(name, (ptr, []))
            hook = C.CFUNCTYPE(result, *args)(callback(name))
            cls.callbacks.append(hook)
            struct.pack_into('<Q', image, rva-base, C.cast(hook, C.c_void_p).value)

        def send(vk, modifiers, hold):
            return cls.fake_send(cls.backend, vk, hold)

        hook = C.CFUNCTYPE(C.c_uint8, C.c_uint32, ptr, C.c_uint32)(send)
        cls.callbacks.append(hook)
        stub = b'\x48\xb8' + struct.pack('<Q', C.cast(hook, C.c_void_p).value) + b'\xff\xe0'
        image[0xab770-base:0xab770-base+len(stub)] = stub
        k = C.WinDLL('kernel32', use_last_error=True)
        k.VirtualAlloc.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32, C.c_uint32]
        k.VirtualAlloc.restype = C.c_void_p
        k.VirtualProtect.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32, C.POINTER(C.c_uint32)]
        k.VirtualFree.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32]
        address = k.VirtualAlloc(None, len(image), 0x3000, 4)
        if not address:
            raise C.WinError(C.get_last_error())
        cls.addClassCleanup(lambda: k.VirtualFree(address, 0, 0x8000))
        C.memmove(address, bytes(image), len(image))
        old = C.c_uint32()
        if not k.VirtualProtect(address, len(image), 0x20, C.byref(old)):
            raise C.WinError(C.get_last_error())
        cls.native = C.CFUNCTYPE(C.c_uint8, ptr, C.c_uint32, ptr, C.c_uint32, ptr)(address+0xab270-base)

    @classmethod
    def fake_send(cls, backend, vk, hold):
        backend.calls.append(('send', vk, hold))
        if cls.switch_to is not None:
            backend.foreground = cls.switch_to
        if cls.close_previous:
            backend.valid.discard(20)
        return cls.send_success

    def test_activation_cleanup_matrix(self):
        count = 0
        for foreground, threads, failures, activate, success, switch_to in itertools.product(
                (0, 10, 20), ((2, 3), (2, 2), (1, 3), (0, 0)),
                (set(), {2}, {3}, {2, 3}), (False, True), (False, True), (None, 30)):
            for close_previous in (False, True):
                with self.subTest(foreground=foreground, threads=threads, failures=failures,
                                  activate=activate, success=success, switch=switch_to,
                                  close_previous=close_previous):
                    type(self).send_success = success
                    type(self).switch_to = switch_to
                    type(self).close_previous = close_previous
                    def backend():
                        b = FakeWin32()
                        b.foreground, b.threads = foreground, dict(zip((10, 20), threads))
                        b.attach_fail, b.activate, b.iconic = failures, activate, True
                        return b
                    type(self).backend = native_backend = backend()
                    self.unexpected.clear()
                    native = bool(self.native(10, 65, 0, 30, 0))
                    rebuilt_backend = backend()
                    with patch('wowbuddy.windows_keys.send_input',
                               side_effect=lambda b, binding, hold: self.fake_send(b, binding.vk, hold)):
                        rebuilt = activate_and_send(rebuilt_backend, 10, parse_keybinding('A'), 30)[0]
                    self.assertEqual(self.unexpected, [])
                    self.assertEqual(rebuilt, native)
                    self.assertEqual(rebuilt_backend.calls, native_backend.calls)
                    self.assertEqual(rebuilt_backend.foreground, native_backend.foreground)
                    count += 1
        self.assertEqual(count, 768)


if __name__ == '__main__':
    unittest.main()
