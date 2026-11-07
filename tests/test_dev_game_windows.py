"""产品名冲突隔离；保留原优选规则及未识别路径行为。"""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_game_windows import AssistantWindowFilter
from wowbuddy.game_windows import TitleResult,enumerate_windows,find_game_window


class Windows:
    def __init__(self,paths):self.paths=paths
    def enum_windows(self,visitor):
        for hwnd in self.paths:visitor(hwnd)
    def window_pid(self,hwnd):return hwnd
    def process_path(self,pid):return self.paths[pid]
    def current_pid(self):return 999
    def is_visible(self,hwnd):return True
    def is_window(self,hwnd):return hwnd in self.paths
    def window_title(self,hwnd):return TitleResult(True,'窗口')


class AssistantFilterTests(unittest.TestCase):
    def test_gui_passes_executable_only_for_frozen_launch(self):
        import ntpath
        from unittest.mock import patch
        import run_dev
        from test_dev_tray import TrayTests
        for frozen in (False,True):
            with self.subTest(frozen=frozen),patch.object(run_dev,'FROZEN',frozen):
                def exercise(window):
                    expected=ntpath.normcase(ntpath.normpath(sys.executable)) if frozen else None
                    self.assertEqual(window.monitor.backend.current_executable,expected)
                TrayTests().run_window(False,exercise)

    def test_current_process_is_excluded_without_querying_its_path(self):
        from unittest.mock import patch
        backend=Windows({999:''})
        with patch.object(backend,'process_path',side_effect=AssertionError('不应查询自身路径')):
            self.assertEqual(enumerate_windows(AssistantWindowFilter(backend)).windows,())

    def test_renamed_frozen_sibling_is_excluded_by_exact_path(self):
        own=r'D:\Own\cache\WOW战斗助手.exe'
        backend=Windows({1:'d:/own/cache/WOW战斗助手.EXE',2:r'D:\Other\WOW战斗助手.exe',
                         3:r'D:\Game\Wow.exe',4:r'D:\Game\WowB.exe'})
        filtered=AssistantWindowFilter(backend,current_executable=own)
        self.assertEqual([w.hwnd for w in enumerate_windows(filtered).windows],[2,3,4])
        self.assertEqual(find_game_window(filtered),4)

    def test_source_mode_does_not_exclude_other_python_windows(self):
        backend=Windows({1:r'C:\Python\python.exe',2:r'C:\Game\Wow.exe'})
        self.assertEqual([w.hwnd for w in enumerate_windows(AssistantWindowFilter(backend)).windows],[1,2])

    def test_original_collision_reproduced_and_product_instance_excluded(self):
        backend=Windows({1:r'D:\download\WowBuddyDev.exe'})
        self.assertEqual(find_game_window(backend),1)
        self.assertEqual(find_game_window(AssistantWindowFilter(backend)),0)

    def test_actual_games_keep_original_priority_and_paths(self):
        backend=Windows({1:r'D:\WoWBuddyDEV.EXE',2:r'C:\Game\Wow.exe',3:r'D:\Game\WowB.exe'})
        filtered=AssistantWindowFilter(backend)
        self.assertEqual(find_game_window(filtered),3)
        self.assertEqual([w.hwnd for w in enumerate_windows(filtered).windows],[2,3])
        self.assertEqual(filtered.process_path(3),backend.process_path(3))
        self.assertTrue(filtered.is_window(3))

    def test_unknown_paths_and_other_windows_are_not_globally_filtered(self):
        backend=Windows({1:'',2:r'C:\Tools\Editor.exe',3:r'C:\Tools\other-wow-tool.exe'})
        filtered=AssistantWindowFilter(backend)
        self.assertEqual([w.hwnd for w in enumerate_windows(filtered).windows],[1,2,3])
        self.assertEqual(find_game_window(filtered),3)


if __name__=='__main__':unittest.main()
