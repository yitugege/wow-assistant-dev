import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.hub_sync import HubSynchronizer,Response
from wowbuddy.dev_hub_online import BackupHubFiles,HUB_URL

class OnlineHubTests(unittest.TestCase):
    def test_real_http_updates_selected_rules_and_preserves_them_on_errors(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from threading import Thread
        import time
        from PySide6.QtTest import QTest
        from test_dev_tray import TrayTests
        from wowbuddy.qt_network import QtHubClient
        from wowbuddy.hub_sync import cache_path
        sys.path.insert(0,str(ROOT/'tests/core'))
        from test_old_protocol import render_old
        responses=[];requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                requests.append((self.path,self.headers.get('User-Agent')))
                status,payload=responses.pop(0)
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_port}/rotations.json'
        def exercise(window):
            frame=window.controller.prepare(render_old(1482)[0]).frame
            self.assertTrue(frame.ok)
            window._render_selection();window.ui.rotation_combo.setCurrentIndex(1)
            selected=window.controller.selection.active_profile
            self.assertIsNotNone(selected)
            original=(ROOT/'assets/rotations.json').read_bytes()
            changed=json.loads(original)
            entry=next(p for p in changed['rotations']
                       if f"{p['specId']}|{p.get('subKey','')}|{p['profileName']}"==selected.key)
            entry['rules'][0]['reason']='真实HTTP更新规则'
            payload=json.dumps(changed,ensure_ascii=False).encode('utf8')
            empty=json.dumps({'format':'wowbuddy-rotation-hub','rotations':[]}).encode()
            responses.extend([(200,payload),(200,b'{bad'),(503,b'unavailable'),(200,empty)])
            window.hub.files=BackupHubFiles()
            window.hub_client=QtHubClient(window.hub,window)
            cache=Path(cache_path(window.hub.environment,window.hub.application_dir,window.hub.files))
            old=cache.read_bytes()
            def fetch():
                window.hub_client.refresh(url)
                deadline=time.monotonic()+5
                while window.hub_client.pending and time.monotonic()<deadline:QTest.qWait(10)
                self.assertFalse(window.hub_client.pending,'本机Qt请求超时')
            fetch()
            self.assertEqual(window.ui.rotation_combo.currentData(),selected.key)
            active=window.controller.selection.active_profile
            self.assertEqual(active.rules[0].reason,'真实HTTP更新规则')
            self.assertEqual(cache.read_bytes(),payload)
            self.assertEqual((cache.parent/'backups'/(hashlib.sha256(old).hexdigest()+'.json')).read_bytes(),old)
            fetch()
            self.assertEqual(window.controller.selection.active_profile,active)
            self.assertEqual(cache.read_bytes(),payload)
            self.assertIn('不是合法 JSON',window.hub.status)
            fetch()
            self.assertEqual(window.controller.selection.active_profile,active)
            self.assertEqual(cache.read_bytes(),payload)
            self.assertIn('继续用本地快照',window.hub.status)
            fetch()
            # 原0999f0/080f60：没有可选项时保留已经应用的规则。
            self.assertEqual(window.controller.selection.active_profile,active)
            self.assertTrue(window.controller.selection.preserve_active)
            self.assertEqual(window.controller.hub.profiles,())
            self.assertEqual(window.ui.rotation_combo.currentData(),'')
            self.assertEqual(cache.read_bytes(),empty)
            self.assertFalse(window.hub_client._request_managers)
        try:
            TrayTests.run_window(self,False,exercise)
            self.assertEqual(requests,[('/rotations.json','WOWBattleAssistant')]*4)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

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
