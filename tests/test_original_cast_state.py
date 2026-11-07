"""直接执行原/独立Core读条状态正文，核对观测码、身份回退和代次回绕。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.packages import read_addon


class OriginalCastStateTests(unittest.TestCase):
    def test_cast_observations_and_generation_history(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.exists():self.skipTest('需要原addon.bin')
        payload=path.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),'361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        old=next(m.data.decode('utf-8-sig') for m in read_addon(payload) if m.name=='Core.lua')
        new=(ROOT/'addon/WowBuddyDev/Core.lua').read_text('utf8')
        runtimes=[]
        for source in (old,new):
            lua=LuaRuntime(unpack_returned_tuples=True)
            lua.execute('''WowBuddyDev={};P07483180=WowBuddyDev;now=10
            function GetTime() return now end
            secret={};function issecretvalue(v) return v==secret end
            function UnitCastingInfo() if broken then error('API failure') end
              if cast then return unpack(cast,1,10) end end
            function UnitChannelInfo() if channel then return unpack(channel,1,11) end end
            function reset() cast=nil;channel=nil;broken=false;now=10 end
            function regular() cast={'cast',nil,nil,9000,12000,false,7,false,116,42} end
            function channeled() channel={'channel',nil,nil,9000,12000,false,false,5143,false,nil,42} end
            ''')
            start=source.index('local castGenerationCounter = 1')
            end=source.index('local empowerGenerationCounter = 0',start)
            lua.execute(source[start:end]);runtimes.append(lua)
        cases=[('',False,(False,0,0,0)),('regular()',False,(True,20,116,1)),
               ('regular();cast[10]=nil',False,(True,20,116,1)),
               ('regular();cast[10]=secret;cast[7]=secret',False,(True,20,116,1)),
               ('regular();cast[10]=nil;cast[7]=nil;cast[4]=nil',False,(False,0,0,10)),
               ('regular();cast[5]=nil',False,(False,0,0,4)),
               ('regular();cast[5]=secret',False,(False,0,0,6)),
               ('regular();cast[5]=10000',False,(False,0,0,8)),
               ('regular();cast[9]=secret',False,(True,20,0,16)),
               ('regular();cast[9]=1',False,(True,20,0,14)),
               ('broken=true',False,(False,0,0,20)),
               ('channeled()',False,(False,0,0,0)),
               ('channeled()',True,(True,20,5143,2)),
               ('channeled();channel[5]=nil',True,(False,0,0,5)),
               ('channeled();channel[5]=secret',True,(False,0,0,7)),
               ('channeled();channel[5]=10000',True,(False,0,0,9)),
               ('channeled();channel[11]=nil;channel[4]=nil',True,(False,0,0,11)),
               ('channeled();channel[8]=secret',True,(True,20,0,17)),
               ('channeled();channel[8]=1',True,(True,20,0,15)),
               ('channeled();channel[9]=true',True,(False,0,5143,3)),
               ('channeled();channel[9]=true;channel[8]=secret',True,(False,0,0,19)),
               ('channeled();channel[9]=true;channel[8]=1',True,(False,0,0,18))]
        for script,include,expected in cases:
            with self.subTest(script=script):
                results=[]
                for lua in runtimes:
                    lua.execute('reset();'+script)
                    value=lua.globals().WowBuddyDev.GetPlayerCastState(include)
                    self.assertEqual(value,expected)
                    results.append((value,lua.globals().WowBuddyDev.playerCastGeneration))
                self.assertEqual(*results)
        generations=[]
        for identity in range(120):
            values=[]
            for lua in runtimes:
                lua.globals().fixtureIdentity=identity
                lua.execute('reset();regular();cast[10]=fixtureIdentity')
                value=lua.globals().WowBuddyDev.GetPlayerCastState(False)
                generation=lua.globals().WowBuddyDev.playerCastGeneration
                self.assertEqual(value,(True,20,116,1))
                # 同一读条再观察不会递增代次。
                lua.globals().WowBuddyDev.GetPlayerCastState(False)
                self.assertEqual(lua.globals().WowBuddyDev.playerCastGeneration,generation)
                values.append(generation)
            self.assertEqual(*values);generations.append(values[0])
        self.assertEqual(set(generations),set(range(1,100)))
        for before,after in zip(generations,generations[1:]):self.assertEqual(after,before%99+1)
        for now,expected in [(9,(True,False,True)),(10.499,(True,False,True)),
                             (10.5,(True,True,True)),(11.999,(True,True,True)),(12,(True,False,True))]:
            for lua in runtimes:
                lua.execute('reset();channeled()');lua.globals().now=now
                self.assertEqual(lua.globals().WowBuddyDev.GetPlayerChannelWindowState(5143,50,100),expected)
        for generation,spell,expected in [('nil','nil',(0,0)),('1','116',(1,116)),
                                          ('99','16777214',(99,16777214)),('100','16777215',(0,0)),
                                          ('1.5','116.5',(0,0)),('0','1',(0,0)),
                                          ('"2"','"116"',(2,116))]:
            for lua in runtimes:
                lua.execute('WowBuddyDev.playerSucceededGeneration='+generation+
                            ';WowBuddyDev.playerSucceededSpellID='+spell)
                self.assertEqual(lua.globals().WowBuddyDev.GetPlayerSucceededState(),expected)


if __name__=='__main__':unittest.main()
