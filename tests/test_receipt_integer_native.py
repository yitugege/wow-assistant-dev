"""回执字段和动作ID转换与原Qt对照，不运行游戏。"""
import ctypes as C
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.aura_probe import field_integer,spell_id_from_action,AuraProbeLedger,Receipt,ProbeResult
from wowbuddy.send_gates import focus_index,should_skip_focus
from wowbuddy.selftest_focus import _health
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

        # 原089570对focus_party后缀直接toInt；不是field_integer的trim/section流程。
        convert32=getattr(dll,'?toInt@QString@@QEBAHPEA_NH@Z')
        convert32.argtypes=convert.argtypes
        convert32.restype=C.c_int32
        focus_samples=['1','4','5','0','-1','+2',' 2 ','2\0junk','\u00a02\u00a0',
                       '0'*5000+'2','9'*5000,str(2**32+2),'2 extra']
        for index,text in enumerate(focus_samples):
            with self.subTest(index=index,kind='focus'):
                raw=text.encode('utf-16-le');buf=C.create_string_buffer(raw+b'\0\0')
                source=QString(None,C.addressof(buf),len(raw)//2);ok=C.c_bool()
                number=convert32(C.byref(source),C.byref(ok),10)
                expected=number if ok.value and 1<=number<=4 else -1
                action='focus_party'+text
                self.assertEqual(focus_index(action),expected)
                self.assertEqual(should_skip_focus(action,last_action='',last_switch_ms=0,
                    now_ms=4000,focus_known=True,observed_index=2),expected==2)
        health_samples=['25','0','-1','100','+25',' 25 ','25\0ignored','\u00a025\u00a0',
                        '0'*5000+'25','9'*5000,str(2**31-1),str(2**31),'25 extra']
        for index,text in enumerate(health_samples):
            raw=text.encode('utf-16-le');buf=C.create_string_buffer(raw+b'\0\0')
            source=QString(None,C.addressof(buf),len(raw)//2);ok=C.c_bool()
            number=convert32(C.byref(source),C.byref(ok),10)
            for unit in ('player','party1','party2','party3','party4'):
                with self.subTest(index=index,kind='selftest_health',unit=unit):
                    self.assertEqual(_health({'health_'+unit:text},'focus_'+unit),
                                     number if ok.value else -1)
        for action in ('focus_party01','focus_party+1','focus_party1\0','focus_party5','focus_unknown'):
            self.assertEqual(_health({'health_party1':'25'},action),-1)

    def test_receipt_conversion_changes_probe_ledger(self):
        for spell,receipt,result,deadline in (
            ('116\0ignored',Receipt.FIRED_SAME,ProbeResult.IMMUNE,11400),
            ('116\u00a0 note',Receipt.FIRED_OTHER,ProbeResult.MISSED,2400),
            ('9'*5000,Receipt.FIRED_OTHER,ProbeResult.MISSED,2400)):
            with self.subTest(spell_length=len(spell),receipt=receipt):
                ledger=AuraProbeLedger()
                action='spell_'+'0'*5000+'116'
                ledger.record_send(action,success=True,now_ms=1000,hold_ms=10000,
                    expect_off=('aura',),fields={'player_succeeded_generation':'0'*5000+'1'})
                self.assertEqual(ledger.sent_generation[action],1)
                events=ledger.check({'player_succeeded_generation':'2\0ignored',
                    'player_succeeded_spell_id':spell,'aura':'OFF'},now_ms=1400,casting=False)
                self.assertEqual(len(events),1)
                self.assertEqual((events[0].receipt,events[0].result),(receipt,result))
                self.assertEqual(ledger.suppression_until[action],deadline)
                self.assertNotIn(action,ledger.check_at)


if __name__=='__main__':unittest.main()
