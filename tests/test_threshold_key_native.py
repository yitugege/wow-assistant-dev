"""阈值键第二阶段使用原包QString整数arg作对照。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from wowbuddy.thresholds import threshold_key, promote_rules, SwitchField
from wowbuddy.candidates import parse_rules
from test_availability_display_native import QString


class ThresholdKeyNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path('D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll')
        if os.name != 'nt' or not path.is_file():
            raise unittest.SkipTest('需要原Windows Qt DLL')
        assert hashlib.sha256(path.read_bytes()).hexdigest() == 'b712b4754588e89f855dc0aa087d6304b2fd21b0e0639d1cdeb9cb969bd5fb72'
        with os.add_dll_directory(str(path.parent)): cls.dll = C.CDLL(str(path))
        cls.convert = getattr(cls.dll, '?arg_impl@QString@@AEBA?AV1@_JHHVQChar@@@Z')
        cls.convert.argtypes = [C.POINTER(QString), C.POINTER(QString), C.c_int64, C.c_int, C.c_int, C.c_uint16]
        cls.convert.restype = C.c_void_p
        cls.destroy = getattr(cls.dll, '??1QString@@QEAA@XZ')
        cls.destroy.argtypes = [C.POINTER(QString)]
        cls.destroy.restype = None

    def native(self, text, number):
        raw = text.encode('utf-16-le')
        buffer = C.create_string_buffer(raw+b'\0\0')
        source = QString(None, C.addressof(buffer), len(raw)//2)
        result = QString()
        self.convert(C.byref(source), C.byref(result), number, 0, 10, 32)
        try: return C.string_at(result.ptr, result.size*2).decode('utf-16-le')
        finally: self.destroy(C.byref(result))

    def test_original_numeric_arg_and_placeholder_rescan(self):
        for token in ('', '%1', '%4', '%0', '%01', '%99', '%%1', '%100', '%１', '%١', '%𝟙', '%²', '%L1', '%L4'):
            for action, field in ((f'cast{token}', 'health'), ('cast', f'health{token}')):
                with self.subTest(action=action, field=field):
                    self.assertEqual(threshold_key(action, field, 'below', 1234),
                                     self.native(f'sw_{action}~{field}_b%4', 1234))
        self.assertEqual(threshold_key('', 'health', 'at_least', 30), 'sw_-~health_a30')

    def test_rule_rewrite_uses_recovered_key(self):
        rule = parse_rules([{'action': 'cast%1', 'when': ['num_below', 'health', 30]}])[0]
        result = promote_rules([rule], {'health': SwitchField('health', '生命')}, {})
        self.assertEqual(result.thresholds[0].key, 'sw_cast30~health_b%4')
        self.assertEqual(result.rules[0].when, ['flag', result.thresholds[0].key, True])


if __name__ == '__main__': unittest.main()
