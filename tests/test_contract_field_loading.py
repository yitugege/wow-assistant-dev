"""02c9e0静态语义与实际文件加载→旧像素整帧链；不运行原EXE。"""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.native_assets import NativeAssetStore
from wowbuddy.old_protocol import OldDecoder
from wowbuddy.pixel_geometry import RGBImage, BarGeometry


class ContractFieldLoadingTests(unittest.TestCase):
    def load(self, raw):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'contract.json'
            path.write_text(json.dumps(raw, ensure_ascii=True), 'utf8')
            store = NativeAssetStore()
            store.load_contract(path)
            return store.contract.document

    def test_field_string_conversion_defaults_order_and_forced_presence(self):
        rows = [None, False, 7, 'text', [], {},
                {'id':'x','label':'','type':'','note':False},
                {'id':7,'label':True,'type':[],'note':{}},
                {'id':' x ','label':' ','type':' ','note':'\ud800'},
                {'id':'duplicate','type':'cooldown'}, {'id':'duplicate','type':'health'}]
        doc = self.load({'commonFields':rows, 'specs':{'1482':{
            'fields':rows, 'presenceFields':rows}}})
        blank = {'id':'','label':'','type':'number','note':''}
        expected = [dict(blank) for _ in range(6)] + [
            {'id':'x','label':'x','type':'number','note':''}, dict(blank),
            {'id':' x ','label':' ','type':' ','note':'\ud800'},
            {'id':'duplicate','label':'duplicate','type':'cooldown','note':''},
            {'id':'duplicate','label':'duplicate','type':'health','note':''}]
        self.assertEqual(doc['commonFields'], expected)
        self.assertEqual(doc['specs']['1482']['fields'], expected)
        self.assertEqual(doc['specs']['1482']['presenceFields'],
                         [dict(row, type='presence') for row in expected])

    def test_invalid_entry_keeps_pixel_index_and_duplicate_last_value(self):
        raw = json.loads((ROOT/'assets/contract.json').read_bytes())
        self.assertEqual(len(raw['commonFields']), 29)
        raw['specs']['1482']['fields'] = [None,
            {'id':'duplicate','label':'','type':''},
            {'id':'duplicate','type':'number','note':'第二项'}]
        raw['specs']['1482']['presenceFields'] = [
            {'id':'aura','type':'number','label':''}]
        doc = self.load(raw)
        # 显式写33个槽；不依据被测解析器决定绘制顺序。
        colors = [0]*29 + [42, 17, 93, 0x00ff00]
        colors[6] = 1482
        colors[18] = raw['constants']['expectedVersion']
        pixels = [[color]*4 for color in colors for _ in range(4)]
        frame = OldDecoder(doc).decode(RGBImage(pixels), BarGeometry(0,0,4,4,1,4,128))
        self.assertTrue(frame.ok, frame.status)
        self.assertEqual(len(frame.rows), 33)
        self.assertEqual([(r.index,r.key,r.label,r.type,r.decoded.value_text,r.is_common)
                          for r in frame.rows[29:]], [
            (29,'','','number','42',False),
            (30,'duplicate','duplicate','number','17',False),
            (31,'duplicate','duplicate','number','93',False),
            (32,'aura','aura','presence','ON',False)])
        self.assertEqual(frame.values['duplicate'], '93')
        self.assertEqual(frame.rows[31].note, '第二项')
        self.assertTrue(all(row.is_common for row in frame.rows[:29]))

    def test_custom_field_type_falls_back_to_hex_without_dropping_following_fields(self):
        raw = json.loads((ROOT/'assets/contract.json').read_bytes())
        raw['specs']['1482']['fields'] = [
            {'id': 'custom', 'type': 'FutureType'},
            {'id': 'rage', 'type': 'resource'},
            {'id': 'following', 'type': 'switch'},
        ]
        raw['specs']['1482']['presenceFields'] = []
        colors = [0] * 29 + [0x000A0F, 101, 0x00FF00]
        colors[6], colors[18] = 1482, raw['constants']['expectedVersion']
        pixels = [[color] * 4 for color in colors for _ in range(4)]
        frame = OldDecoder(self.load(raw)).decode(RGBImage(pixels), BarGeometry(0, 0, 4, 4, 1, 4, 128))
        self.assertTrue(frame.ok)
        self.assertEqual([(row.type, row.decoded.value_text, row.decoded.detail) for row in frame.rows[-3:]], [
            ('FutureType', '#000A0F', ''), ('resource', 'UNKNOWN', '怒气未读到'), ('switch', 'ON', '开启'),
        ])


if __name__ == '__main__': unittest.main()
