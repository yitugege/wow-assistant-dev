"""隔离执行原CRT刷新入口；写入/提交均为记录器，不执行原退出流程。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import unittest


class OuterStreamFlushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path('D:/reverse-analysis/wow-assistant/reconstruction/evidence/outer-observations/original-27ac1127fc/probe/outer-memory-analysis.exe')
        if os.name!='nt' or not path.exists():raise unittest.SkipTest('需要Windows原映像')
        import pefile,capstone
        payload=path.read_bytes()
        if hashlib.sha256(payload).hexdigest()!='fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520':
            raise ValueError('原映像身份不符')
        pe=pefile.PE(data=payload)
        try:
            code=pe.get_data(0xf9c8,0xfb26-0xf9c8);base=pe.OPTIONAL_HEADER.ImageBase
        finally:pe.close()
        decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64);decoder.detail=True
        instructions=list(decoder.disasm(code,base+0xf9c8))
        if sum(i.size for i in instructions)!=len(code):raise ValueError('解码不完整')
        allowed={0xa638,0xf968,0xf9c8,0x1030c,0x10d28,0x115e8}
        for i in instructions:
            if i.mnemonic=='call' or i.group(capstone.CS_GRP_JUMP):
                op=i.operands[0]
                if op.type!=capstone.x86.X86_OP_IMM:raise ValueError('未知间接控制流')
                target=op.imm-base
                if i.mnemonic=='call':
                    if target not in allowed:raise ValueError('未注入调用')
                elif not 0xf9c8<=target<0xfb26:raise ValueError('跳转越界')
        k=C.WinDLL('kernel32',use_last_error=True)
        k.VirtualAlloc.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.c_ulong];k.VirtualAlloc.restype=C.c_void_p
        k.VirtualProtect.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.POINTER(C.c_ulong)]
        k.VirtualFree.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong]
        address=k.VirtualAlloc(None,0x23000,0x3000,4)
        if not address:raise C.WinError(C.get_last_error())
        cls.addClassCleanup(lambda:k.VirtualFree(address,0,0x8000))
        C.memmove(address+0xf9c8,code,len(code))
        cls.events=[];cls.state={};cls.callbacks=[]
        def descriptor(pointer):
            cls.events.append(('descriptor',pointer))
            return C.c_int.from_address(pointer+0x18).value
        def write(fd,pointer,size,context):
            cls.events.append(('write',fd,pointer,size,bool(context)))
            return cls.state.get('written',size)
        def commit(fd):
            cls.events.append(('commit',fd));return cls.state.get('commit',0)
        def flush_all(mode):
            cls.events.append(('all',mode));return cls.state.get('all',0)
        cls.thread=C.create_string_buffer(0x400)
        def thread_context(context):
            cls.events.append(('unexpected-thread-context',context));return C.addressof(cls.thread)
        stubs=[(0x1030c,C.CFUNCTYPE(C.c_int,C.c_void_p),descriptor),
               (0x115e8,C.CFUNCTYPE(C.c_int,C.c_int,C.c_void_p,C.c_uint,C.c_void_p),write),
               (0x10d28,C.CFUNCTYPE(C.c_int,C.c_int),commit),
               (0xf968,C.CFUNCTYPE(C.c_int,C.c_ubyte),flush_all),
               (0xa638,C.CFUNCTYPE(C.c_void_p,C.c_void_p),thread_context)]
        for rva,prototype,fn in stubs:
            callback=prototype(fn);cls.callbacks.append(callback)
            jump=b'\x48\xb8'+C.cast(callback,C.c_void_p).value.to_bytes(8,'little')+b'\xff\xe0'
            C.memmove(address+rva,jump,len(jump))
        old=C.c_ulong()
        for page in (0xa000,0xf000,0x10000,0x11000):
            if not k.VirtualProtect(address+page,0x1000,0x20,C.byref(old)):
                raise C.WinError(C.get_last_error())
        cls.address=address
        cls.flush=C.CFUNCTYPE(C.c_int,C.c_void_p)(address+0xfa54)

    def setUp(self):
        self.events.clear();self.state.clear()

    def test_original_flush_buffer_commit_and_pointer_width(self):
        # 全局上下文初始化两个分支×缓冲状态×写入/提交结果。
        for context_mode in (0,1):
            for flags,pending,written,committed in (
                (0,7,7,0),(0x42,0,0,0),(0x42,7,7,0),
                (0x46,7,7,0),(0x42,7,3,0),(0x42,7,-1,0),
                (0x842,7,7,0),(0x842,7,7,-1),(0x842,7,3,0),
                (0x800,0,0,0),(0x43,7,7,0)):
                with self.subTest(context_mode=context_mode,flags=flags,written=written,committed=committed):
                    self.events.clear();self.state.update(written=written,commit=committed)
                    C.c_uint32.from_address(self.address+0x22504).value=context_mode
                    C.memset(self.address+0x21248,0xa5,16)
                    stream=C.create_string_buffer(0x40);buffer=C.create_string_buffer(32)
                    pointer=C.addressof(stream);data=C.addressof(buffer)
                    self.assertGreater(pointer,0xffffffff)
                    C.c_void_p.from_buffer(stream,0).value=data+pending
                    C.c_void_p.from_buffer(stream,8).value=data
                    C.c_int.from_buffer(stream,0x10).value=99
                    C.c_uint.from_buffer(stream,0x14).value=flags
                    C.c_int.from_buffer(stream,0x18).value=23
                    active=flags&3==2 and bool(flags&0xc0)
                    write_expected=active and pending>0
                    failed=write_expected and written!=pending
                    commit_expected=not failed and bool(flags&0x800)
                    expected=[]
                    if write_expected:expected += [('descriptor',pointer),('write',23,data,pending,True)]
                    if commit_expected:expected += [('descriptor',pointer),('commit',23)]
                    self.assertEqual(self.flush(stream),-1 if failed or (commit_expected and committed) else 0)
                    self.assertEqual(self.events,expected)
                    self.assertEqual(C.c_void_p.from_buffer(stream,0).value,data if active else data+pending)
                    self.assertEqual(C.c_int.from_buffer(stream,0x10).value,0 if active else 99)
                    final_flags=flags|0x10 if failed else flags
                    if write_expected and not failed and flags&4:final_flags &= ~2
                    self.assertEqual(C.c_uint.from_buffer(stream,0x14).value,final_flags)

    def test_null_stream_dispatches_flush_all_false(self):
        for mode in (0,1):
            for result in (0,-1,7):
                self.events.clear();self.state['all']=result
                C.c_uint32.from_address(self.address+0x22504).value=mode
                self.assertEqual(self.flush(None),result)
                self.assertEqual(self.events,[('all',0)])


if __name__=='__main__':unittest.main()
