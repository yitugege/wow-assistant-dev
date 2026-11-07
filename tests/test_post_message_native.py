"""原 0aa7e0 机器码与独立版对照；导入全部替换为记录回调，无真实输入。"""
import ctypes as C
import hashlib
import itertools
import os
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
sys.path.insert(0, str(ROOT / 'tests/core'))
from test_windows_keys import FakeWin32
from wowbuddy.keybindings import KeyBinding
from wowbuddy.windows_keys import post_message


class PostMessageNativeTests(unittest.TestCase):
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
        base = pe.OPTIONAL_HEADER.ImageBase + 0xaa7e0
        code = bytearray(pe.get_data(0xaa7e0, 0x145))
        imports = {i.address: i.name.decode() for d in pe.DIRECTORY_ENTRY_IMPORT
                   for i in d.imports if i.name}
        cls.events = []
        cls.results = []

        def valid(hwnd):
            cls.events.append(('IsWindow', hwnd))
            return int(hwnd == 10)

        def post(hwnd, message, vk, param):
            cls.events.append(('PostMessageW', hwnd, message, vk, param))
            return cls.results.pop(0)

        def sleep(milliseconds):
            cls.events.append(('Sleep', milliseconds))

        cls.callbacks = {
            'IsWindow': C.CFUNCTYPE(C.c_int, C.c_void_p)(valid),
            'PostMessageW': C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32,
                                       C.c_size_t, C.c_ssize_t)(post),
            'Sleep': C.CFUNCTYPE(None, C.c_uint32)(sleep),
        }
        slots = {name: 512 + 8 * index for index, name in enumerate(cls.callbacks)}
        decoder = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64)
        decoder.detail = True
        patched = []
        for ins in decoder.disasm(code, base):
            for operand in ins.operands:
                if operand.type == cs.x86.X86_OP_MEM and operand.mem.base == cs.x86.X86_REG_RIP:
                    assert ins.mnemonic == 'call'
                    name = imports[ins.address + ins.size + operand.mem.disp]
                    assert name in slots, name
                    offset = ins.address - base
                    struct.pack_into('<i', code, offset + ins.disp_offset,
                                     slots[name] - offset - ins.size)
                    patched.append(name)
        assert sorted(patched) == sorted(['IsWindow', 'Sleep'] + ['PostMessageW'] * 4)
        code.extend(bytes(536 - len(code)))
        for name, callback in cls.callbacks.items():
            struct.pack_into('<Q', code, slots[name], C.cast(callback, C.c_void_p).value)
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.VirtualAlloc.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32, C.c_uint32]
        kernel.VirtualAlloc.restype = C.c_void_p
        kernel.VirtualProtect.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32, C.POINTER(C.c_uint32)]
        kernel.VirtualFree.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32]
        address = kernel.VirtualAlloc(None, len(code), 0x3000, 4)
        if not address:
            raise C.WinError(C.get_last_error())
        cls.addClassCleanup(lambda: kernel.VirtualFree(address, 0, 0x8000))
        C.memmove(address, bytes(code), len(code))
        previous = C.c_uint32()
        if not kernel.VirtualProtect(address, len(code), 0x20, C.byref(previous)):
            raise C.WinError(C.get_last_error())
        cls.native = C.CFUNCTYPE(C.c_uint8, C.c_void_p, C.c_int32, C.c_void_p)(address)

    def compare(self, modifiers, results, hwnd=10):
        self.events.clear()
        self.results[:] = results
        data = (C.c_int32 * len(modifiers))(*modifiers)
        array = (C.c_void_p * 3)(None, C.addressof(data), len(modifiers))
        native_result = bool(self.native(hwnd, 111, C.byref(array)))
        backend = FakeWin32()
        backend.post_results = list(results)
        python_result = post_message(backend, hwnd, KeyBinding(111, modifiers, True))
        self.assertEqual(python_result, native_result)
        self.assertEqual(backend.calls, self.events)
        self.assertEqual(backend.post_results, self.results)

    def test_all_failure_combinations_and_release_order(self):
        count = 0
        for modifiers in ((), (18,), (18, 17), (18, 17, 16)):
            for results in itertools.product((0, 1), repeat=2 * (len(modifiers) + 1)):
                with self.subTest(modifiers=modifiers, results=results):
                    self.compare(modifiers, results)
                count += 1
        self.assertEqual(count, 340)

    def test_null_and_invalid_window(self):
        for hwnd in (0, 99):
            with self.subTest(hwnd=hwnd):
                self.compare((18, 17, 16), [], hwnd)


if __name__ == '__main__':
    unittest.main()
