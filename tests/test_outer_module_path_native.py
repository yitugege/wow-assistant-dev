"""原25a0缓冲重试控制流与独立read_module_path对照；显式宿主依赖。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.launcher_host import read_module_path, WideBufferResult, WindowsHostAPI


class ModulePathNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path('D:/reverse-analysis/wow-assistant/reconstruction/evidence/outer-observations/original-27ac1127fc/probe/outer-memory-analysis.exe')
        if os.name != 'nt' or not path.exists():
            raise unittest.SkipTest('需要原Windows内存映像')
        import pefile
        import capstone
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != 'fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520':
            raise ValueError('原映像摘要不符')
        pe = pefile.PE(data=payload)
        code = pe.get_data(0x25a0,0x274b-0x25a0)
        decoder = capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
        decoder.detail = True
        instructions = list(decoder.disasm(code,pe.OPTIONAL_HEADER.ImageBase+0x25a0))
        if sum(i.size for i in instructions) != len(code):
            raise ValueError('原控制流解码不完整')
        for i in instructions:
            if i.mnemonic == 'call':
                op = i.operands[0]
                if op.type == capstone.x86.X86_OP_IMM:
                    if op.imm-pe.OPTIONAL_HEADER.ImageBase not in {0x4d50,0x12d00,0x1300,0x1210,0xad90,0x4d8c,0xaa44}:
                        raise ValueError('未知直接调用')
                elif not (op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP
                          and i.address+i.size+op.mem.disp-pe.OPTIONAL_HEADER.ImageBase == 0x14078):
                    raise ValueError('未知间接调用')
        resize_code = pe.get_data(0x1300,0x148c-0x1300)
        resize_instructions = list(decoder.disasm(resize_code,pe.OPTIONAL_HEADER.ImageBase+0x1300))
        if sum(i.size for i in resize_instructions) != len(resize_code):
            raise ValueError('原向量函数解码不完整')
        for i in resize_instructions:
            if i.mnemonic == 'call' or i.group(capstone.CS_GRP_JUMP):
                op = i.operands[0]
                if op.type != capstone.x86.X86_OP_IMM:
                    raise ValueError('原向量函数意外间接控制流')
                target = op.imm-pe.OPTIONAL_HEADER.ImageBase
                if i.mnemonic == 'call':
                    if target not in {0x11a0,0x12d00,0x12660,0x4d8c,0xaa44,0x1a90,0x1bc0}:
                        raise ValueError('原向量函数未知调用')
                elif not 0x1300 <= target < 0x148c:
                    raise ValueError('原向量函数跳转越界')
        k = C.WinDLL('kernel32',use_last_error=True)
        k.VirtualAlloc.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.c_ulong]
        k.VirtualAlloc.restype=C.c_void_p
        k.VirtualProtect.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.POINTER(C.c_ulong)]
        k.VirtualFree.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong]
        k.GetModuleFileNameW.argtypes=[C.c_void_p,C.c_void_p,C.c_uint32]
        k.GetModuleFileNameW.restype=C.c_uint32
        address=k.VirtualAlloc(None,0x15000,0x3000,4)
        if not address:raise C.WinError(C.get_last_error())
        cls.addClassCleanup(lambda:k.VirtualFree(address,0,0x8000))
        cls.state={}
        cls.callbacks=[]

        def allocate(size):
            # 元数据使原大缓冲释放校验可检查到合法的原分配地址。
            buffer=C.create_string_buffer(size+8)
            raw=C.addressof(buffer)
            C.memset(raw,0xa5,size+8)
            C.c_uint64.from_address(raw).value=raw
            cls.state['buffers'].append(buffer)
            return raw+8

        def module(handle,buffer,capacity):
            cls.state['calls'].append(capacity)
            if cls.state.get('live'):
                return k.GetModuleFileNameW(handle,buffer,capacity)
            returned,text=cls.state['answers'].pop(0)
            data=text.encode('utf-16le','surrogatepass')
            data=data[:max(0,capacity-1)*2]+b'\0\0'
            C.memmove(buffer,data,len(data))
            return returned

        def length(pointer):
            count=0
            while C.c_uint16.from_address(pointer+count*2).value:
                count+=1
            return count

        def construct(output,pointer,units):
            cls.state['text']=C.string_at(pointer,units*2).decode('utf-16le','surrogatepass')
            return output

        def release(pointer):
            cls.state['freed'].append(pointer)

        def install(rva,restype,argtypes,fn):
            callback=C.CFUNCTYPE(restype,*argtypes)(fn)
            cls.callbacks.append(callback)
            target=C.cast(callback,C.c_void_p).value
            trampoline=b'\x48\xb8'+target.to_bytes(8,'little')+b'\xff\xe0'
            C.memmove(address+rva,trampoline,len(trampoline))
            return target

        C.memmove(address+0x25a0,code,len(code))
        C.memmove(address+0x1300,resize_code,len(resize_code))
        C.memmove(address+0x14478,pe.get_data(0x14478,4),4)
        install(0x4d50,C.c_void_p,[C.c_size_t],allocate)
        install(0x11a0,C.c_void_p,[C.c_size_t],allocate)
        install(0xad90,C.c_size_t,[C.c_void_p],length)
        install(0x1210,C.c_void_p,[C.c_void_p,C.c_void_p,C.c_size_t],construct)
        install(0x4d8c,None,[C.c_void_p],release)
        target=install(0x8000,C.c_uint32,[C.c_void_p,C.c_void_p,C.c_uint32],module)
        C.c_uint64.from_address(address+0x14078).value=target
        cls.ucrt=C.CDLL('ucrtbase')
        for rva,name in [(0x12d00,'memset'),(0x12660,'memcpy')]:
            target=C.cast(getattr(cls.ucrt,name),C.c_void_p).value
            C.memmove(address+rva,b'\x48\xb8'+target.to_bytes(8,'little')+b'\xff\xe0',12)
        for rva in (0xaa44,0x1a90,0x1bc0):
            C.memmove(address+rva,b'\xcc',1)
        for page in (0x1000,0x2000,0x4000,0x8000,0xa000,0x12000):
            old=C.c_ulong()
            if not k.VirtualProtect(address+page,0x1000,0x20,C.byref(old)):
                raise C.WinError(C.get_last_error())
        cls.native=C.CFUNCTYPE(C.c_void_p,C.c_void_p)(address+0x25a0)
        cls.resize=C.CFUNCTYPE(None,C.c_void_p,C.c_size_t)(address+0x1300)
        cls.allocate=staticmethod(allocate)

    def test_growth_failure_utf16_and_return_count(self):
        cases=[[(0,'')],[(1,'.')],[(10,'C:\\中文\\😀.exe')],[(1022,'x'*1022)],
               [(1023,'x'*1023),(1023,'x'*1023)],
               [(1024,'x'*1023),(2047,'x'*2047),(2047,'x'*2047)],
               [(1024,'x'*1023),(0,'')],[(1023,'x'*1023),(2048,'x'*2047),(0,'')],
               [(1,'actual text longer than returned count')],[(20,'short')],
               [(1,'a\0ignored')],[(1,'\ud800')]]
        for answers in cases:
            with self.subTest(returns=[r for r,t in answers]):
                self.state.clear()
                self.state.update(buffers=[],calls=[],freed=[],answers=list(answers))
                output=C.create_string_buffer(32)
                self.assertEqual(self.native(output),C.addressof(output))
                expected_calls=[]
                pending=list(answers)
                class API:
                    def module_file_name(self,capacity):
                        expected_calls.append(capacity)
                        returned,text=pending.pop(0)
                        return WideBufferResult(returned,text)
                self.assertEqual(self.state['text'],read_module_path(API()))
                self.assertEqual(self.state['calls'],expected_calls)
                self.assertEqual(len(self.state['freed']),len(expected_calls))
                self.assertEqual(self.state['answers'],[])

    def test_actual_windows_module_query(self):
        self.state.clear()
        self.state.update(buffers=[],calls=[],freed=[],live=True)
        output=C.create_string_buffer(32)
        self.assertEqual(self.native(output),C.addressof(output))
        self.assertEqual(self.state['text'],read_module_path(WindowsHostAPI()))
        self.assertTrue(self.state['text'].lower().endswith('.exe'))
        self.assertEqual(self.state['calls'],[1024])
        self.assertEqual(len(self.state['freed']),1)

    def test_actual_vector_resize_growth_and_preservation(self):
        for initial_capacity in (0,1,7,16,2048):
            with self.subTest(capacity=initial_capacity):
                self.state.clear()
                self.state.update(buffers=[],freed=[])
                start=self.allocate(initial_capacity*2) if initial_capacity else 0
                vector=(C.c_uint64*3)(start,start+initial_capacity*2,start+initial_capacity*2)
                expected=list(range(1,initial_capacity+1))
                if expected:
                    data=(C.c_uint16*len(expected))(*expected)
                    C.memmove(start,data,len(expected)*2)
                capacity=initial_capacity
                for requested in (initial_capacity,initial_capacity//2,initial_capacity,
                                  initial_capacity+1,initial_capacity+2,initial_capacity*2+9):
                    old_start=vector[0]
                    previous_frees=len(self.state['freed'])
                    expected=expected[:requested]+[0]*max(0,requested-len(expected))
                    growing=requested>capacity
                    if growing:capacity=max(requested,capacity+capacity//2)
                    self.resize(vector,requested)
                    self.assertEqual((vector[1]-vector[0])//2,requested)
                    self.assertEqual((vector[2]-vector[0])//2,capacity)
                    actual=list((C.c_uint16*requested).from_address(vector[0])) if requested else []
                    self.assertEqual(actual,expected)
                    self.assertEqual(len(self.state['freed'])-previous_frees,int(growing and bool(old_start)))
                    if not growing:self.assertEqual(vector[0],old_start)
                    elif old_start:self.assertNotEqual(vector[0],old_start)


if __name__=='__main__':unittest.main()
