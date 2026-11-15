"""静态分层约束：core 只依赖自身与标准库；automation 不导入 Qt。

只解析源码中的 import 语句，不执行模块；函数内的延迟导入同样计入。
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'desktop/wowbuddy'
GUI_OR_NATIVE = {'PySide6', 'ctypes', 'winreg'}


def imports(path):
    """返回 (外部顶层包集合, 本包内被导入的完整模块名集合)。"""
    parts = path.parent.relative_to(PACKAGE.parent).parts
    external, internal = set(), set()
    for node in ast.walk(ast.parse(path.read_text('utf-8-sig'))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                (internal if alias.name.startswith('wowbuddy') else external).add(
                    alias.name if alias.name.startswith('wowbuddy') else alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(parts[:len(parts) - (node.level - 1)])
                internal.add('.'.join(base + ([node.module] if node.module else [])))
            elif (node.module or '').startswith('wowbuddy'):
                internal.add(node.module)
            else:
                external.add((node.module or '').split('.')[0])
    return external, internal


class LayerBoundaryTests(unittest.TestCase):
    def layer_files(self, layer):
        files = sorted((PACKAGE / layer).glob('*.py'))
        self.assertTrue(files, layer)
        return files

    def test_core_has_no_gui_native_or_upper_layer_imports(self):
        for path in self.layer_files('core'):
            with self.subTest(module=path.name):
                external, internal = imports(path)
                self.assertFalse(external & GUI_OR_NATIVE)
                outside = {name for name in internal
                           if name != 'wowbuddy.core' and not name.startswith('wowbuddy.core.')}
                self.assertFalse(outside, '核心层只能导入 wowbuddy.core')

    def test_automation_does_not_import_qt_or_app(self):
        for path in self.layer_files('automation'):
            with self.subTest(module=path.name):
                external, internal = imports(path)
                self.assertNotIn('PySide6', external)
                self.assertFalse({name for name in internal if name.startswith('wowbuddy.app')})

    def test_lower_layers_never_import_app(self):
        for layer in ('core', 'win32', 'automation', 'engine', 'update', 'legacy'):
            for path in self.layer_files(layer):
                with self.subTest(module=f'{layer}/{path.name}'):
                    self.assertFalse({name for name in imports(path)[1] if name.startswith('wowbuddy.app')})


if __name__ == '__main__':
    unittest.main()
