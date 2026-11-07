"""原03dc90打断表达式：UTF-16长度和原Qt十六进制转换对照。"""
import ctypes as C
import os
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.expressions import EvaluationContext,evaluate
from test_availability_display_native import QString


class InterruptibleNativeTests(unittest.TestCase):
    def test_original_qt_hex_and_length_gate(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll')
        if os.name!='nt' or not path.is_file():self.skipTest('需要原Qt DLL')
        with os.add_dll_directory(str(path.parent)):dll=C.CDLL(str(path))
        convert=getattr(dll,'?toUInt@QString@@QEBAIPEA_NH@Z')
        convert.argtypes=[C.POINTER(QString),C.POINTER(C.c_bool),C.c_int]
        convert.restype=C.c_uint32
        samples=[f'#00ff{i:02x}' for i in range(256)]
        samples+=['#000000','#ffffff','#00feff','#010000','#ff00\0x','#\u00a0ff00 ',
                  '# ff00 ','#+0ff00','#0xff00','#-0ff00','#ff00\0😀','#\u00a00ff00',
                  '#ff00\0\ud800','#00ff0','#000ff00','00ff00','#FF00\t\t']
        for index,text in enumerate(samples):
            with self.subTest(index=index,text=repr(text)):
                expected=False
                if len(text.encode('utf-16-le','surrogatepass'))==14 and text.startswith('#'):
                    raw=text[1:].encode('utf-16-le','surrogatepass')
                    buf=C.create_string_buffer(raw+b'\0\0')
                    source=QString(None,C.addressof(buf),len(raw)//2);ok=C.c_bool()
                    number=convert(C.byref(source),C.byref(ok),16)
                    expected=ok.value and number&0xffffff00==0xff00
                self.assertEqual(evaluate(['interruptible','target_casting'],
                    EvaluationContext({'target_casting':text})),expected)


if __name__=='__main__':unittest.main()
