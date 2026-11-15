-- ==========================================================================
-- 文件：CoreCooldownLedger.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 226-645 行），语句与顺序未改；
--       原文件级 local 状态改为状态表 coreState 的字段（coreState.X），带 @@状态表@@ 的行原为 local 声明。
-- 作用：持久化冷却账本（按角色分桶）、爆发药水冷却、充能记录与恢复。
-- 加载：TOC 中位于 CoreSettings.lua 之后、Core.lua 之前；只依赖 CoreState 与更早的拆分文件，
--       Core.lua 中赋值的 applyTalentCooldownGates 经状态表在运行期取得。
-- ==========================================================================
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreCooldownLedger", { "CoreSettings", "CoreState", "CoreClassData" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local coreState = WowBuddyDev.Require("CoreState") -- @@拆分新增@@
-- ---- 以下为原 Core.lua 内容 ----
-- 功能：取玩家自己的 GUID，作为持久化冷却账本「按角色分桶」的键。
-- 入参：无。
-- 出参：GUID 字符串；接口不可用或拿到空串时返回 nil。
-- 说明：拿不到就返回 nil，让上层放弃持久化，而不是把数据写进一个错误的桶里串号。
local function getPlayerGUID()
  if type(UnitGUID) ~= "function" then
    return nil
  end
  local playerGUID = UnitGUID("player")
  if type(playerGUID) ~= "string" or playerGUID == "" then
    return nil
  end
  return playerGUID
end
-- 功能：取（必要时先建）当前角色的持久化冷却账本。
-- 入参：createIfMissing 为 true 时允许新建表。
-- 出参：当前角色的账本表；不允许新建又不存在时返回 nil。
-- 说明：分两层——存档里按角色 GUID 分桶，桶里再按技能键存条目。冷却要跨重载和重登保留，但不同角色的账本不能互相污染。读取路径上（createIfMissing 为假）绝不建表，避免只读检查把存档写脏。
local function getPersistentLedger(createIfMissing)
  if not WowBuddyDev.DB then
    WowBuddyDev.InitDB()
  end
  local playerGUID = getPlayerGUID()
  if not playerGUID then
    return nil
  end
  local persistentLedger = WowBuddyDev.DB and WowBuddyDev.DB.persistentCooldownLedger
  if type(persistentLedger) ~= "table" then
    if not createIfMissing then
      return nil
    end
    persistentLedger = {}
    WowBuddyDev.DB.persistentCooldownLedger = persistentLedger
  end
  local playerLedger = persistentLedger[playerGUID]
  if type(playerLedger) ~= "table" then
    if not createIfMissing then
      return nil
    end
    playerLedger = {}
    persistentLedger[playerGUID] = playerLedger
  end
  return playerLedger
end
local LEDGER_CLOCK_SKEW_TOLERANCE_SEC = 3
local BURST_POTION_ID = "item_burst_potion"
local BURST_POTION_LEDGER_KEY = "consumable:" .. BURST_POTION_ID
-- 功能：算账本条目的剩余冷却秒数（登录后重建冷却的核心）。
-- 入参：entry 账本条目（表或裸数字）；serverNow 服务器时间；sessionNow 本地运行时间。
-- 出参：剩余秒数；条目不可用时返回 nil。
-- 说明：优先用服务器时间算，因为本地时间可能被玩家改系统时间或换时区影响。条目里同时记了服务器和本地两套时间戳，只有当「两套时间算出来的已过时长」差值在容差秒数以内，才敢信服务器那份；否则退回服务器绝对过期时间。两条路都不通就返回 nil，让上层放弃这条记录——宁可重算，也不能给出一个偏差几小时的剩余时间。
local function ledgerEntryRemaining(entry, serverNow, sessionNow)
  if type(entry) ~= "table" then
    local expiresAt = tonumber(entry)
    return expiresAt and expiresAt - serverNow or nil
  end
  local serverRecordedAt = tonumber(entry.serverRecordedAt)
  local serverExpiresAt = tonumber(entry.serverExpiresAt)
  local sessionRecordedAt = tonumber(entry.sessionRecordedAt)
  local sessionExpiresAt = tonumber(entry.sessionExpiresAt)
  if serverRecordedAt and (sessionRecordedAt and sessionExpiresAt) then
    local serverElapsed = serverNow - serverRecordedAt
    local sessionElapsed = sessionNow - sessionRecordedAt
    if serverElapsed >= 0 and (sessionElapsed >= 0 and math.abs(serverElapsed - sessionElapsed) <= LEDGER_CLOCK_SKEW_TOLERANCE_SEC) then
      return sessionExpiresAt - sessionNow
    end
  end
  return serverExpiresAt and serverExpiresAt - serverNow or nil
