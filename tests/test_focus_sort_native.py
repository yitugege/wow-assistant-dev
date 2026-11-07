"""对照原031570/0326d0调用图；仅运行原整数索引排序，不启动助手。"""
import ctypes as C
import hashlib
import itertools
import os
import random
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.candidates import Candidate, _reorder_focus_health
from wowbuddy.expressions import EvaluationContext
from wowbuddy.focus_sort import health_order


class FocusSortNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/WOW战斗助手.exe')
        if os.name!='nt' or not path.is_file():raise unittest.SkipTest('需要原Windows x64 EXE')
        import pefile
        payload=path.read_bytes()
        assert hashlib.sha256(payload).hexdigest()=='7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488'
        pe=pefile.PE(data=payload)
        base=0x307a0
        code=pe.get_data(base,0x327e5-base)
        # 完整复制内部排序调用图，保留相对调用；所调用函数无外部依赖。
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
        cls.native=C.CFUNCTYPE(C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p)(address+0x31570-base)
        cls.merge_native=C.CFUNCTYPE(None,C.c_void_p,C.c_void_p,C.c_int64,
                                    C.c_void_p,C.c_int64,C.c_void_p)(address+0x326d0-base)

    def order(self,values,capacity=None):
        indexes=(C.c_int32*len(values))(*range(len(values)))
        health=(C.c_double*len(values))(*values)
        array=(C.c_void_p*3)(None,C.addressof(health),len(values))
        result=C.c_void_p()
        if len(values)<=32:
            self.native(C.byref(result),C.addressof(indexes),C.addressof(indexes)+C.sizeof(indexes),C.byref(array))
        else:
            size=(len(values)+1)//2 if capacity is None else capacity
            buffer=(C.c_int32*size)()
            self.merge_native(C.addressof(indexes),C.addressof(indexes)+C.sizeof(indexes),
                              len(values),C.addressof(buffer),size,C.byref(array))
        return list(indexes)

    def test_reduced_and_zero_buffer(self):
        rng=random.Random(309)
        for count in (33,34,63,64,65,127,257):
            for capacity in (0,1,2,8,16,31,32):
                samples=[list(range(count)),list(range(count))[::-1],[20.0]*count]
                samples += [[rng.choice([0.,10.,20.,50.,99.,float('nan')]) for _ in range(count)]
                            for _ in range(10)]
                for case,values in enumerate(samples):
                    with self.subTest(count=count,capacity=capacity,case=case):
                        self.assertEqual(health_order(values,buffer_capacity=capacity),
                                         self.order(values,capacity))

    def test_large_groups_against_original_merge(self):
        rng=random.Random(326)
        for count in (33,34,63,64,65,66,127,128,129,255,256,257,2048,2049):
            samples=[list(range(count)),list(range(count))[::-1], [20.0]*count]
            samples += [[rng.choice([0.,10.,20.,50.,99.,float('nan')]) for _ in range(count)]
                        for _ in range(20)]
            for case,values in enumerate(samples):
                with self.subTest(count=count,case=case):
                    self.assertEqual(health_order(values),self.order(values))

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
        for count in (2,3,5,16,31,32,33,64,65,128,257):
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
