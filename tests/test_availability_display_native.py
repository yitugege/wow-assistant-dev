"""可用技能统计的int64边界；用原包Qt转换函数作对照。"""
import ctypes as C
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.presentation import availability


class QString(C.Structure):
    _fields_=[('data',C.c_void_p),('ptr',C.c_void_p),('size',C.c_ssize_t)]


class AvailabilityDisplayNativeTests(unittest.TestCase):
    def test_native_int64_boundaries(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll')
        if os.name!='nt' or not path.is_file():
            self.skipTest('需要原Windows包Qt6Core.dll')
        with os.add_dll_directory(str(path.parent)):
            dll=C.CDLL(str(path))
        convert=getattr(dll,'?toLongLong@QString@@QEBA_JPEA_NH@Z')
        convert.argtypes=[C.POINTER(QString),C.POINTER(C.c_bool),C.c_int]
        convert.restype=C.c_int64
        samples=['0','2','-1',str(-2**63),str(2**63-1),str(2**63),str(-2**63-1),
                 '0'*5000+'2','-'+'0'*5000+'2','9'*5000,'2\0junk','\t2\t',
                 '2\u00a0 trailing','2 extra','+2','2.0','１２']
        for index,text in enumerate(samples):
            with self.subTest(index=index,length=len(text)):
                # 原0a2d70先trimmed再section(字面空格,0,0)。本组无首尾Unicode空白。
                token=text.strip().split(' ',1)[0]
                raw=token.encode('utf-16-le')
                buf=C.create_string_buffer(raw+b'\0\0')
                value=QString(None,C.addressof(buf),len(raw)//2)
                ok=C.c_bool()
                number=convert(C.byref(value),C.byref(ok),10)
                result=availability({'actionAvailSpellIDs':[116]}, {'action_avail':text})
                self.assertEqual(result.valid,ok.value)
                self.assertEqual(result.ready_count,((number>>1)&1) if ok.value else 0)


if __name__=='__main__':unittest.main()
