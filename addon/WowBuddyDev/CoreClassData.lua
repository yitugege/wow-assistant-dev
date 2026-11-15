-- ==========================================================================
-- 文件：CoreClassData.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 881-948 行），语句与顺序未改；
--       原文件级 local 状态改为状态表 coreState 的字段（coreState.X），带 @@状态表@@ 的行原为 local 声明。
-- 作用：按当前专精装载职业模块数据并重置职业相关状态。
-- 加载：TOC 中位于 CoreSettings.lua 之后、Core.lua 之前；只依赖 CoreState 与更早的拆分文件，
--       Core.lua 中赋值的 applyTalentCooldownGates 经状态表在运行期取得。
--       reloadClassData 原在 Core.lua 第 93 行前置声明，随本段移入。
-- ==========================================================================
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreClassData", { "CoreCooldownLedger", "Core", "PixelBar" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local coreState = WowBuddyDev.Require("CoreState") -- @@拆分新增@@
local rebuildConsumableIndex = WowBuddyDev.Require("CoreConsumables").rebuildConsumableIndex -- @@拆分新增@@
local reloadClassData -- @@拆分新增@@
-- ---- 以下为原 Core.lua 内容 ----
-- 功能：按当前专精重新装载职业模块数据，把所有职业相关的表重新指向新模块；没有对应职业模块时全部清空。
-- 入参：无。
-- 出参：当前专精 ID（即使没有职业模块也会返回它）。
-- 说明：这是「切专精」的总入口，一次把技能表、像素字段、动作标签、动作到按键的映射、冷却表、持久化冷却、充能追踪、额外取值规则、消耗品都换掉，并清掉本地缓存表。注意清空分支必须把所有表都重置：漏一个就会把上一个专精的冷却残留到新专精上，表现为刚切专精就有技能显示在冷却中。
reloadClassData = function()
  WowBuddyDev.classData = nil
  local specIndex = GetSpecialization and GetSpecialization() or 0
  local specID = nil
  if specIndex and (specIndex > 0 and GetSpecializationInfo) then
    specID = select(1, GetSpecializationInfo(specIndex))
  end
  if specID and WowBuddyDev.classes[specID] then
    WowBuddyDev.classData = WowBuddyDev.classes[specID]
    WowBuddyDev.testSpells = WowBuddyDev.classData.testSpells or {}
    WowBuddyDev.pixelData = WowBuddyDev.classData.pixelData or {}
    WowBuddyDev.ACTION_LABELS = WowBuddyDev.classData.ACTION_LABELS or {}
    WowBuddyDev.ACTION_TO_KEY = WowBuddyDev.classData.ACTION_TO_KEY or {}
    WowBuddyDev.testData = WowBuddyDev.classData.testData or {}
    WowBuddyDev.cooldowns = WowBuddyDev.classData.cooldowns or {}
    WowBuddyDev.persistentCooldowns = WowBuddyDev.classData.persistentCooldowns or {}
    WowBuddyDev.persistentChargeTrackers = WowBuddyDev.classData.persistentChargeTrackers or {}
    coreState.cooldownEndBySpell = {}
    if coreState.applyTalentCooldownGates and WowBuddyDev.classData.talentCooldownGates then
      coreState.applyTalentCooldownGates(WowBuddyDev.classData.talentCooldownGates)
    end
    WowBuddyDev.actionAvailSpellIDs = WowBuddyDev.classData.actionAvailSpellIDs or {}
    coreState.forceAvailableRules = WowBuddyDev.classData.forceAvailableRules or {}
    WowBuddyDev.trinketItemID = WowBuddyDev.classData.trinketItemID
    WowBuddyDev.extraValueRules = WowBuddyDev.classData.extraValues or {}
    WowBuddyDev.consumableItems = WowBuddyDev.classData.consumableItems or {}
    coreState.consumableCooldownStart = {}
    coreState.consumableStateKnown = false
    coreState.trinketCooldownStart = nil
    coreState.lastTrinketCooldownDuration = nil
    WowBuddyDev.forceAvailableState = {}
    rebuildConsumableIndex()
    WowBuddyDev.RestorePersistentCooldowns()
    WowBuddyDev.RestorePersistentConsumableCooldowns()
    if WowBuddyDev.RefreshStateLogo then
      WowBuddyDev.RefreshStateLogo()
    end
    WowBuddyDev.isClassActive = true
    return specID
  end
  WowBuddyDev.isClassActive = false
  WowBuddyDev.testSpells = {}
  WowBuddyDev.pixelData = {}
  WowBuddyDev.ACTION_LABELS = {}
  WowBuddyDev.ACTION_TO_KEY = {}
  WowBuddyDev.testData = {}
  WowBuddyDev.cooldowns = {}
  WowBuddyDev.persistentCooldowns = {}
  WowBuddyDev.persistentChargeTrackers = {}
  coreState.cooldownEndBySpell = {}
  WowBuddyDev.actionAvailSpellIDs = {}
  coreState.forceAvailableRules = {}
  WowBuddyDev.forceAvailableState = {}
  WowBuddyDev.trinketItemID = nil
  WowBuddyDev.extraValueRules = {}
  WowBuddyDev.consumableItems = {}
  coreState.consumableCooldownStart = {}
  coreState.consumableStateKnown = false
  coreState.trinketCooldownStart = nil
  coreState.lastTrinketCooldownDuration = nil
  coreState.consumableByItemSpell = {}
  coreState.pendingItemDataIDs = {}
  return specID
end
WowBuddyDev.ModuleExports("CoreClassData").reloadClassData = reloadClassData -- @@拆分新增@@
WowBuddyDev.RegisterModule("CoreClassData", { "CoreState", "CoreConsumables" })
