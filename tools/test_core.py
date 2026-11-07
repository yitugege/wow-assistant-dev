"""只导入本仓库源码，运行迁入的核心行为回归用例。"""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tests/core'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    imported = {name:str(Path(module.__file__).resolve())
                for name,module in list(sys.modules.items())
                if name.startswith('wowbuddy') and getattr(module,'__file__',None)}
    local = bool(imported) and all(Path(path).is_relative_to(ROOT/'desktop')
                                   for path in imported.values())
    report = {'passed':result.wasSuccessful() and local,
              'tests_run':result.testsRun,'failures':len(result.failures),
              'errors':len(result.errors),'skipped':len(result.skipped),
              'all_imports_from_this_repository':local,'modules':imported,
              'scope':'合成输入与模拟系统后端的核心行为回归，不是游戏实测或完整还原证明'}
    (ROOT/'dist').mkdir(exist_ok=True)
    (ROOT/'dist/core-tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    return int(not report['passed'])


if __name__=='__main__':
    raise SystemExit(main())
