-- ==========================================================================
-- 文件：CoreSettings.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 111-488 行），语句与顺序未改。
-- 作用：存档初始化与迁移、用户宏存储、朱鹤宏迁移、爆发自动关闭设置。
-- 加载：TOC 中位于 Core.lua 之前（Core 加载时可能直接调用 InitDB）；只依赖 WowBuddyDev 全局表。
-- ==========================================================================
-- ---- 以下为原 Core.lua 内容 ----
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreSettings", { "CoreLocale", "CoreEvents", "MacroAuthorize", "PixelBar" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local DB_SCHEMA_VERSION = 1
-- 功能：把旧版存档升级到当前 schema 版本。存档版本低于当前值时，清掉结构化配置缓存，让它们由职业文件重新写入，然后写上当前版本号。
-- 入参：db 存档表（就是全局插件表上的 DB）。
-- 出参：无（就地修改 db.permesSchemaVersion）。
-- 说明：只清 simcProfile、simcBagItems 这类「能再生成」的缓存，不动玩家手动设置的开关和按键，所以升级不会丢配置。
local function migrateDBSchema(db)
  local schemaVersion = tonumber(db.permesSchemaVersion) or 0
  if schemaVersion < DB_SCHEMA_VERSION then
    db.simcProfile = nil
    db.simcProfileTimestamp = nil
    db.simcProfileError = nil
    db.simcBagItems = nil
    schemaVersion = DB_SCHEMA_VERSION
  end
  db.permesSchemaVersion = schemaVersion
end
-- 功能：初始化（首次运行）或补全账号存档 SemrepDB，并把它挂到 P07483180.DB 上。
-- 入参：无。
-- 出参：无。
-- 说明：先跑一次存档结构迁移，再逐项补默认值——只补缺失的键，不覆盖玩家已有设置。末尾「整体隐藏」为真时强制把总开关按灭。masterKey/burstKey/aoeKey 三项「当为 nil 时赋 nil」是空操作，等于声明这几个键允许不存在。
function WowBuddyDev.InitDB()
  _G.WowBuddyDevDB = _G.WowBuddyDevDB or {}
  WowBuddyDev.DB = _G.WowBuddyDevDB
  migrateDBSchema(WowBuddyDev.DB)
  if WowBuddyDev.DB.masterSwitch == nil then
    WowBuddyDev.DB.masterSwitch = true
  end
  if WowBuddyDev.DB.burstSwitch == nil then
    WowBuddyDev.DB.burstSwitch = false
  end
  if type(WowBuddyDev.DB.burstAutoCloseSecondsBySpec) ~= "table" then
    WowBuddyDev.DB.burstAutoCloseSecondsBySpec = {}
  end
  -- ★ 2026-10-04：「自动寻怪」默认改为开（用户预期：打死一个怪自动换下一个目标）。
  --   旧版默认 false 且用户存档里已写成 false（非 nil），光改默认值对老存档无效，
  --   所以做一次性迁移（autoTargetVer=2）：老存档升到 true；之后用户在设置里关掉
  --   不会被翻回来（Ver 已是 2 不再进迁移分支）。
  if WowBuddyDev.DB.autoTargetVer ~= 2 then
    WowBuddyDev.DB.autoTarget = true
    WowBuddyDev.DB.autoTargetVer = 2
  end
  if WowBuddyDev.DB.healerAutoTarget == nil then
    WowBuddyDev.DB.healerAutoTarget = true
  end
  if WowBuddyDev.DB.protectionPaladinAutoTarget == nil then
    WowBuddyDev.DB.protectionPaladinAutoTarget = false
  end
  if WowBuddyDev.DB.masterKey == nil then
    WowBuddyDev.DB.masterKey = nil
  end
  if WowBuddyDev.DB.burstKey == nil then
    WowBuddyDev.DB.burstKey = nil
  end
  if WowBuddyDev.DB.aoeKey == nil then
    WowBuddyDev.DB.aoeKey = nil
  end
  if WowBuddyDev.DB.aoeMode == nil then
    WowBuddyDev.DB.aoeMode = 0
  end
  if type(WowBuddyDev.DB.macroMapBySpec) ~= "table" then
    WowBuddyDev.DB.macroMapBySpec = {}
  end
  if type(WowBuddyDev.DB.userEditedMacrosBySpec) ~= "table" then
    WowBuddyDev.DB.userEditedMacrosBySpec = {}
  end
  if type(WowBuddyDev.DB.persistentCooldownLedger) ~= "table" then
    WowBuddyDev.DB.persistentCooldownLedger = {}
  end
  if WowBuddyDev.DB.disableTextAlert == nil then
    WowBuddyDev.DB.disableTextAlert = false
  end
  if WowBuddyDev.DB.disableSound == nil then
    WowBuddyDev.DB.disableSound = false
  end
  if WowBuddyDev.DB.logoSize == nil then
    WowBuddyDev.DB.logoSize = 64
  end
  if WowBuddyDev.DB.showLogoText == nil then
    WowBuddyDev.DB.showLogoText = true
  end
  if WowBuddyDev.DB.logoHidden == nil then
    WowBuddyDev.DB.logoHidden = false
  end
  if WowBuddyDev.DB.allOverlaysHidden == nil then
    WowBuddyDev.DB.allOverlaysHidden = false
  end
  if WowBuddyDev.DB.allOverlaysHidden then
    WowBuddyDev.DB.masterSwitch = false
  end