end
-- 功能：造一条账本记录，同时写入服务器时间和本地运行时间两套时间戳。
-- 入参：durationSec 冷却总时长；serverNow 服务器时间；sessionNow 本地运行时间。
-- 出参：账本条目表。
-- 说明：两套时间戳是给下次登录时互相校验用的（见账本剩余时间的算法）：本地时间不可信，但只有本地时间才能和服务器时间对齐起来算剩余。
local function makeLedgerEntry(durationSec, serverNow, sessionNow)
  return {
    duration = durationSec,
    serverRecordedAt = serverNow,
    serverExpiresAt = serverNow + durationSec,
    sessionRecordedAt = sessionNow,
    sessionExpiresAt = sessionNow + durationSec,
  }
end
-- 功能：某个持久化冷却技能成功施放时，记录它的开始时间，并把条目写进账本。
-- 入参：cooldownKey 冷却键（技能 ID）。
-- 出参：无。
-- 说明：只处理登记在持久化冷却表里的技能。开始时间优先沿用「上次施放时间」，没有才用当前时间——因为施法成功事件可能比技能真正进入冷却晚一点到，用事件时刻会让剩余时间偏长。服务器时间拿不到时直接不落盘。
local function recordPersistentCooldownStart(cooldownKey)
  if not (WowBuddyDev.persistentCooldowns and WowBuddyDev.persistentCooldowns[cooldownKey]) then
    return
  end
  local talentCooldownGates = WowBuddyDev.classData and WowBuddyDev.classData.talentCooldownGates
  if coreState.applyTalentCooldownGates and (talentCooldownGates and talentCooldownGates[cooldownKey]) then
    coreState.applyTalentCooldownGates(talentCooldownGates)
  end
  local cooldownSeconds = tonumber(WowBuddyDev.cooldowns and WowBuddyDev.cooldowns[cooldownKey])
  if not cooldownSeconds or cooldownSeconds <= 0 then
    return
  end
  local castStartTime = tonumber(coreState.lastCastTimeBySpell[cooldownKey]) or GetTime()
  coreState.cooldownEndBySpell[cooldownKey] = castStartTime + cooldownSeconds
  if type(GetServerTime) ~= "function" then
    return
  end
  local serverNow = GetServerTime()
  if type(serverNow) ~= "number" or serverNow <= 0 then
    return
  end
  local ledger = getPersistentLedger(true)
  if ledger then
    ledger[cooldownKey] = makeLedgerEntry(cooldownSeconds, serverNow, castStartTime)
  end
end
-- 功能：记录爆发药水这一次的使用，写进账本。
-- 入参：consumableID 消耗品 ID；cooldownSeconds 冷却时长；castStartTime 施放时刻。
-- 出参：无。
-- 说明：一个消耗品定义可能挂在多个物品 ID 上，所以固定用「爆发药水」这一条账本键写入，而不是按具体物品 ID 分散写——否则换个药水就会读不到上次的冷却。
local function recordBurstPotionUse(consumableID, cooldownSeconds, castStartTime)
  if consumableID ~= BURST_POTION_ID then
    return
  end
  coreState.consumableStateKnown = true
  cooldownSeconds = tonumber(cooldownSeconds)
  if not cooldownSeconds or cooldownSeconds <= 0 or type(GetServerTime) ~= "function" then
    return
  end
  local serverNow = GetServerTime()
  if type(serverNow) ~= "number" or serverNow <= 0 then
    return
  end
  castStartTime = tonumber(castStartTime) or GetTime()
  local ledger = getPersistentLedger(true)
  if ledger then
    ledger[BURST_POTION_LEDGER_KEY] = makeLedgerEntry(cooldownSeconds, serverNow, castStartTime)
  end
