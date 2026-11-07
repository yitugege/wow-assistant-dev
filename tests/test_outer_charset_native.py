"""执行原字符集合搜索链；memcpy/memset由宿主UCRT提供，非完整原CRT验证。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import random
import unittest
import test_outer_path_native as path_tests


class OuterCharsetNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path('D:/reverse-analysis/wow-assistant/reconstruction/evidence/outer-observations/original-27ac1127fc/probe/outer-memory-analysis.exe')
        if os.name != 'nt' or not path.exists():
            raise unittest.SkipTest('需要原Windows内存映像')
        import capstone
        import pefile
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != 'fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520':
            raise ValueError('原映像摘要不匹配')
        pe = pefile.PE(data=payload)
        base = pe.OPTIONAL_HEADER.ImageBase
        spans = [(0x43d0,0x4429),(0x4430,0x4604),(0x4610,0x4822),
                 (0x4830,0x4965),(0x4970,0x4acc),(0x4eb0,0x4ece)]
        allowed_calls = {0x43d0,0x4610,0x4830,0x4970,0x4eb0,0x12660,0x12d00}
        decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        decoder.detail = True
        k = C.WinDLL('kernel32', use_last_error=True)
        k.VirtualAlloc.argtypes = [C.c_void_p,C.c_size_t,C.c_ulong,C.c_ulong]
        k.VirtualAlloc.restype = C.c_void_p
        k.VirtualProtect.argtypes = [C.c_void_p,C.c_size_t,C.c_ulong,C.POINTER(C.c_ulong)]
        k.VirtualFree.argtypes = [C.c_void_p,C.c_size_t,C.c_ulong]
        address = k.VirtualAlloc(None,0x22000,0x3000,4)
        if not address:
            raise C.WinError(C.get_last_error())
        cls.addClassCleanup(lambda:k.VirtualFree(address,0,0x8000))
        cls.kernel = k
        for start,end in spans:
            code = pe.get_data(start,end-start)
            instructions = list(decoder.disasm(code,base+start))
            if sum(i.size for i in instructions) != len(code):
                raise ValueError('原函数未完全解码')
            for i in instructions:
                if i.mnemonic == 'call' or i.group(capstone.CS_GRP_JUMP):
                    operand = i.operands[0]
                    if operand.type != capstone.x86.X86_OP_IMM:
                        raise ValueError('意外间接控制流')
                    target = operand.imm-base
                    valid = target in allowed_calls if i.mnemonic == 'call' else (
                        any(a <= target < b for a,b in spans) or target == 0x545c)
                    if not valid:
                        raise ValueError(f'未经审读的目标{target:#x}')
            C.memmove(address+start,code,len(code))
        # 原cookie检查保留，失败目标为测试进程陷阱，不能继续执行未映射代码。
        C.memmove(address+0x545c,b'\xcc',1)
        cls.ucrt = C.CDLL('ucrtbase')
        for rva,name in [(0x12660,'memcpy'),(0x12d00,'memset')]:
            target = C.cast(getattr(cls.ucrt,name),C.c_void_p).value
            trampoline = b'\x48\xb8'+target.to_bytes(8,'little')+b'\xff\xe0'
            C.memmove(address+rva,trampoline,len(trampoline))
        C.memmove(address+0x16000,pe.get_data(0x16000,0x1000),0x1000)
        cls.flags = C.c_uint32.from_address(address+0x21094)
        for rva,size,protection in [(0x4000,0x2000,0x20),(0x12000,0x1000,0x20),(0x16000,0x1000,2)]:
            previous = C.c_ulong()
            if not k.VirtualProtect(address+rva,size,protection,C.byref(previous)):
                raise C.WinError(C.get_last_error())
        cls.search = C.CFUNCTYPE(C.c_uint64,C.c_void_p,C.c_uint64,C.c_void_p,C.c_uint64)(address+0x4430)

    def run_cases(self,flags):
        self.flags.value = flags
        rng = random.Random(0x4430)
        count = 0
        for length in (0,1,7,8,9,15,16,17,31,32,33,48,49,80,81,128,129):
            for size in (0,1,2,8,9,20,21,80,81):
                for wide in (False,True):
                    charset = [rng.randrange(256) for _ in range(size)]
                    if wide and size:
                        charset[-1] = 0x4e2d
                    for match in ('none','first','last'):
                        text = [rng.choice([0x100,0xd800,0xdc00,0xffff]) for _ in range(length)]
                        if match != 'none' and length and size:
                            text[0 if match == 'first' else -1] = charset[-1]
                        source = (C.c_uint16 * max(1,len(text)))(*text)
                        needles = (C.c_uint16 * max(1,len(charset)))(*charset)
                        wanted = set(charset)
                        expected = next((i for i in range(len(text)-1,-1,-1) if text[i] in wanted),2**64-1)
                        actual = self.search(source,len(text),needles,len(charset))
                        self.assertEqual(actual,expected,(flags,length,size,wide,match))
                        count += 1
        self.assertEqual(count,918)

    def test_scalar(self):
        self.run_cases(0)

    def test_sse42(self):
        if not all(self.kernel.IsProcessorFeaturePresent(n) for n in (37,38)):
            self.skipTest('缺少SSE4.1/4.2')
        self.run_cases(4)

    def test_avx2(self):
        path_tests.OuterPathNativeTests.require_avx2(self)
        if not all(self.kernel.IsProcessorFeaturePresent(n) for n in (37,38)):
            self.skipTest('缺少SSE4回退支持')
        self.run_cases(0x24)


if __name__ == '__main__':
    unittest.main()