end
-- 功能：取当前专精 ID：先问职业模块，再退回存档里记录的专精 ID。
-- 入参：无。
-- 出参：专精 ID；两个来源都不可用时返回 nil。
-- 说明：职业模块先问，是因为它可能已经按英雄天赋算出了更准确的专精；存档值只是上次登录的残余，用来兜住模块还没加载完的时刻。
local function getCurrentSpecID()
  if WowBuddyDev.GetPlayerClassSpec then
    local v40, v41, specID = WowBuddyDev.GetPlayerClassSpec()
    if type(specID) == "number" and specID > 0 then
      return specID
    end
  end
  local savedSpecID = WowBuddyDev.DB and WowBuddyDev.DB.currentSpecID
  if type(savedSpecID) == "number" and savedSpecID > 0 then
    return savedSpecID
  end
  return nil
end
-- 功能：取（必要时先建）当前专精的宏存储：返回「宏表」和「用户改过的标记表」。
-- 入参：无（内部用当前专精 ID 定位）。
-- 出参：宏表, 用户改动标记表；拿不到专精时返回两个 nil。
-- 说明：首次调用会把旧版「全专精共用一份宏表」迁移成按专精分表（存储版本从 1 升到 2）。迁移时只搬旧表里确实存在、且新表还没有的条目，并把它们标成「用户改过」——否则默认宏会在下次刷新时覆盖玩家手改的内容。
local function getMacroStorage()
  if not WowBuddyDev.DB then
    WowBuddyDev.InitDB()
  end
  local specID = getCurrentSpecID()
  if not specID then
    return nil, nil
  end
  if tonumber(WowBuddyDev.DB.macroStorageVersion) ~= 2 then
    local legacyMacroMap = WowBuddyDev.DB.macroMap
    local legacyUserEditedMacros = WowBuddyDev.DB.userEditedMacros
    local macroMapForSpec = WowBuddyDev.DB.macroMapBySpec[specID] or {}
    local userEditedForSpec = WowBuddyDev.DB.userEditedMacrosBySpec[specID] or {}
    if type(legacyMacroMap) == "table" and type(legacyUserEditedMacros) == "table" then
      for k, v in pairs(legacyUserEditedMacros) do
        local legacyMacroBody = legacyMacroMap[k]
        if v and (type(legacyMacroBody) == "string" and macroMapForSpec[k] == nil) then
          macroMapForSpec[k] = legacyMacroBody
          userEditedForSpec[k] = true
        end
      end
    end
    WowBuddyDev.DB.macroMapBySpec[specID] = macroMapForSpec
    WowBuddyDev.DB.userEditedMacrosBySpec[specID] = userEditedForSpec
    WowBuddyDev.DB.macroMap = nil
    WowBuddyDev.DB.userEditedMacros = nil
    WowBuddyDev.DB.macroStorageVersion = 2
  end
  if type(WowBuddyDev.DB.macroMapBySpec[specID]) ~= "table" then
    WowBuddyDev.DB.macroMapBySpec[specID] = {}
  end
  if type(WowBuddyDev.DB.userEditedMacrosBySpec[specID]) ~= "table" then
    WowBuddyDev.DB.userEditedMacrosBySpec[specID] = {}
  end
  return WowBuddyDev.DB.macroMapBySpec[specID], WowBuddyDev.DB.userEditedMacrosBySpec[specID]