end
-- 功能：清掉爆发药水的本地冷却缓存和账本条目。
-- 入参：consumableID 消耗品 ID。
-- 出参：无。
-- 说明：游戏自己重置了冷却时调用，缓存和账本必须一起清，只清一半会出现「界面上已经好了、但插件还认为在冷却」的不一致。
local function clearBurstPotionRuntime(consumableID)
  if consumableID ~= BURST_POTION_ID then
    return
  end
  coreState.consumableStateKnown = true
  coreState.consumableCooldownStart[consumableID] = nil
  local ledger = getPersistentLedger(false)
  if ledger then
    ledger[BURST_POTION_LEDGER_KEY] = nil
  end
end
-- 功能：登录后用账本把爆发药水的冷却「接着走」，而不是从零开始算。
-- 入参：consumable 消耗品定义（要有 id 和 cooldown）。
-- 出参：true 表示成功接上冷却；false 表示没接上（账本里没有或已经过期）。
-- 说明：账本剩余会被夹到定义冷却时长以内，防止玩家改过冷却配置后出现「剩余比总时长还长」的异常值。
local function restoreBurstPotionCooldown(consumable)
  if not consumable or consumable.id ~= BURST_POTION_ID then
    return false
  end
  coreState.consumableStateKnown = true
  local cooldownSeconds = tonumber(consumable.cooldown)
  if not cooldownSeconds or cooldownSeconds <= 0 or type(GetServerTime) ~= "function" then
    return false
  end
  local ledger = getPersistentLedger(false)
  if not ledger or ledger[BURST_POTION_LEDGER_KEY] == nil then
    return false
  end
  local serverNow = GetServerTime()
  local now = GetTime()
  if type(serverNow) ~= "number" or serverNow <= 0 then
    return false
  end
  local remainingSec = ledgerEntryRemaining(ledger[BURST_POTION_LEDGER_KEY], serverNow, now)
  if remainingSec and remainingSec > 0 then
    remainingSec = math.min(remainingSec, cooldownSeconds)
    coreState.consumableCooldownStart[consumable.id] = now - (cooldownSeconds - remainingSec)
    return true
  end
  coreState.consumableCooldownStart[consumable.id] = nil
  ledger[BURST_POTION_LEDGER_KEY] = nil
  return false
end
-- 功能：登录或重载界面后，用账本把消耗品（目前只有爆发药水）的剩余冷却接着走。
-- 入参：无。
-- 出参：无。
-- 说明：只在消耗品表里挑出爆发药水那一项处理，处理完立刻返回；其余消耗品直接读物品自身冷却，不需要账本。
function WowBuddyDev.RestorePersistentConsumableCooldowns()
  for index, consumableDef in ipairs(WowBuddyDev.consumableItems or {}) do
    if consumableDef.id == BURST_POTION_ID then
      restoreBurstPotionCooldown(consumableDef)
      return
    end
  end
end
-- 功能：把充能类技能的动作键拼成账本键。
-- 入参：actionKey 动作键名。
-- 出参：账本键字符串；入参不是非空字符串时返回 nil。
-- 说明：加前缀是为了和普通冷却键（数字技能 ID）在同一个账本表里区分开，避免字符串键和数字键混在一起难以排查。
local function chargeLedgerKey(actionKey)
  if type(actionKey) ~= "string" or actionKey == "" then
    return nil
  end
  return "charge:" .. actionKey
end
-- 功能：读某个充能技能的追踪配置（最大充能数、每层充能时间）。
-- 入参：actionKey 动作键名。
-- 出参：追踪配置, 最大充能数, 充能时间；配置缺失或数值非法时返回 nil。
-- 说明：充能数或充能时间小于等于 0 都判为配置无效并直接拒绝——否则后面按充能数做的循环和上限判断会算错。
local function getChargeTracker(actionKey)
  local chargeTracker = WowBuddyDev.persistentChargeTrackers and WowBuddyDev.persistentChargeTrackers[actionKey]
  if type(chargeTracker) ~= "table" then
    return nil
  end
  local maxCharges = math.floor(tonumber(chargeTracker.maxCharges) or 0)
  local rechargeSeconds = tonumber(chargeTracker.rechargeSeconds)
  if maxCharges <= 0 or not rechargeSeconds or rechargeSeconds <= 0 then
    return nil
  end
  return chargeTracker, maxCharges, rechargeSeconds
