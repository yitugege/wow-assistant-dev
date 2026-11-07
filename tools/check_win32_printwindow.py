"""自有测试窗口提供协议图像，实际 PrintWindow/DIB 裁剪后再解码。"""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
sys.path.insert(0,str(ROOT/'tests/core'))


def check():
    if os.name!='nt':raise RuntimeError('需要 Windows')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtGui import QImage,QPainter
    from wowbuddy.capture import Win32WindowAPI,Win32PrintWindow
    from wowbuddy.pixel_geometry import RGBImage
    from wowbuddy.assets import Assets
    from test_old_protocol import render_old
    from test_pipeline import render_readable
    app=QApplication.instance() or QApplication([])
    if app.platformName()!='windows':raise RuntimeError('此检查需要原生 Windows Qt 平台')
    class Receiver(QWidget):
        def __init__(self):
            super().__init__(None,Qt.FramelessWindowHint|Qt.Tool)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.frame=None
        def set_frame(self,frame):
            self.frame=frame
            self.resize(frame.width,frame.height)
            data=b''.join(int(pixel).to_bytes(4,'little') for row in frame.rows for pixel in row)
            self.qimage=QImage(data,frame.width,frame.height,frame.width*4,QImage.Format_RGB32).copy()
            self.update()
        def paintEvent(self,event):
            if self.frame is not None:
                painter=QPainter(self)
                painter.drawImage(0,0,self.qimage)
                painter.end()
    window=Receiver()
    windows=Win32WindowAPI();capture=Win32PrintWindow()
    assets=Assets.load(ROOT/'assets')
    results=[]
    try:
        for spec in (1482,1484,1485,1486,1487,1488,1489,1490,1491):
            for protocol in ('old','readable'):
                frame=(render_old(spec,{'master_switch':0x00ff00})[0]
                       if protocol=='old' else render_readable(spec))
                if protocol=='readable':
                    definition=assets.readable_contract['specs'][str(spec)]
                    last_row=max(definition['classicRows']+[p['row'] for p in definition['presenceFields']])
                    frame=RGBImage(frame.rows[:2+4*(last_row+1)+8])
                available=app.primaryScreen().availableGeometry()
                if frame.height>available.height() or window.devicePixelRatioF()!=1:
                    raise RuntimeError('此像素级检查需要1倍缩放且测试色条完整位于屏幕内')
                window.move(available.topLeft())
                window.set_frame(frame)
                window.show()
                app.processEvents()
                hwnd=int(window.winId())
                rect=windows.window_rect(hwnd);client=windows.client_rect(hwnd)
                origin=windows.client_to_screen(hwnd)
                assert rect is not None and client is not None and origin is not None
                image=capture.capture(hwnd,rect,origin,client.width,client.height)
                assert image is not None,(spec,protocol)
                assert (image.width,image.height)==(min(48,frame.width),frame.height)
                differences=[(x,y,image.rows[y][x],frame.rows[y][x])
                             for y in range(image.height) for x in range(image.width)
                             if image.rows[y][x]!=frame.rows[y][x]]
                assert not differences,(spec,protocol,'像素不一致',differences[:8],rect,client,origin)
                decoded=assets.pipeline().evaluate(image).frame
                assert decoded.ok,(spec,protocol,decoded.status)
                assert decoded.spec_id==str(spec),(spec,protocol,decoded.spec_id)
                assert decoded.protocol==protocol,(spec,protocol,decoded.protocol)
                results.append({'spec':spec,'protocol':protocol,'width':image.width,
                                'height':image.height,'pixels_exact':True,'decoded':True})
        return {'passed':True,'backend':'Win32PrintWindow','receiver':'本进程无激活 Qt 测试窗口',
                'cases':results,
                'dxgi_verified':False,'game_capture_verified':False}
    finally:
        window.close();window.destroy()


if __name__=='__main__':
    result=check()
    output=ROOT/'dist/win32-printwindow-check.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
