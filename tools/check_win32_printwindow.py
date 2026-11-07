"""自有测试窗口提供协议图像，实际 PrintWindow 或 DXGI 抓屏后解码。"""
import json
from itertools import product
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
sys.path.insert(0,str(ROOT/'tests/core'))


def check(*, backend='printwindow', move_window=False, decorated=False):
    if backend not in ('printwindow','dxgi'):raise ValueError(backend)
    if os.name!='nt':raise RuntimeError('需要 Windows')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtGui import QImage,QPainter
    from wowbuddy.capture import Win32WindowAPI,Win32PrintWindow,Win32DxgiBackend,DxgiCapture,Rect
    from wowbuddy.pixel_geometry import RGBImage
    from wowbuddy.assets import Assets
    from test_old_protocol import render_old
    from test_pipeline import render_readable
    app=QApplication.instance() or QApplication([])
    if app.platformName()!='windows':raise RuntimeError('此检查需要原生 Windows Qt 平台')
    class Receiver(QWidget):
        def __init__(self):
            flags=Qt.Tool if decorated else Qt.FramelessWindowHint|Qt.Tool
            if backend=='dxgi':flags|=Qt.WindowStaysOnTopHint
            super().__init__(None,flags)
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
    gpu=Win32DxgiBackend() if backend=='dxgi' else None
    dxgi=DxgiCapture(gpu) if gpu is not None else None
    assets=Assets.load(ROOT/'assets')
    results=[]
    try:
        for spec in (1482,1484,1485,1486,1487,1488,1489,1490,1491):
            positions=('top_left','center','bottom_right') if move_window else ('top_left',)
            for protocol,position in product(('old','readable'),positions):
                frame=(render_old(spec,{'master_switch':0x00ff00})[0]
                       if protocol=='old' else render_readable(spec))
                if protocol=='readable':
                    definition=assets.readable_contract['specs'][str(spec)]
                    last_row=max(definition['classicRows']+[p['row'] for p in definition['presenceFields']])
                    frame=RGBImage(frame.rows[:2+4*(last_row+1)+8])
                if decorated:
                    # Windows有标题栏窗口有最小宽度；提供完整客户画布，避免
                    # 将系统自动扩宽后的背景误认为24像素协议图像本身。
                    frame=RGBImage([list(row)+[0x0d0d0d]*(160-frame.width) for row in frame.rows])
                available=app.primaryScreen().availableGeometry()
                if frame.height>available.height() or window.devicePixelRatioF()!=1:
                    raise RuntimeError(
                        f'此像素级检查需要1倍缩放且测试色条完整位于屏幕内: '
                        f'{spec}/{protocol}, frame_height={frame.height}, '
                        f'available_height={available.height()}, dpr={window.devicePixelRatioF()}')
                window.set_frame(frame)
                window.show()
                app.processEvents()
                outer_size=window.frameGeometry().size()
                if outer_size.height()>available.height():
                    raise RuntimeError('含边框的测试窗口必须完整位于屏幕内')
                factor={'top_left':0,'center':0.5,'bottom_right':1}[position]
                x=available.left()+int((available.width()-outer_size.width())*factor)
                y=available.top()+int((available.height()-outer_size.height())*factor)
                window.move(x,y)
                app.processEvents()
                # 同步绘制不保证 Windows 已呈现；下面对两种后端都等待匹配帧。
                window.repaint()
                hwnd=int(window.winId())
                rect=windows.window_rect(hwnd);client=windows.client_rect(hwnd)
                origin=windows.client_to_screen(hwnd)
                assert rect is not None and client is not None and origin is not None
                if not decorated:assert origin==(x,y),(position,origin,(x,y))
                else:
                    assert origin[1]>rect.top,(rect,origin)
                    assert origin[0]>=rect.left and origin[0]+client.width<=rect.right,(rect,client,origin)
                    assert origin[1]+client.height<=rect.bottom,(rect,client,origin)
                attempts=0
                expected=tuple(row[:48] for row in frame.rows)
                deadline=time.monotonic()+4
                while True:
                    app.processEvents()
                    if dxgi is None:
                        image=capture.capture(hwnd,rect,origin,client.width,client.height)
                    else:
                        image=dxgi.capture(Rect(origin[0],origin[1],origin[0]+client.width,origin[1]+client.height))
                    attempts+=1
                    if image is not None and image.rows==expected:break
                    if time.monotonic()>=deadline:
                        raise RuntimeError(f'{backend}未取得匹配帧: {spec}/{protocol}, attempts={attempts}')
                    time.sleep(0.03)
                assert image is not None,(spec,protocol)
                assert (image.width,image.height)==(min(48,frame.width),frame.height),(
                    spec,protocol,'抓屏尺寸不符',image.width,image.height,frame.width,frame.height,client)
                differences=[(x,y,image.rows[y][x],frame.rows[y][x])
                             for y in range(image.height) for x in range(image.width)
                             if image.rows[y][x]!=frame.rows[y][x]]
                assert not differences,(spec,protocol,'像素不一致',differences[:8],rect,client,origin)
                decoded=assets.pipeline().evaluate(image).frame
                assert decoded.ok,(spec,protocol,decoded.status)
                assert decoded.spec_id==str(spec),(spec,protocol,decoded.spec_id)
                assert decoded.protocol==protocol,(spec,protocol,decoded.protocol)
                results.append({'spec':spec,'protocol':protocol,'width':image.width,
                                'height':image.height,'pixels_exact':True,'decoded':True,'attempts':attempts,
                                'position':position,'client_origin':origin,
                                'client_offset':[origin[0]-rect.left,origin[1]-rect.top]})
        return {'passed':True,'backend':'Win32DxgiBackend' if dxgi else 'Win32PrintWindow','receiver':'本进程无激活 Qt 测试窗口',
                'cases':results,'window_movement_checked':move_window,'decorated_window':decorated,
                'dxgi_verified':dxgi is not None,'game_capture_verified':False}
    finally:
        if gpu is not None:gpu.close()
        window.close();window.destroy()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=('printwindow','dxgi'),default='printwindow')
    parser.add_argument('--move-window',action='store_true',help='在屏幕内三个位置重复真实抓屏')
    parser.add_argument('--decorated',action='store_true',help='使用真实标题栏及边框验证客户区裁剪')
    args=parser.parse_args()
    try:
        result=check(backend=args.backend,move_window=args.move_window,decorated=args.decorated)
    except Exception as error:
        result={'passed':False,'backend':args.backend,'error':str(error),'game_capture_verified':False}
    suffix='movement-check' if args.move_window else 'check'
    if args.decorated:suffix='decorated-'+suffix
    output=ROOT/f'dist/win32-{args.backend}-{suffix}.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
    raise SystemExit(0 if result['passed'] else 1)