end
-- 功能：整理充能账本：丢掉已经过期的恢复记录，算出当前可用充能数和锁定状态。
-- 入参：actionKey 动作键名；createIfMissing 是否允许建账本。
-- 出参：充能条目, 可用充能数, 是否锁定, 账本, 服务器时间, 本地时间。
-- 说明：把还有效的恢复记录原地压到数组前部再截掉尾巴，不新建表，避免每次刷新都产生垃圾。若一条有效记录都没有、也不在锁定中，就把整条账本记录删掉，防止存档随游玩时间无上限膨胀。
local function normalizeChargeRecoveries(actionKey, createIfMissing)
  local chargeTracker, maxCharges = getChargeTracker(actionKey)
  local ledgerKey = chargeLedgerKey(actionKey)
  if not chargeTracker or not ledgerKey or type(GetServerTime) ~= "function" then
    return nil, maxCharges or 0, false, nil, nil, nil
  end
  local serverNow = GetServerTime()
  local now2 = GetTime()
  if type(serverNow) ~= "number" or serverNow <= 0 then
    return nil, maxCharges, false, nil, nil, nil
  end
  local ledger = getPersistentLedger(createIfMissing)
  local chargeEntry = ledger and ledger[ledgerKey]
  if type(chargeEntry) ~= "table" then
    return nil, maxCharges, false, ledger, serverNow, now2
  end
  if type(chargeEntry.recoveries) ~= "table" then
    chargeEntry.recoveries = {}
  end
  local recoveries = chargeEntry.recoveries
  local recoveredCount = 0
  local writeIndex = 1
  local recoveryCount = #recoveries
  for i = 1, recoveryCount, 1 do
    local recoveryEntry = recoveries[i]
    local remainingSec = ledgerEntryRemaining(recoveryEntry, serverNow, now2)
    if remainingSec and (remainingSec > 0 and recoveredCount < maxCharges) then
      recoveredCount = recoveredCount + 1
      if writeIndex ~= i then
        recoveries[writeIndex] = recoveryEntry
      end
      writeIndex = writeIndex + 1
    end
  end
  if writeIndex <= recoveryCount then
    for i2 = recoveryCount, writeIndex, -1 do
      recoveries[i2] = nil
    end
  end
  local lockedOut = false
  if chargeEntry.lockout then
    local lockoutRemaining = ledgerEntryRemaining(chargeEntry.lockout, serverNow, now2)
    if lockoutRemaining and lockoutRemaining > 0 then
      lockedOut = true
    else
      chargeEntry.lockout = nil
    end
  end
  if recoveredCount == 0 and not lockedOut then
    ledger[ledgerKey] = nil
    chargeEntry = nil
  end
  return chargeEntry, maxCharges - recoveredCount, lockedOut, ledger, serverNow, now2
end
-- 功能：算某个充能技能当前还剩几层可用充能。
-- 入参：actionKey 动作键名。
-- 出参：可用充能层数；处于锁定期或没有追踪配置时返回 0。
-- 说明：只读不建账本（createIfMissing 传 false），纯查询不会在存档里留下空条目。
function WowBuddyDev.GetPersistentChargeCount(actionKey)
  local chargeTracker, availableCharges, lockedOut = normalizeChargeRecoveries(actionKey, false)
  if lockedOut then
    return 0
  end
  return availableCharges
