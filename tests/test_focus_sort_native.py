"""对照原031570的独立机器码；只运行无外部调用的整数索引排序。"""
import ctypes as C
import hashlib
import itertools
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.candidates import Candidate, _reorder_focus_health
from wowbuddy.expressions import EvaluationContext


class FocusSortNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/WOW战斗助手.exe')
        if os.name!='nt' or not path.is_file():raise unittest.SkipTest('需要原Windows x64 EXE')
        import pefile
        payload=path.read_bytes()
        assert hashlib.sha256(payload).hexdigest()=='7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488'
        pe=pefile.PE(data=payload)
        code=pe.get_data(0x31570,0x103)
        # 031570..031672：无导入、无RIP数据访问，仅内部相对分支。
        k=C.WinDLL('kernel32',use_last_error=True)
        k.VirtualAlloc.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.c_ulong]
        k.VirtualAlloc.restype=C.c_void_p
        k.VirtualProtect.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.POINTER(C.c_ulong)]
        k.VirtualFree.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong]
        address=k.VirtualAlloc(None,len(code),0x3000,4)
        if not address:raise C.WinError(C.get_last_error())
        cls.addClassCleanup(lambda:k.VirtualFree(address,0,0x8000))
        C.memmove(address,code,len(code));previous=C.c_ulong()
        if not k.VirtualProtect(address,len(code),0x20,C.byref(previous)):
            raise C.WinError(C.get_last_error())
        cls.native=C.CFUNCTYPE(C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p)(address)

    def order(self,values):
        indexes=(C.c_int32*len(values))(*range(len(values)))
        health=(C.c_double*len(values))(*values)
        array=(C.c_void_p*3)(None,C.addressof(health),len(values))
        result=C.c_void_p()
        self.native(C.byref(result),C.addressof(indexes),C.addressof(indexes)+C.sizeof(indexes),C.byref(array))
        return list(indexes)

    def test_five_targets_against_original_insertion_sort(self):
        # 与原0495c7/0495e1的ja/jae一致：NaN未触发负值/哨兵拒绝。
        for texts in itertools.permutations(('50','nan','10','20','20')):
            with self.subTest(texts=texts):
                fields={'health_party'+str(i+1):v for i,v in enumerate(texts[:4])}
                fields['health_player']=texts[4]
                units=['party1','party2','party3','party4','player']
                items=[Candidate(action='heal',tag='same',pre_action='focus_'+unit,
                                 label=str(i),priority=1000-5*i) for i,unit in enumerate(units)]
                _reorder_focus_health(items,EvaluationContext(fields),16777215)
                self.assertEqual([int(c.label) for c in items],self.order(list(map(float,texts))))
                self.assertEqual([c.priority for c in items],[1000,995,990,985,980])

    def test_insertion_boundary_and_repeated_targets(self):
        for count in (2,3,5,16,31,32):
            for texts in (('50','nan','10','20','20'),('nan','50','10','0','99'),
                          ('50','40','30','20','10'),('20','20','20','20','20')):
                with self.subTest(count=count,texts=texts):
                    units=['party1','party2','party3','party4','player']
                    fields={'health_'+unit:value for unit,value in zip(units,texts)}
                    items=[Candidate(action='heal',tag='same',pre_action='focus_'+units[i%5],
                                     label=str(i),priority=1000-i) for i in range(count)]
                    values=[float(texts[i%5]) for i in range(count)]
                    _reorder_focus_health(items,EvaluationContext(fields),16777215)
                    self.assertEqual([int(c.label) for c in items],self.order(values))
                    self.assertEqual([c.priority for c in items],list(range(1000,1000-count,-1)))


if __name__=='__main__':unittest.main()
