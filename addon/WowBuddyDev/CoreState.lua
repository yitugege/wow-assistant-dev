-- ==========================================================================
-- 文件：CoreState.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 196-225 行），语句与顺序未改；
--       原文件级 local 状态改为状态表 coreState 的字段（coreState.X），带 @@状态表@@ 的行原为 local 声明。
-- 作用：冷却、消耗品、饰品与施法成功记录的共享状态及初值。
-- 加载：TOC 中位于 CoreSettings.lua 之后、Core.lua 之前；只依赖 CoreState 与更早的拆分文件，
--       Core.lua 中赋值的 applyTalentCooldownGates 经状态表在运行期取得。
-- 状态表字段（原 Core.lua 文件级 local）：
--   forceAvailableRules
--   consumableCooldownStart
--   consumableStateKnown
--   consumableByItemSpell
--   pendingItemDataIDs
--   trinketCooldownStart
--   lastTrinketCooldownDuration
--   lastCastTimeBySpell
--   cooldownEndBySpell
--   lastSucceededSpellID
--   lastSucceededCastGUID
--   lastSpellID
--   lastSucceededTime
--   succeededGeneration
--   healingStoneBlockedInCombat
--   applyTalentCooldownGates  （Core.lua 中赋值的函数）
-- ==========================================================================
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreState", {  }) or _G.WowBuddyDev -- @@注册表命名空间@@
local coreState = WowBuddyDev.ModuleExports("CoreState") -- @@拆分新增@@
-- ---- 以下为原 Core.lua 内容 ----
WowBuddyDev.pixelData = {}
WowBuddyDev.ACTION_LABELS = {}
WowBuddyDev.ACTION_TO_KEY = {}
WowBuddyDev.testData = {}
WowBuddyDev.cooldowns = {}
WowBuddyDev.persistentCooldowns = {}
WowBuddyDev.persistentChargeTrackers = {}
WowBuddyDev.actionAvailSpellIDs = {}
coreState.forceAvailableRules = {} -- @@状态表@@
WowBuddyDev.highlightRules = {}
WowBuddyDev.trinketItemID = nil
WowBuddyDev.extraValueRules = {}
WowBuddyDev.consumableItems = {}
coreState.consumableCooldownStart = {} -- @@状态表@@
coreState.consumableStateKnown = false -- @@状态表@@
coreState.consumableByItemSpell = {} -- @@状态表@@
coreState.pendingItemDataIDs = {} -- @@状态表@@
coreState.trinketCooldownStart = nil -- @@状态表@@
coreState.lastTrinketCooldownDuration = nil -- @@状态表@@
coreState.lastCastTimeBySpell = {} -- @@状态表@@
coreState.cooldownEndBySpell = {} -- @@状态表@@
coreState.lastSucceededSpellID = nil -- @@状态表@@
coreState.lastSucceededCastGUID = nil -- @@状态表@@
coreState.lastSpellID = nil -- @@状态表@@
coreState.lastSucceededTime = 0 -- @@状态表@@
coreState.succeededGeneration = 1 -- @@状态表@@
WowBuddyDev.playerSucceededGeneration = 1
WowBuddyDev.playerSucceededSpellID = 0
WowBuddyDev.forceAvailableState = {}
coreState.healingStoneBlockedInCombat = false -- @@状态表@@
WowBuddyDev.RegisterModule("CoreState", {  })
