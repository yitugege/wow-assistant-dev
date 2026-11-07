"""规则数字字段与原附带Qt QJsonValue转换对照。"""
import ctypes as C
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.candidates import Action,parse_rules


class RuleJsonNativeTests(unittest.TestCase):
    def test_hold_spell_and_off_gcd_types(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll')
        if os.name!='nt' or not path.is_file():self.skipTest('需要原Qt DLL')
        with os.add_dll_directory(str(path.parent)):dll=C.CDLL(str(path))
        def method(name,args,result):
            fn=getattr(dll,name);fn.argtypes=args;fn.restype=result;return fn
        ctor_double=method('??0QJsonValue@@QEAA@N@Z',[C.c_void_p,C.c_double],C.c_void_p)
        ctor_bool=method('??0QJsonValue@@QEAA@_N@Z',[C.c_void_p,C.c_bool],C.c_void_p)
        ctor_string=method('??0QJsonValue@@QEAA@PEBD@Z',[C.c_void_p,C.c_char_p],C.c_void_p)
        ctor_null=method('??0QJsonValue@@QEAA@W4Type@0@@Z',[C.c_void_p,C.c_int],C.c_void_p)
        destroy=method('??1QJsonValue@@QEAA@XZ',[C.c_void_p],None)
        integer=method('?toInt@QJsonValue@@QEBAHH@Z',[C.c_void_p,C.c_int],C.c_int)
        boolean=method('?toBool@QJsonValue@@QEBA_N_N@Z',[C.c_void_p,C.c_bool],C.c_bool)
        values=[None,False,True,'','1','true','-1','3000',0,1,-1,3000,0.5,-0.5,
                2999.999999,3000.000001,2**31-1,2**31,-2**31,-2**31-1,
                2**53,1e308,-1e308,1e-300,-0.0]
        for value in values:
            with self.subTest(value=value):
                storage=(C.c_uint64*3)()
                if value is None:ctor_null(storage,0)
                elif isinstance(value,bool):ctor_bool(storage,value)
                elif isinstance(value,str):ctor_string(storage,value.encode('utf8'))
                else:ctor_double(storage,float(value))
                try:
                    rule=parse_rules([{'action':'heal','when':None,'holdMs':value,'offGcd':value}])[0]
                    self.assertEqual(rule.hold_ms,integer(storage,0))
                    self.assertEqual(rule.off_gcd,boolean(storage,False))
                    self.assertEqual(Action.from_json({'spellId':value}).spell_id,integer(storage,-1))
                    self.assertIsNone(rule.when)
                finally:destroy(storage)


if __name__=='__main__':unittest.main()
