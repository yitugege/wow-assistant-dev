import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.build_client_release import build_client
from wowbuddy.github_client import check_latest,download_checked,run_check_command,REPOSITORY,ZIP_NAME,MANIFEST_NAME

class ClientGithubTests(unittest.TestCase):
    def test_new_version_download_pins_assets_and_checks_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';(source/'_internal').mkdir(parents=True)
            (source/'WowBuddyDev.exe').write_bytes(b'MZ test not executed');(source/'_internal/runtime.dll').write_bytes(b'runtime')
            package=root/ZIP_NAME;manifest=build_client(source,package,'0.3.0')
            base=f'https://github.com/{REPOSITORY}/releases/download/v0.3.0/'
            release={'tag_name':'v0.3.0','assets':[{'name':n,'browser_download_url':base+n} for n in (ZIP_NAME,MANIFEST_NAME)]}
            calls=[]
            def fetch(url,limit):
                calls.append(url)
                if url==base+ZIP_NAME:return package.read_bytes()
                if url==base+MANIFEST_NAME:return json.dumps(manifest).encode()
                return json.dumps(release).encode()
            info=check_latest(current_version='0.2.1',fetch=fetch)
            self.assertTrue(info['has_update'])
            result=download_checked(info,root/'updates',fetch=fetch)
            self.assertTrue((Path(result['staged'])/'WowBuddyDev.exe').exists());self.assertFalse(result['installed'])
            self.assertEqual(len([url for url in calls if 'api.github.com' in url]),1)
            package.write_bytes(b'tampered')
            with self.assertRaises(ValueError):download_checked(info,root/'updates',fetch=fetch)
            release['assets'][0]['browser_download_url']=base.replace('v0.3.0','v0.4.0')+ZIP_NAME
            with self.assertRaises(ValueError):check_latest(fetch=fetch)

    def test_old_release_requires_no_manifest_and_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            def check():return check_latest(current_version='0.2.1',fetch=lambda *args:b'{"tag_name":"v0.2.0"}')
            self.assertFalse(check()['has_update'])
            self.assertEqual(run_check_command(tmp,check=check),0)
            self.assertEqual(run_check_command(tmp,check=lambda:{'current_version':'0.2.1','version':'0.3.0','has_update':True}),10)
            def fail():raise OSError('offline')
            self.assertEqual(run_check_command(tmp,check=fail),1)
            self.assertFalse(json.loads((Path(tmp)/'update-check.json').read_text('utf8'))['ok'])

    def test_gui_check_button_completion(self):
        from test_dev_tray import TrayTests
        from unittest.mock import patch
        def exercise(window):
            with patch('wowbuddy.github_client.check_latest',return_value={'current_version':'0.2.1','version':'0.3.0','has_update':True}):
                window.ui.update_check_button.click()
                window._client_update_future.result(timeout=5)
                window._finish_client_update_task()
            self.assertIn('发现新版本',window.ui.update_status.text())
            self.assertTrue(window.ui.update_apply_button.isEnabled())
            self.assertEqual(window.ui.update_apply_button.text(),'下载更新包')
        TrayTests.run_window(self,False,exercise)

if __name__=='__main__':unittest.main()
