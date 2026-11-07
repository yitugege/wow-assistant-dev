"""原包QString::toDouble对照，按044fd0的trimmed→section顺序准备文本。"""
import ctypes as C
import math
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.expressions import EvaluationContext, _trim
from test_availability_display_native import QString


class ExpressionNumberNativeTests(unittest.TestCase):
    def test_original_qt_number_conversion_boundaries(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll')
        if os.name!='nt' or not path.is_file():self.skipTest('需要原Windows包Qt6Core.dll')
        with os.add_dll_directory(str(path.parent)):dll=C.CDLL(str(path))
        convert=getattr(dll,'?toDouble@QString@@QEBANPEA_N@Z')
        convert.argtypes=[C.POINTER(QString),C.POINTER(C.c_bool)]
        convert.restype=C.c_double
        bases=['12.5','-0','0','1e-999','5e-324','1e999','nan','inf','+inf','-nan','1_000','１２']
        wrappers=[lambda s:s,lambda s:'\u3000'+s+'\u00a0',lambda s:s+'\0junk',
                  lambda s:s+'\u00a0 suffix',lambda s:s+'\t suffix',
                  lambda s:s+'\u2003 suffix',lambda s:s+'\x1c suffix']
        for base in bases:
            for wrap in wrappers:
                text=wrap(base)
                with self.subTest(text=repr(text)):
                    token=_trim(text).split(' ',1)[0]
                    raw=token.encode('utf-16-le')
                    buffer=C.create_string_buffer(raw+b'\0\0')
                    value=QString(None,C.addressof(buffer),len(raw)//2)
                    ok=C.c_bool()
                    number=convert(C.byref(value),C.byref(ok))
                    actual=EvaluationContext({'n':text}).number('n')
                    self.assertEqual(actual is not None,ok.value)
                    if ok.value:
                        if math.isnan(number):self.assertTrue(math.isnan(actual))
                        else:self.assertEqual(actual,number)


if __name__=='__main__':unittest.main()
