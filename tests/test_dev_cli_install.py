import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.build_addon import build
from wowbuddy.dev_cli_install import run_development_install

class CommandInstallTests(unittest.TestCase):
    def test_direct_unicode_path_update_and_no_window_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'addon.zip'
            manifest=build(ROOT/'addon/WowBuddyDev',package,random_names=True)
            package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
            target=root/'直接目标 中文';data=root/'data'
            args=['app','--install-addon','--install-addon-dir=ignored','--install-addon-dir='+str(target)]
            def forbidden():raise AssertionError('显式目录不得探测窗口')
            self.assertEqual(run_development_install(args,package,data,detect=forbidden),0)
            self.assertTrue((target/manifest['addon_directory']/(manifest['addon_directory']+'.toc')).exists())
            self.assertFalse((target/'Interface').exists())
            self.assertTrue((data/'_install_addon_result.txt').read_text('utf8').startswith('OK\n'))
            self.assertEqual(run_development_install(args,package,data,detect=forbidden),0)
            self.assertEqual(len(list((target/'WowBuddyDev-backups').iterdir())),1)

    def test_empty_target_detects_and_prepare_failure_returns_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);calls=[]
            def detect():calls.append(True);return [SimpleNamespace(addons_path=str(root/'chosen'))]
            result=run_development_install(['app','--install-addon','--install-addon-dir='],root/'missing.zip',root/'data',detect=detect)
            self.assertEqual(result,2);self.assertEqual(calls,[True])
            self.assertFalse((root/'chosen').exists())

    def test_real_cli_installs_without_gui_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'target';data=root/'data'
            package=root/'WowBuddyDev-dev.zip'
            manifest=build(ROOT/'addon/WowBuddyDev',package)
            package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
            env=os.environ.copy();env['WOWBUDDY_NO_GAME_SCAN']='1'
            boot='import sys; from pathlib import Path; import run_dev; run_dev.PACKAGE_DIR=Path(sys.argv.pop(1)); raise SystemExit(run_dev.main())'
            cmd=[sys.executable,'-c',boot,str(root),'--install-addon','--install-addon-dir='+str(target),'--data-dir',str(data)]
            result=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue((target/'WowBuddyDev/WowBuddyDev.toc').exists())
            occupied=root/'file';occupied.touch()
            cmd[5]='--install-addon-dir='+str(occupied)
            result=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertTrue((data/'_install_addon_result.txt').read_text('utf8').startswith('FAIL\n'))

if __name__=='__main__':unittest.main()
