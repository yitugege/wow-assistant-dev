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


def check(*, backend='printwindow', move_window=False, decorated=False, readable_pitch=4, cross_screen=False):
    if backend not in ('printwindow','dxgi'):raise ValueError(backend)
    if cross_screen and (backend!='dxgi' or move_window or decorated):
        raise ValueError('跨屏模式使用独立的 DXGI 无边框窗口轨迹')
    if type(readable_pitch) is not int or not 3 <= readable_pitch <= 9:
        raise ValueError('readable_pitch必须在原生支持的3..9像素范围')
    if os.name!='nt':raise RuntimeError('需要 Windows')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtGui import QImage,QPainter
    from wowbuddy.capture import Win32WindowAPI,Win32PrintWindow,Win32DxgiBackend,DxgiCapture,Rect,WindowCapture
    from wowbuddy.game_windows import CtypesWindowBackend,find_game_window
    from wowbuddy.pixel_geometry import RGBImage
    from wowbuddy.assets import Assets
    from test_old_protocol import render_old
    from test_pipeline import render_readable
    app=QApplication.instance() or QApplication([])
    if app.platformName()!='windows':raise RuntimeError('此检查需要原生 Windows Qt 平台')
    primary=app.primaryScreen()
    screens=(primary,)
    game_windows=None
    if cross_screen:
        others=tuple(screen for screen in app.screens() if screen!=primary)
        if not others:raise RuntimeError('跨屏验证至少需要两个屏幕')
        screens=(primary,*others,primary)
        if any(screen.devicePixelRatio()!=1 for screen in screens):
            raise RuntimeError('跨屏逐像素验证要求所有被测屏幕使用 1 倍缩放')
        game_windows=CtypesWindowBackend()

    class Receiver(QWidget):
        def __init__(self):
            flags=Qt.Tool if decorated else Qt.FramelessWindowHint|Qt.Tool
            if backend=='dxgi':flags|=Qt.WindowStaysOnTopHint
            if cross_screen:flags|=Qt.WindowDoesNotAcceptFocus|Qt.WindowTransparentForInput
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

    def game_rectangle(hwnd):
        if not hwnd or not game_windows.is_visible(hwnd) or windows.is_iconic(hwnd):
            return None
        rect=windows.window_rect(hwnd)
        if rect is None:
            raise RuntimeError('无法确认游戏窗口位置，停止跨屏测试')
        return rect

    def clear_corner(available, width, height, protected):
        for name, right, bottom in (('bottom_right',True,True),('bottom_left',False,True),
                                    ('top_right',True,False),('top_left',False,False)):
            x=available.right()-width+1 if right else available.left()
            y=available.bottom()-height+1 if bottom else available.top()
            area=Rect(x,y,x+width,y+height)
            if protected is None or area.intersect(protected).empty:
                return name,area
        raise RuntimeError('找不到与游戏窗口分开的屏幕角落，停止跨屏测试')

    initializations=[]

    class TracedDxgiBackend(Win32DxgiBackend):
        def initialize(self, monitor):
            result=super().initialize(monitor)
            initializations.append((monitor,result.status))
            return result

    gpu=TracedDxgiBackend() if backend=='dxgi' else None
    dxgi=DxgiCapture(gpu) if gpu is not None else None
    combined=WindowCapture(windows,dxgi,capture) if cross_screen else None
    assets=Assets.load(ROOT/'assets')
    results=[]
    monitor_switches=0
    previous_monitor=None
    try:
        for spec in (1482,1484,1485,1486,1487,1488,1489,1490,1491):
            positions=('top_left','center','bottom_right') if move_window else ('top_left',)
            if cross_screen:positions=('bottom_right',)
            for protocol,position,screen in product(('old','readable'),positions,screens):
                frame=(render_old(spec,{'master_switch':0x00ff00})[0]
                       if protocol=='old' else render_readable(spec, pitch=readable_pitch))
                if protocol=='readable':
                    definition=assets.readable_contract['specs'][str(spec)]
                    last_row=max(definition['classicRows']+[p['row'] for p in definition['presenceFields']])
                    frame=RGBImage(frame.rows[:2+readable_pitch*(last_row+1)+8])
                if decorated:
                    # Windows有标题栏窗口有最小宽度；提供完整客户画布，避免
                    # 将系统自动扩宽后的背景误认为24像素协议图像本身。
                    frame=RGBImage([list(row)+[0x0d0d0d]*(160-frame.width) for row in frame.rows])
                if cross_screen:
                    # 每一帧写不同的背景像素，防止缓存碰巧与另一屏幕同色。
                    rows=[list(row) for row in frame.rows]
                    rows[0][min(48,frame.width)-1]=0x010000+len(results)
                    frame=RGBImage(rows)
                available=screen.availableGeometry()
                if frame.height>available.height() or window.devicePixelRatioF()!=1:
                    raise RuntimeError(
                        f'此像素级检查需要1倍缩放且测试色条完整位于屏幕内: '
                        f'{spec}/{protocol}, frame_height={frame.height}, '
                        f'available_height={available.height()}, dpr={window.devicePixelRatioF()}')
                if cross_screen:
                    window.hide()
                    protected_hwnd=find_game_window(game_windows)
                    position,planned=clear_corner(available,frame.width,frame.height,game_rectangle(protected_hwnd))
                    x,y=planned.left,planned.top
                    window.move(x,y)
                window.set_frame(frame)
                window.show()
                app.processEvents()
                if not cross_screen:
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
                frame_before=dxgi.frame_count if dxgi else 0
                init_before=len(initializations)
                expected=tuple(row[:48] for row in frame.rows)
                deadline=time.monotonic()+4
                while True:
                    app.processEvents()
                    if combined is not None:
                        protected=game_rectangle(protected_hwnd)
                        if protected is not None and not rect.intersect(protected).empty:
                            raise RuntimeError('游戏窗口移动到测试区域，停止跨屏测试')
                        shot=combined.capture(hwnd)
                        image=shot.image if shot.backend=='dxgi' else None
                    elif dxgi is None:
                        image=capture.capture(hwnd,rect,origin,client.width,client.height)
                    else:
                        image=dxgi.capture(Rect(origin[0],origin[1],origin[0]+client.width,origin[1]+client.height))
                    attempts+=1
                    if image is not None and image.rows==expected:break
                    if time.monotonic()>=deadline:
                        reason=dxgi.last_error if dxgi else ''
                        raise RuntimeError(f'{backend}未取得匹配帧: {spec}/{protocol}, attempts={attempts}, reason={reason}')
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
                result={'spec':spec,'protocol':protocol,'width':image.width,
                        'readable_pitch':readable_pitch if protocol=='readable' else None,
                        'height':image.height,'pixels_exact':True,'decoded':True,'attempts':attempts,
                        'position':position,'client_origin':origin,
                        'client_offset':[origin[0]-rect.left,origin[1]-rect.top]}
                if cross_screen:
                    bounds=screen.geometry()
                    expected_desktop=Rect(bounds.left(),bounds.top(),bounds.right()+1,bounds.bottom()+1)
                    monitor=gpu.monitor_from_rect(expected_desktop)
                    assert dxgi.monitor==monitor and dxgi.desktop==expected_desktop
                    assert dxgi.cached_rect==Rect(origin[0],origin[1],origin[0]+image.width,origin[1]+image.height)
                    assert dxgi.frame_count>frame_before
                    reinitialized=monitor!=previous_monitor
                    assert initializations[init_before:]==([(monitor,'ok')] if reinitialized else [])
                    monitor_switches+=int(previous_monitor is not None and reinitialized)
                    previous_monitor=monitor
                    result.update(screen=screen.name(),desktop=[bounds.x(),bounds.y(),bounds.width(),bounds.height()],
                                  reinitialized=reinitialized,dxgi_frame_count=dxgi.frame_count)
                results.append(result)
        if cross_screen:
            assert monitor_switches==18*(len(screens)-1)
        return {'passed':True,'backend':'Win32DxgiBackend' if dxgi else 'Win32PrintWindow','receiver':'本进程无激活 Qt 测试窗口',
                'cases':results,'window_movement_checked':move_window or cross_screen,'decorated_window':decorated,
                'dxgi_verified':dxgi is not None,'cross_screen':cross_screen,'monitor_switches':monitor_switches,
                'game_capture_verified':False}
    finally:
        if gpu is not None:gpu.close()
        window.close();window.destroy()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=('printwindow','dxgi'),default='printwindow')
    parser.add_argument('--move-window',action='store_true',help='在屏幕内三个位置重复真实抓屏')
    parser.add_argument('--cross-screen',action='store_true',help='在真实显示器之间移动同一 DXGI 测试窗口')
    parser.add_argument('--decorated',action='store_true',help='使用真实标题栏及边框验证客户区裁剪')
    parser.add_argument('--readable-pitch',type=int,default=4,choices=range(3,10),
                        help='显式指定readable合成色块尺寸；不自动缩小或删减协议行')
    args=parser.parse_args()
    try:
        result=check(backend=args.backend,move_window=args.move_window,decorated=args.decorated,
                     readable_pitch=args.readable_pitch,cross_screen=args.cross_screen)
    except Exception as error:
        result={'passed':False,'backend':args.backend,'error':str(error),'game_capture_verified':False}
    suffix='movement-check' if args.move_window else 'check'
    if args.cross_screen:suffix='cross-screen-check'
    if args.decorated:suffix='decorated-'+suffix
    if args.readable_pitch != 4:suffix+=f'-pitch{args.readable_pitch}'
    output=ROOT/f'dist/win32-{args.backend}-{suffix}.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
    raise SystemExit(0 if result['passed'] else 1)
