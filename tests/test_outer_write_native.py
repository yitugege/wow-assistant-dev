"""原30e0写入循环与独立实现对照；WinAPI显式注入，不写用户文件。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.launcher import _write_native


class OuterWriteNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path('D:/reverse-analysis/wow-assistant/reconstruction/evidence/outer-observations/original-27ac1127fc/probe/outer-memory-analysis.exe')
        if os.name!='nt' or not path.exists():raise unittest.SkipTest('需要原Windows内存映像')
        import pefile,capstone
        payload=path.read_bytes()
        if hashlib.sha256(payload).hexdigest()!='fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520':
            raise ValueError('原映像摘要不符')
        pe=pefile.PE(data=payload)
        code=pe.get_data(0x30e0,0x31cc-0x30e0)
        decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64);decoder.detail=True
        instructions=list(decoder.disasm(code,pe.OPTIONAL_HEADER.ImageBase+0x30e0))
        if sum(i.size for i in instructions)!=len(code):raise ValueError('写入循环解码不完整')
        calls=[]
        for i in instructions:
            if i.mnemonic=='call':
                op=i.operands[0]
                if op.type!=capstone.x86.X86_OP_MEM or op.mem.base!=capstone.x86.X86_REG_RIP:
                    raise ValueError('未知调用')
                calls.append(i.address+i.size+op.mem.disp-pe.OPTIONAL_HEADER.ImageBase)
            elif i.group(capstone.CS_GRP_JUMP):
                op=i.operands[0]
                if op.type!=capstone.x86.X86_OP_IMM or not 0x30e0<=op.imm-pe.OPTIONAL_HEADER.ImageBase<0x31cc:
                    raise ValueError('跳转越界')
        if calls!=[0x14030,0x14040,0x14050]:raise ValueError('WinAPI调用槽不符')
        k=C.WinDLL('kernel32',use_last_error=True)
        k.VirtualAlloc.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.c_ulong];k.VirtualAlloc.restype=C.c_void_p
        k.VirtualProtect.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.POINTER(C.c_ulong)]
        k.VirtualFree.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong]
        address=k.VirtualAlloc(None,0x15000,0x3000,4)
        if not address:raise C.WinError(C.get_last_error())
        cls.addClassCleanup(lambda:k.VirtualFree(address,0,0x8000))
        C.memmove(address+0x30e0,code,len(code))
        old=C.c_ulong()
        if not k.VirtualProtect(address+0x3000,0x1000,0x20,C.byref(old)):
            raise C.WinError(C.get_last_error())
        cls.address=address
        cls.native=C.CFUNCTYPE(C.c_ubyte,C.c_void_p,C.c_void_p,C.c_uint64)(address+0x30e0)

    def test_chunks_short_writes_failures_and_close(self):
        class FS:
            def __init__(self,plan,create_fail,close_ok):
                self.plan=list(plan);self.create_fail=create_fail;self.close_ok=close_ok
                self.events=[];self.written=bytearray()
            def create_always(self,path):
                self.events.append(('create',path))
                if self.create_fail:raise OSError('create fixture')
                return 123
            def write(self,handle,data):
                self.events.append(('write',handle,len(data),hashlib.sha256(data).hexdigest()))
                result=self.plan.pop(0) if self.plan else len(data)
                if result=='error':raise OSError('write fixture')
                count=min(result,len(data))
                self.written.extend(data[:count])
                return count
            def close(self,handle):self.events.append(('close',handle));return self.close_ok
        cases=[(size,[],False,True) for size in (0,1,0xfffff,0x100000,0x100001,0x200011)]
        cases += [(50,[1,3,7],False,True),(50,[1,3,0],False,True),
                  (50,[17,'error'],False,True),(50,['error'],False,True),
                  (50,[],True,True),(0,[],True,True),(50,[],False,False)]
        for size,plan,create_fail,close_ok in cases:
            for path in ('a','D:\\测试\\member.bin'):
                with self.subTest(size=size,plan=plan,path=path,close_ok=close_ok):
                    data=(bytes(range(256))*(size//256+1))[:size]
                    native_fs=FS(plan,create_fail,close_ok);python_fs=FS(plan,create_fail,close_ok)
                    parameters=[]
                    def create(name,access,share,security,disposition,attributes,template):
                        parameters.append((access,share,security,disposition,attributes,template))
                        try:return native_fs.create_always(name)
                        except OSError:return C.c_void_p(-1).value
                    def write(handle,pointer,count,written,overlapped):
                        parameters.append(('overlapped',overlapped))
                        try:
                            written[0]=native_fs.write(handle,C.string_at(pointer,count));return 1
                        except OSError:return 0
                    def close(handle):return int(native_fs.close(handle))
                    callbacks=[C.CFUNCTYPE(C.c_void_p,C.c_wchar_p,C.c_uint32,C.c_uint32,C.c_void_p,C.c_uint32,C.c_uint32,C.c_void_p)(create),
                               C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_void_p,C.c_uint32,C.POINTER(C.c_uint32),C.c_void_p)(write),
                               C.CFUNCTYPE(C.c_int,C.c_void_p)(close)]
                    for slot,callback in zip((0x14030,0x14040,0x14050),callbacks):
                        C.c_uint64.from_address(self.address+slot).value=C.cast(callback,C.c_void_p).value
                    encoded=path.encode('utf-16le');units=len(encoded)//2
                    text=C.create_string_buffer(encoded+b'\0\0')
                    obj=C.create_string_buffer(32);fields=(C.c_uint64*4).from_buffer(obj)
                    fields[2]=units;fields[3]=7 if units<8 else units|7
                    if units<8:C.memmove(obj,encoded+b'\0\0',len(encoded)+2)
                    else:fields[0]=C.addressof(text)
                    buffer=C.create_string_buffer(data)
                    actual=bool(self.native(obj,buffer,len(data)))
                    expected=_write_native(python_fs,path,data)
                    self.assertEqual(actual,expected)
                    self.assertEqual(native_fs.events,python_fs.events)
                    self.assertEqual(native_fs.written,python_fs.written)
                    self.assertEqual(parameters[0],(0x40000000,0,None,2,0x80,None))
                    self.assertTrue(all(value==('overlapped',None) for value in parameters[1:]))
                    self.assertEqual(actual,not(create_fail or 0 in plan or 'error' in plan))


if __name__=='__main__':unittest.main()