end
-- 功能：记一次充能技能成功施放——往账本追加一条恢复记录，必要时一起写锁定时间。
-- 入参：actionKey 动作键名。
-- 出参：true, 剩余可用层数；记账条件不满足时 false, 当前可用层数。
-- 说明：新恢复记录的到期时间接在「上一条记录的剩余时间」之后，而不是从当前时刻重新计时——这样连续施放时充能才是排队恢复的。返回的层数用「最大充能数 − 恢复记录条数」算；上一层都没恢复时 normalizeChargeRecoveries 已经把空条目清掉了，所以恢复记录条数就是已用掉的层数。
function WowBuddyDev.RecordPersistentChargeSuccess(actionKey)
  local chargeTracker, maxCharges, rechargeSeconds = getChargeTracker(actionKey)
  if not chargeTracker then
    return false, 0
  end
  local chargeEntry, availableCharges, lockedOut, ledger, serverNow, sessionNow = normalizeChargeRecoveries(actionKey, true)
  if not ledger or not serverNow or not sessionNow or availableCharges <= 0 then
    return false, math.max(0, availableCharges or 0)
  end
  chargeEntry = chargeEntry or { schema = 1, recoveries = {} }
  local recoveries = chargeEntry.recoveries or {}
  local lastRecoveryRemaining = 0
  if #recoveries > 0 then
    lastRecoveryRemaining = ledgerEntryRemaining(recoveries[#recoveries], serverNow, sessionNow) or 0
  end
  table.insert(recoveries, makeLedgerEntry(math.max(0, lastRecoveryRemaining) + rechargeSeconds, serverNow, sessionNow))
  chargeEntry.recoveries = recoveries
  local lockoutSeconds = tonumber(chargeTracker.lockoutSeconds) or 0
  if lockoutSeconds > 0 then
    chargeEntry.lockout = makeLedgerEntry(lockoutSeconds, serverNow, sessionNow)
  end
  ledger[chargeLedgerKey(actionKey)] = chargeEntry
  return true, maxCharges - #recoveries
end
-- 功能：清掉某个持久化冷却的运行时缓存（结束时间表 + 账本条目）。
-- 入参：cooldownKey 冷却键。
-- 出参：无。
local function clearPersistentCooldownState(cooldownKey)
  if not (WowBuddyDev.persistentCooldowns and WowBuddyDev.persistentCooldowns[cooldownKey]) then
    return
  end
  coreState.cooldownEndBySpell[cooldownKey] = nil
  local ledger = getPersistentLedger(false)
  if ledger then
    ledger[cooldownKey] = nil
  end
end
-- 功能：把账本条目换算成运行时冷却：写回开始时间、结束时间，并给出剩余秒数。
-- 入参：cooldownKey 冷却键；ledger 账本（可空，空了会自己取）；serverNow 服务器时间；sessionNow 本地运行时间。
-- 出参：true, 剩余秒数 表示还在冷却；false, 0 表示已结束（同时清掉缓存）。
-- 说明：总时长优先用账本里记下的时长，没有才用当前配置值——玩家中途改过配置时，用新配置去套旧记录会算歪。剩余同样会被夹到总时长以内。
local function applyLedgerEntryToRuntime(cooldownKey, ledger, serverNow, sessionNow)
  if not (WowBuddyDev.persistentCooldowns and WowBuddyDev.persistentCooldowns[cooldownKey]) then
    return false
  end
  ledger = ledger or getPersistentLedger(false)
  if not ledger or ledger[cooldownKey] == nil then
    return false
  end
  if type(GetServerTime) ~= "function" then
    return false
  end
  serverNow = serverNow or GetServerTime()
  sessionNow = sessionNow or GetTime()
  if type(serverNow) ~= "number" or serverNow <= 0 then
    return false
  end
  local cooldownSeconds = tonumber(WowBuddyDev.cooldowns and WowBuddyDev.cooldowns[cooldownKey])
  local storedEntry = ledger[cooldownKey]
  local durationSec = type(storedEntry) == "table" and tonumber(storedEntry.duration) or cooldownSeconds
  local remainingSec = ledgerEntryRemaining(storedEntry, serverNow, sessionNow)
  if durationSec and (durationSec > 0 and remainingSec) then
    if remainingSec > 0 then
      remainingSec = math.min(remainingSec, durationSec)
      coreState.lastCastTimeBySpell[cooldownKey] = sessionNow - (durationSec - remainingSec)
      coreState.cooldownEndBySpell[cooldownKey] = sessionNow + remainingSec
      return true, remainingSec
    end
    coreState.lastCastTimeBySpell[cooldownKey] = nil
    coreState.cooldownEndBySpell[cooldownKey] = nil
    ledger[cooldownKey] = nil
  else
    coreState.cooldownEndBySpell[cooldownKey] = nil
    ledger[cooldownKey] = nil
  end
  return false, 0
end
-- 功能：登录或重载界面后，按账本重建所有持久化技能的剩余冷却。
-- 入参：无。
-- 出参：无。
-- 说明：只认服务器时间：取不到 GetServerTime、或时间不是正数、或账本不存在时整体跳过——宁可当作冷却未知，也不要用本地时间算歪。遍历的是冷却配置表，没配账本的技能不会被动到。
function WowBuddyDev.RestorePersistentCooldowns()
  if type(GetServerTime) ~= "function" then
    return
  end
  local ledger = getPersistentLedger(false)
  if not ledger then
    return
  end
  local serverNow = GetServerTime()
  local now3 = GetTime()
  if type(serverNow) ~= "number" or serverNow <= 0 then
    return
  end
  for k2 in pairs(WowBuddyDev.persistentCooldowns or {}) do
    applyLedgerEntryToRuntime(k2, ledger, serverNow, now3)
  end
end
-- 功能：游戏重置冷却时（副本重置、Boss 战结束等），把标记了 resetOnGameCooldownReset 的技能的冷却和充能记账清掉。
-- 入参：无。
-- 出参：无。
-- 说明：只清标记过 resetOnGameCooldownReset 的技能——玩家自己打的普通冷却不该被这次重置一起带走。爆发药水是硬编码清掉的，它不在技能配置表里，所以单独处理并把「消耗品状态已知」标记置位。
function WowBuddyDev.ClearPersistentCooldownsForGameReset()
  local ledger = getPersistentLedger(false)
  for k3, cooldownDef in pairs(WowBuddyDev.persistentCooldowns or {}) do
    if type(cooldownDef) == "table" and cooldownDef.resetOnGameCooldownReset == true then
      coreState.lastCastTimeBySpell[k3] = nil
      coreState.cooldownEndBySpell[k3] = nil
      if ledger then
        ledger[k3] = nil
      end
    end
  end
  coreState.consumableCooldownStart[BURST_POTION_ID] = nil
  coreState.consumableStateKnown = true
  if ledger then
    ledger[BURST_POTION_LEDGER_KEY] = nil
  end
  for k4, chargeTrackerDef in pairs(WowBuddyDev.persistentChargeTrackers or {}) do
    if type(chargeTrackerDef) == "table" and chargeTrackerDef.resetOnGameCooldownReset == true then
      local chargeLedgerKey = chargeLedgerKey(k4)
      if ledger and chargeLedgerKey then
        ledger[chargeLedgerKey] = nil
      end
    end
  end
end
WowBuddyDev.ModuleExports("CoreCooldownLedger").BURST_POTION_ID = BURST_POTION_ID -- @@拆分新增@@
WowBuddyDev.ModuleExports("CoreCooldownLedger").applyLedgerEntryToRuntime = applyLedgerEntryToRuntime -- @@拆分新增@@
WowBuddyDev.ModuleExports("CoreCooldownLedger").clearBurstPotionRuntime = clearBurstPotionRuntime -- @@拆分新增@@
WowBuddyDev.ModuleExports("CoreCooldownLedger").clearPersistentCooldownState = clearPersistentCooldownState -- @@拆分新增@@
WowBuddyDev.ModuleExports("CoreCooldownLedger").recordBurstPotionUse = recordBurstPotionUse -- @@拆分新增@@
WowBuddyDev.ModuleExports("CoreCooldownLedger").recordPersistentCooldownStart = recordPersistentCooldownStart -- @@拆分新增@@
WowBuddyDev.ModuleExports("CoreCooldownLedger").restoreBurstPotionCooldown = restoreBurstPotionCooldown -- @@拆分新增@@
WowBuddyDev.RegisterModule("CoreCooldownLedger", { "CoreState" })
