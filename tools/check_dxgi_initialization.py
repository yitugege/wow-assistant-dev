"""只读记录真实 DXGI 初始化调用，不创建窗口、不抓屏、不发键。"""
import ctypes as C
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))


def check():
    import wowbuddy.capture as capture
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    if app.platformName()!='windows':raise RuntimeError('需要 Windows Qt 平台')
    backend=capture.Win32DxgiBackend()
    screen=app.primaryScreen().geometry()
    rect=capture.Rect(screen.x(),screen.y(),screen.x()+screen.width(),screen.y()+screen.height())
    monitor=backend.monitor_from_rect(rect)
    calls=[]
    native_com=capture._com
    native_create=backend.d3d11.D3D11CreateDevice
    def trace(pointer,slot,result,args,*values):
        hr=native_com(pointer,slot,result,args,*values)
        if result==capture.I32:
            calls.append({'slot':slot,'hresult':f'0x{hr & 0xffffffff:08X}'})
        if slot==7 and args==[C.POINTER(capture._OUTPUT_DESC)] and not capture.failed(hr):
            desc=C.cast(values[0],C.POINTER(capture._OUTPUT_DESC)).contents
            calls.append({'output_monitor':desc.monitor,'rotation':desc.rotation,'attached':desc.attached})
        return hr
    def create(*args):
        hr=native_create(*args)
        calls.append({'D3D11CreateDevice':f'0x{hr & 0xffffffff:08X}'})
        return hr
    try:
        with patch.object(capture,'_com',trace),patch.object(backend.d3d11,'D3D11CreateDevice',create):
            outcome=backend.initialize(monitor)
        return {'initialized':outcome.status=='ok','monitor':monitor,
                'status':outcome.status,'calls':calls,'capture_verified':False}
    finally:backend.close()


if __name__=='__main__':
    report=check()
    output=ROOT/'dist/dxgi-initialization-trace.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,indent=2),'utf8')
    print(json.dumps(report))
    raise SystemExit(0 if report['initialized'] else 1)