end
-- 功能：取某个动作键上玩家自己改写过的宏内容。
-- 入参：actionKey 动作键名。
-- 出参：是否被玩家改过, 宏内容；没改过、存档不是字符串或宏表取不到时返回 false, nil。
-- 说明：必须先查「玩家改过」标记再取内容——宏表里可能还留着默认宏的副本，只看内容分不清是不是玩家写的。
function WowBuddyDev.GetUserMacro(actionKey)
  local macroMap, userEditedFlags = getMacroStorage()
  if not macroMap or not userEditedFlags or not userEditedFlags[actionKey] then
    return false, nil
  end
  local macroBody = macroMap[actionKey]
  if type(macroBody) ~= "string" then
    return false, nil
  end
  return true, macroBody
end
-- 功能：把玩家改写的宏按当前专精存进宏表，并打上「玩家改过」标记。
-- 入参：actionKey 动作键名；macroBody 宏内容字符串。
-- 出参：true 保存成功；false 入参类型不对或宏表取不到（专精无效等）。
-- 说明：两个入参都必须是字符串，非字符串一律拒绝，免得把表或数字写进宏表后渲染成空按钮。宏按专精分开存，切专精不会互相覆盖。
function WowBuddyDev.SaveUserMacro(actionKey, macroBody)
  if type(actionKey) ~= "string" or type(macroBody) ~= "string" then
    return false
  end
  local macroMap, userEditedFlags = getMacroStorage()
  if not macroMap or not userEditedFlags then
    return false
  end
  macroMap[actionKey] = macroBody
  userEditedFlags[actionKey] = true
  return true
end
-- 功能：清掉某个动作键的玩家宏，让它重新走默认宏。
-- 入参：actionKey 动作键名。
-- 出参：true 清除成功；false 宏表取不到（专精无效等）。
-- 说明：宏内容和「玩家改过」标记必须一起清；只清内容会留下空壳标记，下次取宏会拿到 false，默认宏反而被顶掉。
function WowBuddyDev.ClearUserMacro(actionKey)
  local macroMap, userEditedFlags = getMacroStorage()
  if not macroMap or not userEditedFlags then
    return false
  end
  macroMap[actionKey] = nil
  userEditedFlags[actionKey] = nil
  return true
