-- ==========================================================================
-- 文件：CoreDiagnostics.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 3731-3814 行（不含注册表）），语句与顺序未改。
-- 作用：/pmstest 诊断输出，不修改状态。
-- 加载：TOC 中位于 Core.lua 之后；只使用 WowBuddyDev 全局表。
-- ==========================================================================
-- ---- 以下为原 Core.lua 内容 ----
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreDiagnostics", { "CoreClassData", "CDMImport" }) or _G.WowBuddyDev -- @@注册表命名空间@@
SLASH_PMSTEST1 = "/pmstest"
-- 功能：/pmstest 命令：把角色与专精信息、关键 API 可用性、插件加载状态和场景状态逐条打到聊天框，用于排查问题。
-- 入参：无。
-- 出参：无。
-- 说明：纯诊断输出，不修改任何状态。CDM 数据读取整段包了 pcall，接口缺失时只打一行失败提示，不会中断后面的输出；同时也会把新旧两种 ProfileName 拼出来，方便判断存档键会不会超长。
SlashCmdList.PMSTEST = function()
  print("|cff00ff00========== WowBuddyDev 测试输出 ==========|r")
  local name, realmName = UnitName("player"), GetRealmName()
  local className2, classFile = UnitClass("player")
  local localizedClassName = LOCALIZED_CLASS_NAMES_MALE and LOCALIZED_CLASS_NAMES_MALE[classFile] or classFile or "未知"
  local specIndex = GetSpecialization and GetSpecialization() or 0
  local specName = "未知"
  if specIndex and (specIndex > 0 and GetSpecializationInfo) then
    specName = select(2, GetSpecializationInfo(specIndex)) or "未知"
  end
  print("|cffffcc00[角色信息]|r")
  print("  角色名: |cffffffff" .. tostring(name or "nil") .. "|r")
  print("  服务器: |cffffffff" .. tostring(realmName or "nil") .. "|r")
  print("  职业:   |cffffffff" .. tostring(localizedClassName) .. "|r")
  print("  专精:   |cffffffff" .. tostring(specName) .. "|r (序号: " .. tostring(specIndex) .. ")")
  local specNameKey = specName:gsub("%s+", "_")
  local realmKey = realmName and realmName:gsub("%s+", "_") or "未知"
  local characterName = name or "未知"
  local legacyProfileName = "auto-" .. (classFile or "UNKNOWN") .. "-" .. specNameKey
  local profileName = legacyProfileName .. "-" .. characterName .. "-" .. realmKey
  print("|cffffcc00[ProfileName 生成]|r")
  print("  旧格式: |cffffffff" .. legacyProfileName .. "|r")
  print("  新格式: |cffffffff" .. profileName .. "|r")
  print("  长度:   旧=" .. tostring(#legacyProfileName) .. " 新=" .. tostring(#profileName))
  print("|cffffcc00[API 可用性]|r")
  local encodingUtil = C_EncodingUtil
  if encodingUtil and (encodingUtil.SerializeCBOR and (encodingUtil.CompressString and (encodingUtil.EncodeBase64 and (encodingUtil.DecodeBase64 and (encodingUtil.DecompressString and encodingUtil.DeserializeCBOR))))) then
    print("  C_EncodingUtil:   |cff00ff00可用|r")
  else
    print("  C_EncodingUtil:   |cffff0000不可用|r")
  end
  local cooldownViewer = C_CooldownViewer
  if cooldownViewer and (cooldownViewer.GetLayoutData and cooldownViewer.SetLayoutData) then
    print("  C_CooldownViewer: |cff00ff00可用|r")
  else
    print("  C_CooldownViewer: |cffff0000不可用|r")
  end
  if C_EditMode and (C_EditMode.GetLayouts and C_EditMode.SaveLayouts) then
    print("  C_EditMode:       |cff00ff00可用|r")
  else
    print("  C_EditMode:       |cffff0000不可用|r")
  end
  print("|cffffcc00[WowBuddyDev 状态]|r")
  if WowBuddyDev then
    if WowBuddyDev.classData then
      print("  职业模块:         |cff00ff00已加载|r")
    else
      print("  职业模块:         |cffff0000未加载|r")
    end
    if WowBuddyDev.CDMManager and WowBuddyDev.CDMManager.GetDB then
      local callOK, cdmDB = pcall(WowBuddyDev.CDMManager.GetDB)
      if callOK and cdmDB then
        print("  CDM 当前档案:     |cffffffff " .. tostring(cdmDB.activeProfile or "nil") .. "|r")
        local cdmProfileCount = 0
        if cdmDB.profiles then
          for k15 in pairs(cdmDB.profiles) do
            cdmProfileCount = cdmProfileCount + 1
          end
        end
        print("  CDM 档案数量:     |cffffffff" .. tostring(cdmProfileCount) .. "|r")
        if cdmProfileCount > 0 and cdmDB.profiles then
          print("  全部档案列表:")
          for k16, v34 in pairs(cdmDB.profiles) do
            print("    - |cffffffff" .. tostring(k16) .. "|r")
          end
        end
      else
        print("  CDM 数据库:       |cffff0000读取失败|r")
      end
    else
      print("  CDM 管理器:       |cffff0000未加载|r")
    end
  else
    print("  WowBuddyDev:           |cffff0000全局表不存在|r")
  end
  print("|cffffcc00[场景状态]|r")
  print("  战斗中:           " .. (InCombatLockdown() and "|cffff0000是|r" or "|cff00ff00否|r"))
  print("|cff00ff00========== 测试结束 ==========|r")
end
WowBuddyDev.RegisterModule("CoreDiagnostics", { "Core" })
