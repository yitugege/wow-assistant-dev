import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_addon_cleanup import cleanup_old_addons
from wowbuddy.addon_install import SIGNATURE_FILES


class CleanupTests(unittest.TestCase):
    def fixture(self,root):
        client=root/'client';client.mkdir();(client/'Wow.exe').touch()
        addons=client/'Interface/AddOns';addons.mkdir(parents=True)
        for name in ('legacy','WowBuddyDev','unrelated','partial'):
            folder=addons/name;folder.mkdir()
            (folder/(name+'.toc')).write_text('fixture','utf8')
            for signature in SIGNATURE_FILES:
                if name not in ('unrelated','partial'):(folder/signature).touch()
        (addons/'partial/pixelbar.lua').touch()
        (client/'.wowbuddy-install.json').write_text(json.dumps({'product':'wowbuddy-dev','addon_directory':'WowBuddyDev'}),'utf8')
        return client,addons

    def test_deletes_only_legacy_and_keeps_installed_and_unrelated(self):
        with tempfile.TemporaryDirectory() as tmp:
            client,addons=self.fixture(Path(tmp))
            result=cleanup_old_addons(client)
            self.assertEqual(result.deleted,1)
            self.assertFalse((addons/'legacy').exists())
            for name in ('WowBuddyDev','unrelated','partial'):self.assertTrue((addons/name).is_dir())
            self.assertEqual(cleanup_old_addons(client).deleted,0)

    def test_failed_delete_reports_failure_and_keeps_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            client,addons=self.fixture(Path(tmp))
            with patch('wowbuddy.addon_actions._remove_plugin_directory',side_effect=OSError('locked')):
                result=cleanup_old_addons(client)
            self.assertEqual(result.deleted,0);self.assertIn('删除失败',result.notes)
            self.assertTrue((addons/'legacy').exists())

    def test_gui_button_and_monitor_guard(self):
        from test_dev_tray import TrayTests
        def exercise(window):
            with tempfile.TemporaryDirectory() as tmp:
                client,addons=self.fixture(Path(tmp))
                window._select_development_client(str(client))
                with patch('wowbuddy.addon_games.selected_executable',return_value=str(client/'Wow.exe')):
                    window._addon_cleanup_button.click()
                    self.assertTrue((addons/'legacy').exists())
                    self.assertIn('正在运行',window.ui.addon_status.text())
                with patch('wowbuddy.addon_games.selected_executable',return_value=''):
                    window.toggle_monitor()
                    window._addon_cleanup_button.click()
                    self.assertTrue((addons/'legacy').exists())
                    self.assertIn('停止监控',window.ui.addon_status.text())
                    window.toggle_monitor()
                    window._addon_cleanup_button.click()
                    self.assertFalse((addons/'legacy').exists())
                    self.assertIn('删除 1',window.ui.addon_status.text())
        TrayTests.run_window(self,False,exercise)

if __name__=='__main__':unittest.main()
