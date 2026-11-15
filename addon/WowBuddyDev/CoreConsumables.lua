-- ==========================================================================
-- 文件：CoreConsumables.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 707-880 行），语句与顺序未改；
--       原文件级 local 状态改为状态表 coreState 的字段（coreState.X），带 @@状态表@@ 的行原为 local 声明。
-- 作用：物品冷却读取、消耗品反查表与消耗品剩余冷却。
-- 加载：TOC 中位于 CoreSettings.lua 之后、Core.lua 之前；只依赖 CoreState 与更早的拆分文件，
--       Core.lua 中赋值的 applyTalentCooldownGates 经状态表在运行期取得。
-- ==========================================================================
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreConsumables", { "CoreState", "Core" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local coreState = WowBuddyDev.Require("CoreState") -- @@拆分新增@@
local BURST_POTION_ID = WowBuddyDev.Require("CoreCooldownLedger").BURST_POTION_ID -- @@拆分新增@@
local clearBurstPotionRuntime = WowBuddyDev.Require("CoreCooldownLedger").clearBurstPotionRuntime -- @@拆分新增@@
local restoreBurstPotionCooldown = WowBuddyDev.Require("CoreCooldownLedger").restoreBurstPotionCooldown -- @@拆分新增@@
-- ---- 以下为原 Core.lua 内容 ----
-- 功能：取物品当前的剩余冷却秒数。
-- 入参：itemID 物品 ID。
-- 出参：剩余秒数（保留小数）；不在冷却返回 0。
-- 说明：整段读取包在保护调用里，因为物品信息还没加载时这些接口会直接抛错。新版接口返回 table、旧版返回三个值，两种都要处理，可用标记在旧接口里是数字 1 也要认。
local function getItemCooldownRemaining(itemID)
  if not itemID then
    return 0
  end
  local startTime, duration, isEnabled = 0, 0, true
  pcall(function()
    if C_Item and C_Item.GetItemCooldown then
      local cooldownInfo, itemCooldownDuration, isEnabledLegacy = C_Item.GetItemCooldown(itemID)
      if type(cooldownInfo) == "table" then
        startTime = WowBuddyDev.SafeNumber(cooldownInfo.startTime)
        duration = WowBuddyDev.SafeNumber(cooldownInfo.duration)
        isEnabled = cooldownInfo.isEnabled ~= false and cooldownInfo.isEnabled ~= 0
      else
        startTime = WowBuddyDev.SafeNumber(cooldownInfo)
        duration = WowBuddyDev.SafeNumber(itemCooldownDuration)
        isEnabled = isEnabledLegacy ~= false and isEnabledLegacy ~= 0
      end
    elseif GetItemCooldown then
      startTime, duration, isEnabled = GetItemCooldown(itemID)
      isEnabled = isEnabled == 1 or isEnabled == true
    end
  end)
  if isEnabled and (duration > 0 and startTime > 0) then
    local remainingSeconds = duration - (GetTime() - startTime)
    if remainingSeconds > 0 then
      -- 【改装】原来 math.ceil(remainingSeconds)：药水/物品冷却也要能出十分位
      return remainingSeconds
    end
  end
  return 0
end
-- 功能：重建「物品/技能 → 消耗品」的反查表。
-- 入参：无。
-- 出参：无。
-- 说明：物品数据可能还没加载完（取不到对应技能），这时把物品 ID 记进待加载集合，等物品信息到达事件再补一次。整个表先清空重建，避免残留上一个专精的映射。
local function rebuildConsumableIndex()
  coreState.consumableByItemSpell = {}
  coreState.pendingItemDataIDs = {}
  for index2, consumableDef in ipairs(WowBuddyDev.consumableItems) do
    for index3, itemID in ipairs(consumableDef.itemIDs or {}) do
      local itemSpellID = nil
      pcall(function()
        if C_Item and C_Item.GetItemSpell then
          itemSpellID = select(2, C_Item.GetItemSpell(itemID))
        end
      end)
      if itemSpellID then
        coreState.consumableByItemSpell[itemSpellID] = consumableDef.id
      else
        coreState.pendingItemDataIDs[itemID] = true
        if C_Item and C_Item.RequestLoadItemDataByID then
          pcall(C_Item.RequestLoadItemDataByID, itemID)
        end
      end
    end
    if consumableDef.spellIDs then
      for index4, spellID in ipairs(consumableDef.spellIDs) do
        coreState.consumableByItemSpell[spellID] = consumableDef.id
      end
    end
  end
  if WowBuddyDev.trinketItemID then
    local trinketSpellID = nil
    pcall(function()
      if C_Item and C_Item.GetItemSpell then
        trinketSpellID = select(2, C_Item.GetItemSpell(WowBuddyDev.trinketItemID))
      end
    end)
    if trinketSpellID then
      coreState.consumableByItemSpell[trinketSpellID] = "trinketCD"
    end
  end
