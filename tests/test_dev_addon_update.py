import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from tools.build_addon import build
from wowbuddy.addon_update import AddonGame,ReinstallResult
from wowbuddy.dev_addon_update import apply_release,refresh_package
from wowbuddy.github_addon import download_latest,ZIP_NAME,MANIFEST_NAME,REPOSITORY
from wowbuddy.dev_protocol import DEV_VERSION

class Pending:
    def __init__(self):self.paths=()
    def read(self):return self.paths
    def write(self,paths):self.paths=paths

class HotUpdateTests(unittest.TestCase):
    def test_gui_timers_dispatch_and_shutdown(self):
        from test_dev_tray import TrayTests
        from unittest.mock import patch
        from concurrent.futures import Future
        from wowbuddy.addon_update import AddonUpdateState
        def exercise(window):
            window._configure_addon_refresh(True)
            self.assertEqual(window.addon_startup_timer.interval(),5000)
            self.assertTrue(window.addon_startup_timer.isActive())
            self.assertEqual(window.hub_timer.interval(),1800000)
            done=Future();done.set_result({'changed':False})
            with patch('wowbuddy.dev_addon_update.refresh_package',return_value={'changed':False}),patch('wowbuddy.dev_addon_update.apply_release',return_value=AddonUpdateState(pending=('test',))) as apply:
                window.addon_startup_timer.timeout.emit()
                window._addon_refresh_future.result(timeout=5)
                window._addon_refresh_future=done
                window._finish_addon_refresh()
                self.assertEqual(apply.call_count,1)
                self.assertIn('待补装 1',window.ui.addon_status.text())
                self.assertTrue(window.ui.addon_install_button.isEnabled())
                window.hub_timer.timeout.emit()
                self.assertTrue(window._addon_refresh_timer.isActive())
                window.shutdown()
                self.assertFalse(window._addon_refresh_timer.isActive())
                self.assertFalse(window.addon_startup_timer.isActive())
                self.assertFalse(window.hub_timer.isActive())
        TrayTests.run_window(self,False,exercise)

    def package(self,root):
        source=root/'source';source.mkdir()
        (source/'WowBuddyDev.toc').write_text('Core.lua\n','utf8')
        (source/'Core.lua').write_text('-- own addon','utf8')
        package=root/ZIP_NAME
        manifest=build(source,package,random_names=True)
        manifest['protocol_version']=DEV_VERSION
        package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
        return package,manifest

    def test_running_game_deferred_then_stopped_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package,manifest=self.package(root)
            addons=root/'client/Interface/AddOns';pending=Pending()
            release={'package':str(package),'changed':True}
            games=lambda:(AddonGame('game',str(addons),True,'WowBuddyDev'),AddonGame('fresh',str(root/'fresh')))
            result=apply_release(release,pending,games=games,installed_name=lambda p:'')
            self.assertEqual([a.status for a in result.actions],['deferred','skipped_not_installed'])
            self.assertFalse(addons.exists());self.assertEqual(pending.paths,(str(addons),))
            release['changed']=False
            result=apply_release(release,pending,games=lambda:(AddonGame('game',str(addons)),),installed_name=lambda p:'')
            self.assertEqual(result.actions[0].status,'installed');self.assertEqual(pending.paths,())
            self.assertTrue((addons/manifest['addon_directory']/(manifest['addon_directory']+'.toc')).is_file())

    def test_pending_failure_retained_missing_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            package,_=self.package(Path(tmp));pending=Pending();pending.paths=('stopped','running','missing')
            result=apply_release({'package':str(package),'changed':False},pending,
                games=lambda:(AddonGame('a','stopped'),AddonGame('b','running',True)),installed_name=lambda p:'',
                install=lambda p:ReinstallResult(False,error='locked'))
            self.assertEqual([a.status for a in result.actions],['install_failed','still_running','dropped_not_detected'])
            self.assertEqual(pending.paths,('stopped','running'))

    def test_cache_hit_avoids_zip_download_and_failure_preserves_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package,manifest=self.package(root)
            base=f'https://github.com/{REPOSITORY}/releases/download/v0.2.1/'
            release={'tag_name':'v0.2.1','assets':[{'name':n,'browser_download_url':base+n} for n in (ZIP_NAME,MANIFEST_NAME)]}
            requests=[]
            def fetch(url,limit):
                requests.append(url)
                if url==base+ZIP_NAME:return package.read_bytes()
                if url==base+MANIFEST_NAME:return json.dumps(manifest).encode()
                return json.dumps(release).encode()
            def download(path,*,cached):return download_latest(path,fetch=fetch,cached=cached)
            first=refresh_package(root/'data',fetch_package=download)
            self.assertTrue(first['changed']);requests.clear()
            second=refresh_package(root/'data',fetch_package=download)
            self.assertFalse(second['changed']);self.assertNotIn(base+ZIP_NAME,requests)
            pointer=root/'data/addon-release.json';before=pointer.read_bytes()
            def fail(*args,**kwargs):raise OSError('offline')
            with self.assertRaises(OSError):refresh_package(root/'data',fetch_package=fail)
            self.assertEqual(pointer.read_bytes(),before)
            Path(second['package']).write_bytes(b'corrupt');requests.clear()
            repaired=refresh_package(root/'data',fetch_package=download)
            self.assertTrue(repaired['changed']);self.assertIn(base+ZIP_NAME,requests)

if __name__=='__main__':unittest.main()
