"""抓屏访问丢失及缓存坐标变化；显式替身不接触桌面。"""
import ctypes
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from wowbuddy.capture import DxgiCapture,DxgiInitialization,Rect,DXGI_ERROR_WAIT_TIMEOUT,WindowCapture,Win32WindowAPI
from wowbuddy.pixel_geometry import RGBImage


class Backend:
    def __init__(self):
        self.results=[];self.calls=[];self.fail_read=False
    def monitor_from_rect(self,rect):return 1
    def reset(self):self.calls.append(('reset',))
    def initialize(self,monitor):
        self.calls.append(('initialize',monitor))
        return DxgiInitialization('ok',Rect(0,0,1920,1080))
    def create_staging(self,w,h):return True
    def acquire(self,timeout):
        self.calls.append(('acquire',timeout));return self.results.pop(0)
    def read_region(self,resource,box):
        self.calls.append(('read',box))
        if self.fail_read:raise OSError('simulated GPU mapping failure')
        return RGBImage([[resource]*box.width for _ in range(box.height)])
    def release_frame(self):self.calls.append(('release_frame',))
    def release_resource(self,resource):self.calls.append(('release_resource',resource))


class CaptureRecoveryTests(unittest.TestCase):
    def test_windows_session_state_uses_only_the_valid_status_header(self):
        windows = Win32WindowAPI.__new__(Win32WindowAPI)
        windows.wtsapi32 = api = Mock()
        cases = ((1, 0, 0, 20, 'desktop_locked'), (1, 0, 1, 20, None),
                 (1, 4, 1, 20, 'desktop_disconnected'), (1, 0, -1, 20, 'desktop_unverified'),
                 (2, 0, 1, 20, 'desktop_unverified'), (1, 0, 1, 8, 'desktop_unverified'))
        for level, connection, lock, size, expected in cases:
            with self.subTest(level=level, connection=connection, lock=lock, size=size):
                api.reset_mock()
                header = ctypes.create_string_buffer(struct.pack('<I4xIIi', level, 1, connection, lock))
                def query(server, session, category, buffer, count):
                    self.assertEqual((server, session, category), (None, 0xffffffff, 25))
                    ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(header)
                    ctypes.cast(count, ctypes.POINTER(ctypes.c_uint32))[0] = size
                    return 1
                api.WTSQuerySessionInformationW.side_effect = query
                self.assertEqual(windows.desktop_status(), expected)
                api.WTSFreeMemory.assert_called_once()
        api.reset_mock()
        api.WTSQuerySessionInformationW.side_effect = None
        api.WTSQuerySessionInformationW.return_value = 0
        self.assertEqual(windows.desktop_status(), 'desktop_unverified')
        api.WTSFreeMemory.assert_not_called()

    def test_lock_suspends_both_capture_backends_and_drops_cached_frames(self):
        backend = Backend()
        dxgi = DxgiCapture(backend, lambda: 1000)
        dxgi.cached_image = RGBImage([[0xff00ff] * 48])
        windows, printed = Mock(), Mock()
        status = Mock(return_value='desktop_locked')
        capture = WindowCapture(windows, dxgi, printed, desktop_status=status)
        for _ in range(2):
            result = capture.capture(10)
            self.assertEqual(result.status, 'desktop_locked')
            self.assertIsNone(result.image)
        self.assertIsNone(dxgi.cached_image)
        self.assertEqual(backend.calls, [('reset',)])
        windows.is_iconic.assert_not_called()
        printed.capture.assert_not_called()
        status.return_value = None
        windows.is_iconic.return_value = True
        self.assertEqual(capture.capture(10).status, 'minimized')

    def test_two_backend_selection_matrix_and_origin_marker(self):
        def image(kind):
            if kind=='none':return None
            rows=[[0x123456]*48 for _ in range(10)]
            if kind=='marker':rows[2][4:6]=[0xff00ff]*2
            if kind=='origin':rows[0][0:2]=[0xff00ff]*2
            return RGBImage(rows)
        for dxgi_kind in ('none','blank','origin','marker'):
            for print_kind in ('none','blank','origin','marker'):
                with self.subTest(dxgi=dxgi_kind,printed=print_kind):
                    dxgi,printed=image(dxgi_kind),image(print_kind)
                    calls=[]
                    windows=SimpleNamespace(is_iconic=lambda hwnd:False,
                        window_rect=lambda hwnd:Rect(90,190,300,400),
                        client_rect=lambda hwnd:Rect(0,0,100,10),client_to_screen=lambda hwnd:(100,200))
                    primary=SimpleNamespace(capture=lambda *args:calls.append(('dxgi',args)) or dxgi)
                    fallback=SimpleNamespace(capture=lambda *args:calls.append(('print',args)) or printed)
                    result=WindowCapture(windows,primary,fallback).capture(10)
                    if dxgi_kind=='marker':
                        expected=dxgi;backend='dxgi';self.assertEqual(len(calls),1)
                    else:
                        self.assertEqual(len(calls),2)
                        if dxgi_kind=='none' or print_kind=='marker':expected=printed;backend='printwindow'
                        else:expected=dxgi;backend='dxgi'
                    self.assertIs(result.image,expected)
                    self.assertEqual(result.backend,backend)
                    self.assertEqual(result.status,'ok' if expected is not None else 'capture_failed')
                    self.assertEqual(result.marker_found,dxgi_kind=='marker' or print_kind=='marker')
                    self.assertEqual(result.client_rect,Rect(100,200,200,210))

    def test_timeout_reuses_only_identical_screen_crop(self):
        backend=Backend();capture=DxgiCapture(backend,lambda:1000)
        original=Rect(10,10,110,20);moved=Rect(11,10,111,20)
        backend.results=[(0,0x123456),(DXGI_ERROR_WAIT_TIMEOUT,None),
                         (DXGI_ERROR_WAIT_TIMEOUT,None),(0,0x654321)]
        image=capture.capture(original)
        self.assertIs(capture.capture(original),image)
        self.assertIsNone(capture.capture(moved))
        fresh=capture.capture(moved)
        self.assertIsNot(fresh,image)
        self.assertEqual(capture.cached_rect,Rect(11,10,59,20))
        self.assertEqual([c for c in backend.calls if c[0]=='acquire'],
                         [('acquire',50),('acquire',0),('acquire',0),('acquire',0)])
        self.assertEqual(backend.calls.count(('release_frame',)),2)
        self.assertEqual(capture.frame_count,2)

    def test_access_lost_discards_cache_and_waits_exact_backoff(self):
        backend=Backend();now=[1000];capture=DxgiCapture(backend,lambda:now[0])
        rect=Rect(10,10,110,20)
        backend.results=[(0,1),(0x887a0026,None),(0,2)]
        capture.capture(rect)
        self.assertIsNone(capture.capture(rect))
        self.assertIsNone(capture.cached_image)
        self.assertEqual(capture.retry_after_ms,2500)
        before=len(backend.calls);now[0]=2499
        self.assertIsNone(capture.capture(rect));self.assertEqual(len(backend.calls),before)
        now[0]=2500
        self.assertIsNotNone(capture.capture(rect))
        self.assertEqual(capture.frame_count,2)
        self.assertEqual([c for c in backend.calls if c[0]=='acquire'],
                         [('acquire',50),('acquire',0),('acquire',50)])

    def test_incompatible_output_does_not_disable_capture_after_display_change(self):
        for reason in ('rotated', 'unsupported_format'):
            with self.subTest(reason=reason):
                backend = Backend()
                now = [1000]
                landscape = Rect(0, 0, 1920, 1080)
                portrait = Rect(1920, 0, 3000, 1920)
                display_mode = {1: 'ok', 2: reason}
                backend.monitor_from_rect = lambda rect: 1 if rect.left < 1920 else 2

                def initialize(monitor):
                    backend.calls.append(('initialize', monitor))
                    return DxgiInitialization(display_mode[monitor], (landscape, portrait)[monitor - 1])

                backend.initialize = initialize
                left = Rect(10, 10, 110, 20)
                right = Rect(1940, 20, 2040, 30)
                original = DxgiCapture(backend, lambda: now[0])
                self.assertIsNone(original.capture(right))
                self.assertTrue(original.permanent_format_failure)
                self.assertIsNone(original.capture(left))
                self.assertEqual(backend.calls, [('reset',), ('initialize', 2)])

                backend.calls.clear()
                backend.results = [(0, 1), (DXGI_ERROR_WAIT_TIMEOUT, None), (0, 2), (0, 3)]
                capture = DxgiCapture(backend, lambda: now[0], recover_output_changes=True)
                self.assertIsNotNone(capture.capture(left))
                self.assertIsNone(capture.capture(right))
                self.assertIsNone(capture.cached_image)
                self.assertEqual(capture.last_error, reason)
                self.assertEqual(capture.retry_after_ms, 2500)
                self.assertIsNone(capture.capture(right))
                self.assertEqual(backend.calls.count(('initialize', 2)), 1)

                # 移回横屏后先丢弃超时帧，再取得新图像。
                self.assertIsNone(capture.capture(left))
                self.assertIsNotNone(capture.capture(left))
                self.assertEqual(backend.calls.count(('initialize', 1)), 2)
                self.assertIsNone(capture.capture(right))
                display_mode[2] = 'ok'
                now[0] = 2499
                self.assertIsNone(capture.capture(right))
                now[0] = 2500
                self.assertIsNotNone(capture.capture(right))
                self.assertEqual(capture.monitor, 2)
                self.assertEqual(backend.calls.count(('initialize', 2)), 3)

    def test_read_failure_releases_acquired_frame_and_resource(self):
        backend=Backend();capture=DxgiCapture(backend,lambda:1000)
        backend.results=[(0,123)];backend.fail_read=True
        with self.assertRaises(OSError):capture.capture(Rect(0,0,48,4))
        self.assertEqual(backend.calls[-2:],[('release_frame',),('release_resource',123)])
        self.assertIsNone(capture.cached_image)
        self.assertEqual(capture.frame_count,0)

    def test_all_native_reset_hresult_encodings_drop_old_frame(self):
        # 02f4e0: -0x7785ffda，或无符号(hr+0x7785fffb)<3。
        for error in (0x887a0026,0x887a0005,0x887a0006,0x887a0007):
            for signed in (False,True):
                with self.subTest(error=hex(error),signed=signed):
                    backend=Backend();now=[1000]
                    capture=DxgiCapture(backend,lambda:now[0])
                    rect=Rect(10,10,110,20)
                    backend.results=[(0,1),(error-(1<<32) if signed else error,None),
                                     (DXGI_ERROR_WAIT_TIMEOUT,None),(0,2)]
                    old=capture.capture(rect)
                    self.assertIsNone(capture.capture(rect))
                    self.assertIsNone(capture.cached_rect)
                    self.assertIsNone(capture.cached_image)
                    self.assertIsNone(capture.monitor)
                    now[0]=2499;before=list(backend.calls)
                    self.assertIsNone(capture.capture(rect))
                    self.assertEqual(backend.calls,before)
                    now[0]=2500
                    self.assertIsNone(capture.capture(rect))
                    fresh=capture.capture(rect)
                    self.assertIsNot(fresh,old)
                    self.assertEqual(fresh.pixel(0,0),2)
                    self.assertEqual(capture.frame_count,2)
                    self.assertEqual(backend.calls.count(('release_frame',)),2)
                    self.assertEqual([c[1] for c in backend.calls if c[0]=='acquire'],[50,0,50,50])

    def test_monitor_switch_reinitializes_and_translates_negative_desktop_origin(self):
        backend=Backend();monitor=[1]
        backend.monitor_from_rect=lambda rect:monitor[0]
        def initialize(which):
            backend.calls.append(('initialize',which))
            return DxgiInitialization('ok',Rect(0,0,1920,1080) if which==1
                                      else Rect(-1920,-100,0,980))
        backend.initialize=initialize
        capture=DxgiCapture(backend,lambda:1000)
        backend.results=[(0,1),(DXGI_ERROR_WAIT_TIMEOUT,None),(0,2)]
        first=capture.capture(Rect(10,10,110,20))
        monitor[0]=2
        moved=Rect(-1910,-90,-1810,-80)
        self.assertIsNone(capture.capture(moved))
        self.assertIsNone(capture.cached_image)
        fresh=capture.capture(moved)
        self.assertIsNot(first,fresh)
        self.assertEqual(capture.cached_rect,Rect(-1910,-90,-1862,-80))
        self.assertEqual([c for c in backend.calls if c[0]=='read'],
                         [('read',Rect(10,10,58,20)),('read',Rect(10,10,58,20))])
        self.assertEqual([c for c in backend.calls if c[0]=='initialize'],
                         [('initialize',1),('initialize',2)])
        self.assertEqual([c[1] for c in backend.calls if c[0]=='acquire'],[50,50,50])
