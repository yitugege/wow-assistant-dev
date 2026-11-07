"""执行PixelBar真实取包/数字上色片段；不模拟完整OnUpdate或游戏渲染。"""
import json
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.auto_target import PACKET_BASE,parse_auto_target


class AutoTargetPixelTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        source=(ROOT/'addon/WowBuddyDev/PixelBar.lua').read_text('utf8')
        def section(start,end):
            offset=source.index(start)
            return source[offset:source.index(end,offset)]
        functions=section('local function setTextureColor(', '\nlocal maxRgbValue')
        packet=section('  local ttdValue = 0','\n  valuesById.ttf = 0')
        number=section('          local numberValue = value or 0','\n        end\n      elseif field.type == "spell"')
        self.lua.execute('WowBuddyDev={}; texture={SetColorTexture=function(self,r,g,b,a) self.r=r;self.g=g;self.b=b;self.a=a end}')
        self.render=self.lua.execute(functions+'\nreturn function()\nlocal valuesById={}\n'+packet+
            '\nlocal value=valuesById.ttd\nlocal r,g,b\n'+number+
            '\nsetTextureColor(texture,r,g,b)\nreturn texture.r,texture.g,texture.b,texture.a end')
        self.lua.execute('function setPacket(n) WowBuddyDev.GetAutoTargetPacket=function() return n end end')

    def packed_color(self):
        r,g,b,a=self.render()
        self.assertEqual(a,1)
        return (round(r*255)<<16)|(round(g*255)<<8)|round(b*255)

    def test_all_valid_packet_bits_survive_real_lua_numeric_texture_path(self):
        set_packet=self.lua.globals().setPacket
        count=0
        for key in range(1,82):
            for state in range(5):
                for ack in range(32):
                    for sequence in range(1,32):
                        expected=PACKET_BASE+key*8192+state*1024+ack*32+sequence
                        set_packet(expected)
                        actual=self.packed_color()
                        self.assertEqual(actual,expected)
                        decoded=parse_auto_target(actual)
                        self.assertIsNotNone(decoded)
                        self.assertEqual((decoded.key_index,decoded.state,decoded.ack,decoded.sequence),
                                         (key,state,ack,sequence))
                        count+=1
        self.assertEqual(count,401760)

    def test_missing_throwing_and_wrong_type_provider_render_zero(self):
        for provider in ('nil','function() error("fixture") end','function() return "123" end',
                         'function() return false end','function() return {} end'):
            with self.subTest(provider=provider):
                self.lua.execute('WowBuddyDev.GetAutoTargetPacket='+provider)
                self.assertEqual(self.packed_color(),0)
                self.assertIsNone(parse_auto_target(self.packed_color()))

    def test_common_field_position_and_numeric_type_match_contract(self):
        source=(ROOT/'addon/WowBuddyDev/Core.lua').read_text('utf8')
        start=source.index('WowBuddyDev.COMMON_PIXEL_DATA = {')
        end=source.index('\n}',start)+2
        self.lua.execute(source[start:end])
        fields=self.lua.globals().WowBuddyDev.COMMON_PIXEL_DATA
        rows=[(i-1,fields[i]['type']) for i in range(1,len(fields)+1) if fields[i]['id']=='ttd']
        contract=json.loads((ROOT/'assets/contract.json').read_text('utf8'))
        expected=[(i,row['type']) for i,row in enumerate(contract['commonFields']) if row['id']=='ttd']
        self.assertEqual(rows,expected)
        self.assertEqual(rows,[(19,'number')])


if __name__=='__main__':unittest.main()
