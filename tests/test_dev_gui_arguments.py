"""普通GUI沿用原列表匹配语义；不启动游戏、窗口或网络。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
import run_dev


class GuiArgumentsTests(unittest.TestCase):
    def launch_options(self,arguments):
        with patch.object(sys,'argv',['run_dev.py',*arguments]),patch.object(run_dev,'launch',return_value=0) as launch:
            self.assertEqual(run_dev.main(),0)
            launch.assert_called_once()
            return launch.call_args

    def test_unknown_and_irrelevant_arguments_do_not_prevent_gui(self):
        for tail in (['--unknown','value'],['--aut'],['--AUTO'],['--auto=true'],
                     ['--spec'],['--spec=1482'],['--talent'],['--rotation=bad'],['--hub-fetch'],
                     ['--install-addon-dir'],['--dump-ui=true']):
            with self.subTest(tail=tail):
                call=self.launch_options(tail)
                self.assertFalse(call.kwargs['auto_start'])
                self.assertTrue(call.kwargs['watch'])
                self.assertTrue(call.kwargs['staged'])

    def test_exact_flags_are_recognized_even_after_double_dash(self):
        call=self.launch_options(['--','--auto','--no-update','--auto'])
        self.assertTrue(call.kwargs['auto_start'])
        self.assertTrue(call.kwargs['no_update'])
        self.assertFalse(self.launch_options(['--no-update=true']).kwargs['no_update'])

    def test_independent_data_directory_and_no_watch_remain_supported(self):
        call=self.launch_options(['--data-dir=first','--data-dir','second','--no-watch','--unknown'])
        self.assertEqual(call.args,(Path('second'),))
        self.assertFalse(call.kwargs['watch'])


if __name__=='__main__':unittest.main()
