from pathlib import Path
import tempfile
import sys
import json
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_game_paths import discover_clients,normalize_client
from wowbuddy.settings import open_ini_settings

class GamePathsTests(unittest.TestCase):
    def test_variants_normalization_rank_history_and_scan_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);settings=open_ini_settings(str(root/'settings.ini'))
            clients=[]
            for name,exe in [('_classic_beta_','WowB.exe'),('_forever_','Wow.exe')]:
                client=root/'游戏'/name;client.mkdir(parents=True);(client/exe).touch();clients.append(client)
                for path in (client,client/'Interface',client/'Interface/AddOns'):
                    self.assertEqual(normalize_client(path),client)
            self.assertEqual(normalize_client(root/'游戏'),clients[0])
            settings.save_addon_dir(str(clients[1]))
            paths=discover_clients(settings,running_executable=str(clients[0]/'WowB.exe'),search_roots=[root/'游戏'])
            self.assertEqual(paths,tuple(clients))
            self.assertEqual(discover_clients(settings,search_roots=[root/'游戏'],environment={'WOWBUDDY_NO_GAME_SCAN':''}),())
            addon=clients[1]/'Interface/AddOns/w123456789abc';addon.mkdir(parents=True);(addon/(addon.name+'.toc')).touch()
            (clients[1]/'.wowbuddy-install.json').write_text(json.dumps({'product':'wowbuddy-dev','addon_directory':addon.name}),'utf8')
            self.assertEqual(discover_clients(settings,search_roots=[root/'游戏'])[0],clients[1])
            settings.save_addon_dir(str(root/'missing'))
            self.assertEqual(discover_clients(settings,search_roots=[root/'游戏'])[0],clients[1])
            with self.assertRaises(ValueError):normalize_client(root/'missing')

    def test_gui_detection_and_history_selection(self):
        from test_dev_tray import TrayTests
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QPoint,QTimer
        def exercise(window):
            with tempfile.TemporaryDirectory() as tmp:
                client=Path(tmp)/'_forever_';client.mkdir();(client/'Wow.exe').touch()
                with patch('wowbuddy.addon_games.selected_executable',return_value=str(client/'Wow.exe')),patch('wowbuddy.dev_game_paths.common_roots',return_value=()):
                    window.ui.addon_clean_button.click()
                self.assertEqual(Path(window.ui.addon_path.text()),client)
                self.assertEqual(window.settings.snapshot().addon_history,(str(client).replace('\\','/'),))
                def choose():
                    menu=QApplication.activePopupWidget();menu.actions()[0].trigger();menu.close()
                QTimer.singleShot(20,choose)
                window._recent_development_clients(QPoint(0,0))
                self.assertEqual(Path(window.ui.addon_path.text()),client)
                def clear():
                    menu=QApplication.activePopupWidget();menu.actions()[-1].trigger();menu.close()
                QTimer.singleShot(20,clear)
                window._recent_development_clients(QPoint(0,0))
                self.assertEqual(window.settings.snapshot().addon_history,())
        TrayTests.run_window(self,False,exercise)

if __name__=='__main__':unittest.main()