end
local CHIJI_MIGRATION_VERSION = 1
local CHIJI_LEGACY_MACRO_BODY = "/cast [nochanneling:天神御身] 朱鹤下凡\n/use 圣光潜力\n/use 光盲圣怒的连祷"
local CHIJI_LEGACY_MACRO_IR = {
  {
    line = 1,
    command = "cast",
    role = "condition_argument",
    condition_type = "nochanneling",
    source_value = "天神御身",
    kind = "spell",
    id = 443028,
    hero_applicability = {},
  },
  {
    line = 1,
    command = "cast",
    role = "command_argument",
    source_value = "朱鹤下凡",
    kind = "spell",
    id = 325197,
    hero_applicability = {},
  },
  {
    line = 2,
    command = "use",
    role = "command_argument",
    source_value = "圣光潜力",
    kind = "item",
    id = 241308,
    hero_applicability = {},
  },
  {
    line = 3,
    command = "use",
    role = "command_argument",
    source_value = "光盲圣怒的连祷",
    kind = "item",
    id = 249808,
    hero_applicability = {},
  },
}
-- 功能：一次性迁移：把踏风「朱鹤下凡」那条带隐藏用药命令的旧宏体删掉，让插件重新生成干净的宏。
-- 入参：无。
-- 出参：无。
-- 说明：只在专精 270 执行，且靠存档里的迁移版本号保证只跑一次。宏体比对走两条路：中文客户端直接按字符串比；其它客户端先让宏编译器把标准宏体编译成等价形式再比，两条都不匹配就完全不碰玩家的宏。这样比「按内容猜测」安全：宁可漏迁移，也不能误删玩家自己写的宏。
local function migrateChijiMacro()
  if getCurrentSpecID() ~= 270 then
    return
  end
  if not WowBuddyDev.DB then
    WowBuddyDev.InitDB()
  end
  if (tonumber(WowBuddyDev.DB.mistweaverChijiHiddenUseMigrationVersion) or 0) >= CHIJI_MIGRATION_VERSION then
    return
  end
  local isUserEdited, userMacroBody = WowBuddyDev.GetUserMacro("cd_325197")
  if not isUserEdited then
    WowBuddyDev.DB.mistweaverChijiHiddenUseMigrationVersion = CHIJI_MIGRATION_VERSION
    return
  end
  local canMigrate = false
  local macroMatchesLegacy = userMacroBody == CHIJI_LEGACY_MACRO_BODY
  if macroMatchesLegacy then
    canMigrate = true
  elseif WowBuddyDev.IsChineseClient and WowBuddyDev.IsChineseClient() then
    canMigrate = true
  elseif type(WowBuddyDev.CompileAuthorizedMacro) == "function" then
    local compiledLegacyMacro = WowBuddyDev.CompileAuthorizedMacro(CHIJI_LEGACY_MACRO_BODY, CHIJI_LEGACY_MACRO_IR)
    if compiledLegacyMacro then
      canMigrate = true
      macroMatchesLegacy = userMacroBody == compiledLegacyMacro
    end
  end
  if not canMigrate then
    return
  end
  if macroMatchesLegacy and not WowBuddyDev.ClearUserMacro("cd_325197") then
    return
  end
  WowBuddyDev.DB.mistweaverChijiHiddenUseMigrationVersion = CHIJI_MIGRATION_VERSION
end
-- 功能：把任意输入规整成「非负整数秒」。
-- 入参：value 任意值（可能是字符串、负数、小数）。
-- 出参：0 或正整数。
-- 说明：设置项可能存成字符串或负数，统一向下取整并夹到 0；负数不进缓存，否则会被当成「冷却早就结束了」而漏掉自动关闭爆发的时机。
local function toWholeSeconds(value)
  return math.max(0, math.floor(tonumber(value) or 0))
end
-- 功能：取当前专精 ID 和专精名；专精无效时返回两个 nil。
-- 入参：无。
-- 出参：专精 ID, 专精名。
local function getSpecIDAndName()
  if not WowBuddyDev.GetPlayerClassSpec then
    return nil, nil
  end
  local v58, v59, specID, specName = WowBuddyDev.GetPlayerClassSpec()
  if type(specID) ~= "number" or specID <= 0 then
    return nil, nil
  end
  return specID, specName
end
-- 功能：取当前专精「爆发开关自动关闭」的秒数。
-- 入参：无。
-- 出参：整秒数；专精无效时返回 0（0 表示不自动关闭）。
-- 说明：顺手把旧版不分专精的 burstAutoCloseSeconds 迁移进按专精存的 burstAutoCloseSecondsBySpec，迁完立刻删掉旧键，避免下次重复迁移；两边都没有时按 0 处理。
function WowBuddyDev.GetBurstAutoCloseSeconds()
  if not WowBuddyDev.DB then
    WowBuddyDev.InitDB()
  end
  local burstAutoCloseSpecID = getSpecIDAndName()
  if not burstAutoCloseSpecID then
    return 0
  end
  if WowBuddyDev.DB.burstAutoCloseSeconds ~= nil then
    if WowBuddyDev.DB.burstAutoCloseSecondsBySpec[burstAutoCloseSpecID] == nil then
      WowBuddyDev.DB.burstAutoCloseSecondsBySpec[burstAutoCloseSpecID] = toWholeSeconds(WowBuddyDev.DB.burstAutoCloseSeconds)
    end
    WowBuddyDev.DB.burstAutoCloseSeconds = nil
  end
  return toWholeSeconds(WowBuddyDev.DB.burstAutoCloseSecondsBySpec[burstAutoCloseSpecID])
