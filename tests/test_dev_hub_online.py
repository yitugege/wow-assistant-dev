import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.hub_sync import HubSynchronizer,Response
from wowbuddy.dev_hub_online import BackupHubFiles,HUB_URL

class OnlineHubTests(unittest.TestCase):
    def test_replace_backup_failure_and_offline_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'hub/rotations.json';cache.parent.mkdir()
            old=(ROOT/'assets/rotations.json').read_bytes();cache.write_bytes(old)
            sync=HubSynchronizer(BackupHubFiles(),application_dir=str(root),environment={'WOWBUDDY_HOME':str(root)})
            self.assertTrue(sync.load_cache().accepted)
            changed=json.loads(old);changed['rotations'][0]['rules'][0]['reason']='online test'
            payload=json.dumps(changed).encode()
            result=sync.finish_response(Response(payload))
            self.assertTrue(result.accepted and result.cache_written)
            self.assertEqual(cache.read_bytes(),payload)
            self.assertEqual((cache.parent/'backups'/(hashlib.sha256(old).hexdigest()+'.json')).read_bytes(),old)
            self.assertFalse(sync.finish_response(Response(b'{bad')).accepted)
            self.assertEqual(cache.read_bytes(),payload)
            previous=sync.hub.profiles
            self.assertFalse(sync.finish_response(Response(network_error=1,error_string='offline')).accepted)
            self.assertEqual(sync.hub.profiles,previous)
            self.assertIn('继续用本地快照',sync.status)
            with patch.object(sync.files,'begin_atomic',side_effect=OSError('backup denied')):
                result=sync.finish_response(Response(old))
            self.assertTrue(result.accepted);self.assertFalse(result.cache_written)
            self.assertEqual(cache.read_bytes(),payload)

    def test_gui_manual_periodic_and_shutdown(self):
        from test_dev_tray import TrayTests
        from wowbuddy.qt_network import QtHubClient
        def exercise(window):
            calls=[]
            class Client:
                def refresh(self,url):calls.append(url)
                def close(self):calls.append('close')
            window.hub_client=Client()
            window._refresh_online_library()
            window._periodic_library_refresh()
            self.assertEqual(calls,[HUB_URL,HUB_URL])
            self.assertEqual(window.hub_timer.interval(),1800000)
            window.shutdown()
            self.assertEqual(calls[-1],'close')
        TrayTests.run_window(self,False,exercise)

    def test_online_entry_startup_button_timer_and_cache(self):
        from test_dev_tray import TrayTests
        calls=[]
        payload=(ROOT/'assets/rotations.json').read_bytes()
        class Client:
            def __init__(self,sync,parent):self.sync=sync
            def refresh(self,url):
                calls.append(url)
                self.sync.begin_request(url)
                self.sync.finish_response(Response(payload))
            def close(self):calls.append('close')
        def exercise(window):
            self.assertEqual(calls,[HUB_URL])
            self.assertTrue(window.ui.hub_online_button.isVisible())
            self.assertTrue(window.hub_timer.isActive())
            self.assertEqual(len(window.controller.hub.profiles),41)
            window.ui.hub_online_button.click()
            window.hub_timer.timeout.emit()
            self.assertEqual(calls,[HUB_URL]*3)
        with patch('wowbuddy.qt_network.QtHubClient',Client):
            TrayTests.run_window(self,False,exercise,hub_online=True)
        self.assertEqual(calls[-1],'close')

if __name__=='__main__':unittest.main()
