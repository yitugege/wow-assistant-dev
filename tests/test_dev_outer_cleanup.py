"""启动回调及隔离缓存清理；不访问已有源码发布缓存。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import QCoreApplication,QEvent
from wowbuddy.dev_staged_startup import create_staged_startup
from wowbuddy.cache_cleanup_host import cleanup_source_release
from wowbuddy.release_identity import ReleaseIdentity,CACHE_NAMESPACE,file_sha256
from wowbuddy.launcher import BUSINESS_EXE,APPLICATION_NAME


class OuterCleanupTests(unittest.TestCase):
    def tearDown(self):
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)

    def test_authorization_callback_precedes_construction_once(self):
        from test_dev_watch import Windows
        app=QApplication.instance() or QApplication([])
        order=[];backend=Windows();backend.handle=123
        def construct(assets):order.append('construct');return QWidget()
        host=create_staged_startup(app,ROOT/'assets',backend,construct,lambda _:None,
                                  after_authorization=lambda:order.append('cleanup'))
        try:
            host.start();host.timer.stop()
            for _ in range(9):host.stages.tick()
            self.assertEqual(order,['cleanup','construct'])
        finally:
            host.close()
            if host.stages.main_window:host.stages.main_window.close()

    def test_frozen_entry_calls_cleanup_and_source_entry_does_not(self):
        import run_dev
        from test_dev_staged_startup import StagedStartupTests
        for frozen in (False,True):
            with self.subTest(frozen=frozen),patch.object(run_dev,'FROZEN',frozen),patch('wowbuddy.cache_cleanup_host.cleanup_source_release') as cleanup:
                fixture=StagedStartupTests();fixture.setUp()
                try:fixture.test_independent_entry_constructs_real_window_then_shuts_down()
                finally:fixture.tearDown()
                self.assertEqual(cleanup.call_count,int(frozen))
                if frozen:self.assertEqual(cleanup.call_args.args[0],Path(sys.executable))

    @unittest.skipUnless((ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe').is_file(),'需要自有PE构建作为身份资源载体')
    def test_actual_verified_cache_deletes_only_admitted_sibling(self):
        from PyInstaller.utils.win32.winresource import add_or_update_resource
        with TemporaryDirectory() as directory:
            root=Path(directory).resolve();key='a'*16
            parent=root/CACHE_NAMESPACE/key/APPLICATION_NAME
            current=parent/'app-current';current.mkdir(parents=True)
            inner=current/BUSINESS_EXE
            shutil.copy2(ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe',inner)
            outer=root/'owned-outer.exe';shutil.copy2(inner,outer)
            identity=ReleaseIdentity('a'*64,file_sha256(inner))
            add_or_update_resource(str(outer),identity.encode(),10,[203],[1033])
            old=parent/'app-old';old.mkdir();(old/'fixture.txt').write_text('old')
            unrelated=parent/'keep';unrelated.mkdir()
            other=root/CACHE_NAMESPACE/('b'*16)/APPLICATION_NAME/'app-old'
            other.mkdir(parents=True)
            records=[]
            result=cleanup_source_release(inner,str(outer),record=records.append)
            self.assertEqual(result['deleted'],1)
            self.assertEqual(Path(result['attempts'][0]['path']).resolve(),old)
            self.assertFalse(old.exists())
            self.assertTrue(inner.exists());self.assertTrue(unrelated.exists());self.assertTrue(other.exists())
            self.assertEqual(len(records),1)
            old.mkdir()
            with inner.open('ab') as stream:stream.write(b'changed')
            result=cleanup_source_release(inner,str(outer))
            self.assertEqual(result['stop_reason'],'unverified_source_release')
            self.assertTrue(old.exists())


if __name__=='__main__':unittest.main()