end
-- 功能：按当前专精存下「爆发自动关闭秒数」，并重排自动关闭计时器。
-- 入参：seconds 秒数（小数向下取整，负数归 0）。
-- 出参：true, 实际存入的整秒数, 专精名；专精无效时 false, 0, nil。
-- 说明：改完必须重排计时器，否则旧计时器还按老秒数在跑。存入前统一归整成整秒，和取用侧的 toWholeSeconds 保持一致。
function WowBuddyDev.SaveBurstAutoCloseSeconds(seconds)
  if not WowBuddyDev.DB then
    WowBuddyDev.InitDB()
  end
  local burstAutoCloseSpecID, burstAutoCloseSpecName = getSpecIDAndName()
  if not burstAutoCloseSpecID then
    return false, 0, nil
  end
  local burstAutoCloseSeconds = toWholeSeconds(seconds)
  WowBuddyDev.DB.burstAutoCloseSecondsBySpec[burstAutoCloseSpecID] = burstAutoCloseSeconds
  WowBuddyDev.DB.burstAutoCloseSeconds = nil
  WowBuddyDev.ResetBurstAutoCloseTimer()
  return true, burstAutoCloseSeconds, burstAutoCloseSpecName
end
WowBuddyDev.burstAutoCloseGeneration = WowBuddyDev.burstAutoCloseGeneration or 0
local burstAutoCloseTimer = nil
-- 功能：重排「爆发自动关闭」计时器：先取消旧的，再按当前设置起一个新的。
-- 入参：无。
-- 出参：无。
-- 说明：用自增的 burstAutoCloseGeneration 做代次标记，回调里代次对不上就直接返回——避免连点开关时旧计时器把刚开的爆发又关掉。爆发开关没开、或秒数为 0 时只取消不起表；如果切换专精后秒数变了，也要靠这个函数换表。
function WowBuddyDev.ResetBurstAutoCloseTimer()
  if not WowBuddyDev.DB then
    WowBuddyDev.InitDB()
  end
  WowBuddyDev.burstAutoCloseGeneration = WowBuddyDev.burstAutoCloseGeneration + 1
  if burstAutoCloseTimer then
    burstAutoCloseTimer:Cancel()
    burstAutoCloseTimer = nil
  end
  if not WowBuddyDev.DB.burstSwitch then
    return
  end
  local burstAutoCloseSeconds = WowBuddyDev.GetBurstAutoCloseSeconds()
  if burstAutoCloseSeconds <= 0 then
    return
  end
  local burstAutoCloseGeneration = WowBuddyDev.burstAutoCloseGeneration
  burstAutoCloseTimer = C_Timer.NewTimer(burstAutoCloseSeconds, function()
    if WowBuddyDev.burstAutoCloseGeneration ~= burstAutoCloseGeneration then
      return
    end
    burstAutoCloseTimer = nil
    if not WowBuddyDev.DB or not WowBuddyDev.DB.burstSwitch then
      return
    end
    WowBuddyDev.SetBurstSwitch(false)
  end)
end
-- 功能：设置爆发开关状态，并同步界面和自动关闭计时器。
-- 入参：enabled 任意值，非 nil/false 即视为开。
-- 出参：无。
-- 说明：入参用 not not 归一成布尔再写存档，避免把 nil 或其它非布尔值存进去导致界面判断走偏。
function WowBuddyDev.SetBurstSwitch(enabled)
  if not WowBuddyDev.DB then
    WowBuddyDev.InitDB()
  end
  WowBuddyDev.DB.burstSwitch = not not enabled
  if WowBuddyDev.UpdateBurstSwitchUI then
    WowBuddyDev.UpdateBurstSwitchUI(WowBuddyDev.DB.burstSwitch)
  end
  WowBuddyDev.ResetBurstAutoCloseTimer()
end
WowBuddyDev.ModuleExports("CoreSettings").migrateChijiMacro = migrateChijiMacro -- @@拆分新增@@
WowBuddyDev.RegisterModule("CoreSettings", { "Modules" })
