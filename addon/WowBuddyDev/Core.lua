-- ==========================================================================
-- 文件：5c78cc.lua
-- 来源：P07483180.rar → P07483180/5c78cc.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：5c78cc.lua → Core.lua（按功能重命名）
-- 作用：核心：P07483180 表、专精注册、安全按钮、按键绑定、版本号
-- ==========================================================================
-- 【改装】版本号：
--   10576666 → 10576667：冷却从"整秒"改成"十分位"（0.1 秒）
--   10576667 → 10576668：踏风新增 3 个冷却颜色字段（怒雷破/旭日/升龙霸），竖排 41 → 44 项
--   10576674 → 10576675：治疗专精（德/骑/牧/萨）末尾新增「当前焦点」字段 focus_index
-- 读取端靠这个号判断该不该信这些字段。★ 改字段表必须同步改号，否则读取端会因
-- 版本不符直接停发；号改了就必须把插件重装一次，两端要一起换。
local addonVersionCode = 0x574201 -- 独立0.2协议：24位技能状态，需配套WowBuddyDev桌面端。
local addonName, addonTableArg = ...
_G.WowBuddyDev = _G.WowBuddyDev or {}
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("Core", { "CoreSettings", "CoreState", "CoreClassData", "RaidFocus", "PixelBar" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local coreState = WowBuddyDev.Require("CoreState") -- @@拆分新增@@
local BURST_POTION_ID = WowBuddyDev.Require("CoreCooldownLedger").BURST_POTION_ID -- @@拆分新增@@
local applyLedgerEntryToRuntime = WowBuddyDev.Require("CoreCooldownLedger").applyLedgerEntryToRuntime -- @@拆分新增@@
local clearBurstPotionRuntime = WowBuddyDev.Require("CoreCooldownLedger").clearBurstPotionRuntime -- @@拆分新增@@
local clearPersistentCooldownState = WowBuddyDev.Require("CoreCooldownLedger").clearPersistentCooldownState -- @@拆分新增@@
local recordBurstPotionUse = WowBuddyDev.Require("CoreCooldownLedger").recordBurstPotionUse -- @@拆分新增@@
local recordPersistentCooldownStart = WowBuddyDev.Require("CoreCooldownLedger").recordPersistentCooldownStart -- @@拆分新增@@
local restoreBurstPotionCooldown = WowBuddyDev.Require("CoreCooldownLedger").restoreBurstPotionCooldown -- @@拆分新增@@
WowBuddyDev.classes = WowBuddyDev.classes or {}
-- ==========================================================================
-- 【取证】Lua 错误收集器（2026-10-03 加）
-- 功能：把本插件会话内弹过窗的 Lua 错误文本留底，/mklerr 一键打印。
-- 为什么需要：用户只看到「进副本弹错误」却截不全红字，远程排障拿不到堆栈
-- 就只能盲猜。装在文件最顶部 = 任何后续代码报错前收集器已就位。
-- 注意：
--   * seterrorhandler 是受限 API —— 必须在**非战斗**状态调用（登录/重载时装，
--     正好满足；战斗中调用会静默失败，所以装失败时探测并降级为不装）。
--   * 收集后**转发**原 handler：弹窗行为不变，只多留底，不吞错。
--   * 同一文本只计一条并累加次数，避免「每帧报错」刷爆缓存。
-- ==========================================================================
do
  local capturedErrors = {}          -- { {text=, count=, firstAt=, lastAt=} }
  local CAPTURE_LIMIT = 10
  local handlerInstalled = false
  local origHandler = geterrorhandler and geterrorhandler()

  local function captureError(err)
    if err == nil then return end
    local text = tostring(err)
    for _, entry in ipairs(capturedErrors) do
      if entry.text == text then
        entry.count = entry.count + 1
        entry.lastAt = date("%H:%M:%S")
        return
      end
    end
    -- 新文本：置顶插入，超限从尾部淘汰
    table.insert(capturedErrors, 1, {
      text = text,
      count = 1,
      firstAt = date("%H:%M:%S"),
      lastAt = date("%H:%M:%S"),
    })
    if #capturedErrors > CAPTURE_LIMIT then
      table.remove(capturedErrors)
    end
  end

  if origHandler and seterrorhandler then
    local installOK = pcall(seterrorhandler, function(err)
      pcall(captureError, err)
      return origHandler(err)
    end)
    handlerInstalled = installOK
  end

  WowBuddyDev.GetCapturedLuaErrors = function() return capturedErrors end
  WowBuddyDev.LuaErrorCollectorActive = handlerInstalled

  SLASH_MKLERR1 = "/mklerr"
  SlashCmdList.MKLERR = function()
    print("|cff33ff99[WowBuddyDev]|r 错误收集器: " ..
      (handlerInstalled and "|cff00ff00已启用|r" or "|cffff0000未启用（登录时已在战斗中？/reload 后重试）|r"))
    if #capturedErrors == 0 then
      print("|cff33ff99[WowBuddyDev]|r 本会话没有捕获到任何 Lua 错误。")
      return
    end
    print("|cff33ff99[WowBuddyDev]|r 最近 Lua 错误（新→旧，最多 " .. CAPTURE_LIMIT .. " 种）：")
    for i, entry in ipairs(capturedErrors) do
      print(string.format("|cffaaaaaa%d.|r %s   |cff888888首次 %s / 最近 %s / 共 %d 次|r",
        i, entry.text, entry.firstAt, entry.lastAt, entry.count))
    end
    print("|cff33ff99[WowBuddyDev]|r 把上面的红字原文发给开发者即可定位。")
  end
end
WowBuddyDev.addonVersionCode = addonVersionCode or 0
dock = nil
WowBuddyDev.classData = nil
-- @@原行：local lastSpecID = nil@@
-- @@原行：local lastHeroSpecID = nil@@
WowBuddyDev.isClassActive = false
local unknownMarker
-- @@原行：local reloadClassData@@
-- @@原行：local refreshMacroBindings@@
-- @@原行：local applyTalentCooldownGates@@
WowBuddyDev.DB = nil
-- @@拆分：CoreSettings.lua@@
local migrateChijiMacro = WowBuddyDev.Require("CoreSettings").migrateChijiMacro -- @@拆分新增@@
local getSpellInfo = GetSpellInfo or function(spellID)
  if not spellID then
    return nil
  end
  local spellInfo = C_Spell.GetSpellInfo(spellID)
  if spellInfo then
    return spellInfo.name, nil, spellInfo.iconID, spellInfo.castTime, spellInfo.minRange, spellInfo.maxRange, spellInfo.spellID, spellInfo.originalIconID
  end
end
WowBuddyDev.ModuleExports("Core").getSpellInfo = getSpellInfo -- @@拆分新增@@
-- 功能：把任意值稳妥地转成数字，转不出来就给 0。
-- 入参：value 任意值。
-- 出参：数字；无法转换时为 0。
-- 说明：本来就是数字的值要走一遍 tostring 再 tonumber 回来，这是为了绕开 12.x 客户端里带「秘密值」标记的数字——直接拿去做运算会抛错。所有读冷却和时间的接口都过这一层。
function WowBuddyDev.SafeNumber(value)
  if type(value) == "number" then
    return tonumber(tostring(value)) or 0
  end
  return tonumber(value) or 0
end
local getSpellCooldown = C_Spell and C_Spell.GetSpellCooldown or _G.GetSpellCooldown
-- 功能：统一读技能的冷却三元组（开始时间 / 持续时长 / 是否可用）。
-- 入参：spellID 技能 ID。
-- 出参：startTime, duration, isEnabled。
-- 说明：新版接口返回 table，旧接口返回三个值，两种都要吃。技能 ID 为空时直接给 0, 0, true，当成「可用」处理，避免把空 ID 当作「冷却中」而卡住流程。
local function getSpellCooldownState(spellID)
  if not spellID then
    return 0, 0, true
  end
  local cooldownInfo, duration, isEnabled = getSpellCooldown(spellID)
  if cooldownInfo and type(cooldownInfo) == "table" then
    return WowBuddyDev.SafeNumber(cooldownInfo.startTime), WowBuddyDev.SafeNumber(cooldownInfo.duration), cooldownInfo.isEnabled ~= false
  elseif cooldownInfo then
    return WowBuddyDev.SafeNumber(cooldownInfo), WowBuddyDev.SafeNumber(duration), isEnabled
  end
  return 0, 0, true
end
-- 功能：判断技能当前能不能放，法力/能量不足直接判不可用。
-- 入参：spellID 技能 ID。
-- 出参：true/false。
-- 说明：底层接口（C_Spell.IsSpellUsable / IsUsableSpell）在法力不足时返回的
--       usable 仍是 true（缺蓝信息在第二返回值 noMana / insufficientMana 里），
--       直接透传会让引擎对着空蓝继续发键：游戏放不出 → 施法回查 miss → 连续
--       miss 被判免疫油封 → 油封过期再按再失败再油封。双目标拉锯战（双倍承伤、
--       自保治疗多读、蓝耗尽）的表现就是「一只怪死了，另一只只会平A」（2026-10-14
--       用户报）。这里把「usable=true 但缺蓝」组合归一成 false，avail 位图如实
--       变灰，引擎不发键、不进油封循环，回蓝后自动恢复。新版接口返回
--       SpellUsableInfo 表、旧版返回双值，两种形态都接；调用抛错按不可用处理。
do
  local rawIsUsable = C_Spell and C_Spell.IsSpellUsable or IsUsableSpell
  if type(rawIsUsable) == "function" then
    WowBuddyDev.IsSpellUsable = function(spellID)
      local okCall, usable, noMana = pcall(rawIsUsable, spellID)
      if not okCall then
        return false
      end
      if type(usable) == "table" then
        -- ★ 表形态但读不出 isUsable 字段（客户端返回结构与预期不同的形态类
        --   技能，如 5487 熊形态）→ 不表态，回退旧行为的「透传为真」。
        --   严格判 false 会把变身类技能恒判不可用，熊/猫整个循环卡死
        --   （2026-10-15 用户报「熊不自动变身」）。缺蓝三字段仍优先判。
        if usable.insufficientMana == true or usable.insufficientPower == true or usable.insufficientResources == true then
          return false
        end
        if usable.isUsable == nil then
          return true
        end
        return usable.isUsable == true
      end
      if noMana == true then
        return false
      end
      return usable == true or usable == 1
    end
  else
    WowBuddyDev.IsSpellUsable = rawIsUsable
  end
end
local libSharedMedia = LibStub and LibStub:GetLibrary("LibSharedMedia-3.0", true)
WowBuddyDev.LibRangeCheck = LibStub and LibStub:GetLibrary("LibRangeCheck-3.0", true)
-- 功能：从共享材质库取材质路径，取不到就用兜底常量。
-- 入参：mediaType 材质类型（字体/背景/边框）；mediaName 材质名；fallbackPath 兜底路径。
-- 出参：路径字符串。
-- 说明：库没装或库里没这个名字时直接用兜底，保证界面元素始终有材质可用。
local function fetchSharedMediaPath(mediaType, mediaName, fallbackPath)
  if libSharedMedia then
    return libSharedMedia:Fetch(mediaType, mediaName, true) or fallbackPath
  end
  return fallbackPath
end
local tooltipBackground = fetchSharedMediaPath("background", "Blizzard Tooltip", "Interface\\Tooltips\\UI-Tooltip-Background")
local tooltipBorder = fetchSharedMediaPath("border", "Blizzard Tooltip", "Interface\\Tooltips\\UI-Tooltip-Border")
WowBuddyDev.fontFile = fetchSharedMediaPath("font", "默认", "Fonts\\ARKai_T.ttf")
if not fetchSharedMediaPath("font", "默认", nil) and libSharedMedia then
  WowBuddyDev.fontFile = libSharedMedia:Fetch("font", libSharedMedia:GetDefault("font"), true) or "Fonts\\ARKai_T.ttf"
end
WowBuddyDev.testSpells = {}
-- @@拆分：CoreState.lua@@
-- @@拆分：CoreCooldownLedger.lua@@
-- 功能：判断这个事件是否意味着「游戏冷却已经被重置」，需要跟着清插件缓存。
-- 入参：eventName 事件名；... 事件参数。
-- 出参：true/false。
-- 说明：只认两种情况——挑战模式开始，以及首领战结束；后者还要用副本类型确认确实是团队副本，避免在小队副本或场景战役里误清掉了本来有效的冷却记录。
local function shouldResetCooldownsOnEvent(eventName, ...)
  if eventName == "CHALLENGE_MODE_START" then
    return true
  end
  if eventName == "ENCOUNTER_END" then
    local inInstance, instanceType = IsInInstance()
    return inInstance == true and instanceType == "raid"
  end
  return false
end
-- 功能：判断某个技能是不是当前职业的宠物技能。
-- 入参：spellID 技能 ID。
-- 出参：true/false。
-- 说明：名单来自职业模块的 classData.petSpells；职业模块没加载或名单为空时一律返回 false，不会因为数据没到位就把普通技能误判成宠物技能。
function WowBuddyDev.IsPetSpell(spellID)
  local petSpells = WowBuddyDev.classData and WowBuddyDev.classData.petSpells
  return petSpells ~= nil and petSpells[spellID] == true
end
-- 功能：把事件回调里的技能 ID 换成职业配置里登记的别名键。
-- 入参：spellID 技能 ID。
-- 出参：别名键；没登记就原样返回技能 ID。
-- 说明：让技能和「触发它的宠物技能、天赋变体」共用同一条冷却记录，别名表由各职业文件提供。
local function resolveCooldownEventAlias(spellID)
  local eventAliases = WowBuddyDev.classData and WowBuddyDev.classData.cooldownEventAliases
  return eventAliases and eventAliases[spellID] or spellID
end
WowBuddyDev.COMMON_PIXEL_DATA = {
  { id = "master_switch", label = "总开关", type = "switch" },
  { id = "burst", label = "爆发", type = "switch" },
  { id = "aoe_mode", label = "模式", type = "count" },
  { id = "distance", label = "距离", type = "distance" },
  { id = "isMoving", label = "移动", type = "switch" },
  { id = "target_health_pct", label = "目标血量", type = "number" },
  { id = "spec_id", label = "专精ID", type = "number" },
  { id = "target_casting", label = "目标施法", type = "switch" },
  { id = "focus_casting", label = "焦点施法", type = "switch" },
  { id = "player_health_pct", label = "自身血量", type = "number" },
  { id = "active_enemies", label = "怪物数量", type = "count" },
  { id = "item_red_potion", label = "红药水", type = "cooldown" },
  { id = "item_healing_stone", label = "治疗石", type = "cooldown" },
  { id = "item_burst_potion", label = "爆发药水", type = "cooldown" },
  { id = "trinket1_cd", label = "饰品1", type = "cooldown" },
  { id = "trinket2_cd", label = "饰品2", type = "cooldown" },
  { id = "enemies_8yd", label = "8码内敌人", type = "count" },
  { id = "gcd", label = "GCD", type = "validity" },
  { id = "addon_version_code", label = "插件版本", type = "count" },
  { id = "ttd", label = "TTD", type = "number" },
  { id = "ttf", label = "TTF", type = "number" },
  { id = "player_casting", label = "玩家读条", type = "switch" },
  { id = "cast_remaining", label = "读条剩余", type = "number" },
  { id = "player_succeeded_generation", label = "成功代次", type = "count" },
  { id = "player_succeeded_spell_id", label = "成功技能ID", type = "number" },
  { id = "combat_time", label = "战斗计时", type = "number" },
  { id = "action_avail", label = "动作可用", type = "count" },
  { id = "player_cast_spell_id", label = "当前读条技能ID", type = "number" },
  { id = "player_cast_observation_code", label = "读条观测状态", type = "count" },
}
-- @@拆分：CoreConsumables.lua@@
-- @@拆分：CoreClassData.lua@@
local eventFrame = CreateFrame("Frame")
eventFrame:SetScript("OnEvent", function(self, event, castSource, castGUID, castSpellID)
  local spellID = resolveCooldownEventAlias(castSpellID)
  if castSource == "pet" and (spellID and WowBuddyDev.IsPetSpell(spellID)) then
    coreState.lastCastTimeBySpell[spellID] = GetTime()
    return
  end
  if castSource == "player" and castSpellID then
    local now4 = GetTime()
    local duplicateCast = false
    if castGUID then
      duplicateCast = castGUID == coreState.lastSucceededCastGUID
    else
      duplicateCast = coreState.lastSpellID == castSpellID and now4 - coreState.lastSucceededTime < .05
    end
    if not duplicateCast then
      coreState.succeededGeneration = coreState.succeededGeneration % 99 + 1
      coreState.lastSucceededCastGUID = castGUID
      coreState.lastSpellID = castSpellID
      coreState.lastSucceededTime = now4
      WowBuddyDev.playerSucceededSpellID = castSpellID
      WowBuddyDev.playerSucceededGeneration = coreState.succeededGeneration
    end
    if duplicateCast then
      return
    end
    local healFocusSpellIDs = WowBuddyDev.classData and WowBuddyDev.classData.HEAL_FOCUS_SPELL_IDS
    if healFocusSpellIDs and (WowBuddyDev.IsRaidFocusFeedbackEnabled and WowBuddyDev.RecordRaidFocusFeedback) then
      pcall(function()
        if healFocusSpellIDs[castSpellID] and WowBuddyDev.IsRaidFocusFeedbackEnabled() then
          WowBuddyDev.RecordRaidFocusFeedback("success")
        end
      end)
    end
    coreState.lastCastTimeBySpell[spellID] = now4
    recordPersistentCooldownStart(spellID)
    coreState.lastSucceededSpellID = castSpellID
    WowBuddyDev.lastCastSpellID = castSpellID
    local consumableID = coreState.consumableByItemSpell[castSpellID]
    if consumableID then
      if consumableID == "trinketCD" then
        coreState.trinketCooldownStart = now4
      else
        coreState.consumableCooldownStart[consumableID] = now4
        for index8, consumableDef in ipairs(WowBuddyDev.consumableItems or {}) do
          if consumableDef.id == consumableID then
            recordBurstPotionUse(consumableID, consumableDef.cooldown, now4)
            break
          end
        end
        if consumableID == "item_healing_stone" and InCombatLockdown() then
          coreState.healingStoneBlockedInCombat = true
        end
      end
    end
    if WowBuddyDev.classData and WowBuddyDev.classData.forceAvailableRules then
      local availableRule = WowBuddyDev.classData.forceAvailableRules[castSpellID]
      if availableRule then
        if availableRule.setAvailable then
          WowBuddyDev.forceAvailableState[availableRule.setAvailable] = true
        end
        if availableRule.clearAvailable then
          WowBuddyDev.forceAvailableState[availableRule.clearAvailable] = false
        end
      end
    end
    if WowBuddyDev.classData and WowBuddyDev.classData.OnSpellCast then
      WowBuddyDev.classData.OnSpellCast(castSpellID, consumableID)
    end
  end
end)
eventFrame:RegisterUnitEvent("UNIT_SPELLCAST_SUCCEEDED", "player", "pet")
local healingStoneResetFrame = CreateFrame("Frame")
healingStoneResetFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
healingStoneResetFrame:SetScript("OnEvent", function(self2, event2)
  coreState.healingStoneBlockedInCombat = false
end)
local combatEndFrame = CreateFrame("Frame")
combatEndFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
combatEndFrame:SetScript("OnEvent", function()
  WowBuddyDev._lastCombatEnd = GetTime()
end)
-- 功能：算某个技能 ID 的剩余冷却秒数。
-- 入参：spellID 技能 ID。
-- 出参：剩余秒数（小数）；不在冷却、冷却已结束或读不到时返回 0。
-- 说明：分两条路——配置表里登记过的技能先查持久化账本，账本没有或已过期就退回本插件自己记的施法时间；没登记过的技能直接问游戏原生冷却接口。三条分支都返回**原始小数**（原来在每处都做 math.ceil 取整），因为像素条的十分位显示要靠小数部分。冷却归零时会顺手清掉运行时缓存和账本条目，不留残值。
function WowBuddyDev.GetSpellCooldownRemaining(spellID)
  if not spellID then
    return 0
  end
  if WowBuddyDev.cooldowns and WowBuddyDev.cooldowns[spellID] then
    if WowBuddyDev.persistentCooldowns and WowBuddyDev.persistentCooldowns[spellID] then
      if not coreState.cooldownEndBySpell[spellID] then
        applyLedgerEntryToRuntime(spellID)
      end
      local cooldownEnd = coreState.cooldownEndBySpell[spellID]
      if cooldownEnd then
        local remainingSec = cooldownEnd - GetTime()
        if remainingSec > 0 then
          -- 【改装】原来是 math.ceil(remainingSec)：把剩余时间向上取整成整秒，
          -- 于是后面的十分位编码只能拿到 90、89 这种整数值。改成返回原始小数。
          return remainingSec
        end
        coreState.lastCastTimeBySpell[spellID] = nil
        clearPersistentCooldownState(spellID)
        return 0
      end
    end
    local castStartTime = coreState.lastCastTimeBySpell[spellID] or 0
    if castStartTime == 0 then
      return 0
    end
    local remainingSec = WowBuddyDev.cooldowns[spellID] - (GetTime() - castStartTime)
    if remainingSec <= 0 then
      coreState.lastCastTimeBySpell[spellID] = nil
      clearPersistentCooldownState(spellID)
      return 0
    end
    -- 【改装】同上：原来 math.ceil(remainingSec) 会丢掉小数部分
    return remainingSec
  end
  local startTime, spellCooldownDuration, isEnabled = getSpellCooldownState(spellID)
  if not isEnabled then
    return 0
  end
  if spellCooldownDuration and (spellCooldownDuration > 0 and startTime) then
    local remainingSec = startTime + spellCooldownDuration - GetTime()
    if remainingSec > 0 then
      -- 【改装】同上：原来 math.ceil(remainingSec)
      return remainingSec
    end
  end
  return 0
end
WowBuddyDev.lastCastTime = coreState.lastCastTimeBySpell
-- 功能：按当前已经点出的天赋门控修正技能冷却基准值。
-- 入参：gates 天赋门控表（每项含基础冷却和若干减冷却项）。
-- 出参：无（就地改写技能冷却表）。
-- 说明：每个技能的基础冷却可以叠加多个天赋的「减固定秒数」和「减百分比」，这里先算完再一次性四舍五入写回。只要有一个门控天赋查不出来（抛错或返回值不是布尔），就整体放弃这次修正：半套数据算出来的冷却会明显偏长，比不修正更糟。
coreState.applyTalentCooldownGates = function(gates)
  if not (C_SpellBook and type(C_SpellBook.IsSpellKnown) == "function") then
    return
  end
  for k5, gate in pairs(gates) do
    if type(gate) == "table" and (type(gate.base) == "number" and type(gate.reductions) == "table") then
      local baseCooldown = gate.base
      local reductionFactor = 1
      local allTalentsKnown = true
      for index9, reduction in ipairs(gate.reductions) do
        local callOK, isKnown = pcall(C_SpellBook.IsSpellKnown, reduction.talentID)
        if not (callOK and type(isKnown) == "boolean") then
          allTalentsKnown = false
          break
        end
        if isKnown then
          if reduction.reduceBy then
            baseCooldown = baseCooldown - reduction.reduceBy
          end
          if reduction.reducePct then
            reductionFactor = reductionFactor * (1 - reduction.reducePct / 100)
          end
        end
      end
      if allTalentsKnown then
        WowBuddyDev.cooldowns[k5] = math.floor(baseCooldown * reductionFactor + .5)
      end
    end
  end
end
local talentGateFrame = CreateFrame("Frame")
talentGateFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
talentGateFrame:RegisterEvent("ACTIVE_TALENT_GROUP_CHANGED")
talentGateFrame:RegisterEvent("SPELLS_CHANGED")
talentGateFrame:SetScript("OnEvent", function()
  local talentCooldownGates = WowBuddyDev.classData and WowBuddyDev.classData.talentCooldownGates
  if not talentCooldownGates or not WowBuddyDev.cooldowns then
    return
  end
  C_Timer.After(.1, function()
    coreState.applyTalentCooldownGates(talentCooldownGates)
  end)
end)
SLASH_PERMESCDCHECK1 = "/pmscdcheck"
-- 功能：斜杠命令实现的冷却自检：逐个比对「插件认为的冷却」和「客户端真实冷却」。
-- 入参：无。
-- 出参：无（只往聊天框打结果）。
-- 说明：偏差超过 1 秒就标记为不一致，用来排查天赋门控和热修改导致的基准值不对；只有当前真正在冷却中的技能才能比对，所以提示里说明「就绪技能要先进一次冷却再跑」。
SlashCmdList.PERMESCDCHECK = function()
  if not WowBuddyDev.cooldowns then
    print("[CDCheck] 无 cooldowns 表")
    return
  end
  local activeCount, mismatchCount = 0, 0
  for k6, declaredCooldown in pairs(WowBuddyDev.cooldowns) do
    local callOK, cooldownInfo = pcall(C_Spell.GetSpellCooldown, k6)
    local realCooldown = nil
    if callOK and type(cooldownInfo) == "table" then
      local readOK, duration = pcall(function()
        return WowBuddyDev.SafeNumber(cooldownInfo.duration)
      end)
      if readOK then
        realCooldown = duration
      end
    end
    if realCooldown and realCooldown > 0 then
      activeCount = activeCount + 1
      local spellInfo = C_Spell and (C_Spell.GetSpellInfo and C_Spell.GetSpellInfo(k6))
      local mismatchNote = ""
      if math.abs(realCooldown - declaredCooldown) > 1 then
        mismatchNote = "  <<< 不一致（候选天赋门控/热修改基准）"
        mismatchCount = mismatchCount + 1
      end
      print(string.format("[CDCheck] %s(%d) 声明=%d 真实=%d%s", spellInfo and spellInfo.name or "?", k6, declaredCooldown, realCooldown, mismatchNote))
    end
  end
  print(string.format("[CDCheck] 冷却中 %d 个，不一致 %d 个（就绪技能需先施法再跑）", activeCount, mismatchCount))
end
-- @@拆分：CoreCastState.lua@@
-- 功能：取当前装备饰品（双饰品槽）的剩余冷却秒数。
-- 入参：无。
-- 出参：剩余秒数；饰品没装备返回专用哨兵值，不在冷却返回 0。
-- 说明：先确认饰品确实在两个饰品槽之一。用物品冷却接口读到的时长小于 10 秒时不返回——那是公共冷却之类的短冷却，不是饰品主动效果，返回它会污染像素编码。读到有效冷却时顺手把总时长缓存下来，供下次读不到时兜底。
function WowBuddyDev.GetTrinketCooldownRemaining()
  if not WowBuddyDev.trinketItemID then
    return 0
  end
  local trinketEquipped = false
  for i4 = 13, 14, 1 do
    if GetInventoryItemID("player", i4) == WowBuddyDev.trinketItemID then
      trinketEquipped = true
      break
    end
  end
  if not trinketEquipped then
    return 601
  end
  if coreState.trinketCooldownStart and coreState.lastTrinketCooldownDuration then
    local remainingSec = coreState.lastTrinketCooldownDuration - (GetTime() - coreState.trinketCooldownStart)
    if remainingSec > 0 then
      -- 【改装】原来 math.ceil(remainingSec)
      return remainingSec
    end
    coreState.trinketCooldownStart = nil
  end
  for i5 = 13, 14, 1 do
    local itemID = GetInventoryItemID("player", i5)
    if itemID == WowBuddyDev.trinketItemID then
      local startTime, trinketCooldownDuration, isEnabled = GetInventoryItemCooldown("player", i5)
      if isEnabled == 1 and (trinketCooldownDuration > 0 and startTime > 0) then
        if trinketCooldownDuration < 10 then
          return 0
        end
        local remainingSec = trinketCooldownDuration - (GetTime() - startTime)
        if remainingSec > 0 then
          coreState.lastTrinketCooldownDuration = trinketCooldownDuration
          -- 【改装】原来 math.ceil(remainingSec)
          return remainingSec
        end
      end
      break
    end
  end
  return 0
end
-- 功能：取指定饰品槽的剩余冷却秒数（供外部读取端按槽查询）。
-- 入参：slotID 装备槽号。
-- 出参：剩余秒数（最多 600，保留小数）；槽空、物品未加载或不可用返回哨兵值。
-- 说明：先确认槽里有物品且物品技能已加载，没有就请求加载并返回哨兵值——外层下一轮再问就好，不能在这条热路径上阻塞。物品还没进过冷却时直接返回 0，避免把「冷却时长未知」当成「正在长时间冷却」。
function WowBuddyDev.GetTrinketSlotCooldownRemaining(slotID)
  local callOK, remainingSec = pcall(function()
    local itemID = GetInventoryItemID("player", slotID)
    if not itemID then
      return 601
    end
    if not C_Item or not C_Item.GetItemSpell then
      return 601
    end
    local itemName, itemSpellID = C_Item.GetItemSpell(itemID)
    if not itemName and not itemSpellID then
      if C_Item.RequestLoadItemDataByID then
        C_Item.RequestLoadItemDataByID(itemID)
      end
      return 601
    end
    local startTime, slotCooldownDuration, isEnabled = GetInventoryItemCooldown("player", slotID)
    startTime = WowBuddyDev.SafeNumber(startTime)
    slotCooldownDuration = WowBuddyDev.SafeNumber(slotCooldownDuration)
    if isEnabled ~= 1 and isEnabled ~= true then
      return 601
    end
    if slotCooldownDuration <= 0 or startTime <= 0 then
      return 0
    end
    if slotCooldownDuration < 10 then
      return 0
    end
    local remainingSec = slotCooldownDuration - (GetTime() - startTime)
    if remainingSec <= 0 then
      return 0
    end
    -- 【改装】原来是 math.min(600, math.ceil(remainingSec))，去掉 ceil 才能出十分位
    return math.min(600, remainingSec)
  end)
  if not callOK or type(remainingSec) ~= "number" then
    return 601
  end
  return remainingSec
end
-- 功能：判断公共冷却是否正在进行。
-- 入参：无。
-- 出参：true/false；缺失或不可读为 nil，不得显示成 OFF。
-- 无限服没有 61304，使用已学且无独立冷却的技能查询同一个原生接口。
function WowBuddyDev.IsGcdActive()
  local spellID = 61304
  local probeIDs = WowBuddyDev.classData and WowBuddyDev.classData.gcdProbeSpellIDs
  local callOK, isActive, reason = pcall(function()
    local getCooldown = C_Spell and C_Spell.GetSpellCooldown or _G.GetSpellCooldown
    if type(getCooldown) ~= "function" then
      return nil, "missing cooldown API"
    end
    if probeIDs then
      spellID = nil
      for _, id in ipairs(probeIDs) do
        if WowBuddyDev.IsSpellKnown(id) == true then
          spellID = id
          break
        end
      end
      if not spellID then return nil, "no learned GCD probe" end
    end
    local cooldownInfo, duration, isEnabled = getCooldown(spellID)
    local startTime = cooldownInfo
    if type(cooldownInfo) == "table" then
      if type(cooldownInfo.isActive) == "boolean" then
        if cooldownInfo.isActive then return true, "isActive" end
        return false, "isActive"
      end
      startTime = cooldownInfo.startTime
      duration = cooldownInfo.duration
      isEnabled = cooldownInfo.isEnabled
    end
    if isEnabled == false or isEnabled == 0 then
      return nil, "cooldown disabled"
    end
    if type(startTime) ~= "number" or type(duration) ~= "number" then
      return nil, "missing cooldown data"
    end
    -- Do not turn protected or malformed values into zero through SafeNumber.
    return startTime > 0 and duration > 0 and startTime + duration > GetTime(), "timestamps"
  end)
  if not callOK then isActive, reason = nil, "cooldown query unreadable" end
  local status = isActive == nil and "UNKNOWN" or (isActive and "ON" or "OFF")
  local previous = WowBuddyDev.gcdDiagnostic
  if not previous or previous.status ~= status or previous.spellID ~= spellID or previous.reason ~= reason then
    local diagnostic = { spellID = spellID, status = status, reason = reason,
      api = C_Spell and C_Spell.GetSpellCooldown and "C_Spell.GetSpellCooldown" or "GetSpellCooldown",
      at = GetTime() }
    WowBuddyDev.gcdDiagnostic = diagnostic
    if WowBuddyDev.DB then
      WowBuddyDev.DB.gcdDiagnostic = diagnostic
      if status == "ON" then WowBuddyDev.DB.gcdLastActive = diagnostic end
    end
  end
  return isActive
end
-- 功能：按规则取「额外取值」：能量类、充能资源类、能量百分比类。
-- 入参：rule 规则（类型、资源类型）。
-- 出参：数值；符能类可能返回颜色对象；认不出的规则类型返回 nil。
-- 说明：符能条要的是颜色百分比对象而不是数字，所以先试颜色接口再退回普通数值；死亡骑士的符文按「可用符文个数」逐个统计，其它充能资源直接用当前值。任何查询失败都返回 0 而不是 nil，避免主流程因为缺值中断。
function WowBuddyDev.GetExtraValueByRule(rule)
  if rule.type == "power" then
    local callOK, power = pcall(UnitPower, "player", rule.powerType)
    if callOK and type(power) == "number" then
      return power
    end
    return 0
  elseif rule.type == "charge_resource" then
    if rule.powerType == Enum.PowerType.Runes then
      local readyRunes = 0
      for i6 = 1, 6, 1 do
        local v247, v248, runeReady = GetRuneCooldown(i6)
        if runeReady then
          readyRunes = readyRunes + 1
        end
      end
      return readyRunes
    end
    local callOK, power = pcall(UnitPower, "player", rule.powerType)
    if callOK and type(power) == "number" then
      return power
    end
    return 0
  elseif rule.type == "energy_resource" then
    if rule.powerType == Enum.PowerType.RunicPower and WowBuddyDev.runicPowerColorCurve then
      local callOK, powerPercentColor = pcall(UnitPowerPercent, "player", rule.powerType, false, WowBuddyDev.runicPowerColorCurve)
      if callOK and (powerPercentColor and (type(powerPercentColor) == "table" and powerPercentColor.GetRGB)) then
        return powerPercentColor
      end
    end
    local callOK, power = pcall(UnitPower, "player", rule.powerType)
    if callOK and type(power) == "number" then
      return power
    end
    return 0
  end
  return nil
end
-- @@拆分：CoreLocale.lua@@
-- @@拆分：CoreButtons.lua@@
WowBuddyDev.ModuleExports("Core").eventFrame = eventFrame -- @@拆分新增@@
WowBuddyDev.ModuleExports("Core").shouldResetCooldownsOnEvent = shouldResetCooldownsOnEvent -- @@拆分新增@@
-- @@拆分：CoreEvents.lua@@
-- @@拆分：CoreControls.lua@@
-- @@拆分：CoreMovement.lua@@
-- @@拆分：CoreDiagnostics.lua@@
WowBuddyDev.RegisterModule("Core", { "Modules", "CoreSettings" })