end
-- 功能：物品数据到达后，如果这个物品正等着加载就重建反查表。
-- 入参：itemID 物品 ID；loadOK 取物品数据的保护调用是否成功（false 表示这次没取到）。
-- 出参：无。
-- 说明：这里的重建参数为假，表示只补数据、不新建表结构——事件回调里不该重新初始化缓存。
local function onItemDataLoaded(itemID, loadOK)
  if loadOK == false or not coreState.pendingItemDataIDs[itemID] then
    return
  end
  rebuildConsumableIndex()
end
-- 功能：算某个消耗品的剩余冷却（慢速版）：会连背包里还有没有存货一起查。
-- 入参：consumable 消耗品定义（要有 id、cooldown、itemIDs）。
-- 出参：剩余秒数（可能是小数）；背包里一件都没有、或治疗石在战斗中不可用时返回哨兵 601。
-- 说明：601 是约定的「读不到/用不了」哨兵，渲染端认到这个值会画成无值色块，所以它和「还剩 601 秒」是两回事，改动前先看渲染侧。物品数量和冷却读取都套了 pcall，某个接口在新旧客户端上不存在也不会把整条链带崩。
function WowBuddyDev.GetConsumableCooldownRemaining(consumable)
  if not consumable then
    return 0
  end
  local hasItem = false
  for index5, candidateItemID in ipairs(consumable.itemIDs or {}) do
    local itemCount = 0
    pcall(function()
      if C_Item and C_Item.GetItemCount then
        itemCount = C_Item.GetItemCount(candidateItemID, false, false, true)
      elseif GetItemCount then
        itemCount = GetItemCount(candidateItemID)
      end
    end)
    if itemCount > 0 then
      hasItem = true
      break
    end
  end
  if not hasItem then
    return 601
  end
  if consumable.id == "item_healing_stone" and (coreState.healingStoneBlockedInCombat and InCombatLockdown()) then
    return 601
  end
  if consumable.id == BURST_POTION_ID and not coreState.consumableStateKnown then
    restoreBurstPotionCooldown(consumable)
  end
  local cooldownStart = coreState.consumableCooldownStart[consumable.id]
  if cooldownStart then
    local remainingSeconds = consumable.cooldown - (GetTime() - cooldownStart)
    if remainingSeconds > 0 then
      -- 【改装】原来 math.ceil(remainingSeconds)
      return remainingSeconds
    end
    coreState.consumableCooldownStart[consumable.id] = nil
    clearBurstPotionRuntime(consumable.id)
  end
  local maxRemaining = 0
  for index6, itemID in ipairs(consumable.itemIDs or {}) do
    local remainingSeconds = getItemCooldownRemaining(itemID)
    if remainingSeconds > maxRemaining then
      maxRemaining = remainingSeconds
    end
  end
  if maxRemaining > 0 then
    return maxRemaining
  end
  return 0
end
-- 功能：算消耗品剩余冷却的快速版：只查冷却，不查背包存货。
-- 入参：consumable 消耗品定义（要有 id、cooldown、itemIDs）。
-- 出参：剩余秒数（可能是小数）；没有冷却时返回 0。
-- 说明：给每帧刷新的像素条用，省掉每帧的物品数量查询；「有没有货」由慢速版按固定间隔补上，所以这个版本永远不会返回哨兵 601。
function WowBuddyDev.GetConsumableCooldownFast(consumable)
  if not consumable then
    return 0
  end
  if consumable.id == BURST_POTION_ID and not coreState.consumableStateKnown then
    restoreBurstPotionCooldown(consumable)
  end
  local cooldownStart = coreState.consumableCooldownStart[consumable.id]
  if cooldownStart then
    local remainingSeconds = consumable.cooldown - (GetTime() - cooldownStart)
    if remainingSeconds > 0 then
      -- 【改装】原来 math.ceil(remainingSeconds)
      return remainingSeconds
    end
    coreState.consumableCooldownStart[consumable.id] = nil
    clearBurstPotionRuntime(consumable.id)
  end
  local maxRemaining = 0
  for index7, itemID in ipairs(consumable.itemIDs or {}) do
    local remainingSeconds = getItemCooldownRemaining(itemID)
    if remainingSeconds > maxRemaining then
      maxRemaining = remainingSeconds
    end
  end
  if maxRemaining > 0 then
    return maxRemaining
  end
  return 0
end
WowBuddyDev.ModuleExports("CoreConsumables").onItemDataLoaded = onItemDataLoaded -- @@拆分新增@@
WowBuddyDev.ModuleExports("CoreConsumables").rebuildConsumableIndex = rebuildConsumableIndex -- @@拆分新增@@
WowBuddyDev.RegisterModule("CoreConsumables", { "CoreState", "CoreCooldownLedger" })
