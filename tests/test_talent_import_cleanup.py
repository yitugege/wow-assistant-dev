"""执行SettingsUI实际导入函数片段；天赋API只记录，不修改游戏配置。"""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]


class TalentImportCleanupTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        calls={};combat=false;editable=true;loaded=true;loadOK=true;headerOK=true;ids={1,2,3,4,5,6}
        function record(value) calls[#calls+1]=value end
        function print() end
        WowBuddyDev={L=function(s) return s end,GetPlayerClassSpec=function() return 1,1,1482 end}
        function InCombatLockdown() return combat end
        C_AddOns={IsAddOnLoaded=function() return loaded end,LoadAddOn=function() return loadOK end}
        C_ClassTalents={
          CanEditTalents=function() return editable end,
          GetConfigIDsBySpecID=function(spec) record('list:'..spec);return ids end,
          DeleteConfig=function(id) record('delete:'..id);if id==4 then error('delete failed') end end,
          GetActiveConfigID=function() return 99 end,
          GetTraitTreeForSpec=function() return 1 end,
          ImportLoadout=function(id,entries,name,text) record('import:'..name);return true end}
        C_Traits={GetConfigInfo=function(id)
            record('info:'..id)
            if id==5 then error('gone') end
            return {name=({[1]='WowBuddyDev_old',[2]='MKL导入_旧',[3]='玩家_WowBuddyDev_自建',
                          [4]='WowBuddyDev_other',[6]='P07483180_旧'})[id]}
          end,GetLoadoutSerializationVersion=function() return 1 end}
        ExportUtil={MakeImportDataStream=function(text) record('parse');return {} end}
        ClassTalentImportExportMixin={ReadLoadoutHeader=function() return headerOK,1,1482,{0} end,
          ReadLoadoutContent=function() return {} end,ConvertToImportLoadoutEntryInfo=function() return {} end}
        ''')
        source=(ROOT/'addon/WowBuddyDev/SettingsUI.lua').read_text('utf8')
        start=source.index('local pendingLoadout = nil')
        end=source.index('WowBuddyDev.talentPickerFrame = CreateFrame',start)
        self.run_import,self.pending=self.lua.execute(source[start:end]+
            '\nreturn importTalentLoadout,function() return pendingLoadout end')

    def calls(self):return list(self.lua.globals().calls.values())

    def test_own_imports_cleaned_before_parse_and_failure_does_not_abort(self):
        self.assertTrue(self.run_import('data','测试'))
        self.assertEqual(self.calls(),['list:1482','info:1','delete:1','info:2','info:3',
            'info:4','delete:4','info:5','info:6','parse','import:WowBuddyDev_测试'])
        self.assertEqual((self.pending().configID,self.pending().name),(99,'测试'))

    def test_combat_edit_or_framework_failure_prevents_cleanup(self):
        for change in ('combat=true','editable=false','loaded=false;loadOK=false'):
            with self.subTest(change=change):
                self.setUp();self.lua.execute(change)
                self.assertFalse(self.run_import('data','测试'))
                self.assertEqual(self.calls(),[])
                self.assertIsNone(self.pending())

    def test_invalid_header_preserves_original_pre_validation_cleanup_order(self):
        self.lua.execute('headerOK=false')
        self.assertFalse(self.run_import('invalid','测试'))
        self.assertIn('delete:1',self.calls())
        self.assertEqual(self.calls()[-1],'parse')
        self.assertIsNone(self.pending())

    def test_no_configs_still_imports_and_repeated_import_uses_same_namespace(self):
        self.lua.execute('ids=nil')
        for _ in range(2):self.assertTrue(self.run_import('data','测试'))
        self.assertEqual(self.calls(),['list:1482','parse','import:WowBuddyDev_测试']*2)


if __name__=='__main__':unittest.main()
