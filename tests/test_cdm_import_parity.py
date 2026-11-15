"""原交付完整 CDM 模块的迁移/导入轨迹；游戏 API 为显式替身。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime, lua_type

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.addons.packages import read_addon


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
UIParent={CreateFontString=function() return {SetFont=function() end,Hide=function() end} end,
  GetWidth=function() return 1000 end,GetHeight=function() return 500 end}
function string.trim(value) return value:match('^%s*(.-)%s*$') end
C_Timer={NewTimer=function(delay,callback)
  local t={delay=delay,callback=callback,Cancel=function(self) self.cancelled=true end}
  timers[#timers+1]=t;return t end}
layout='existing'
C_CooldownViewer={GetLayoutData=function() return layout end,
  SetLayoutData=function(data) writes[#writes+1]=data
    if writeFails then error('fixture write failure',0) end;layout=data end}
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

    def run_module(self, command, seed='', *, original=False):
        source = self.original if original else (ROOT/'addon/WowBuddyDev/CDMImport.lua').read_text('utf-8-sig')
        lua = LuaRuntime(unpack_returned_tuples=True, register_eval=False, register_builtins=False)
        lua.execute(HOST+seed)
        lua.execute(source)
        return plain(lua.execute(command))

    def run_pair(self, command, seed=''):
        current = self.run_module(command, seed)
        self.assertEqual(self.run_module(command, seed, original=True), current)
        return current

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

    def test_data_import_commits_cache_only_after_successful_write(self):
        for setup,expected_writes in (('',{1:'new'}),('combat=true',{}),
                                      ('C_CooldownViewer=nil',{}),('writeFails=true',{1:'new'})):
            with self.subTest(setup=setup):
                command = '''local ok=fixtureAddon.CDMImportDataConfig('CDMSSdata|abc')
                  return {ok=ok,db=fixtureAddon.CDMManager.GetDB(),writes=writes}'''
                seed = "payload={d='new',c='MAGE',s=1};"+setup
                old = self.run_module(command, seed, original=True)
                current = self.run_module(command, seed)
                self.assertTrue(old['ok'])
                self.assertEqual(old['writes'], expected_writes)
                self.assertEqual(current['writes'], expected_writes)
                self.assertEqual(old['db']['specDataConfigs']['MAGE-1'], {'dataConfig':'new','importedAt':123456})
                if setup:
                    self.assertFalse(current['ok'])
                    self.assertNotIn('specDataConfigs', current['db'])
                else:
                    self.assertEqual(old, current)

    def test_failed_profile_import_preserves_active_and_existing_profiles(self):
        command = '''local ok=fixtureAddon.CDMImportProfile('trial','CDMSSv2|abc')
          return {ok=ok,db=fixtureAddon.CDMManager.GetDB(),writes=writes}'''
        for setup, writes in (('combat=true', {}), ('writeFails=true', {1:'new'})):
            with self.subTest(setup=setup):
                seed = '''fixtureAddon.DB.cdmStateSaverDB={activeProfile='keep',fontVersion=3,
                  profiles={keep={dataConfig='keep'},trial={dataConfig='old'}}};
                  payload={v=2,d='new',cds={EssentialCooldownViewer=19}};'''+setup
                old = self.run_module(command, seed, original=True)
                current = self.run_module(command, seed)
                self.assertTrue(old['ok'])
                self.assertEqual(old['db']['activeProfile'], 'trial')
                self.assertEqual(old['db']['profiles']['trial']['dataConfig'], 'new')
                self.assertFalse(current['ok'])
                self.assertEqual(current['writes'], writes)
                self.assertEqual(current['db']['activeProfile'], 'keep')
                self.assertEqual(current['db']['profiles']['trial']['dataConfig'], 'old')
                self.assertEqual(current['db']['cooldownFontSize'], {})

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

    def test_missing_edit_mode_global_does_not_abort_loading_or_saving(self):
        command = '''local ok,result=pcall(fixtureAddon.CDMImportProfile,'trial','CDMSSv2|abc')
          local saved,saveError=pcall(SlashCmdList.CDMSS,'save trial')
          return {ok=ok,result=result,saved=saved,saveError=saveError,db=fixtureAddon.CDMManager.GetDB(),
            writes=writes,activeLayout=activeLayout,refreshes=refreshes}'''
        seed = '''payload={v=2,d='new',e={fixture=true}}; refreshes=0
          CooldownViewerSettings={RefreshLayout=function() refreshes=refreshes+1 end}
          C_EditMode={GetLayouts=function() return {activeLayout=7} end,
            SetActiveLayout=function(id) activeLayout=id end}'''
        old = self.run_module(command, seed, original=True)
        self.assertFalse(old['ok'])
        self.assertIn('ApplyEditModeSettings', old['result'])
        self.assertFalse(old['saved'])
        self.assertIn('ExtractEditModeSettings', old['saveError'])
        current = self.run_module(command, seed)
        self.assertTrue(current['ok'])
        self.assertTrue(current['result'])
        self.assertTrue(current['saved'])
        self.assertEqual(current['writes'], {1:'new'})
        self.assertEqual(current['activeLayout'], 7)
        self.assertEqual(current['refreshes'], 2)
        profile = current['db']['profiles']['trial']
        self.assertEqual(profile['editModeSettings'], {'fixture':True})
        self.assertEqual(profile['dataConfig'], 'new')

    def test_export_then_import_preserves_layout_fonts_and_saved_edit_fields(self):
        command = '''fixtureAddon.CDMManager.ExportProfile('snapshot')
          layout='another layout'
          local ok=fixtureAddon.CDMImportProfile('copy',exported)
          return {ok=ok,exported=exported,serialized=serialized,layout=layout,
            db=fixtureAddon.CDMManager.GetDB()}'''
        seed = '''fixtureAddon.DB.cdmStateSaverDB={activeProfile='snapshot',fontVersion=3,fontSize=20,
            profiles={snapshot={dataConfig='old',editModeSettings={fixture=true}}}}
          function StaticPopup_Show(which, first, second, text)
            assert(which=='CDMSS_COPY'); exported=text
          end
          function C_EncodingUtil.SerializeCBOR(data) serialized=data;return 'cbor' end
          function C_EncodingUtil.CompressString(data,method)
            assert(data=='cbor' and method==7);return 'compressed'
          end
          function C_EncodingUtil.EncodeBase64(data) assert(data=='compressed');return 'encoded' end
          function C_EncodingUtil.DeserializeCBOR(data)
            assert(data=='DecompressString:DecodeBase64:encoded');return serialized
          end'''
        row = self.run_module(command, seed)
        self.assertTrue(row['ok'])
        self.assertEqual(row['exported'], 'CDMSSv2|encoded')
        self.assertEqual(row['layout'], 'existing')
        self.assertEqual(row['db']['activeProfile'], 'copy')
        self.assertEqual(row['db']['profiles']['copy']['editModeSettings'], {'fixture':True})
        self.assertEqual(row['serialized']['fz'], 20)

    def test_failed_popup_write_does_not_reload_and_refresh_can_retry(self):
        command = '''local popup={EditBox={GetText=function() return 'CDMSSv2|abc' end}}
          StaticPopupDialogs.CDMSS_IMPORT.OnAccept(popup)
          local delay=timers[1] and timers[1].delay
          if delay then timers[1].callback() end
          return {reloads=reloads,delay=delay,refreshes=refreshes}'''
        seed = '''payload={v=2,d='new'}; reloads=0; refreshes=0
          function ReloadUI() reloads=reloads+1 end
          CooldownViewerSettings={RefreshLayout=function()
            refreshes=refreshes+1; if refreshes==1 then error('not ready') end
          end}'''
        self.assertEqual(self.run_module(command, seed+';writeFails=true'), {'reloads':0,'refreshes':0})
        self.assertEqual(self.run_module(command, seed), {'reloads':1,'delay':1.5,'refreshes':2})


if __name__=='__main__': unittest.main()
