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
        string_blocks=[]
        for start,end in [(0x11a0,0x120a),(0x1210,0x12fa)]:
            block=pe.get_data(start,end-start)
            decoded=list(decoder.disasm(block,pe.OPTIONAL_HEADER.ImageBase+start))
            if sum(i.size for i in decoded)!=len(block):
                raise ValueError('字符串依赖解码不完整')
            for i in decoded:
                if i.mnemonic=='call' or i.group(capstone.CS_GRP_JUMP):
                    op=i.operands[0]
                    if op.type!=capstone.x86.X86_OP_IMM:
                        raise ValueError('字符串依赖意外间接控制流')
                    target=op.imm-pe.OPTIONAL_HEADER.ImageBase
                    if not (start<=target<end or target in {0x11a0,0x4d50,0x12660,0x1a90,0x1ba0,0xaa44}):
                        raise ValueError('字符串依赖未知控制流')
            string_blocks.append((start,block))
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
        for start,block in string_blocks:
            C.memmove(address+start,block,len(block))
        C.memmove(address+0x14478,pe.get_data(0x14478,4),4)
        install(0x4d50,C.c_void_p,[C.c_size_t],allocate)
        install(0xad90,C.c_size_t,[C.c_void_p],length)
        install(0x4d8c,None,[C.c_void_p],release)
        target=install(0x8000,C.c_uint32,[C.c_void_p,C.c_void_p,C.c_uint32],module)
        C.c_uint64.from_address(address+0x14078).value=target
        cls.ucrt=C.CDLL('ucrtbase')
        for rva,name in [(0x12d00,'memset'),(0x12660,'memcpy')]:
            target=C.cast(getattr(cls.ucrt,name),C.c_void_p).value
            C.memmove(address+rva,b'\x48\xb8'+target.to_bytes(8,'little')+b'\xff\xe0',12)
        for rva in (0xaa44,0x1a90,0x1ba0,0x1bc0):
            C.memmove(address+rva,b'\xcc',1)
        for page in (0x1000,0x2000,0x4000,0x8000,0xa000,0x12000):
            old=C.c_ulong()
            if not k.VirtualProtect(address+page,0x1000,0x20,C.byref(old)):
                raise C.WinError(C.get_last_error())
        cls.native=C.CFUNCTYPE(C.c_void_p,C.c_void_p)(address+0x25a0)
        cls.resize=C.CFUNCTYPE(None,C.c_void_p,C.c_size_t)(address+0x1300)
        cls.construct=C.CFUNCTYPE(None,C.c_void_p,C.c_void_p,C.c_size_t)(address+0x1210)
        cls.aligned_allocate=C.CFUNCTYPE(C.c_void_p,C.c_size_t)(address+0x11a0)
        cls.allocate=staticmethod(allocate)

    def decode_string(self,output):
        fields=(C.c_uint64*4).from_buffer(output)
        pointer=C.addressof(output) if fields[3]<=7 else fields[0]
        self.assertEqual(C.c_uint16.from_address(pointer+fields[2]*2).value,0)
        return C.string_at(pointer,fields[2]*2).decode('utf-16le','surrogatepass')

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
                self.assertEqual(self.decode_string(output),read_module_path(API()))
                self.assertEqual(self.state['calls'],expected_calls)
                self.assertEqual(len(self.state['freed']),len(expected_calls))
                self.assertEqual(self.state['answers'],[])

    def test_actual_windows_module_query(self):
        self.state.clear()
        self.state.update(buffers=[],calls=[],freed=[],live=True)
        output=C.create_string_buffer(32)
        self.assertEqual(self.native(output),C.addressof(output))
        self.assertEqual(self.decode_string(output),read_module_path(WindowsHostAPI()))
        self.assertTrue(self.decode_string(output).lower().endswith('.exe'))
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

    def test_original_string_layout_and_large_alignment(self):
        self.state.clear()
        self.state.update(buffers=[],freed=[])
        for units in (0,1,7,8,9,15,16,31,2040,2048,4096):
            with self.subTest(units=units):
                raw=b''.join((i%65536).to_bytes(2,'little') for i in range(units))
                source=C.create_string_buffer(raw)
                output=C.create_string_buffer(b'\xa5'*32,32)
                self.construct(output,source,units)
                fields=(C.c_uint64*4).from_buffer(output)
                self.assertEqual(fields[2],units)
                self.assertEqual(fields[3],7 if units<8 else units|7)
                self.assertEqual(self.decode_string(output).encode('utf-16le','surrogatepass'),raw)
                if (fields[3]+1)*2>=4096:
                    self.assertEqual(fields[0]%32,0)
                    original=C.c_uint64.from_address(fields[0]-8).value
                    self.assertLessEqual(fields[0]-original-8,31)
        for size in (0,1,4095,4096,4097,8192):
            pointer=self.aligned_allocate(size)
            if not size:self.assertIsNone(pointer)
            elif size>=4096:self.assertEqual(pointer%32,0)


if __name__=='__main__':unittest.main()
