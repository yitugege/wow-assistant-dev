"""原Core命令及爆发自动关闭计时器对照；不加载游戏或修改用户存档。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.packages import read_addon


class SwitchCommandTests(unittest.TestCase):
    def test_commands_migration_and_cancelled_timer_generation(self):
        path = Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.is_file():self.skipTest('需要原内置插件包')
        payload = path.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        original = next(m.data.decode('utf-8-sig') for m in read_addon(payload) if m.name=='Core.lua')
        rebuilt = (ROOT/'addon/WowBuddyDev/Core.lua').read_text('utf8')
        def create(source):
            lua=LuaRuntime(unpack_returned_tuples=True)
            lua.execute('''WowBuddyDev={DB={burstAutoCloseSecondsBySpec={},masterSwitch=false,aoeMode=0}}
            P07483180=WowBuddyDev;SlashCmdList={};timers={};calls={};spec=1482;now=100
            function GetTime() return now end
            function WowBuddyDev.GetPlayerClassSpec() return nil,nil,spec,'fixture' end
            function WowBuddyDev.ToggleDock() calls[#calls+1]='dock' end
            function WowBuddyDev.UpdateMasterSwitchUI(value) calls[#calls+1]='master:'..tostring(value) end
            function WowBuddyDev.UpdateBurstSwitchUI(value) calls[#calls+1]='burst:'..tostring(value) end
            function WowBuddyDev.UpdateAoeModeUI(value) calls[#calls+1]='aoe:'..tostring(value) end
            C_Timer={NewTimer=function(seconds,callback)
              local timer={seconds=seconds,callback=callback,cancelled=false}
              function timer:Cancel() self.cancelled=true end
              timers[#timers+1]=timer;return timer
            end}''')
            start=source.index('local function toWholeSeconds(value)')
            lua.execute(source[start:source.index('local getSpellInfo =',start)])
            start=source.index('SLASH_MAOKELI1 =')
            lua.execute(source[start:source.index('local MOVEMENT_STATE_BASE',start)])
            return lua
        old,new=create(original),create(rebuilt)
        steps=[
            "SlashCmdList.MAOKELI();SlashCmdList.MKL_ON();assert(WowBuddyDev.DB.masterSwitch)",
            "SlashCmdList.MKL_OFF();assert(not WowBuddyDev.DB.masterSwitch)",
            "SlashCmdList.MKL_DAN();assert(WowBuddyDev.DB.aoeMode==1)",
            "SlashCmdList.MKL_QUN();assert(WowBuddyDev.DB.aoeMode==2)",
            "SlashCmdList.MKL_AUTO();assert(WowBuddyDev.DB.aoeMode==0)",
            "assert(SlashCmdList.MKL_ZI==SlashCmdList.MKL_AUTO);SlashCmdList.MKL_ZI()",
            "SlashCmdList.CHARU();assert(PermesCharuExpire==100.5)",
            "WowBuddyDev.DB.burstAutoCloseSeconds='3.9';assert(WowBuddyDev.GetBurstAutoCloseSeconds()==3);assert(WowBuddyDev.DB.burstAutoCloseSeconds==nil)",
            "SlashCmdList.MKL_BFK();assert(#timers==1 and timers[1].seconds==3)",
            "SlashCmdList.MKL_BFG();assert(timers[1].cancelled and not WowBuddyDev.DB.burstSwitch)",
            "SlashCmdList.MKL_BFK();timers[1].callback();assert(WowBuddyDev.DB.burstSwitch)",
            "timers[2].callback();assert(not WowBuddyDev.DB.burstSwitch)",
            "WowBuddyDev.SaveBurstAutoCloseSeconds(-1);SlashCmdList.MKL_BFK();assert(#timers==2)",
            "WowBuddyDev.SaveBurstAutoCloseSeconds('5.8');assert(timers[3].seconds==5)",
            "spec=1484;WowBuddyDev.SaveBurstAutoCloseSeconds(2);assert(timers[3].cancelled and timers[4].seconds==2)",
            "timers[3].callback();assert(WowBuddyDev.DB.burstSwitch);timers[4].callback();assert(not WowBuddyDev.DB.burstSwitch)",
            "spec=0;local ok,n,name=WowBuddyDev.SaveBurstAutoCloseSeconds(8);assert(not ok and n==0 and name==nil)",
        ]
        for index,script in enumerate(steps):
            with self.subTest(step=index):
                snapshots=[]
                for lua in (old,new):
                    lua.execute(script)
                    g=lua.globals();db=g.WowBuddyDev.DB
                    snapshots.append((db.masterSwitch,db.burstSwitch,db.aoeMode,g.PermesCharuExpire,
                                      g.WowBuddyDev.burstAutoCloseGeneration,
                                      tuple(g.calls.values()),
                                      tuple((t.seconds,t.cancelled) for t in g.timers.values()),
                                      dict(db.burstAutoCloseSecondsBySpec.items())))
                self.assertEqual(*snapshots)


if __name__=='__main__':unittest.main()
