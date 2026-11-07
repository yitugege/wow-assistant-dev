"""原交付完整 CDM 模块的迁移/导入轨迹；游戏 API 为显式替身。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime, lua_type

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.packages import read_addon


def plain(value):
    if lua_type(value) == 'table':
        return {k: plain(v) for k, v in value.items()}
    return value


HOST = '''
fixtureAddon={DB={},L=function(s) return s end}
WowBuddyDev=fixtureAddon; P07483180=fixtureAddon
StaticPopupDialogs={}; SlashCmdList={}; Enum={CompressionMethod={Deflate=7}}
logs={}; writes={}; stages={}; timers={}; combat=false
function print(...) end
function time() return 123456 end
function InCombatLockdown() return combat end
function UnitClass() return 'Mage','MAGE',8 end
function GetSpecialization() return 1 end
UIParent={CreateFontString=function() return {SetFont=function() end,Hide=function() end} end}
C_Timer={NewTimer=function(delay,callback)
  local t={delay=delay,callback=callback,Cancel=function(self) self.cancelled=true end}
  timers[#timers+1]=t;return t end}
C_CooldownViewer={GetLayoutData=function() return 'existing' end,
  SetLayoutData=function(data) writes[#writes+1]=data
    if writeFails then error('fixture write failure',0) end end}
C_EncodingUtil={}
for _,name in ipairs({'DecodeBase64','DecompressString','DeserializeCBOR'}) do
  C_EncodingUtil[name]=function(value,method)
    stages[#stages+1]={name=name,value=value,method=method}
    if failStage==name then error('fixture decoding failure',0) end
    if name=='DeserializeCBOR' then return payload end
    return name..':'..value
  end
end
'''


class CDMImportParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.exists(): raise unittest.SkipTest('需要原交付 addon.bin')
        data=path.read_bytes()
        assert hashlib.sha256(data).hexdigest()=='361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed'
        cls.original={m.name:m.data for m in read_addon(data)}['CDMImport.lua'].decode('utf-8-sig')

    def run_pair(self, command, seed=''):
        rows=[]
        for source in (self.original,(ROOT/'addon/WowBuddyDev/CDMImport.lua').read_text('utf-8-sig')):
            lua=LuaRuntime(unpack_returned_tuples=True,register_eval=False,register_builtins=False)
            lua.execute(HOST+seed)
            lua.execute(source)
            rows.append(plain(lua.execute(command)))
        self.assertEqual(rows[0],rows[1])
        return rows[1]

    def test_flat_saved_variables_migration_and_cached_identity(self):
        row=self.run_pair('''local db=fixtureAddon.CDMManager.GetDB()
          fixtureAddon.DB.cdmStateSaverDB={sentinel=true}
          return {db=db,same=fixtureAddon.CDMManager.GetDB()==db}''', '''
          fixtureAddon.DB.cdmStateSaverDB={dataConfig='old',positions={x=3},
            dataSavedAt=99,fontVersion=2,fontSize=22,fontFlags='OUTLINE',
            cooldownFontSize={EssentialCooldownViewer=33},autoRestore=true}''')
        self.assertTrue(row['same'])
        db=row['db'];self.assertEqual(db['profiles']['default']['dataConfig'],'old')
        self.assertEqual(db['profiles']['default']['savedAt'],99)
        self.assertEqual(db['fontVersion'],3)
        self.assertEqual(db['cooldownFontSize'],{})
        self.assertNotIn('dataConfig',db);self.assertNotIn('fontSize',db)
        self.assertTrue(db['autoRestore'])

    def test_data_import_decode_failures_do_not_store(self):
        for stage in ('DecodeBase64','DecompressString','DeserializeCBOR'):
            with self.subTest(stage=stage):
                row=self.run_pair('''local ok=fixtureAddon.CDMImportDataConfig('CDMSSdata|abc')
                  return {ok=ok,db=fixtureAddon.DB,writes=writes,stages=stages}''',
                  f"failStage='{stage}';payload={{d='new'}}")
                self.assertFalse(row['ok']);self.assertEqual(row['writes'],{})
                self.assertEqual(row['db'],{})
                self.assertEqual(len(row['stages']),('DecodeBase64','DecompressString','DeserializeCBOR').index(stage)+1)

    def test_data_import_preserves_original_false_success_and_cache(self):
        for setup,expected_writes in (('',{1:'new'}),('combat=true',{}),
                                      ('C_CooldownViewer=nil',{}),('writeFails=true',{1:'new'})):
            with self.subTest(setup=setup):
                row=self.run_pair('''local ok=fixtureAddon.CDMImportDataConfig('CDMSSdata|abc')
                  return {ok=ok,db=fixtureAddon.CDMManager.GetDB(),writes=writes}''',
                  "payload={d='new',c='MAGE',s=1};"+setup)
                self.assertTrue(row['ok'])
                self.assertEqual(row['writes'],expected_writes)
                self.assertEqual(row['db']['specDataConfigs']['MAGE-1'],
                                 {'dataConfig':'new','importedAt':123456})

    def test_profile_import_in_combat_saves_without_applying(self):
        row=self.run_pair('''local ok=fixtureAddon.CDMImportProfile('trial','CDMSSv2|abc')
          return {ok=ok,db=fixtureAddon.CDMManager.GetDB(),writes=writes}''',
          "combat=true;payload={v=2,d='new',cds={EssentialCooldownViewer=19}}")
        self.assertTrue(row['ok']);self.assertEqual(row['writes'],{})
        self.assertEqual(row['db']['activeProfile'],'trial')
        self.assertEqual(row['db']['profiles']['trial']['dataConfig'],'new')
        self.assertEqual(row['db']['cooldownFontSize'],{})

    def test_valid_profile_applies_fonts_and_preserves_other_profiles(self):
        row=self.run_pair('''local ok=fixtureAddon.CDMImportProfile('trial','CDMSSv2|abc')
          return {ok=ok,db=fixtureAddon.CDMManager.GetDB(),writes=writes,
            retryDelay=timers[1] and timers[1].delay}''', '''
          fixtureAddon.DB.cdmStateSaverDB={fontVersion=3,profiles={keep={dataConfig='keep'}},
            cooldownFontSize={EssentialCooldownViewer=12},autoRestore=true}
          payload={v=2,d='new',cds={EssentialCooldownViewer=19},ss={BuffIconCooldownViewer=15},
            fp='Fonts/test.ttf',ff='OUTLINE',fz=20,c='MAGE',s=1}''')
        self.assertTrue(row['ok']);self.assertEqual(row['writes'],{1:'new'})
        db=row['db'];self.assertEqual(db['activeProfile'],'trial')
        self.assertEqual(db['profiles']['keep'],{'dataConfig':'keep'})
        self.assertEqual(db['cooldownFontSize'],{'EssentialCooldownViewer':19})
        self.assertEqual(db['stackFontSize'],{'BuffIconCooldownViewer':15})
        self.assertEqual((db['fontPath'],db['fontFlags'],db['fontSize']),('Fonts/test.ttf','OUTLINE',20))
        self.assertEqual(row['retryDelay'],1.5)

    def test_popup_combat_guard_prevents_import_and_reload(self):
        row=self.run_pair('''local popup={EditBox={GetText=function() return 'CDMSSv2|abc' end}}
          StaticPopupDialogs.CDMSS_IMPORT.OnAccept(popup)
          return {db=fixtureAddon.DB,writes=writes,stages=stages,reloads=reloads}''',
          "combat=true;reloads=0;function ReloadUI() reloads=reloads+1 end;payload={v=2,d='new'}")
        self.assertEqual(row,{'db':{},'writes':{},'stages':{},'reloads':0})

    def test_missing_edit_mode_global_fails_after_storing_and_layout_write(self):
        row=self.run_pair('''local ok,err=pcall(fixtureAddon.CDMImportProfile,'trial','CDMSSv2|abc')
          return {ok=ok,missing=type(err)=='string' and not not err:find('ApplyEditModeSettings',1,true),
            db=fixtureAddon.CDMManager.GetDB(),writes=writes}''',
          "payload={v=2,d='new',e={fixture=true}}")
        self.assertFalse(row['ok']);self.assertTrue(row['missing'])
        self.assertEqual(row['writes'],{1:'new'})
        self.assertEqual(row['db']['profiles']['trial']['editModeSettings'],{'fixture':True})


if __name__=='__main__': unittest.main()
