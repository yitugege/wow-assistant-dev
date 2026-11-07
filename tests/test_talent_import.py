"""验证实际天赋导入函数的调用顺序，不调用游戏接口。"""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[1]/'addon/WowBuddyDev/SettingsUI.lua'


class TalentImportTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        valid=true; combat=false; imported=0; deleted=0
        WowBuddyDev={L=function(s) return s end,
          GetPlayerClassSpec=function() return 'MAGE','Frost',1491 end}
        function print() end
        function InCombatLockdown() return combat end
        C_ClassTalents={CanEditTalents=function() return true end,
          GetActiveConfigID=function() return 42 end,
          GetTraitTreeForSpec=function() return 7 end,
          GetConfigIDsBySpecID=function() return {42,43} end,
          DeleteConfig=function() deleted=deleted+1 end,
          ImportLoadout=function(id,entries,name,text)
            imported=imported+1; importedID=id; importedName=name; return true end}
        C_Traits={GetLoadoutSerializationVersion=function() return 1 end,
          GetConfigInfo=function() return {name='MKL用户保留'} end}
        C_AddOns={IsAddOnLoaded=function() return true end}
        ExportUtil={MakeImportDataStream=function(s) return s end}
        ClassTalentImportExportMixin={
          ReadLoadoutHeader=function() return valid,1,1491,{0,0} end,
          ReadLoadoutContent=function() return {} end,
          ConvertToImportLoadoutEntryInfo=function() return {} end}
        ''')
        source = SOURCE.read_text('utf8')
        start = source.index('local pendingLoadout = nil')
        end = source.index('WowBuddyDev.talentPickerFrame = CreateFrame',start)
        self.lua.execute(source[start:end] + '\nimportForTest=importTalentLoadout')

    def test_invalid_input_preserves_existing_configs(self):
        self.lua.execute('valid=false')
        self.assertFalse(self.lua.globals().importForTest('bad','测试'))
        self.assertEqual(self.lua.globals().deleted,0)
        self.assertEqual(self.lua.globals().imported,0)

    def test_valid_import_uses_own_name_without_cleanup(self):
        self.assertTrue(self.lua.globals().importForTest('valid','冰霜'))
        self.assertEqual(self.lua.globals().deleted,0)
        self.assertEqual(self.lua.globals().imported,1)
        self.assertEqual(self.lua.globals().importedID,42)
        self.assertEqual(self.lua.globals().importedName,'WowBuddyDev_冰霜')

    def test_combat_prevents_import(self):
        self.lua.execute('combat=true')
        self.assertFalse(self.lua.globals().importForTest('valid','冰霜'))
        self.assertEqual(self.lua.globals().imported,0)
        self.assertEqual(self.lua.globals().deleted,0)
