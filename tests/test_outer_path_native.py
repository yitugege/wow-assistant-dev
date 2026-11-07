"""以原外层4ad0的UTF16反向搜索核对路径边界；只运行隔离叶函数。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.launcher import module_directory


class OuterPathNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path('D:/reverse-analysis/wow-assistant/reconstruction/evidence/outer-observations/original-27ac1127fc/probe/outer-memory-analysis.exe')
        if os.name != 'nt' or not path.is_file():
            raise unittest.SkipTest('需要原Windows x64内存映像')
        import capstone
        import pefile
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != 'fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520':
            raise ValueError('原映像摘要不匹配')
        pe = pefile.PE(data=payload)
        start, end = 0x4ad0, 0x4c27
        code = pe.get_data(start, end-start)
        decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        decoder.detail = True
        instructions = list(decoder.disasm(code, pe.OPTIONAL_HEADER.ImageBase+start))
        if sum(i.size for i in instructions) != len(code):
            raise ValueError('叶函数未完全解码')
        for instruction in instructions:
            if instruction.mnemonic == 'call':
                raise ValueError('意外外部调用')
            if instruction.group(capstone.CS_GRP_JUMP):
                operand = instruction.operands[0]
                if (operand.type != capstone.x86.X86_OP_IMM or
                        not start <= operand.imm-pe.OPTIONAL_HEADER.ImageBase < end):
                    raise ValueError('跳转超出已审读函数')
        k = C.WinDLL('kernel32', use_last_error=True)
        k.VirtualAlloc.argtypes = [C.c_void_p, C.c_size_t, C.c_ulong, C.c_ulong]
        k.VirtualAlloc.restype = C.c_void_p
        k.VirtualProtect.argtypes = [C.c_void_p, C.c_size_t, C.c_ulong, C.POINTER(C.c_ulong)]
        k.VirtualFree.argtypes = [C.c_void_p, C.c_size_t, C.c_ulong]
        address = k.VirtualAlloc(None, 0x22000, 0x3000, 4)
        if not address:
            raise C.WinError(C.get_last_error())
        cls.addClassCleanup(lambda: k.VirtualFree(address, 0, 0x8000))
        cls.kernel = k
        cls.cpu_flags = C.c_uint32.from_address(address+0x21094)
        C.memmove(address+start, code, len(code))
        # 私有映像RVA21094保留为0，明确只测基线CPU分支；不启动原CRT或SDK。
        previous = C.c_ulong()
        if not k.VirtualProtect(address+0x4000, 0x1000, 0x20, C.byref(previous)):
            raise C.WinError(C.get_last_error())
        cls.native = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_void_p, C.c_uint16)(address+start)

    def original_offset(self, value, separator):
        data = value.encode('utf-16le', 'surrogatepass')
        buffer = C.create_string_buffer(data, len(data)+64)
        begin = C.addressof(buffer)
        finish = begin+len(data)
        result = self.native(begin, finish, ord(separator))
        if result == finish:
            return -1
        self.assertGreaterEqual(result, begin)
        self.assertLess(result, finish)
        self.assertEqual((result-begin) % 2, 0)
        return result-begin

    def test_reverse_search_and_module_directory(self):
        self.cpu_flags.value = 0
        self.check_reverse_search_and_module_directory()

    def test_sse2_reverse_search_and_module_directory(self):
        # x64保证SSE2；原4bd2..4c1d仅使用SSE2/整数指令，不进入AVX2。
        self.cpu_flags.value = 4
        self.check_reverse_search_and_module_directory()

    def check_reverse_search_and_module_directory(self):
        values = ['', '.', 'x.exe', '/', '\\', 'C:\\x.exe', 'C:/x.exe',
                  '\\\\server\\share\\x.exe', 'C:\\中文/😀\\x.exe',
                  'C:\\a\ud800/b.exe', 'C:/a\udc00\\b.exe']
        rng = random.Random(0x4ad0)
        for length in [1, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65, 128, 259, 260, 511]:
            for _ in range(12):
                values.append(''.join(rng.choice('ab中😀/\\') for _ in range(length)))
        for value in values:
            with self.subTest(value=ascii(value)):
                offsets = []
                for separator in ('/', '\\'):
                    actual = self.original_offset(value, separator)
                    index = value.rfind(separator)
                    expected = -1 if index < 0 else len(value[:index].encode('utf-16le', 'surrogatepass'))
                    self.assertEqual(actual, expected)
                    offsets.append(actual)
                cut = max(offsets)
                original = '.' if cut < 0 else value.encode('utf-16le', 'surrogatepass')[:cut].decode('utf-16le', 'surrogatepass')
                self.assertEqual(module_directory(value), original)
        self.assertEqual(len(values), 215)

    def test_sse2_guarded_buffer_boundaries(self):
        self.cpu_flags.value = 4
        k = self.kernel
        address = k.VirtualAlloc(None, 0x3000, 0x3000, 4)
        if not address:
            raise C.WinError(C.get_last_error())
        self.addCleanup(lambda: k.VirtualFree(address, 0, 0x8000))
        previous = C.c_ulong()
        for guard in (address, address+0x2000):
            if not k.VirtualProtect(guard, 0x1000, 1, C.byref(previous)):
                raise C.WinError(C.get_last_error())
        count = 0
        for length in (0, 1, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65):
            for match in range(-1, length):
                units = [0x4e2d] * length
                if match >= 0:
                    units[match] = 0x5c
                data = b''.join(unit.to_bytes(2, 'little') for unit in units)
                for begin in (address+0x1000, address+0x2000-len(data)):
                    C.memmove(begin, data, len(data))
                    finish = begin+len(data)
                    result = self.native(begin, finish, 0x5c)
                    self.assertEqual(result, finish if match < 0 else begin+match*2,
                                     (length, match, begin % 16))
                    count += 1
        self.assertEqual(count, 750)


if __name__ == '__main__':
    unittest.main()
