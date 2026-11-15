"""独立生成x64保护线程入口；不使用Python线程回调，不自动卸载SDK。"""
import ctypes as C
import os
import struct

_workers = []


def start_windows_protection_thread():
    """正式宿主启动回调；原CreateThread失败不阻止释放及启动业务程序。"""
    try:
        task = NativeProtectionThread()
        _workers.append(task)
        return task.start()
    except OSError:
        return None


def worker_code():
    """RCX为8个指针的数据表；Win64 ABI，保留非易失寄存器和shadow space。"""
    code=bytearray();labels={};fixups=[]
    def emit(value):code.extend(bytes.fromhex(value))
    def label(name):labels[name]=len(code)
    def jump(op,name):
        emit(op);fixups.append((len(code),name));code.extend(b'\0'*4)
    emit('53 56 57 41 54 41 55 48 83 ec 20 48 89 cb')
    # LoadLibraryW(name)，RSI为模块句柄。
    emit('48 8b 0b ff 53 20 48 89 c6 48 85 c0');jump('0f 84','done')
    for offset,dest in ((8,'48 89 c7'),(16,'49 89 c4'),(24,'49 89 c5')):
        emit('48 89 f1 48 8b 53');code.append(offset);emit('ff 53 28 '+dest)
    for test in ('48 85 ff','4d 85 e4','4d 85 ed'):
        emit(test);jump('0f 84','done')
    emit('ff d7 84 c0');jump('0f 84','done')
    emit('31 f6')
    label('loop');emit('b9 88 13 00 00 ff 53 30 41 ff d4 48 85 c0');jump('0f 85','debugger')
    emit('41 ff d5 84 c0');jump('0f 85','reset')
    emit('ff c6 83 fe 02');jump('0f 83','crc')
    jump('e9','loop')
    label('reset');emit('31 f6');jump('e9','loop')
    label('debugger');emit('b9 0b 00 00 00');jump('e9','terminate')
    label('crc');emit('b9 0c 00 00 00')
    label('terminate');emit('ff 53 38 cc')
    label('done');emit('31 c0 48 83 c4 20 41 5d 41 5c 5f 5e 5b c3')
    for offset,name in fixups:struct.pack_into('<i',code,offset,labels[name]-offset-4)
    return bytes(code)


class NativeProtectionThread:
    """私有代码/数据页保留至进程退出；调用start才启动，不join也不CloseHandle。"""
    def __init__(self, *, terminate_address=None):
        if os.name!='nt' or C.sizeof(C.c_void_p)!=8:
            raise OSError('保护线程仅支持Windows x64')
        self.k=C.WinDLL('kernel32',use_last_error=True)
        signatures={
            'VirtualAlloc':([C.c_void_p,C.c_size_t,C.c_uint32,C.c_uint32],C.c_void_p),
            'VirtualProtect':([C.c_void_p,C.c_size_t,C.c_uint32,C.POINTER(C.c_uint32)],C.c_int),
            'FlushInstructionCache':([C.c_void_p,C.c_void_p,C.c_size_t],C.c_int),
            'GetCurrentProcess':([],C.c_void_p),
            'CreateThread':([C.c_void_p,C.c_size_t,C.c_void_p,C.c_void_p,C.c_uint32,C.c_void_p],C.c_void_p)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.k,name);fn.argtypes=args;fn.restype=result
        # 原0xad78与系统ucrtbase.quick_exit同为EDX=1/R8D=0的公共退出入口。
        # 不用ExitProcess替代CRT清理路径；DLL对象保留在实例上。
        self.crt = C.CDLL('ucrtbase') if terminate_address is None else None
        self.terminate_address=(C.cast(self.crt.quick_exit,C.c_void_p).value
                                if terminate_address is None else terminate_address)
        self.started=False;self.handle=None

    def start(self):
        if self.started:raise RuntimeError('同一线程入口不能重复启动')
        self.started=True
        # 所有线程所需数据都复制到Win32私有页，避免解释器清理Python缓冲。
        data=bytearray(64)
        for index,text in enumerate(('SProtectSDK64.dll','SPIsProtected','SPCheckDebugger','SPCrc')):
            if index==0 and len(data)%2:data.append(0)
            offset=len(data)
            encoded=(text+'\0').encode('utf-16le' if index==0 else 'ascii')
            data.extend(encoded);struct.pack_into('<Q',data,index*8,offset)
        for index,name in enumerate(('LoadLibraryW','GetProcAddress','Sleep'),4):
            struct.pack_into('<Q',data,index*8,C.cast(getattr(self.k,name),C.c_void_p).value)
        struct.pack_into('<Q',data,56,self.terminate_address)
        self.data=self.k.VirtualAlloc(None,len(data),0x3000,4)
        if not self.data:raise C.WinError(C.get_last_error())
        for index in range(4):struct.pack_into('<Q',data,index*8,struct.unpack_from('<Q',data,index*8)[0]+self.data)
        C.memmove(self.data,bytes(data),len(data))
        code=worker_code();self.code=self.k.VirtualAlloc(None,len(code),0x3000,4)
        if not self.code:raise C.WinError(C.get_last_error())
        C.memmove(self.code,code,len(code));old=C.c_uint32()
        if not self.k.VirtualProtect(self.code,len(code),0x20,C.byref(old)):raise C.WinError(C.get_last_error())
        if not self.k.FlushInstructionCache(self.k.GetCurrentProcess(),self.code,len(code)):raise C.WinError(C.get_last_error())
        self.handle=self.k.CreateThread(None,0,self.code,self.data,0,None)
        return self.handle
