"""用原包QString字符串arg验证色块悬停字幕，不执行原主程序。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import sys
import unittest
from PySide6.QtWidgets import QApplication
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from wowbuddy.app.swatch_strip import SwatchStrip, SwatchItem
from test_availability_display_native import QString

class StringView(C.Structure):
    _fields_=[('ptr',C.c_void_p),('size',C.c_size_t)]

class SwatchHoverNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll')
        if os.name!='nt' or not path.is_file(): raise unittest.SkipTest('需要原包Qt')
        assert hashlib.sha256(path.read_bytes()).hexdigest()=='b712b4754588e89f855dc0aa087d6304b2fd21b0e0639d1cdeb9cb969bd5fb72'
        with os.add_dll_directory(str(path.parent)): cls.dll=C.CDLL(str(path))
        cls.arg=getattr(cls.dll,'?arg_impl@QString@@AEBA?AV1@VQAnyStringView@@HVQChar@@@Z')
        cls.arg.argtypes=[C.POINTER(QString),C.POINTER(QString),C.POINTER(StringView),C.c_int,C.c_uint16]
        cls.arg.restype=C.c_void_p
        cls.destroy=getattr(cls.dll,'??1QString@@QEAA@XZ')
        cls.destroy.argtypes=[C.POINTER(QString)]
        cls.destroy.restype=None

    def native(self,text,value):
        raw=text.encode('utf-16-le','surrogatepass')
        replacement=value.encode('utf-16-le','surrogatepass')
        buf=C.create_string_buffer(raw+b'\0\0')
        val=C.create_string_buffer(replacement+b'\0\0')
        source=QString(None,C.addressof(buf),len(raw)//2)
        view=StringView(C.addressof(val),(len(replacement)//2)|(1<<63))
        result=QString()
        self.arg(C.byref(source),C.byref(result),C.byref(view),0,32)
        try:return C.string_at(result.ptr,result.size*2).decode('utf-16-le','surrogatepass')
        finally:self.destroy(C.byref(result))

    def test_hover_rescans_label_but_tooltip_does_not(self):
        widget=SwatchStrip()
        try:
            for label in ('生命','', '%1','%0','%01','%3','%4','%L1','%%1','%100','%１','%١','%𝟙'):
                for value in ('19','', '%2'):
                    with self.subTest(label=label,value=value):
                        widget.set_items([SwatchItem((1,2,3),label,value,7)])
                        expected=self.native(self.native('#7 %2 = %3',label),value or '—')
                        self.assertEqual(widget.hover_text(0),expected)
                        self.assertEqual(widget.tooltip_text(0),f"#7  {label or '(通用)'} = {value or '—'}")
        finally:
            widget.close();widget.deleteLater()

if __name__=='__main__':unittest.main()
