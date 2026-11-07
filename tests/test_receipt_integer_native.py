"""回执字段和动作ID转换与原Qt对照，不运行游戏。"""
import ctypes as C
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.aura_probe import field_integer,spell_id_from_action
from test_availability_display_native import QString


class ReceiptIntegerNativeTests(unittest.TestCase):
    def test_field_and_action_conversion(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll')
        if os.name!='nt' or not path.is_file():self.skipTest('需要原Qt DLL')
        with os.add_dll_directory(str(path.parent)):dll=C.CDLL(str(path))
        convert=getattr(dll,'?toLongLong@QString@@QEBA_JPEA_NH@Z')
        convert.argtypes=[C.POINTER(QString),C.POINTER(C.c_bool),C.c_int]
        convert.restype=C.c_int64
        def native(text):
            raw=text.encode('utf-16-le');buf=C.create_string_buffer(raw+b'\0\0')
            source=QString(None,C.addressof(buf),len(raw)//2);ok=C.c_bool()
            number=convert(C.byref(source),C.byref(ok),10)
            return number if ok.value else -1
        samples=['116','2','1','0','-1','+116','116\0junk','116\u00a0 tail',
                 '\u00a0116\u00a0','\t116\t','116 extra','0'*5000+'116',
                 '9'*5000,str(2**63-1),str(2**63),str(0xfffffe),str(0xffffff),'']
        for index,text in enumerate(samples):
            with self.subTest(index=index,kind='field'):
                expected=native(text.strip().split(' ',1)[0])
                self.assertEqual(field_integer({'value':text},'value'),expected)
            with self.subTest(index=index,kind='action'):
                value=native(text)
                expected=value if 2<=value<=0xfffffe else -1
                self.assertEqual(spell_id_from_action('spell_'+text+'_target'),expected)


if __name__=='__main__':unittest.main()
