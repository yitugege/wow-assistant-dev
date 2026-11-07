"""原/独立Core蓄力事件生命周期；显式API替身，不执行游戏操作。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.packages import read_addon


class OriginalEmpowerEventsTests(unittest.TestCase):
    def test_outcome_identity_expiry_and_stage_fallbacks(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.exists():self.skipTest('需要原addon.bin')
        payload=path.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),'361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        sources=[next(m.data.decode('utf-8-sig') for m in read_addon(payload) if m.name=='Core.lua'),
                 (ROOT/'addon/WowBuddyDev/Core.lua').read_text('utf8')]
        def create(source,index):
            lua=LuaRuntime(unpack_returned_tuples=True)
            lua.execute('''WowBuddyDev={};P07483180=WowBuddyDev;now=10;secret={}
            function GetTime() return now end
            function issecretvalue(v) return v==secret end
            function CreateFrame() return {SetScript=function(self,k,fn) self[k]=fn end,
              RegisterUnitEvent=function() end} end
            C_Spell={IsCurrentSpell=function(id) if broken then error('query') end return id==current end}
            function UnitChannelInfo() return 'channel',nil,nil,nil,nil,nil,nil,current,empowered,stages end
            function UnitEmpoweredStageDurations()
              if durationError then error('durations') end
              local result={}
              for i=1,(provided or 3) do local n=i
                result[i]={HasSecretValues=function() return secretStage==n end,
                  HasExpired=function() return n<=(completed or 0) end}
              end
              return result
            end''')
            namespace='P07483180' if index==0 else 'WowBuddyDev'
            start=source.index('local empowerGenerationCounter = 0')
            end=source.index('function '+namespace+'.GetTrinketCooldownRemaining()',start)
            lua.execute(source[start:end]+'''
            function fire(event,guid,spell,a,b,c)
              empowerEventFrame.OnEvent(empowerEventFrame,event,'player',guid,spell,a,b,c)
            end
            function state() return WowBuddyDev.GetPlayerEmpowerState({357208}) end
            ''')
            return lua
        cases=[('UNIT_SPELLCAST_EMPOWER_STOP',True,100),('UNIT_SPELLCAST_EMPOWER_STOP',False,200),
               ('UNIT_SPELLCAST_FAILED',False,200),('UNIT_SPELLCAST_FAILED_QUIET',False,200),
               ('UNIT_SPELLCAST_INTERRUPTED',False,200)]
        for event,succeeded,base in cases:
            runtimes=[create(s,i) for i,s in enumerate(sources)]
            for lua in runtimes:
                g=lua.globals();g.state() # 缓存本专精蓄力列表。
                g.fire('UNIT_SPELLCAST_EMPOWER_START','a',357208,5,None,None)
                g.fire('UNIT_SPELLCAST_EMPOWER_START','a',357208,5,None,None)
                g.fire(event,'unrelated',357208,None,None,None)
                self.assertEqual(g.state(),(0,0,0))
                args=(succeeded,None,5) if event.endswith('STOP') else ((None,5,None) if event.endswith('INTERRUPTED') else (5,None,None))
                g.fire(event,'a',357208,*args)
                self.assertEqual(g.state(),(357208,base+1,0))
                g.now=10.35
                self.assertEqual(g.state(),(357208,base+1,0))
                g.now=10.350001
                self.assertEqual(g.state(),(0,0,0))
                # 相同施法条ID仍能匹配不同GUID；技能不匹配的停止事件不清理当前蓄力。
                g.fire('UNIT_SPELLCAST_EMPOWER_START','b',357208,6,None,None)
                g.fire('UNIT_SPELLCAST_FAILED','b',999,6,None,None)
                self.assertEqual(g.state(),(0,0,0))
                g.fire('UNIT_SPELLCAST_FAILED','different',357208,6,None,None)
                self.assertEqual(g.state(),(357208,202,0))
        runtimes=[create(s,i) for i,s in enumerate(sources)]
        scenarios=[('current=357208;empowered=true;stages=3;completed=2',(357208,2,3)),
                   ('secretStage=1',(357208,0,3)),('secretStage=nil;durationError=true',(357208,0,3)),
                   ('durationError=false;provided=2',(357208,0,3)),
                   ('provided=3;stages=secret',(357208,0,0)),('stages=3;broken=true',(1,0,0))]
        for script,expected in scenarios:
            results=[]
            for lua in runtimes:
                lua.execute(script);results.append(lua.globals().state())
            self.assertEqual(*results);self.assertEqual(results[0],expected)


if __name__=='__main__':unittest.main()
