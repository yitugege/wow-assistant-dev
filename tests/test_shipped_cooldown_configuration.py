"""核对交付职业的实际冷却配置，区分支持能力与已启用功能。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime,lua_type
from tests import test_addon_full_load as full_load
ROOT=full_load.ROOT
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.packages import read_addon


def plain(value):
    return {k:plain(v) for k,v in value.items()} if lua_type(value)=='table' else value


class ShippedCooldownTests(unittest.TestCase):
    def test_all_nine_original_class_registrations_have_no_persistent_spell_tables(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.exists():self.skipTest('需要原addon.bin')
        data=path.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        original={m.name:m.data for m in read_addon(data)}
        histories=[]
        for original_mode in (True,False):
            lua=LuaRuntime(unpack_returned_tuples=True,register_eval=False,register_builtins=False)
            for host in ('pixelbar_host.lua','addon_load_host.lua'):
                lua.execute((ROOT/'tests'/host).read_text('utf8'))
            lua.execute('''WowBuddyDev={classes={}};P07483180=WowBuddyDev
              function WowBuddyDev.RegisterClass(id,data) WowBuddyDev.classes[id]=data end
              function WowBuddyDev.RegisterPixelStripV2() end''')
            for path in sorted((full_load.SOURCE/'classes').glob('*/class_forever.lua')):
                name=path.relative_to(full_load.SOURCE).as_posix()
                lua.execute((original[name] if original_mode else path.read_bytes()).decode('utf-8-sig'))
            rows={}
            for spec,config in lua.globals().WowBuddyDev.classes.items():
                rows[spec]={key:plain(config[key]) for key in
                            ('cooldowns','persistentCooldowns','persistentChargeTrackers')}
                self.assertIsNone(config.persistentCooldowns)
                self.assertIsNone(config.persistentChargeTrackers)
                self.assertEqual(plain(config.cooldowns),{3044:6,5116:12,2973:6} if spec==1485 else None)
            self.assertEqual(len(rows),9)
            histories.append(rows)
        self.assertEqual(*histories)

    def test_hunter_session_cooldown_is_not_restored_into_new_runtime(self):
        def load(saved=None):
            pre="fixtureClass='HUNTER';fixtureClassID=3;fixtureSpecID=1485\n"
            pre+='\n'.join((ROOT/'tests'/n).read_text('utf8') for n in
                           ('addon_login_host.lua','addon_world_host.lua'))
            pre+='\nfunction UnitGUID() return "fixture-player" end'
            pre+='\nfunction GetServerTime() return '+str(1002 if saved is not None else 1000)+' end'
            lua,_=full_load.AddonFullLoadTests().load(full_load.SOURCE,'WowBuddyDev',pre)
            g=lua.globals()
            g.now=1 if saved is not None else 100
            if saved is not None:
                # 同一保存变量表内容，跨真正独立Lua运行时重建，不仅清空局部缓存。
                restored=lua.table_from(saved,recursive=True)
                g.WowBuddyDevDB=restored;g.WowBuddyDev.DB=restored
            g.EmitFixtureEvent('ADDON_LOADED','WowBuddyDev')
            g.EmitFixtureEvent('PLAYER_LOGIN')
            g.EmitFixtureEvent('PLAYER_ENTERING_WORLD',True,False)
            # 不执行15秒延时队列：重载只过了2秒，不能让6秒冷却自然过期掩盖差异。
            return lua
        lua=load();g=lua.globals();g.now=100
        g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED','player','Cast-shot',3044)
        self.assertEqual(g.WowBuddyDev.GetSpellCooldownRemaining(3044),6)
        g.now=102.25
        self.assertEqual(g.WowBuddyDev.GetSpellCooldownRemaining(3044),3.75)
        saved=plain(g.WowBuddyDevDB)
        self.assertEqual(saved.get('persistentCooldownLedger',{}),{})
        reloaded=load(saved).globals()
        self.assertEqual(reloaded.WowBuddyDev.GetSpellCooldownRemaining(3044),0)
        self.assertEqual(plain(reloaded.WowBuddyDev.persistentCooldowns),{})


if __name__=='__main__':unittest.main()
