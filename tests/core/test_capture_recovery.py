"""抓屏访问丢失及缓存坐标变化；显式替身不接触桌面。"""
import unittest
from wowbuddy.capture import DxgiCapture,DxgiInitialization,Rect,DXGI_ERROR_WAIT_TIMEOUT
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

    def test_read_failure_releases_acquired_frame_and_resource(self):
        backend=Backend();capture=DxgiCapture(backend,lambda:1000)
        backend.results=[(0,123)];backend.fail_read=True
        with self.assertRaises(OSError):capture.capture(Rect(0,0,48,4))
        self.assertEqual(backend.calls[-2:],[('release_frame',),('release_resource',123)])
        self.assertIsNone(capture.cached_image)
        self.assertEqual(capture.frame_count,0)
