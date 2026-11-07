"""0b6b50数字分段：使用原包QChar及QString转换，不执行EXE/联网。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from wowbuddy.updater import version_segments
from test_availability_display_native import QString


class VersionSegmentsNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path('D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll')
        if os.name != 'nt' or not path.is_file():
            raise unittest.SkipTest('需要原Windows包Qt6Core.dll')
        assert hashlib.sha256(path.read_bytes()).hexdigest() == 'b712b4754588e89f855dc0aa087d6304b2fd21b0e0639d1cdeb9cb969bd5fb72'
        with os.add_dll_directory(str(path.parent)):
            cls.dll = C.CDLL(str(path))
        cls.digit = getattr(cls.dll, '?isDigit@QChar@@SA_N_U@Z')
        cls.digit.argtypes = [C.c_uint32]
        cls.digit.restype = C.c_bool
        cls.convert = getattr(cls.dll, '?toLongLong@QString@@QEBA_JPEA_NH@Z')
        cls.convert.argtypes = [C.POINTER(QString), C.POINTER(C.c_bool), C.c_int]
        cls.convert.restype = C.c_int64

    def native_segments(self, text):
        raw = text.encode('utf-16-le', 'surrogatepass')
        units = struct.unpack('<' + 'H' * (len(raw)//2), raw)
        result, part = [], []
        for unit in (*units, 0):
            if self.digit(unit):
                part.append(unit)
            elif part:
                buffer = (C.c_uint16 * (len(part)+1))(*part, 0)
                value = QString(None, C.addressof(buffer), len(part))
                # 原函数不接收ok标志，保留Qt失败返回0。
                result.append(self.convert(C.byref(value), None, 10))
                part = []
        return tuple(result)

    def test_all_utf16_units_digit_classification(self):
        for unit in range(65536):
            self.assertEqual(bool(self.digit(unit)), chr(unit).isdecimal(), hex(unit))

    def test_segmentation_and_original_integer_conversion(self):
        samples = ['', 'v1.0.38', '-1+02rc3', '1\0２.3', '１２.3', '١٢.3',
                   '1𝟚3', '1\ud8002', '²1.Ⅲ2', str(2**63-1), str(2**63),
                   '0'*5000+'7', '9'*5000, '1.'+'0'*5000+'7.4']
        for index, text in enumerate(samples):
            with self.subTest(index=index):
                self.assertEqual(version_segments(text), self.native_segments(text))


if __name__ == '__main__':
    unittest.main()
