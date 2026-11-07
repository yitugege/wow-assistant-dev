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
local lastSpecID = nil
local lastHeroSpecID = nil
WowBuddyDev.isClassActive = false
local unknownMarker
local reloadClassData
local refreshMacroBindings
local applyTalentCooldownGates
WowBuddyDev.DB = nil
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
local getSpellInfo = GetSpellInfo or function(spellID)
  if not spellID then
    return nil
  end
  local spellInfo = C_Spell.GetSpellInfo(spellID)
  if spellInfo then
    return spellInfo.name, nil, spellInfo.iconID, spellInfo.castTime, spellInfo.minRange, spellInfo.maxRange, spellInfo.spellID, spellInfo.originalIconID
  end
end
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
WowBuddyDev.pixelData = {}
WowBuddyDev.ACTION_LABELS = {}
WowBuddyDev.ACTION_TO_KEY = {}
WowBuddyDev.testData = {}
WowBuddyDev.cooldowns = {}
WowBuddyDev.persistentCooldowns = {}
WowBuddyDev.persistentChargeTrackers = {}
WowBuddyDev.actionAvailSpellIDs = {}
local forceAvailableRules = {}
WowBuddyDev.highlightRules = {}
WowBuddyDev.trinketItemID = nil
WowBuddyDev.extraValueRules = {}
WowBuddyDev.consumableItems = {}
local consumableCooldownStart = {}
local consumableStateKnown = false
local consumableByItemSpell = {}
local pendingItemDataIDs = {}
local trinketCooldownStart = nil
local lastTrinketCooldownDuration = nil
local lastCastTimeBySpell = {}
local cooldownEndBySpell = {}
local lastSucceededSpellID = nil
local lastSucceededCastGUID = nil
local lastSpellID = nil
local lastSucceededTime = 0
local succeededGeneration = 1
WowBuddyDev.playerSucceededGeneration = 1
WowBuddyDev.playerSucceededSpellID = 0
WowBuddyDev.forceAvailableState = {}
local healingStoneBlockedInCombat = false
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
  if applyTalentCooldownGates and (talentCooldownGates and talentCooldownGates[cooldownKey]) then
    applyTalentCooldownGates(talentCooldownGates)
  end
  local cooldownSeconds = tonumber(WowBuddyDev.cooldowns and WowBuddyDev.cooldowns[cooldownKey])
  if not cooldownSeconds or cooldownSeconds <= 0 then
    return
  end
  local castStartTime = tonumber(lastCastTimeBySpell[cooldownKey]) or GetTime()
  cooldownEndBySpell[cooldownKey] = castStartTime + cooldownSeconds
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
  consumableStateKnown = true
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
  consumableStateKnown = true
  consumableCooldownStart[consumableID] = nil
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
  consumableStateKnown = true
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
    consumableCooldownStart[consumable.id] = now - (cooldownSeconds - remainingSec)
    return true
  end
  consumableCooldownStart[consumable.id] = nil
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
  cooldownEndBySpell[cooldownKey] = nil
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
      lastCastTimeBySpell[cooldownKey] = sessionNow - (durationSec - remainingSec)
      cooldownEndBySpell[cooldownKey] = sessionNow + remainingSec
      return true, remainingSec
    end
    lastCastTimeBySpell[cooldownKey] = nil
    cooldownEndBySpell[cooldownKey] = nil
    ledger[cooldownKey] = nil
  else
    cooldownEndBySpell[cooldownKey] = nil
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
      lastCastTimeBySpell[k3] = nil
      cooldownEndBySpell[k3] = nil
      if ledger then
        ledger[k3] = nil
      end
    end
  end
  consumableCooldownStart[BURST_POTION_ID] = nil
  consumableStateKnown = true
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
  consumableByItemSpell = {}
  pendingItemDataIDs = {}
  for index2, consumableDef in ipairs(WowBuddyDev.consumableItems) do
    for index3, itemID in ipairs(consumableDef.itemIDs or {}) do
      local itemSpellID = nil
      pcall(function()
        if C_Item and C_Item.GetItemSpell then
          itemSpellID = select(2, C_Item.GetItemSpell(itemID))
        end
      end)
      if itemSpellID then
        consumableByItemSpell[itemSpellID] = consumableDef.id
      else
        pendingItemDataIDs[itemID] = true
        if C_Item and C_Item.RequestLoadItemDataByID then
          pcall(C_Item.RequestLoadItemDataByID, itemID)
        end
      end
    end
    if consumableDef.spellIDs then
      for index4, spellID in ipairs(consumableDef.spellIDs) do
        consumableByItemSpell[spellID] = consumableDef.id
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
      consumableByItemSpell[trinketSpellID] = "trinketCD"
    end
  end
end
-- 功能：物品数据到达后，如果这个物品正等着加载就重建反查表。
-- 入参：itemID 物品 ID；loadOK 取物品数据的保护调用是否成功（false 表示这次没取到）。
-- 出参：无。
-- 说明：这里的重建参数为假，表示只补数据、不新建表结构——事件回调里不该重新初始化缓存。
local function onItemDataLoaded(itemID, loadOK)
  if loadOK == false or not pendingItemDataIDs[itemID] then
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
  if consumable.id == "item_healing_stone" and (healingStoneBlockedInCombat and InCombatLockdown()) then
    return 601
  end
  if consumable.id == BURST_POTION_ID and not consumableStateKnown then
    restoreBurstPotionCooldown(consumable)
  end
  local cooldownStart = consumableCooldownStart[consumable.id]
  if cooldownStart then
    local remainingSeconds = consumable.cooldown - (GetTime() - cooldownStart)
    if remainingSeconds > 0 then
      -- 【改装】原来 math.ceil(remainingSeconds)
      return remainingSeconds
    end
    consumableCooldownStart[consumable.id] = nil
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
  if consumable.id == BURST_POTION_ID and not consumableStateKnown then
    restoreBurstPotionCooldown(consumable)
  end
  local cooldownStart = consumableCooldownStart[consumable.id]
  if cooldownStart then
    local remainingSeconds = consumable.cooldown - (GetTime() - cooldownStart)
    if remainingSeconds > 0 then
      -- 【改装】原来 math.ceil(remainingSeconds)
      return remainingSeconds
    end
    consumableCooldownStart[consumable.id] = nil
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
    cooldownEndBySpell = {}
    if applyTalentCooldownGates and WowBuddyDev.classData.talentCooldownGates then
      applyTalentCooldownGates(WowBuddyDev.classData.talentCooldownGates)
    end
    WowBuddyDev.actionAvailSpellIDs = WowBuddyDev.classData.actionAvailSpellIDs or {}
    forceAvailableRules = WowBuddyDev.classData.forceAvailableRules or {}
    WowBuddyDev.trinketItemID = WowBuddyDev.classData.trinketItemID
    WowBuddyDev.extraValueRules = WowBuddyDev.classData.extraValues or {}
    WowBuddyDev.consumableItems = WowBuddyDev.classData.consumableItems or {}
    consumableCooldownStart = {}
    consumableStateKnown = false
    trinketCooldownStart = nil
    lastTrinketCooldownDuration = nil
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
  cooldownEndBySpell = {}
  WowBuddyDev.actionAvailSpellIDs = {}
  forceAvailableRules = {}
  WowBuddyDev.forceAvailableState = {}
  WowBuddyDev.trinketItemID = nil
  WowBuddyDev.extraValueRules = {}
  WowBuddyDev.consumableItems = {}
  consumableCooldownStart = {}
  consumableStateKnown = false
  trinketCooldownStart = nil
  lastTrinketCooldownDuration = nil
  consumableByItemSpell = {}
  pendingItemDataIDs = {}
  return specID
end
local eventFrame = CreateFrame("Frame")
eventFrame:SetScript("OnEvent", function(self, event, castSource, castGUID, castSpellID)
  local spellID = resolveCooldownEventAlias(castSpellID)
  if castSource == "pet" and (spellID and WowBuddyDev.IsPetSpell(spellID)) then
    lastCastTimeBySpell[spellID] = GetTime()
    return
  end
  if castSource == "player" and castSpellID then
    local now4 = GetTime()
    local duplicateCast = false
    if castGUID then
      duplicateCast = castGUID == lastSucceededCastGUID
    else
      duplicateCast = lastSpellID == castSpellID and now4 - lastSucceededTime < .05
    end
    if not duplicateCast then
      succeededGeneration = succeededGeneration % 99 + 1
      lastSucceededCastGUID = castGUID
      lastSpellID = castSpellID
      lastSucceededTime = now4
      WowBuddyDev.playerSucceededSpellID = castSpellID
      WowBuddyDev.playerSucceededGeneration = succeededGeneration
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
    lastCastTimeBySpell[spellID] = now4
    recordPersistentCooldownStart(spellID)
    lastSucceededSpellID = castSpellID
    WowBuddyDev.lastCastSpellID = castSpellID
    local consumableID = consumableByItemSpell[castSpellID]
    if consumableID then
      if consumableID == "trinketCD" then
        trinketCooldownStart = now4
      else
        consumableCooldownStart[consumableID] = now4
        for index8, consumableDef in ipairs(WowBuddyDev.consumableItems or {}) do
          if consumableDef.id == consumableID then
            recordBurstPotionUse(consumableID, consumableDef.cooldown, now4)
            break
          end
        end
        if consumableID == "item_healing_stone" and InCombatLockdown() then
          healingStoneBlockedInCombat = true
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
  healingStoneBlockedInCombat = false
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
      if not cooldownEndBySpell[spellID] then
        applyLedgerEntryToRuntime(spellID)
      end
      local cooldownEnd = cooldownEndBySpell[spellID]
      if cooldownEnd then
        local remainingSec = cooldownEnd - GetTime()
        if remainingSec > 0 then
          -- 【改装】原来是 math.ceil(remainingSec)：把剩余时间向上取整成整秒，
          -- 于是后面的十分位编码只能拿到 90、89 这种整数值。改成返回原始小数。
          return remainingSec
        end
        lastCastTimeBySpell[spellID] = nil
        clearPersistentCooldownState(spellID)
        return 0
      end
    end
    local castStartTime = lastCastTimeBySpell[spellID] or 0
    if castStartTime == 0 then
      return 0
    end
    local remainingSec = WowBuddyDev.cooldowns[spellID] - (GetTime() - castStartTime)
    if remainingSec <= 0 then
      lastCastTimeBySpell[spellID] = nil
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
WowBuddyDev.lastCastTime = lastCastTimeBySpell
-- 功能：按当前已经点出的天赋门控修正技能冷却基准值。
-- 入参：gates 天赋门控表（每项含基础冷却和若干减冷却项）。
-- 出参：无（就地改写技能冷却表）。
-- 说明：每个技能的基础冷却可以叠加多个天赋的「减固定秒数」和「减百分比」，这里先算完再一次性四舍五入写回。只要有一个门控天赋查不出来（抛错或返回值不是布尔），就整体放弃这次修正：半套数据算出来的冷却会明显偏长，比不修正更糟。
applyTalentCooldownGates = function(gates)
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
    applyTalentCooldownGates(talentCooldownGates)
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
local castGenerationCounter = 1
local lastCastSpellID = nil
local lastCastKind = nil
WowBuddyDev.playerCastGeneration = 1
-- 功能：取玩家当前读条/引导状态，输出给像素编码用的四个值。
-- 入参：includeChannel 为 true 时才把「引导」也算作正在施法。
-- 出参：isCasting, 读条剩余十分位秒数, 读条技能 ID, 观测状态码。
-- 说明：观测状态码是一套诊断码，用来区分「没读条 / 正常 / 被秘密值挡住 / 缺少字段 / 派发异常」等不同情况，方便读取端判断这个值能不能信。无限客户端没有新版 castBarID 时，沿用同一接口里的 castID 或开始时间标识本次读条。
-- 说明2：按 12.x 的 UnitCastingInfo 签名，第 11 个返回值是 delayTimeMs（施法被推迟的累计毫秒），这一版没有解构它，所以读条时长里不含推迟量。
function WowBuddyDev.GetPlayerCastState(includeChannel)
  local isCasting = false
  local castRemainingTenths = 0
  local observedCastSpellID = 0
  local castObservationCode = 0
  local callOK = pcall(function()
    local castName, castText, castTexture, castStartMs, castEndMs, castIsTradeSkill, castID, castUninterruptible, castSpellID, castBarID = UnitCastingInfo("player")
    local castKind = "cast"
    if not castName and includeChannel == true then
      local channelName, channelText, channelTexture, channelStartMs, channelEndMs, channelIsTradeSkill, channelUninterruptible, channelSpellID, channelIsEmpowered, channelEmpowerStages, channelCastBarID = UnitChannelInfo("player")
      if channelName and channelIsEmpowered ~= true then
        castName = channelName
        castStartMs = channelStartMs
        castEndMs = channelEndMs
        castID = nil
        castSpellID = channelSpellID
        castBarID = channelCastBarID
        castKind = "channel"
      elseif channelName then
        if channelIsEmpowered == true then
          lastCastSpellID = nil
          lastCastKind = nil
          if issecretvalue and issecretvalue(channelSpellID) then
            castObservationCode = 19
          elseif type(channelSpellID) == "number" and (channelSpellID > 1 and (channelSpellID < 16777215 and channelSpellID % 1 == 0)) then
            observedCastSpellID = channelSpellID
            castObservationCode = 3
          else
            castObservationCode = 18
          end
          return
        end
      end
    end
    if not castName then
      lastCastSpellID = nil
      lastCastKind = nil
      return
    end
    if not castEndMs then
      WowBuddyDev.playerCastGeneration = 0
      castObservationCode = castKind == "channel" and 5 or 4
      return
    end
    if castName and castEndMs then
      if issecretvalue and issecretvalue(castEndMs) then
        WowBuddyDev.playerCastGeneration = 0
        castObservationCode = castKind == "channel" and 7 or 6
        return
      end
      local castRemainingSec = (castEndMs - GetTime() * 1000) / 1000
      if castRemainingSec > 0 then
        local castIdentity = castBarID
        if issecretvalue and issecretvalue(castIdentity) then
          castIdentity = nil
        end
        if type(castIdentity) ~= "number" and type(castIdentity) ~= "string" then
          castIdentity = castID
          if issecretvalue and issecretvalue(castIdentity) then
            castIdentity = nil
          end
        end
        if type(castIdentity) ~= "number" and type(castIdentity) ~= "string" then
          castIdentity = castStartMs
          if issecretvalue and issecretvalue(castIdentity) then
            castIdentity = nil
          end
        end
        if type(castIdentity) ~= "number" and type(castIdentity) ~= "string" then
          WowBuddyDev.playerCastGeneration = 0
          castObservationCode = castKind == "channel" and 11 or 10
          return
        end
        if castIdentity ~= lastCastSpellID or castKind ~= lastCastKind then
          castGenerationCounter = castGenerationCounter % 99 + 1
          lastCastSpellID = castIdentity
          lastCastKind = castKind
        end
        WowBuddyDev.playerCastGeneration = castGenerationCounter
        isCasting = true
        castRemainingTenths = math.floor(castRemainingSec * 10 + .5)
        if issecretvalue and issecretvalue(castSpellID) then
          castObservationCode = castKind == "channel" and 17 or 16
        elseif type(castSpellID) == "number" and (castSpellID > 1 and (castSpellID < 16777215 and castSpellID % 1 == 0)) then
          observedCastSpellID = castSpellID
          castObservationCode = castKind == "channel" and 2 or 1
        else
          castObservationCode = castKind == "channel" and 15 or 14
        end
      else
        castObservationCode = castKind == "channel" and 9 or 8
      end
    end
  end)
  if not callOK then
    WowBuddyDev.playerCastGeneration = 0
    castObservationCode = 20
  end
  return isCasting, castRemainingTenths, observedCastSpellID, castObservationCode
end
-- 功能：给外部读取端做「引导时间窗」判定：当前是否落在引导的某个百分比区间内。
-- 入参：spellID 期望的技能 ID；windowStartPercent 区间起点百分比；windowEndPercent 区间终点百分比。
-- 出参：是否在引导, 是否落在窗口内, 数据是否可读。
-- 说明：要求传入的技能 ID 和实际引导技能一致，否则直接不算。只要时间字段是秘密值或类型不对，就把「数据可读」置假返回，让读取端知道这次判定无效而不是误判成「不在窗口内」。区间是按引导总时长的百分比换算成绝对毫秒后和当前时间比较的。
function WowBuddyDev.GetPlayerChannelWindowState(spellID, windowStartPercent, windowEndPercent)
  local inWindow = false
  local isWindowOpen = false
  local valuesReadable = true
  local callOK = pcall(function()
    local channelName, channelText, channelTexture, channelStartMs, channelEndMs, channelIsTradeSkill, channelUninterruptible, channelSpellID, channelIsEmpowered = UnitChannelInfo("player")
    if not channelName then
      return
    end
    if issecretvalue and (issecretvalue(channelStartMs) or issecretvalue(channelEndMs) or issecretvalue(channelSpellID) or issecretvalue(channelIsEmpowered)) then
      valuesReadable = false
      return
    end
    if channelIsEmpowered == true then
      return
    end
    if type(channelSpellID) ~= "number" then
      valuesReadable = false
      return
    end
    if channelSpellID ~= spellID then
      return
    end
    inWindow = true
    if type(channelStartMs) ~= "number" or type(channelEndMs) ~= "number" or type(windowStartPercent) ~= "number" or type(windowEndPercent) ~= "number" or windowEndPercent <= 0 or windowStartPercent < 0 or windowStartPercent >= windowEndPercent or channelEndMs <= channelStartMs then
      valuesReadable = false
      return
    end
    local windowStartMs = channelStartMs + (channelEndMs - channelStartMs) * windowStartPercent / windowEndPercent
    local nowMs = GetTime() * 1000
    isWindowOpen = nowMs >= windowStartMs and nowMs < channelEndMs
  end)
  if not callOK then
    return false, false, false
  end
  return inWindow, isWindowOpen, valuesReadable
end
-- 功能：取「最近一次成功施法」的代次号和技能 ID，并做范围校验。
-- 入参：无。
-- 出参：代次号（1 到 99 的整数）, 技能 ID；不合法时对应项为 0。
-- 说明：这两个值要编码进颜色通道，通道容量有限，所以超出范围或非整数一律置 0 表示「本次无有效值」，而不是截断成一个假的 ID。
function WowBuddyDev.GetPlayerSucceededState()
  local generation = tonumber(WowBuddyDev.playerSucceededGeneration) or 0
  local spellID = tonumber(WowBuddyDev.playerSucceededSpellID) or 0
  if generation < 1 or generation > 99 or generation % 1 ~= 0 then
    generation = 0
  end
  if spellID <= 1 or spellID >= 16777215 or spellID % 1 ~= 0 then
    spellID = 0
  end
  return generation, spellID
end
local empowerGenerationCounter = 0
local activeEmpower = nil
local lastEmpowerOutcome = nil
local empowerSpellIDs = nil
local EMPOWER_OUTCOME_TTL_SEC = .35
-- 功能：在当前专精的蓄力技能列表里找「正在蓄力」的那一个。
-- 入参：无（列表由取蓄力状态时传入并缓存在本地）。
-- 出参：技能 ID；没有正在蓄力的返回 nil。
-- 说明：查询本身会抛错，所以逐个包保护调用；只要有一个命中就直接返回，不再继续查。
local function findCurrentEmpowerSpell()
  if type(empowerSpellIDs) ~= "table" or not C_Spell or type(C_Spell.IsCurrentSpell) ~= "function" then
    return nil
  end
  for index10, spellID in ipairs(empowerSpellIDs) do
    local callOK, isCurrent = pcall(function()
      return C_Spell.IsCurrentSpell(spellID) == true
    end)
    if callOK and isCurrent then
      return spellID
    end
  end
  return nil
end
-- 功能：把蓄力相关的施法事件统一解析成一条「蓄力事件」记录。
-- 入参：eventName 事件名；... 事件参数（蓄力层数、施法 GUID、1/0 标记、技能 ID 等）。
-- 出参：事件记录（技能 ID、施法 GUID、施法条 ID、是否成功）；无法识别的事件或参数全是秘密值时返回 nil。
-- 说明：不同事件的参数位置不一样，开始/停止/失败/被打断各自取不同位置的值，所以要按事件名分别取。所有参数都必须先过秘密值检查：当前客户端里读条相关字段可能是「秘密值」，插件既不能比较也不能存，只能整条丢弃，否则后续判断会报错。
local function parseEmpowerCastEvent(eventName, ...)
  local v200, v201, v202, v203, v204, v205 = ...
  return pcall(function()
    local rawCastBarID = nil
    local succeeded = nil
    if eventName == "UNIT_SPELLCAST_EMPOWER_START" then
      rawCastBarID = v203
    elseif eventName == "UNIT_SPELLCAST_EMPOWER_STOP" then
      if issecretvalue and issecretvalue(v203) then
        succeeded = false
      else
        succeeded = v203 == true
      end
      rawCastBarID = v205
    elseif eventName == "UNIT_SPELLCAST_FAILED" or eventName == "UNIT_SPELLCAST_FAILED_QUIET" then
      succeeded = false
      rawCastBarID = v203
    elseif eventName == "UNIT_SPELLCAST_INTERRUPTED" then
      succeeded = false
      rawCastBarID = v204
    else
      return nil
    end
    local castGUID = nil
    if not (issecretvalue and issecretvalue(v201)) and (type(v201) == "string" and v201 ~= "") then
      castGUID = v201
    end
    local castBarID = nil
    if not (issecretvalue and issecretvalue(rawCastBarID)) and type(rawCastBarID) == "number" then
      castBarID = rawCastBarID
    end
    if not castGUID and not castBarID then
      return nil
    end
    local spellID = nil
    if not (issecretvalue and issecretvalue(v202)) and (type(v202) == "number" and v202 > 1) then
      spellID = math.floor(v202)
    end
    if eventName == "UNIT_SPELLCAST_EMPOWER_START" and not spellID then
      spellID = findCurrentEmpowerSpell()
    end
    return { spellID = spellID, castGUID = castGUID, castBarID = castBarID, succeeded = succeeded }
  end)
end
-- 功能：判断两条蓄力事件记录说的是不是同一次施法（先比施法 GUID，再比施法条 ID）。
-- 入参：left 记录甲；right 记录乙。
-- 出参：true/false。
-- 说明：有些事件只给施法条 ID、不给施法 GUID，所以两个字段都要试；这正是「开始」事件能被后续「停止/失败」事件认出来的依据。
local function isSameCast(left, right)
  if left.castGUID and (right.castGUID and left.castGUID == right.castGUID) then
    return true
  end
  return left.castBarID and (right.castBarID and left.castBarID == right.castBarID)
end
local empowerEventFrame = CreateFrame("Frame")
empowerEventFrame:SetScript("OnEvent", function(self3, eventName, ...)
  local callOK, castEvent = parseEmpowerCastEvent(eventName, ...)
  if not callOK or type(castEvent) ~= "table" then
    return
  end
  if eventName == "UNIT_SPELLCAST_EMPOWER_START" then
    if activeEmpower and isSameCast(activeEmpower, castEvent) then
      if not activeEmpower.spellID then
        activeEmpower.spellID = castEvent.spellID
      end
      return
    end
    empowerGenerationCounter = empowerGenerationCounter % 99 + 1
    activeEmpower = { spellID = castEvent.spellID, castGUID = castEvent.castGUID, castBarID = castEvent.castBarID, generation = empowerGenerationCounter }
    lastEmpowerOutcome = nil
    return
  end
  if not activeEmpower or not isSameCast(activeEmpower, castEvent) then
    return
  end
  if castEvent.spellID then
    if activeEmpower.spellID and activeEmpower.spellID ~= castEvent.spellID then
      return
    end
    activeEmpower.spellID = castEvent.spellID
  end
  lastEmpowerOutcome = {
    spellID = activeEmpower.spellID,
    generation = activeEmpower.generation,
    succeeded = castEvent.succeeded == true,
    expiresAt = GetTime() + EMPOWER_OUTCOME_TTL_SEC,
  }
  activeEmpower = nil
end)
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_EMPOWER_START", "player")
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_EMPOWER_STOP", "player")
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_FAILED", "player")
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_FAILED_QUIET", "player")
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_INTERRUPTED", "player")
-- 功能：判断技能 ID 是否在给定列表里。
-- 入参：spellList 技能 ID 列表；spellID 待查技能 ID。
-- 出参：true/false。
local function isSpellIDInList(spellList, spellID)
  for index11, listedSpellID in ipairs(spellList) do
    if listedSpellID == spellID then
      return true
    end
  end
  return false
end
-- 功能：取玩家当前的蓄力状态：技能 ID、已经完成的蓄力层数、本次蓄力要读的总层数。
-- 入参：spellIDs 当前专精的蓄力技能 ID 列表。
-- 出参：技能 ID, 已完成层数, 总层数。
-- 说明：先看最近一次蓄力结果是否还在有效期内、且技能在本次列表里，命中就直接用记录（客户端在蓄力结束瞬间读不到当前技能，只能靠事件补）。否则再逐个问客户端当前施法。层数只能从逐层时长对象上反推：对象带秘密值或查询抛错就无法确定，这时退回「已完成层数 0」，但仍把总层数告诉读取端。
-- 说明2：引导的第 9、10 个返回值分别是 isEmpowered（是否蓄力）和 numEmpowerStages（蓄力层数），这两个字段是 NeverSecret 的，所以能用；同函数里对它们做了 issecretvalue 兜底只是因为客户端不同版本行为不一致。
function WowBuddyDev.GetPlayerEmpowerState(spellIDs)
  if type(spellIDs) ~= "table" then
    return 1, 0, 0
  end
  empowerSpellIDs = spellIDs
  if lastEmpowerOutcome then
    if GetTime() > lastEmpowerOutcome.expiresAt then
      lastEmpowerOutcome = nil
    elseif isSpellIDInList(spellIDs, lastEmpowerOutcome.spellID) then
      local outcomeBase = lastEmpowerOutcome.succeeded and 100 or 200
      return lastEmpowerOutcome.spellID, outcomeBase + lastEmpowerOutcome.generation, 0
    end
  end
  if not C_Spell or type(C_Spell.IsCurrentSpell) ~= "function" then
    return 1, 0, 0
  end
  local currentSpellID = 0
  for index12, spellID in ipairs(spellIDs) do
    local callOK, isCurrent = pcall(function()
      return C_Spell.IsCurrentSpell(spellID) == true
    end)
    if not callOK then
      return 1, 0, 0
    end
    if isCurrent then
      currentSpellID = spellID
      break
    end
  end
  if currentSpellID > 0 and (activeEmpower and not activeEmpower.spellID) then
    activeEmpower.spellID = currentSpellID
  end
  if not UnitChannelInfo then
    return currentSpellID > 0 and currentSpellID or 1, 0, 0
  end
  local callOK, isEmpowered, stagesToRead = pcall(function()
    local v212, v213, v214, v215, v216, v217, v218, v219, channelIsEmpowered, channelEmpowerStages = UnitChannelInfo("player")
    if channelIsEmpowered ~= true then
      return false, 0
    end
    if issecretvalue and issecretvalue(channelEmpowerStages) then
      return true, 0
    end
    return true, math.floor(tonumber(channelEmpowerStages) or 0)
  end)
  if not callOK then
    return currentSpellID > 0 and currentSpellID or 1, 0, 0
  end
  if not isEmpowered then
    return currentSpellID, 0, 0
  end
  if currentSpellID == 0 then
    return 1, 0, 0
  end
  if stagesToRead < 1 or not UnitEmpoweredStageDurations then
    return currentSpellID, 0, 0
  end
  local callOK, stageDurations = pcall(UnitEmpoweredStageDurations, "player")
  if not callOK or type(stageDurations) ~= "table" or #stageDurations < stagesToRead then
    return currentSpellID, 0, stagesToRead
  end
  local callOK, completedStages = pcall(function()
    local completedStages = 0
    for i3 = 1, stagesToRead, 1 do
      local stageDuration = stageDurations[i3]
      if not stageDuration or stageDuration:HasSecretValues() then
        return nil
      end
      if not stageDuration:HasExpired() then
        break
      end
      completedStages = i3
    end
    return completedStages
  end)
  if not callOK or type(completedStages) ~= "number" then
    return currentSpellID, 0, stagesToRead
  end
  return currentSpellID, completedStages, stagesToRead
end
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
  if trinketCooldownStart and lastTrinketCooldownDuration then
    local remainingSec = lastTrinketCooldownDuration - (GetTime() - trinketCooldownStart)
    if remainingSec > 0 then
      -- 【改装】原来 math.ceil(remainingSec)
      return remainingSec
    end
    trinketCooldownStart = nil
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
          lastTrinketCooldownDuration = trinketCooldownDuration
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
WowBuddyDev.LANG = nil
WowBuddyDev._spellNameToID = WowBuddyDev._spellNameToID or {}
local CHINESE_SPELL_NAME_TO_ID = {
  ["狂风怒号"] = 454015,
  ["能量灌注"] = 10060,
  ["氤氲之雾"] = 124682,
  ["复苏之雾"] = 119611,
  ["活血术"] = 116670,
  ["清创生血"] = 115450,
  ["还魂术"] = 115310,
  ["治疗链"] = 1064,
  ["治疗波"] = 331,
  ["激流"] = 61295,
  ["召唤宠物 1"] = 883,
  ["复活宠物"] = 982,
  ["治疗宠物"] = 136,
}
for k7, spellID in pairs(CHINESE_SPELL_NAME_TO_ID) do
  if not WowBuddyDev._spellNameToID[k7] then
    WowBuddyDev._spellNameToID[k7] = spellID
  end
end
-- 功能：把插件内部用的中文技能名翻成当前客户端语言的技能名。
-- 入参：chineseName 中文技能名。
-- 出参：本地化技能名；查不到就原样返回入参。
-- 说明：中文客户端直接用原文，不走查表。查表链路是「中文名 → 技能 ID → 客户端语言名」，中间任何一步查不到都退回原文——退回原文比返回空串安全，至少界面上还有东西可显示。
function WowBuddyDev.L(chineseName)
  if WowBuddyDev.IsChineseClient() then
    return chineseName
  end
  local englishName = WowBuddyDev._localeEN[chineseName]
  if englishName then
    return englishName
  end
  local spellID = WowBuddyDev._spellNameToID and WowBuddyDev._spellNameToID[chineseName]
  local englishName = spellID and getSpellInfo(spellID)
  return englishName or chineseName
end
-- 功能：把动作键名翻成给人看的标签。
-- 入参：actionKey 动作键名；fallbackLabel 兜底标签。
-- 出参：显示用标签。
-- 说明：中文客户端直接用兜底标签。饰品冷却键要用饰品物品名（更直观），其余动作试着从键名里抠出技能 ID 再取技能名，最后才查固定标签表，全都不中才退回兜底标签。
function WowBuddyDev.LocalizeActionLabel(actionKey, fallbackLabel)
  if WowBuddyDev.IsChineseClient() then
    return fallbackLabel
  end
  if actionKey == "trinketCD" and WowBuddyDev.trinketItemID then
    local trinketItemName = C_Item and (C_Item.GetItemInfo and C_Item.GetItemInfo(WowBuddyDev.trinketItemID))
    if trinketItemName then
      return trinketItemName
    end
  end
  if tostring(actionKey):match("_nearest$") or tostring(actionKey):match("_six_line$") or actionKey == "spell_5143_chain" or actionKey == "spell_44425_stopcasting" or actionKey == "spell_475" or actionKey == "spell_51886" then
    return WowBuddyDev.L(fallbackLabel)
  end
  local spellID = tonumber(tostring(actionKey):match("spell_(%d+)") or tostring(actionKey):match("cd_(%d+)") or tostring(actionKey):match("seq_(%d+)"))
  local spellName = spellID and getSpellInfo(spellID)
  if spellName then
    return spellName
  end
  local FOCUS_LABELS_EN = {
    focus_player = "Focus: Self",
    focus_party1 = "Focus: Party 1",
    focus_party2 = "Focus: Party 2",
    focus_party3 = "Focus: Party 3",
    focus_party4 = "Focus: Party 4",
    focus_mouseover = "Focus: Mouseover",
    focus_interrupt = "Focus Interrupt",
    focus_eruption = "Focus Eruption",
  }
  return FOCUS_LABELS_EN[actionKey] or WowBuddyDev.L(fallbackLabel)
end
-- 功能：取客户端语言代码。
-- 入参：无。
-- 出参：语言代码字符串；接口不可用时给英文。
function WowBuddyDev.GetClientLocale()
  return GetLocale and GetLocale() or "enUS"
end
-- 功能：判断当前是不是中文客户端。
-- 入参：无。
-- 出参：true/false。
-- 说明：允许外部先写死语言标记来强制指定，标记没设时才按客户端语言判断。简体和繁体都算中文。
function WowBuddyDev.IsChineseClient()
  if WowBuddyDev.LANG == "zh" then
    return true
  end
  if WowBuddyDev.LANG == "en" then
    return false
  end
  local locale = WowBuddyDev.GetClientLocale()
  return locale == "zhCN" or locale == "zhTW"
end
-- 功能：把宏体里的中文技能名替换成当前客户端语言的技能名。
-- 入参：macroBody 宏体文本。
-- 出参：替换后的宏体。
-- 说明：逐行解析宏命令，只处理施法和取消光环两种命令，并且保留原有的中括号条件段——条件里的技能名同样要翻译，否则条件会失配。认不出的行原样保留。
function WowBuddyDev.LocalizeMacroBody(macroBody)
  if not macroBody or macroBody == "" then
    return macroBody
  end
  if WowBuddyDev.IsChineseClient() then
    return macroBody
  end
  local macroLines = { strsplit("\n", macroBody) }
  for index13, macroLine in ipairs(macroLines) do
    local command, condition, argument = macroLine:match("^(/%a+)%s*(%b[])%s*(.+)$")
    if not command then
      command, argument = macroLine:match("^(/%a+)%s+(.+)$")
      condition = nil
    end
    if command and argument then
      command = command:lower()
      if command == "/cast" or command == "/cancelaura" then
        argument = argument:gsub("^%s+", ""):gsub("%s+$", "")
        local spellID = WowBuddyDev._spellNameToID[argument]
        if spellID then
          local englishName = getSpellInfo(spellID)
          if englishName then
            if condition then
              macroLines[index13] = command .. " " .. condition .. " " .. englishName
            else
              macroLines[index13] = command .. " " .. englishName
            end
          end
        end
      end
    end
  end
  return table.concat(macroLines, "\n")
end
-- 功能：取某个动作的默认宏体。
-- 入参：actionKey 动作键名。
-- 出参：宏体字符串；取不到给空串。
-- 说明：职业模块登记过默认宏就用它，否则从动作键里抠出技能 ID 拼一条简单施法宏。返回空串而不是 nil，是因为调用方会直接拿它去比字符串。
function WowBuddyDev.GetDefaultMacro(actionKey)
  local macroBody
  if WowBuddyDev.GetClassDefaultMacro and WowBuddyDev.classData then
    local key = (WowBuddyDev.classData.ACTION_TO_KEY or {})[actionKey]
    macroBody = key and WowBuddyDev.GetClassDefaultMacro(key)
    if macroBody then
      return WowBuddyDev.LocalizeMacroBody(macroBody)
    end
  end
  if WowBuddyDev.classData and (WowBuddyDev.classData.DEFAULT_MACROS and WowBuddyDev.classData.DEFAULT_MACROS[actionKey]) then
    macroBody = WowBuddyDev.classData.DEFAULT_MACROS[actionKey]
  else
    local spellID = tonumber(actionKey:match("spell_(%d+)") or actionKey:match("cd_(%d+)"))
    if not spellID then
      return ""
    end
    local englishName = getSpellInfo(spellID)
    return englishName and "/cast " .. englishName or ""
  end
  return WowBuddyDev.LocalizeMacroBody(macroBody)
end
WowBuddyDev.errorLogs = {}
-- 功能：往插件错误日志里追加一条，并刷新日志界面。
-- 入参：logType 类型；message 内容。
-- 出参：无。
-- 说明：新记录插到最前面，最多保留一批，超出就丢最老的，避免长时间运行把内存吃满。
function WowBuddyDev.AddErrorLog(logType, message)
  local timeText = date("%H:%M:%S")
  table.insert(WowBuddyDev.errorLogs, 1, { time = timeText, type = logType, message = message })
  while #WowBuddyDev.errorLogs > 50 do
    table.remove(WowBuddyDev.errorLogs)
  end
  if WowBuddyDev.RefreshErrorLog then
    WowBuddyDev.RefreshErrorLog()
  end
end
-- 功能：取错误日志列表。
-- 入参：无。
-- 出参：日志表（内部表本身，调用方不要改）。
function WowBuddyDev.GetErrorLogs()
  return WowBuddyDev.errorLogs
end
-- 功能：清空错误日志并刷新界面。
-- 入参：无。
-- 出参：无。
function WowBuddyDev.ClearErrorLogs()
  wipe(WowBuddyDev.errorLogs)
  if WowBuddyDev.RefreshErrorLog then
    WowBuddyDev.RefreshErrorLog()
  end
end
local secureButtons = {}
local macroBindingRegistry = {}
local macroBindingErrors = {}
WowBuddyDev.macroBindingBackend = "ZZHELPER"
local NUMPAD_KEY_ALIASES = { NUMPADADD = "NUMPADPLUS", NUMPADSUBTRACT = "NUMPADMINUS" }
-- 功能：把按键字符串规范化：取出修饰键、统一大小写、把小键盘别名换成标准名，最后按固定顺序拼回修饰键。
-- 入参：key 原始按键字符串。
-- 出参：规范化后的按键字符串。
-- 说明：客户端不同来源的按键写法不一致（大小写、修饰键顺序、小键盘两套名字），不统一就会出现「同一个键被当成两个键」，导致按键判定和冲突检测漏判。
local function normalizeBindingKey(key)
  if type(key) ~= "string" then
    return key
  end
  local normalizedKey = key:match("^%s*(.-)%s*$"):upper()
  local hasAlt = normalizedKey:find("ALT%-") ~= nil
  local hasCtrl = normalizedKey:find("CTRL%-") ~= nil
  local hasShift = normalizedKey:find("SHIFT%-") ~= nil
  normalizedKey = normalizedKey:gsub("ALT%-", ""):gsub("CTRL%-", ""):gsub("SHIFT%-", "")
  normalizedKey = NUMPAD_KEY_ALIASES[normalizedKey] or normalizedKey
  return (hasAlt and "ALT-" or "") .. (hasCtrl and "CTRL-" or "") .. (hasShift and "SHIFT-" or "") .. normalizedKey
end
local overrideOwnerFrame = CreateFrame("Frame", "WowBuddyDevOverrideOwner")
local applyingMacroBindings = false
local bindingRefreshScheduled = false
local function reportMacroBindingError(actionKey, message)
  message = tostring(message)
  if macroBindingErrors[actionKey] == message then
    return
  end
  macroBindingErrors[actionKey] = message
  WowBuddyDev.AddErrorLog("MacroBinding", tostring(actionKey) .. ": " .. message)
end
WowBuddyDev.ReportMacroBindingError = reportMacroBindingError
-- 功能：建（或复用）一个安全按钮，并按当前配置给它设置好点击行为。
-- 入参：actionKey 动作键；bindingKey 绑定的按键；macroBody 要执行的宏体。
-- 出参：true 成功；false 表示战斗中延后处理。
-- 说明：采用 ZZHELPER Layout.lua 的隐藏宏按钮方式，每个按钮拥有自己的覆写绑定。
function WowBuddyDev.CreateSecureButton(actionKey, bindingKey, macroBody)
  if InCombatLockdown() then
    overrideOwnerFrame.pendingMacroBindings = true
    return false
  end
  local normalizedKey = normalizeBindingKey(bindingKey)
  if WowBuddyDev.GetClassBindingAction then
    actionKey = WowBuddyDev.GetClassBindingAction(actionKey, normalizedKey)
  end
  assert(type(actionKey) == "string" and actionKey ~= "", "Invalid action key")
  assert(type(normalizedKey) == "string" and normalizedKey ~= "", "Invalid binding key")
  assert(macroBody == nil or type(macroBody) == "string", "Invalid macro text")
  local buttonName = "WBD_BTN_" .. actionKey
  local secureButton = secureButtons[actionKey]
  if not secureButton then
    secureButton = CreateFrame("Button", buttonName, UIParent, "SecureActionButtonTemplate")
    secureButton:SetSize(30, 30)
    secureButton:SetPoint("TOPLEFT", UIParent, "BOTTOMRIGHT", 1, -1)
    secureButton:RegisterForClicks("AnyDown", "AnyUp")
    secureButton:Show()
    secureButtons[actionKey] = secureButton
  end
  ClearOverrideBindings(secureButton)
  macroBindingRegistry[actionKey] = nil
  secureButton:SetAttribute("spell", nil)
  secureButton:SetAttribute("unit", nil)
  secureButton:SetAttribute("type", "macro")
  secureButton:SetAttribute("macrotext", macroBody or "")
  local ok, result = pcall(SetOverrideBindingClick, secureButton, true, normalizedKey, buttonName, "LeftButton")
  if not ok or result == false then
    local message = ok and "SetOverrideBindingClick rejected binding" or result
    reportMacroBindingError(actionKey, message)
    error(message, 0)
  end
  macroBindingRegistry[actionKey] = {
    key = normalizedKey, buttonName = buttonName, macroText = macroBody or "",
  }
  macroBindingErrors[actionKey] = nil
  return true
end
-- 功能：按动作键取回它的安全按钮对象。
-- 入参：actionKey 动作键。
-- 出参：按钮对象；取不到时返回 nil。
-- 说明：给需要往按钮上挂硬件事件钩子的模块用（如自动选目标的执行回执）。
--       按钮在 CreateFrame 时带了全局名，所以登记表里查不到也能按名字兜回来。
function WowBuddyDev.GetSecureButton(actionKey)
  if type(actionKey) ~= "string" or actionKey == "" then
    return nil
  end
  local button = secureButtons[actionKey]
  if button then
    return button
  end
  return _G["WBD_BTN_" .. actionKey]
end
-- 功能：建（或复用）一个安全按钮，用于把焦点设到指定单位。
-- 入参：actionKey 动作键；bindingKey 绑定的按键；unit 目标单位。
-- 出参：true 成功；false 表示战斗中延后处理。
-- 说明：焦点切换也使用隐藏宏按钮，保留单位存在条件。
function WowBuddyDev.CreateSecureFocusButton(actionKey, bindingKey, unit)
  assert(type(unit) == "string" and unit:match("^%w+$"), "Invalid focus unit")
  return WowBuddyDev.CreateSecureButton(actionKey, bindingKey, "/focus [@" .. unit .. ",exists]")
end
-- 功能：全局重刷宏的总入口——把所有动作键重新写成安全按钮绑定。
-- 入参：无。
-- 出参：无。
-- 说明：战斗中改绑定会被客户端拒绝，所以直接记下 pendingMacroBindings 标记，等 PLAYER_REGEN_ENABLED 再重刷。宏体里带 `spell:数字` 的一律丢弃并改回默认宏——这种缩写宏已经不能用，留着只会刷出无效按钮。每个动作键单独包 pcall 创建，某个键失败不影响其余按键；职业模块的团队焦点、自动选目标绑定和按键冲突缓存也在这里一起刷新。
ApplyMacros_Internal = function()
  if InCombatLockdown() then
    overrideOwnerFrame.pendingMacroBindings = true
    return
  end
  overrideOwnerFrame.pendingMacroBindings = nil
  migrateChijiMacro()
  ClearOverrideBindings(overrideOwnerFrame)
  -- Per-button owners must all be cleared when the specialization changes.
  for _, button in pairs(secureButtons) do
    ClearOverrideBindings(button)
    button:SetAttribute("type", nil)
    button:SetAttribute("macrotext", nil)
  end
  wipe(macroBindingRegistry)
  wipe(macroBindingErrors)
  local hasClassMacros = false
  if WowBuddyDev.ApplyClassMacros then
    local ok, result = pcall(WowBuddyDev.ApplyClassMacros)
    hasClassMacros = ok and result
    if not ok then
      reportMacroBindingError("class", result)
    end
  end
  for k8, boundKey in pairs(WowBuddyDev.ACTION_TO_KEY or {}) do
    local macroBody = WowBuddyDev.GetDefaultMacro(k8)
    local isUserEdited, userMacroBody = WowBuddyDev.GetUserMacro(k8)
    if isUserEdited then
      macroBody = userMacroBody
    end
    if macroBody and macroBody:find("spell:%d+") then
      macroBody = nil
      isUserEdited = false
    end
    if not isUserEdited and (not macroBody or macroBody == "") then
      macroBody = WowBuddyDev.GetDefaultMacro(k8)
    end
    if not hasClassMacros or isUserEdited then
      local callOK, callErr = pcall(WowBuddyDev.CreateSecureButton, k8, boundKey, macroBody)
      if not callOK then
        reportMacroBindingError(k8, callErr)
      end
    end
  end
  if WowBuddyDev.ApplyRaidFocusBindings then
    local ok, err = pcall(WowBuddyDev.ApplyRaidFocusBindings)
    if not ok then reportMacroBindingError("raid_focus", err) end
  end
  if WowBuddyDev.ApplyAutoTargetBinding then
    local ok, err = pcall(WowBuddyDev.ApplyAutoTargetBinding)
    if not ok then reportMacroBindingError("auto_target", err) end
  end
  if WowBuddyDev.InvalidateControlBindingConflicts then
    WowBuddyDev.InvalidateControlBindingConflicts()
  end
end
-- 功能：安全地重刷所有安全按钮的宏绑定（整体包一层保护调用）。
-- 入参：无。
-- 出参：无。
-- 说明：记录绑定失败，并阻止刷新期间的 UPDATE_BINDINGS 递归调度。
refreshMacroBindings = function()
  if applyingMacroBindings then
    return
  end
  applyingMacroBindings = true
  local callOK, callErr = pcall(ApplyMacros_Internal)
  applyingMacroBindings = false
  if not callOK then
    reportMacroBindingError("refresh", callErr)
  end
end
WowBuddyDev.RefreshMacroBindings = refreshMacroBindings
overrideOwnerFrame:RegisterEvent("UPDATE_BINDINGS")
overrideOwnerFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
overrideOwnerFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
overrideOwnerFrame:SetScript("OnEvent", function(self4, eventName)
  if eventName == "UPDATE_BINDINGS" then
    if applyingMacroBindings or bindingRefreshScheduled then
      return
    end
    bindingRefreshScheduled = true
    C_Timer.After(0, function()
      bindingRefreshScheduled = false
      refreshMacroBindings()
    end)
  elseif eventName == "PLAYER_ENTERING_WORLD" then
    for index14, delaySec in ipairs({ 3, 6, 9 }) do
      C_Timer.After(delaySec, function()
        refreshMacroBindings()
      end)
    end
  elseif eventName == "PLAYER_REGEN_ENABLED" and self4.pendingMacroBindings then
    refreshMacroBindings()
  end
end)
function WowBuddyDev.CheckMacroBindings()
  local passed, total = 0, 0
  local failures = {}
  local activeBindings = {}
  for actionKey, entry in pairs(macroBindingRegistry) do
    local button = secureButtons[actionKey]
    if GetBindingAction(entry.key, true) == "CLICK " .. entry.buttonName .. ":LeftButton"
        and button:GetAttribute("type") == "macro"
        and button:GetAttribute("macrotext") == entry.macroText then
      activeBindings[entry.key] = entry
    end
  end
  for actionKey, entry in pairs(macroBindingRegistry) do
    total = total + 1
    local button = secureButtons[actionKey]
    local expected = "CLICK " .. entry.buttonName .. ":LeftButton"
    local actual = GetBindingAction(entry.key, true) or ""
    -- Cooldown and spell actions can intentionally share a key and macro.
    local alias = activeBindings[entry.key]
    local matches = actual == expected or (alias and alias.macroText == entry.macroText)
    if matches and button:GetAttribute("type") == "macro"
        and button:GetAttribute("macrotext") == entry.macroText then
      passed = passed + 1
    else
      failures[#failures + 1] = actionKey .. " (" .. entry.key .. "): " .. actual
    end
  end
  for actionKey in pairs(WowBuddyDev.ACTION_TO_KEY or {}) do
    local registeredAction = actionKey
    if WowBuddyDev.GetClassBindingAction then
      registeredAction = WowBuddyDev.GetClassBindingAction(actionKey, WowBuddyDev.ACTION_TO_KEY[actionKey])
    end
    if not macroBindingRegistry[registeredAction] then
      total = total + 1
      failures[#failures + 1] = actionKey .. ": " .. (macroBindingErrors[actionKey] or "not bound")
    end
  end
  for _, key in ipairs(WowBuddyDev.GetClassMacroKeys and WowBuddyDev.GetClassMacroKeys() or {}) do
    if not macroBindingRegistry["class_" .. key] then
      total = total + 1
      failures[#failures + 1] = key .. ": class macro not bound"
    end
  end
  for actionKey, message in pairs(macroBindingErrors) do
    if not (WowBuddyDev.ACTION_TO_KEY or {})[actionKey] then
      failures[#failures + 1] = actionKey .. ": " .. message
    end
  end
  if overrideOwnerFrame.pendingMacroBindings then
    failures[#failures + 1] = "pending combat end"
  end
  if total == 0 then
    failures[#failures + 1] = "no actions registered"
  end
  table.sort(failures)
  return #failures == 0, passed, total, failures
end
SLASH_PMBIND1 = "/pmbind"
SlashCmdList.PMBIND = function()
  local ok, passed, total, failures = WowBuddyDev.CheckMacroBindings()
  print(string.format("[WowBuddyDev] ZZHELPER bindings: %d/%d %s", passed, total, ok and "OK" or "FAILED"))
  if WowBuddyDev.GetClassMacroInfo then
    local classToken, slotCount = WowBuddyDev.GetClassMacroInfo()
    if classToken then
      print(string.format("[WowBuddyDev] %s: %d slots", classToken, slotCount))
    end
  end
  for _, message in ipairs(failures) do
    print("[WowBuddyDev] " .. message)
  end
end
do
  local SENSITIVE_ACTIONS = { "TOGGLESOUND", "TOGGLEMUSIC", "TOGGLEAMBIENCE", "TOGGLEUI" }
  local sensitiveBindingFrame = CreateFrame("Frame")
  local retryPending = false
  -- 功能：把带 Ctrl/Alt/Shift 修饰的系统功能键解绑并记进存档，避免和插件的功能键抢键。
  -- 入参：无。
  -- 出参：无。
  -- 说明：只处理带修饰键的绑定，普通绑定是玩家的常用键不动。解绑前先把原绑定记进存档（按战网账号或角色 GUID 分桶），方便以后还原。战斗中不能改绑定，这时只置一个待办标记，出战斗再补做。
  local function removeSensitiveBindings()
    if InCombatLockdown() then
      retryPending = true
      return
    end
    retryPending = false
    if not WowBuddyDev.DB then
      return
    end
    local bindingSet = GetCurrentBindingSet()
    if bindingSet ~= 1 and bindingSet ~= 2 then
      return
    end
    local ledgerScope = bindingSet == 1 and "account" or UnitGUID("player")
    if not ledgerScope then
      return
    end
    local removedAny = false
    for index15, sensitiveAction in ipairs(SENSITIVE_ACTIONS) do
      local bindingContext = C_KeyBindings.GetBindingContextForAction(sensitiveAction)
      local boundKeys = { GetBindingKey(sensitiveAction, nil, bindingContext) }
      for k9, boundKey in pairs(boundKeys) do
        if type(boundKey) == "string" and ((boundKey:find("^CTRL%-") or boundKey:find("^ALT%-") or boundKey:find("^SHIFT%-")) and GetBindingAction(boundKey, nil, bindingContext) == sensitiveAction) then
          local removedSensitiveBindings = WowBuddyDev.DB.removedSensitiveBindings or {}
          WowBuddyDev.DB.removedSensitiveBindings = removedSensitiveBindings
          removedSensitiveBindings[ledgerScope] = removedSensitiveBindings[ledgerScope] or {}
          local bindingRecordKey = tostring(bindingContext) .. ":" .. boundKey
          removedSensitiveBindings[ledgerScope][bindingRecordKey] = removedSensitiveBindings[ledgerScope][bindingRecordKey] or { key = boundKey, action = sensitiveAction, context = bindingContext }
          if SetBinding(boundKey, nil, bindingContext) then
            removedAny = true
          end
        end
      end
    end
    if removedAny then
      SaveBindings(bindingSet)
    end
  end
  sensitiveBindingFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
  sensitiveBindingFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
  sensitiveBindingFrame:SetScript("OnEvent", function(self5, eventName)
    if eventName == "PLAYER_ENTERING_WORLD" or retryPending then
      pcall(removeSensitiveBindings)
    end
  end)
end
-- 功能：注册一个职业模块，并把它的默认宏和标签登记进「技能名反查表」。
-- 入参：classFile 职业文件名；classData 职业模块数据表。
-- 出参：无。
-- 说明：反查表是给「中文技能名 → 技能 ID」用的，所以从默认宏里解析施法命令、从动作标签和像素字段里逐条登记。只登记新键、不覆盖已有值，避免后面的职业模块把先前登记的正确 ID 冲掉。如果注册的正是当前专精所属职业，就立刻重载职业数据、重刷绑定并重建像素条——职业文件是在登录后才注册的，所以这一跳是必须的。
function WowBuddyDev.RegisterClass(classFile, classData)
  WowBuddyDev.classes[classFile] = classData
  if classData.DEFAULT_MACROS then
    for k10, macroBody in pairs(classData.DEFAULT_MACROS) do
      local spellID = tonumber(k10:match("spell_(%d+)") or k10:match("cd_(%d+)") or k10:match("seq_(%d+)"))
      if spellID and type(macroBody) == "string" then
        local isFirstCast = true
        for k11 in gmatch(macroBody, "[^\n]+") do
          local castTarget = k11:match("^/cast%s+%b[]%s*(.+)$")
          if not castTarget then
            castTarget = k11:match("^/cast%s+(.+)$")
          end
          if castTarget and castTarget ~= "" then
            castTarget = castTarget:gsub("^%s+", ""):gsub("%s+$", "")
            if castTarget ~= "" and (isFirstCast and not WowBuddyDev._spellNameToID[castTarget]) then
              WowBuddyDev._spellNameToID[castTarget] = spellID
            end
            isFirstCast = false
          else
            if not k11:match("^/cast") then

            end
          end
        end
      end
    end
  end
  if classData.pixelData then
    for index16, pixelField in ipairs(classData.pixelData) do
      if pixelField.spellID and (pixelField.label and not WowBuddyDev._spellNameToID[pixelField.label]) then
        WowBuddyDev._spellNameToID[pixelField.label] = pixelField.spellID
      end
    end
  end
  if classData.ACTION_LABELS then
    for k12, label in pairs(classData.ACTION_LABELS) do
      local spellID = tonumber(k12:match("spell_(%d+)") or k12:match("cd_(%d+)") or k12:match("seq_(%d+)"))
      if spellID and (label and not WowBuddyDev._spellNameToID[label]) then
        WowBuddyDev._spellNameToID[label] = spellID
      end
    end
  end
  if IsLoggedIn and IsLoggedIn() then
    local currentSpecID = select(3, WowBuddyDev.GetPlayerClassSpec())
    if currentSpecID == classFile then
      reloadClassData()
      refreshMacroBindings()
      WowBuddyDev.RebuildPixelBars()
      if WowBuddyDev.RefreshDockButtonColors then
        WowBuddyDev.RefreshDockButtonColors()
      end
    end
  end
end
local coreEventFrame = CreateFrame("Frame")
local specChangeTimerGeneration = 0
-- 功能：延迟一小段时间再检查专精是否变化，并用代次号去掉重复触发。
-- 入参：无。
-- 出参：无。
-- 说明：切专精时相关事件会连发好几次，延迟加代次号保证只有最后一次真正生效，避免重复重建界面和宏绑定。
local function scheduleSpecChangeCheck()
  if not (C_Timer and C_Timer.After) then
    return
  end
  specChangeTimerGeneration = specChangeTimerGeneration + 1
  local specChangeTimerToken = specChangeTimerGeneration
  C_Timer.After(.3, function()
    if specChangeTimerToken ~= specChangeTimerGeneration then
      return
    end
    WowBuddyDev.CheckSpecChange()
  end)
end
local errorSpeechFrame = CreateFrame("Frame")
errorSpeechFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
errorSpeechFrame:SetScript("OnEvent", function()
  pcall(SetCVar, "Sound_EnableErrorSpeech", "0")
  if UIErrorsFrame then
    pcall(UIErrorsFrame.UnregisterEvent, UIErrorsFrame, "UI_ERROR_MESSAGE")
  end
end)
-- 功能：取玩家职业和专精信息。
-- 入参：无。
-- 出参：职业文件名, 专精序号, 专精 ID, 专精名。
-- 说明：职业名拿不到时给固定的未知标记，专精名拿不到时给本地化的「未知」，保证调用方拿到的永远是非空可比较的值。
function WowBuddyDev.GetPlayerClassSpec()
  local className, classFile = UnitClass("player")
  local specIndex = GetSpecialization and GetSpecialization() or 0
  local specID, specName = nil, nil
  if specIndex and (specIndex > 0 and GetSpecializationInfo) then
    specID, specName = GetSpecializationInfo(specIndex)
  end
  if WowBuddyDev.GetForeverSpecDisplayName then
    specName = WowBuddyDev.GetForeverSpecDisplayName(specID, specName)
  end
  return classFile or "UNKNOWN", specIndex or 0, specID or 0, specName or WowBuddyDev.L("未知")
end
-- 功能：判断当前专精职责是不是治疗。
-- 入参：无。
-- 出参：true/false。
-- 说明：无限每职业只有 1 个 specID，三系靠天赋加点区分，客户端的
--       GetSpecializationRole 只会返回该职业唯一专精的固定职责，反映不了玩家
--       实际点了哪一系（1487 牧师既可能是神圣治疗也可能是暗影输出）。
--       所以先问 ForeverCompat 的天赋主系职责表；拿不到（低于 10 级未解锁天赋、
--       天赋 API 缺失、正式服客户端）才退回客户端职责。
function WowBuddyDev.IsHealingSpec()
  if WowBuddyDev.GetForeverSpecRole then
    local foreverRole = WowBuddyDev.GetForeverSpecRole()
    if foreverRole then
      return foreverRole == "HEALER"
    end
  end
  local specIndex = GetSpecialization and GetSpecialization() or 0
  if specIndex <= 0 or not GetSpecializationRole then
    return false
  end
  return GetSpecializationRole(specIndex) == "HEALER"
end
-- 功能：判断当前专精是不是防护骑士。
-- 入参：无。
-- 出参：true/false。
-- 说明：防骑的自动选目标开关是独立设置，所以要单独识别出来。
--       无限圣骑 specID 恒为 1486，`GetSpecializationInfo(idx) == 66` 永不成立，
--       必须由 ForeverCompat 按天赋主系判定（主修防护 → TANK）。
local function isProtectionPaladin()
  if WowBuddyDev.IsForeverProtectionPaladin then
    return WowBuddyDev.IsForeverProtectionPaladin() == true
  end
  local specIndex = GetSpecialization and GetSpecialization() or 0
  if specIndex <= 0 or not GetSpecializationInfo then
    return false
  end
  return GetSpecializationInfo(specIndex) == 66
end
-- 功能：取当前专精的自动选目标开关（治疗、防骑、其它各有一份独立设置）。
-- 入参：无。
-- 出参：true/false。
function WowBuddyDev.GetAutoTargetEnabled()
  if WowBuddyDev.IsHealingSpec() then
    return WowBuddyDev.DB.healerAutoTarget == true
  end
  if isProtectionPaladin() then
    return WowBuddyDev.DB.protectionPaladinAutoTarget == true
  end
  return WowBuddyDev.DB.autoTarget == true
end
-- 功能：写当前专精的自动选目标开关。
-- 入参：enabled 目标状态。
-- 出参：无。
function WowBuddyDev.SetAutoTargetEnabled(enabled)
  if WowBuddyDev.IsHealingSpec() then
    WowBuddyDev.DB.healerAutoTarget = enabled == true
  elseif isProtectionPaladin() then
    WowBuddyDev.DB.protectionPaladinAutoTarget = enabled == true
  else
    WowBuddyDev.DB.autoTarget = enabled == true
  end
end
local MELEE_SPEC_IDS = {
  [1491] = true,
  [250] = true,
  [251] = true,
  [252] = true,
  [577] = true,
  [581] = true,
  [103] = true,
  [104] = true,
  [255] = true,
  [268] = true,
  [269] = true,
  [66] = true,
  [70] = true,
  [259] = true,
  [260] = true,
  [261] = true,
  [263] = true,
  [71] = true,
  [72] = true,
  [73] = true,
}
-- 功能：判断当前专精是不是近战专精。
-- 入参：无。
-- 出参：true/false。
-- 说明：专精信息取不到时按近战处理——近战分支更保守（依赖距离判断），比按远程处理安全。
--       无限优先走天赋主系职责表（MELEE/TANK 都算近战：坦克必然贴身），
--       因为一张写死正式服 ID 的白名单在无限上必然漏判 —— 例如无限潜行者 1488
--       不在下面的 MELEE_SPEC_IDS 里，会被当成远程，自动选目标随之走错分支。
function WowBuddyDev.IsMeleeSpec()
  if WowBuddyDev.GetForeverSpecRole then
    local foreverRole = WowBuddyDev.GetForeverSpecRole()
    if foreverRole then
      return foreverRole == "MELEE" or foreverRole == "TANK"
    end
  end
  local specIndex = GetSpecialization and GetSpecialization() or 0
  if specIndex <= 0 or not GetSpecializationInfo then
    return true
  end
  return MELEE_SPEC_IDS[GetSpecializationInfo(specIndex) or 0] == true
end
-- 功能：判断某个技能是不是「当前专精（天赋主系）」的。
-- 入参：spellID 技能 ID；允许 nil（表示这不是技能，如切焦点 / 自动攻击）。
-- 出参：true 显示 / false 隐藏。
-- 说明：给「按键页 + 调试浮层只列当前专精的技能」用（都由 IsActionOfCurrentSpec /
--       IsSpellOfCurrentSpec 统一判定，避免两处口径漂移）。判据三层，越靠前越权威：
--         1) 天赋树上的技能 —— ForeverSpecSpells 由 tools/build_forever_spec_spells.py
--            从 pinned DB2 生成（TraitNode 的 PosX 分区 -> 系，用 SkillLineAbility 交叉校过）。
--            这类归属明确，只看当前主系在不在它的系列表里。
--         2) 天赋树上没有的（训练师通用技能，如圣光术、力量祝福）—— 没有系别归属，
--            改用「学会了没有」兜底：没学会的技能摆个按键也按不出来。
--            ★ 不能拿 SkillLineAbility.SkillLine 给这类技能定系 —— 它只是「技能线」，
--            不是专精专属（例：力量祝福的线是惩戒 184，但神圣/防护骑士照样在用）。
--         3) 表缺失 / 天赋读不到（未加点、缺 Traits API、非本职业）—— 一律放行：
--            宁可多显示，也不能把正常按键整片藏没。
function WowBuddyDev.IsSpellOfCurrentSpec(spellID)
  if not spellID then
    return true
  end
  local specID = WowBuddyDev.DB and tonumber(WowBuddyDev.DB.currentSpecID)
  local specSpells = specID and WowBuddyDev.ForeverSpecSpells and WowBuddyDev.ForeverSpecSpells[specID]
  if not specSpells then
    return true
  end
  local groups = specSpells[spellID]
  if groups then
    if type(WowBuddyDev.GetForeverTalentState) ~= "function" then
      return true
    end
    local okState, state = pcall(WowBuddyDev.GetForeverTalentState, specID)
    local mainIndex = okState and type(state) == "table" and state.readable and state.mainIndex or nil
    if type(mainIndex) ~= "number" or mainIndex <= 0 then
      return true
    end
    for _, group in ipairs(groups) do
      if group == mainIndex then
        return true
      end
    end
    return false
  end
  local okKnown, known = pcall(WowBuddyDev.IsSpellKnown, spellID)
  if not okKnown or known == nil then
    return true
  end
  return known and true or false
end
-- 功能：从动作键名里取出它对应的技能 ID。
-- 入参：actionKey 动作键，如 spell_635 / spell_633_focus / cd_633 / seq_1234。
-- 出参：技能 ID；focus_player / start_attack 这类非技能动作返回 nil。
-- 说明：前缀口径与 RegisterClass 注册职业宏时用的完全一致（spell_/cd_/seq_）。
--       不能图省事抓字符串里第一个数字 —— focus_party1 的 1 会被误当成技能 ID，
--       结果是「切焦点按键」被按队友 1 的技能归属过滤掉。
local function actionSpellID(actionKey)
  if type(actionKey) ~= "string" then
    return nil
  end
  return tonumber(actionKey:match("spell_(%d+)"))
      or tonumber(actionKey:match("cd_(%d+)"))
      or tonumber(actionKey:match("seq_(%d+)"))
end
-- 功能：判断一个动作键是不是当前专精的。
-- 入参：actionKey 动作键。
-- 出参：true 显示 / false 隐藏；非技能动作（切焦点、自动攻击）一律放行。
function WowBuddyDev.IsActionOfCurrentSpec(actionKey)
  return WowBuddyDev.IsSpellOfCurrentSpec(actionSpellID(actionKey))
end
-- 功能：取当前专精的职责。
-- 入参：无。
-- 出参："HEALER"/"TANK"/"MELEE"/"RANGED"/"DAMAGER"；取不到返回 nil。
-- 说明：统一入口。无限优先用 ForeverCompat 的天赋主系职责表（能区分同一职业
--       的不同系），拿不到才退回客户端 GetSpecializationRole。
--       客户端那套返回值在正式服是 DAMAGER/HEALER/TANK，不含近战/远程之分，
--       所以调用方若要区分远程，必须叠加 IsMeleeSpec()。
function WowBuddyDev.GetSpecRole()
  if WowBuddyDev.GetForeverSpecRole then
    local foreverRole = WowBuddyDev.GetForeverSpecRole()
    if foreverRole then
      return foreverRole
    end
  end
  local specIndex = GetSpecialization and GetSpecialization() or 0
  if specIndex <= 0 or not GetSpecializationRole then
    return nil
  end
  return GetSpecializationRole(specIndex)
end
-- 功能：判断当前专精是不是远程输出。
-- 入参：无。
-- 出参：true/false。
-- 说明：先要求职责是输出，再排除近战专精，两个条件都成立才算远程输出。
--       职责走统一入口：无限上客户端 role 反映不了天赋主系（暗影牧会被报成
--       HEALER），必须用天赋职责表才判得准。
function WowBuddyDev.IsRangedDamageSpec()
  local role = WowBuddyDev.GetSpecRole()
  if not role then
    return false
  end
  if role == "HEALER" or role == "TANK" then
    return false
  end
  return not WowBuddyDev.IsMeleeSpec()
end
-- 功能：安全调用一个「单位 → 布尔」的客户端接口，把结果收敛成 true / false / nil。
-- 入参：apiFunc 要调用的函数（可为 nil，此时视为不可用）；... 透传给它的参数。
-- 出参：true / false / nil（接口缺失、抛错、或返回秘密值/非布尔值时给 nil）。
-- 说明：★ 本函数存在的唯一理由 —— 副本里 target 可能是受保护单位、或返回带「秘密值」
--       标记的布尔（12.x 客户端机制），这种值直接参与 and/or/not 运算会当场抛错。
--       IsAutoTargetGateOpen 的调用方是 PixelBar 的每帧渲染，那一层没有 pcall 兜底，
--       所以异常会一路冒到插件外层，表现为「进副本选中目标就报错弹窗」。
--       这里一律吃掉异常并返回 nil（= 读不到），调用方按「不冒进」处理。
local function callUnitBoolSafe(apiFunc, ...)
  if type(apiFunc) ~= "function" then
    return nil
  end
  local ok, value = pcall(apiFunc, ...)
  if not ok then
    return nil
  end
  if issecretvalue then
    local secretOk, isSecret = pcall(issecretvalue, value)
    if not secretOk or isSecret == true then
      return nil
    end
  end
  if value == true then
    return true
  end
  if value == false then
    return false
  end
  return nil
end
-- 功能：综合判断「现在能不能自动选目标」。
-- 入参：enemyCount 附近敌人数量。
-- 出参：true/false。
-- 说明：治疗鼠标指向了需要治疗的友方时优先放行。自动选目标开启时，输出和坦克职责在战斗中走远程专用判定；不在战斗中则要求已有可攻击目标。自动选目标关闭时，只允许近战在确实有敌人时放行——这样停手状态下不会乱选目标。
-- 说明2：单位接口一律走 callUnitBoolSafe。判定阈值从「非 false 即真」收紧成「必须显式为
--        true / false」—— 读不到（秘密值、受保护、接口缺失）时按不满足处理，宁可不放行，
--        也不要因为一个读不到的值就冒进放行。这与 AutoTarget.lua 的 hasAttackableTarget 同口径。
function WowBuddyDev.IsAutoTargetGateOpen(enemyCount)
  if WowBuddyDev.IsHealingSpec() and (type(WowBuddyDev.HasHealingNpcMouseover) == "function" and WowBuddyDev.HasHealingNpcMouseover()) then
    return true
  end
  local autoTargetEnabled = WowBuddyDev.GetAutoTargetEnabled()
  if autoTargetEnabled then
    local specIndex = GetSpecialization and GetSpecialization() or 0
    local specRole = specIndex > 0 and (GetSpecializationRole and GetSpecializationRole(specIndex))
    local isDamageOrTank = specRole == "DAMAGER" or specRole == "TANK"
    if not isDamageOrTank or callUnitBoolSafe(UnitAffectingCombat, "player") == true then
      if WowBuddyDev.IsRangedDamageSpec() then
        return WowBuddyDev.IsRemoteAutoTargetGateOpen()
      end
      return true
    end
  end
  local hasHostileTarget = callUnitBoolSafe(UnitExists, "target") == true and (callUnitBoolSafe(UnitIsDeadOrGhost, "target") == false and callUnitBoolSafe(UnitCanAttack, "player", "target") == true)
  if hasHostileTarget then
    return true
  end
  return not autoTargetEnabled and (WowBuddyDev.IsMeleeSpec() and (tonumber(enemyCount) or 0) >= 1)
end
-- 功能：取当前英雄天赋专精 ID。
-- 入参：无。
-- 出参：英雄天赋专精 ID；接口不可用或返回异常值时为 nil。
-- 说明：接口本身会抛错，所以包保护调用，并且对返回值的类型和合理范围都做校验——英雄天赋专精 ID 会被编码进像素通道，非法值必须先挡掉。
function WowBuddyDev.GetActiveHeroTalentSpecID()
  if not C_ClassTalents or type(C_ClassTalents.GetActiveHeroTalentSpec) ~= "function" then
    return nil
  end
  local callOK, heroSpecID = pcall(C_ClassTalents.GetActiveHeroTalentSpec)
  if not callOK or type(heroSpecID) ~= "number" or heroSpecID <= 0 or heroSpecID >= 4096 then
    return nil
  end
  return heroSpecID
end
-- 功能：把专精 ID 和英雄天赋专精 ID 打包成一个整数，供读取端一次拿到两个身份。
-- 入参：无。
-- 出参：打包后的整数；专精 ID 非法时返回 nil。
-- 说明：专精 ID 有效而英雄天赋无效时只返回专精 ID（不做打包），让读取端能区分「老客户端没有英雄天赋」和「有英雄天赋」两种情况。
function WowBuddyDev.GetPackedGameIdentity()
  local specID = WowBuddyDev.DB and WowBuddyDev.DB.currentSpecID or nil
  local heroSpecID = WowBuddyDev.DB and WowBuddyDev.DB.currentHeroSpecID or nil
  if type(specID) ~= "number" or specID <= 0 or specID >= 4096 then
    return nil
  end
  if type(heroSpecID) ~= "number" or heroSpecID <= 0 or heroSpecID >= 4096 then
    return specID
  end
  return specID * 4096 + heroSpecID
end
-- 功能：把当前职业和专精信息写进存档。
-- 入参：无。
-- 出参：无。
-- 说明：写存档既是为了让外部读取端拿到当前专精，也是为了下次登录能直接取用；同时把英雄天赋专精一起记下来，供切换判断使用。
local function saveCurrentSpecInfo()
  local className, specIndex, specID, specName = WowBuddyDev.GetPlayerClassSpec()
  WowBuddyDev.DB.currentClass = className
  WowBuddyDev.DB.currentSpecIndex = specIndex
  WowBuddyDev.DB.currentSpecID = specID
  WowBuddyDev.DB.currentSpecName = specName
  WowBuddyDev.DB.currentHeroSpecID = WowBuddyDev.GetActiveHeroTalentSpecID()
end
-- 功能：检查专精或英雄天赋专精是否变化，变化了就重载职业数据、重刷绑定并刷新相关设置界面。
-- 入参：无。
-- 出参：当前专精 ID。
-- 说明：两个维度分开判断，但都变化时只重载一次职业数据，避免重复重建界面。只有专精变化才需要重刷绑定和设置界面，英雄天赋变化只更新记录——英雄天赋只影响数值，不影响按键布局。
function WowBuddyDev.CheckSpecChange()
  local v298, v299, specID = WowBuddyDev.GetPlayerClassSpec()
  local heroSpecID = WowBuddyDev.GetActiveHeroTalentSpecID()
  local specChanged = specID and specID ~= lastSpecID
  local heroSpecChanged = heroSpecID ~= lastHeroSpecID
  -- Forever's class ID stays the same when talent points change.
  if not specChanged and not heroSpecChanged then saveCurrentSpecInfo() end
  if specChanged or heroSpecChanged then
    lastSpecID = specID
    lastHeroSpecID = heroSpecID
    saveCurrentSpecInfo()
    if specChanged then
      local newSpecID = reloadClassData()
      if newSpecID then
        WowBuddyDev.RebuildPixelBars()
        refreshMacroBindings()
      end
      if WowBuddyDev.RefreshBurstAutoCloseSettingUI then
        WowBuddyDev.RefreshBurstAutoCloseSettingUI()
      end
      if WowBuddyDev.RefreshAutoTargetSettingUI then
        WowBuddyDev.RefreshAutoTargetSettingUI()
      end
      if WowBuddyDev.RefreshControlKeySettingUI then
        WowBuddyDev.RefreshControlKeySettingUI()
      end
      WowBuddyDev.ResetBurstAutoCloseTimer()
    end
  end
  return specID
end
local focusCastUnreachableUntil = 0
local spellFailedAt = 0
local uiErrorAt = 0
local uiErrorKind = nil
local failedGUIDTracked = false
local lastFailedCastGUID = nil
local lastFailedCastAt = 0
local recentCastGUIDs = {}
local recentCastGUIDOrder = {}
local RECENT_CAST_GUID_LIMIT = 64
local FOCUS_PAIR_MAX_SKEW_SEC = .6
local FOCUS_UNREACHABLE_HOLD_SEC = .3
local GLOBAL_ERROR_MESSAGES = {
  { "SPELL_FAILED_OUT_OF_RANGE", "range" },
  { "SPELL_FAILED_LINE_OF_SIGHT", "los" },
  { "ERR_OUT_OF_RANGE", "range" },
}
local ERROR_TEXT_BY_LOCALE = {
  zhCN = { { "距离太远", "range" }, { "目标不在射程内", "range" }, { "目标不在视野中", "los" } },
  enUS = { { "Out of range", "range" }, { "Target not in line of sight", "los" } },
  enGB = { { "Out of range", "range" }, { "Target not in line of sight", "los" } },
}
-- 功能：把界面报错文本归类成「距离」或「视野」问题。
-- 入参：errorText 报错文本。
-- 出参：问题类别；认不出来返回 nil。
-- 说明：先比对全局常量的当前语言文本，再按客户端语言查内置文本表。之所以两步走：同一类报错的实际文案随语言不同，硬编码一种语言的文字在别的客户端会完全失配。
local function classifyErrorText(errorText)
  if type(errorText) ~= "string" then
    return false
  end
  for index17, errorEntry in ipairs(GLOBAL_ERROR_MESSAGES) do
    local globalErrorText = rawget(_G, errorEntry[1])
    if type(globalErrorText) == "string" and errorText == globalErrorText then
      return errorEntry[2]
    end
  end
  local localeErrorMessages = ERROR_TEXT_BY_LOCALE[GetLocale() or ""]
  for index18, messageEntry in ipairs(localeErrorMessages or {}) do
    if errorText == messageEntry[1] then
      return messageEntry[2]
    end
  end
  return nil
end
-- 功能：清空「施法失败 + 界面报错」配对用的全部状态。
-- 入参：无。
-- 出参：无。
-- 说明：专精或天赋变化时必须清，否则上一套专精残留的配对时间会和新专精的事件错配，误报治疗落空。
function WowBuddyDev.ClearFocusHealFailurePair()
  spellFailedAt = 0
  uiErrorAt = 0
  uiErrorKind = nil
  failedGUIDTracked = false
  lastFailedCastGUID = nil
  lastFailedCastAt = 0
  for k13 in pairs(recentCastGUIDs) do
    recentCastGUIDs[k13] = nil
  end
  for i7 = #recentCastGUIDOrder, 1, -1 do
    recentCastGUIDOrder[i7] = nil
  end
end
-- 功能：记住一个最近失败过的施法 GUID，用于去重。
-- 入参：castGUID 施法 GUID。
-- 出参：true 表示是新记下的；false 表示已经记过或入参无效。
-- 说明：用「集合 + 队列」两个结构，超过上限就按插入顺序淘汰最老的，防止长时间游戏后这张表无限增长。
local function rememberCastGUID(castGUID)
  if not castGUID or recentCastGUIDs[castGUID] then
    return false
  end
  recentCastGUIDs[castGUID] = true
  recentCastGUIDOrder[#recentCastGUIDOrder + 1] = castGUID
  if #recentCastGUIDOrder > RECENT_CAST_GUID_LIMIT then
    local evictedCastGUID = table.remove(recentCastGUIDOrder, 1)
    recentCastGUIDs[evictedCastGUID] = nil
  end
  return true
end
-- 功能：如果「施法失败」和「界面报错」挨得很近，就判定成一次治疗落空并上报。
-- 入参：now 当前时间。
-- 出参：true 表示这次配对成功并已上报；false 表示没配上或已作废。
-- 说明：两个独立信号（技能失败事件、界面报错）在很短时间内出现，才认定为「真的因为超距或卡视野没打出去」。两侧时间差超过容差就丢弃，并且只清掉较早的那一侧，避免把两次无关事件错配成一次；配对成功后两侧状态一起清空，防止同一次失败被重复上报。
local function tryPairFocusHealFailure(now)
  if spellFailedAt <= 0 or uiErrorAt <= 0 or not uiErrorKind then
    return false
  end
  local failureSkewSec = spellFailedAt - uiErrorAt
  if math.abs(failureSkewSec) >= FOCUS_PAIR_MAX_SKEW_SEC then
    if failureSkewSec < 0 then
      spellFailedAt = 0
      failedGUIDTracked = false
    else
      uiErrorAt = 0
      uiErrorKind = nil
    end
    return false
  end
  focusCastUnreachableUntil = now + FOCUS_UNREACHABLE_HOLD_SEC
  local uiErrorKindSnapshot = uiErrorKind
  local failedGUIDTrackedSnapshot = failedGUIDTracked
  spellFailedAt = 0
  uiErrorAt = 0
  uiErrorKind = nil
  failedGUIDTracked = false
  if failedGUIDTrackedSnapshot and (WowBuddyDev.IsRaidFocusFeedbackEnabled and WowBuddyDev.RecordRaidFocusFeedback) then
    pcall(function()
      if WowBuddyDev.IsRaidFocusFeedbackEnabled() then
        WowBuddyDev.RecordRaidFocusFeedback(uiErrorKindSnapshot)
      end
    end)
  end
  return true
end
-- 功能：判断现在是否处于「焦点施法够不到」的保持窗口内。
-- 入参：无。
-- 出参：true/false。
-- 说明：配对成功后要压制一小段时间，避免同一次落空被后续事件重复触发。
function WowBuddyDev.GetFocusCastUnreachable()
  return GetTime() < focusCastUnreachableUntil
end
-- 功能：核心事件分发：游戏冷却重置、物品数据到达、施法失败、界面报错、专精与天赋变化、分辨率与缩放变化。
-- 入参：eventFrame 事件帧；eventName 事件名；... 事件参数。
-- 出参：无。
-- 说明：施法失败要先做 GUID 去重（同一 GUID 短时间内只处理一次），因为客户端会把一次失败报多次；报错文案要先自己归类，再和施法失败的时间配对来判断治疗是否落空。
local function onCoreEvent(eventFrame, eventName, ...)
  if shouldResetCooldownsOnEvent(eventName, ...) then
    WowBuddyDev.ClearPersistentCooldownsForGameReset()
  elseif eventName == "GET_ITEM_INFO_RECEIVED" then
    onItemDataLoaded(...)
  elseif eventName == "UNIT_SPELLCAST_FAILED" then
    local unit, failedCastGUID, failedSpellID = ...
    if unit == "player" then
      if WowBuddyDev.classData and WowBuddyDev.classData.OnSpellCastFailed then
        WowBuddyDev.classData.OnSpellCastFailed(failedSpellID, consumableByItemSpell[failedSpellID])
      end
      local healFocusSpellIDs = WowBuddyDev.classData and WowBuddyDev.classData.HEAL_FOCUS_SPELL_IDS
      if healFocusSpellIDs then
        pcall(function()
          if failedSpellID and healFocusSpellIDs[failedSpellID] then
            local now5 = GetTime()
            if failedCastGUID ~= lastFailedCastGUID or now5 - lastFailedCastAt > .5 then
              lastFailedCastGUID = failedCastGUID
              lastFailedCastAt = now5
              local castGUID = nil
              if not (issecretvalue and issecretvalue(failedCastGUID)) and (type(failedCastGUID) == "string" and failedCastGUID ~= "") then
                castGUID = failedCastGUID
              end
              failedGUIDTracked = rememberCastGUID(castGUID)
              spellFailedAt = now5
              tryPairFocusHealFailure(now5)
            end
          end
        end)
      end
    end
  elseif eventName == "UI_ERROR_MESSAGE" then
    local errorType, errorText = ...
    if errorText then
      pcall(function()
        local failureKind = classifyErrorText(errorText)
        if failureKind then
          local now6 = GetTime()
          uiErrorAt = now6
          uiErrorKind = failureKind
          tryPairFocusHealFailure(now6)
        end
      end)
    end
  elseif eventName == "ACTIVE_TALENT_GROUP_CHANGED" or eventName == "ACTIVE_PLAYER_SPECIALIZATION_CHANGED" or eventName == "TRAIT_CONFIG_UPDATED" or eventName == "PLAYER_TALENT_UPDATE" or eventName == "SPELLS_CHANGED" then
    WowBuddyDev.ClearFocusHealFailurePair()
    WowBuddyDev.CheckSpecChange()
    scheduleSpecChangeCheck()
  elseif eventName == "DISPLAY_SIZE_CHANGED" or eventName == "UI_SCALE_CHANGED" then
    if WowBuddyDev.RebuildPixelBars then
      WowBuddyDev.RebuildPixelBars()
    end
  end
end
-- 功能：逐条注册核心事件，注册前先确认客户端认识这个事件。
-- 入参：eventFrame 事件帧。
-- 出参：无。
-- 说明：不同客户端版本的事件名有增删，直接注册未知事件会报错，所以先用事件工具接口过滤一遍。
local function registerCoreEvents(eventFrame)
  eventFrame:RegisterUnitEvent("UNIT_SPELLCAST_FAILED", "player")
  local resetEvents = {
    "ACTIVE_TALENT_GROUP_CHANGED",
    "ACTIVE_PLAYER_SPECIALIZATION_CHANGED",
    "TRAIT_CONFIG_UPDATED",
    "PLAYER_TALENT_UPDATE",
    "SPELLS_CHANGED",
    "GET_ITEM_INFO_RECEIVED",
    "CHALLENGE_MODE_START",
    "ENCOUNTER_END",
    "DISPLAY_SIZE_CHANGED",
    "UI_SCALE_CHANGED",
    "UI_ERROR_MESSAGE",
  }
  for index19, eventName in ipairs(resetEvents) do
    local isEventValid = true
    if C_EventUtils and type(C_EventUtils.IsEventValid) == "function" then
      local callOK, eventIsValid = pcall(C_EventUtils.IsEventValid, eventName)
      isEventValid = callOK and eventIsValid == true
    end
    if isEventValid then
      eventFrame:RegisterEvent(eventName)
    end
  end
end
coreEventFrame:SetScript("OnEvent", function(self6, eventName, ...)
  if eventName == "ADDON_LOADED" then
    local loadedAddonName = ...
    if loadedAddonName == addonName then
      WowBuddyDev.InitDB()
    end
  elseif eventName == "PLAYER_LOGIN" then
    WowBuddyDev.InitDB()
    saveCurrentSpecInfo()
    lastSpecID = select(3, WowBuddyDev.GetPlayerClassSpec())
    lastHeroSpecID = WowBuddyDev.DB.currentHeroSpecID
    reloadClassData()
    WowBuddyDev.ResetBurstAutoCloseTimer()
    refreshMacroBindings()
    WowBuddyDev.RebuildPixelBars()
    if WowBuddyDev.RefreshDockButtonColors then
      WowBuddyDev.RefreshDockButtonColors()
    end
    self6:UnregisterEvent("PLAYER_LOGIN")
    self6:SetScript("OnEvent", onCoreEvent)
    registerCoreEvents(self6)
  else
    onCoreEvent(self6, eventName, ...)
  end
end)
if IsLoggedIn() then
  WowBuddyDev.InitDB()
  saveCurrentSpecInfo()
  C_Timer.After(0, function()
    lastSpecID = select(3, WowBuddyDev.GetPlayerClassSpec())
    lastHeroSpecID = WowBuddyDev.DB.currentHeroSpecID
    reloadClassData()
    WowBuddyDev.ResetBurstAutoCloseTimer()
    refreshMacroBindings()
    if WowBuddyDev.RebuildPixelBars then
      WowBuddyDev.RebuildPixelBars()
    end
    if WowBuddyDev.RefreshDockButtonColors then
      WowBuddyDev.RefreshDockButtonColors()
    end
  end)
  coreEventFrame:SetScript("OnEvent", onCoreEvent)
  registerCoreEvents(coreEventFrame)
else
  coreEventFrame:RegisterEvent("ADDON_LOADED")
  coreEventFrame:RegisterEvent("PLAYER_LOGIN")
end
do
  local cachedActionToKey, cachedActionKeyOrder, cachedGetRaidFocusKeys, cachedRaidFocusEnabled
  local keyOwners = {}
  -- 功能：作废「按键归属」缓存，下次查询时重建。
  -- 入参：无。
  -- 出参：无。
  -- 说明：职业数据或动作键表换过之后必须调一次，否则冲突检测会拿着上一套按键表的结果，把撞键判断错。
  function WowBuddyDev.InvalidateControlBindingConflicts()
    cachedActionToKey = nil
  end
  -- 功能：查某个按键被谁占用了（普通动作键还是团队焦点键）。
  -- 入参：key 按键字符串。
  -- 出参：占用方类型（"action" 动作键 / "raid" 团队焦点键）和它的序号；空按键或没人占用时返回 nil。
  -- 说明：整张归属表按「动作键表、按键顺序表、GetRaidFocusKeys、团队焦点是否开启」四个引用做缓存，四者都没变就不重建——这个函数在按键检测里调用很频繁，每次重建会很费。普通动作键优先登记，团队焦点键和它撞车时不会覆盖它。
  function WowBuddyDev.GetControlBindingConflict(key)
    if not key or key == "" then
      return nil
    end
    local raidFocusEnabled = WowBuddyDev.classData and WowBuddyDev.classData.raidFocusEnabled == true or false
    if cachedActionToKey ~= WowBuddyDev.ACTION_TO_KEY or cachedActionKeyOrder ~= WowBuddyDev.ACTION_KEY_ORDER or cachedGetRaidFocusKeys ~= WowBuddyDev.GetRaidFocusKeys or cachedRaidFocusEnabled ~= raidFocusEnabled then
      keyOwners = {}
      for _, boundKey in ipairs(WowBuddyDev.GetClassMacroKeys and WowBuddyDev.GetClassMacroKeys() or {}) do
        keyOwners[WowBuddyDev.NormalizeActionKey(boundKey)] = { "action", boundKey }
      end
      for k14, boundKey in pairs(WowBuddyDev.ACTION_TO_KEY or {}) do
        keyOwners[WowBuddyDev.NormalizeActionKey(boundKey)] = { "action", k14 }
      end
      if raidFocusEnabled and WowBuddyDev.GetRaidFocusKeys then
        for index20, raidFocusKey in ipairs(WowBuddyDev.GetRaidFocusKeys()) do
          local normalizedKey = WowBuddyDev.NormalizeActionKey(raidFocusKey)
          if not keyOwners[normalizedKey] then
            keyOwners[normalizedKey] = { "raid", index20 }
          end
        end
      end
      cachedActionToKey = WowBuddyDev.ACTION_TO_KEY
      cachedActionKeyOrder = WowBuddyDev.ACTION_KEY_ORDER
      cachedGetRaidFocusKeys = WowBuddyDev.GetRaidFocusKeys
      cachedRaidFocusEnabled = raidFocusEnabled
    end
    local keyOwner = keyOwners[WowBuddyDev.NormalizeActionKey(key)]
    if keyOwner then
      return keyOwner[1], keyOwner[2]
    end
  end
end
WowBuddyDev.waitingForKey = nil
WowBuddyDev.masterKeyPressed = false
WowBuddyDev.burstKeyPressed = false
-- 功能：判断某个绑定名的按键此刻是不是真的按着（含修饰键状态校验）。
-- 入参：key 绑定名字符串，如 "SHIFT-BUTTON1"、"F1"。
-- 出参：true/false。
-- 说明：修饰键按严格相等比对——要求按住 Shift 时，没按或按了别的修饰键都算没按。主开关/爆发/群体这三个键如果和别人撞了绑定，直接返回 false，避免一次按键触发两套功能。鼠标键走 IsMouseButtonDown，键盘键走 IsKeyDown；旧客户端没有 IsKeyDown 时一律返回 false。
function WowBuddyDev.IsBindPressed(key)
  if not key or key == "" then
    return false
  end
  local db = WowBuddyDev.DB
  if db and ((key == db.masterKey or key == db.burstKey or key == db.aoeKey) and WowBuddyDev.GetControlBindingConflict(key)) then
    return false
  end
  local normalizedKey = key
  local needsShift, needsCtrl, needsAlt = false, false, false
  if normalizedKey:find("SHIFT%-") then
    needsShift = true
    normalizedKey = normalizedKey:gsub("SHIFT%-", "")
  end
  if normalizedKey:find("CTRL%-") then
    needsCtrl = true
    normalizedKey = normalizedKey:gsub("CTRL%-", "")
  end
  if normalizedKey:find("ALT%-") then
    needsAlt = true
    normalizedKey = normalizedKey:gsub("ALT%-", "")
  end
  local shiftDown = IsShiftKeyDown() and true or false
  local ctrlDown = IsControlKeyDown() and true or false
  local altDown = IsAltKeyDown() and true or false
  if shiftDown ~= needsShift then
    return false
  end
  if ctrlDown ~= needsCtrl then
    return false
  end
  if altDown ~= needsAlt then
    return false
  end
  if normalizedKey:find("^BUTTON") then
    local mouseButton = tonumber(normalizedKey:match("BUTTON(%d+)"))
    if mouseButton then
      return IsMouseButtonDown(mouseButton)
    end
    return false
  end
  if IsKeyDown then
    return IsKeyDown(normalizedKey)
  end
  return false
end
-- 功能：把按键名转成界面上显示的文字。
-- 入参：key 按键名。
-- 出参：按键名本身；空值时返回本地化的「未设置」。
-- 说明：只做空值兜底，按键名不做翻译——键名就是游戏里的物理键位，界面和提示都要显示原始名字。
function WowBuddyDev.GetKeyDisplayText(key)
  if not key or key == "" then
    return WowBuddyDev.L("未设置")
  end
  return key
end
-- 功能：建一个统一样式的按钮：隐藏原生材质，自绘背景、边框和文字，并带悬停高亮。
-- 入参：parent 父框；label 按钮文字（会过本地化）；width/height 尺寸（省略时 70×22）。
-- 出参：建好的 Button。
-- 说明：原生三张纹理只是设成全透明而不是取消，这样点击区域和按下反馈都还在。悬停时背景和边框变红、文字变白；离开时按 restoreTextColor 还原文字颜色，所以外部若改过文字颜色，必须同步更新这个字段，否则鼠标一进一出颜色就被还原成默认值。
function WowBuddyDev.CreateStyledButton(parent, label, width, height)
  local styledButton = CreateFrame("Button", nil, parent)
  styledButton:SetSize(width or 70, height or 22)
  local normalTexture = styledButton:GetNormalTexture()
  if normalTexture then
    normalTexture:SetAlpha(0)
  end
  local highlightTexture = styledButton:GetHighlightTexture()
  if highlightTexture then
    highlightTexture:SetAlpha(0)
  end
  local pushedTexture = styledButton:GetPushedTexture()
  if pushedTexture then
    pushedTexture:SetAlpha(0)
  end
  local backgroundTexture = styledButton:CreateTexture(nil, "BACKGROUND")
  backgroundTexture:SetAllPoints()
  backgroundTexture:SetColorTexture(0, 0, 0, 0)
  styledButton.bg = backgroundTexture
  local borderTexture = styledButton:CreateTexture(nil, "BORDER")
  borderTexture:SetPoint("TOPLEFT", -1, 1)
  borderTexture:SetPoint("BOTTOMRIGHT", 1, -1)
  borderTexture:SetColorTexture(0, 0, 0, 0)
  styledButton.border = borderTexture
  local labelText = styledButton:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  labelText:SetPoint("CENTER")
  labelText:SetText(WowBuddyDev.L(label or ""))
  labelText:SetTextColor(.9, .75, .35, 1)
  styledButton:SetFontString(labelText)
  styledButton.restoreTextColor = { .9, .75, .35, 1 }
  styledButton:SetScript("OnEnter", function(self7)
    self7.bg:SetColorTexture(.6, .1, .15, .9)
    self7.border:SetColorTexture(.8, .2, .25, 1)
    self7:GetFontString():SetTextColor(1, 1, 1, 1)
  end)
  styledButton:SetScript("OnLeave", function(self8)
    self8.bg:SetColorTexture(0, 0, 0, 0)
    self8.border:SetColorTexture(0, 0, 0, 0)
    local restoreTextColor = self8.restoreTextColor
    if restoreTextColor then
      self8:GetFontString():SetTextColor(restoreTextColor[1], restoreTextColor[2], restoreTextColor[3], restoreTextColor[4])
    end
  end)
  return styledButton
end
-- 功能：开或关主面板（/pms 命令的落点）。
-- 入参：无。
-- 出参：无。
-- 说明：面板还没建出来时直接返回，不会新建。从隐藏切到显示时顺手把页签切回第 1 页，避免上次停在的页签带着旧数据出现。
function WowBuddyDev.ToggleDock()
  if not WowBuddyDev.mainFrame then
    return
  end
  if WowBuddyDev.mainFrame:IsShown() then
    WowBuddyDev.mainFrame:Hide()
  else
    WowBuddyDev.mainFrame:Show()
    WowBuddyDev.SwitchTab(1)
  end
end
SLASH_MAOKELI1 = "/pms"
SlashCmdList.MAOKELI = WowBuddyDev.ToggleDock
SLASH_CHARU1 = "/charu"
-- 功能：/charu 命令：把「插入」压制的到期时间设成半秒之后。
-- 入参：无。
-- 出参：无。
-- 说明：这里不直接改开关，而是写一个到期时间戳，由渲染循环自己判断——未过期时强制把主开关当关闭处理，于是输出只停 0.5 秒就自动恢复，不需要再有人把它打开。
SlashCmdList.CHARU = function()
  _G.PermesCharuExpire = GetTime() + .5
end
SLASH_MKL_ON1 = "/ON"
-- 功能：/ON 命令：打开总开关并刷新界面。
-- 入参：无。
-- 出参：无。
-- 说明：直接写存档再调 UpdateMasterSwitchUI，界面、提示音和状态图标由它一并同步。
SlashCmdList.MKL_ON = function()
  WowBuddyDev.DB.masterSwitch = true
  if WowBuddyDev.UpdateMasterSwitchUI then
    WowBuddyDev.UpdateMasterSwitchUI(true)
  end
end
SLASH_MKL_OFF1 = "/OFF"
-- 功能：/OFF 命令：关闭总开关并刷新界面。
-- 入参：无。
-- 出参：无。
-- 说明：直接写存档再调 UpdateMasterSwitchUI；这条命令不会去动「整体隐藏」开关，只关总开关。
SlashCmdList.MKL_OFF = function()
  WowBuddyDev.DB.masterSwitch = false
  if WowBuddyDev.UpdateMasterSwitchUI then
    WowBuddyDev.UpdateMasterSwitchUI(false)
  end
end
SLASH_MKL_BFK1 = "/bfk"
-- 功能：/bfk 命令：打开爆发开关。
-- 入参：无。
-- 出参：无。
-- 说明：走 SetBurstSwitch，界面同步和「自动关闭」计时器由它一起处理，命令本身不碰计时器。
SlashCmdList.MKL_BFK = function()
  WowBuddyDev.SetBurstSwitch(true)
end
SLASH_MKL_BFG1 = "/bfg"
-- 功能：/bfg 命令：关闭爆发开关。
-- 入参：无。
-- 出参：无。
-- 说明：走 SetBurstSwitch，关掉之后自动关闭计时器也会被一并取消。
SlashCmdList.MKL_BFG = function()
  WowBuddyDev.SetBurstSwitch(false)
end
SLASH_MKL_DAN1 = "/dan"
-- 功能：/dan 命令：把 AOE 模式切成「单体」。
-- 入参：无。
-- 出参：无。
-- 说明：AOE 模式取值约定是 0 自动、1 单体、2 群体；改完调 UpdateAoeModeUI 同步图标和提示。
SlashCmdList.MKL_DAN = function()
  WowBuddyDev.DB.aoeMode = 1
  if WowBuddyDev.UpdateAoeModeUI then
    WowBuddyDev.UpdateAoeModeUI(1)
  end
end
SLASH_MKL_QUN1 = "/qun"
-- 功能：/qun 命令：把 AOE 模式切成「群体」。
-- 入参：无。
-- 出参：无。
-- 说明：AOE 模式取值约定是 0 自动、1 单体、2 群体；改完调 UpdateAoeModeUI 同步图标和提示。
SlashCmdList.MKL_QUN = function()
  WowBuddyDev.DB.aoeMode = 2
  if WowBuddyDev.UpdateAoeModeUI then
    WowBuddyDev.UpdateAoeModeUI(2)
  end
end
SLASH_MKL_AUTO1 = "/AUTO"
-- 功能：/AUTO 命令：把 AOE 模式切回「自动」（/zi 是同一个函数的别名）。
-- 入参：无。
-- 出参：无。
-- 说明：AOE 模式取值约定是 0 自动、1 单体、2 群体；改完调 UpdateAoeModeUI 同步图标和提示。
SlashCmdList.MKL_AUTO = function()
  WowBuddyDev.DB.aoeMode = 0
  if WowBuddyDev.UpdateAoeModeUI then
    WowBuddyDev.UpdateAoeModeUI(0)
  end
end
SLASH_MKL_ZI1 = "/zi"
SlashCmdList.MKL_ZI = SlashCmdList.MKL_AUTO
local MOVEMENT_STATE_BASE = 3527936
local MOVEMENT_STATE_FALLBACK_SIDE = 7
local MOVEMENT_STATE_WSAD_QE = 10
local MOVEMENT_BINDING_PROFILES = {
  { name = "WSAD", forward = "W", backward = "S", left = "A", right = "D", turnCode = 1, strafeCode = 2 },
  { name = "EDSF", forward = "E", backward = "D", left = "S", right = "F", turnCode = 3, strafeCode = 4 },
  { name = "RFDG", forward = "R", backward = "F", left = "D", right = "G", turnCode = 5, strafeCode = 6 },
  { name = "WSQE", forward = "W", backward = "S", left = "Q", right = "E", turnCode = 8, strafeCode = 9 },
}
-- 功能：把「移动键位方案编号」编码成要写给读取端的数值。
-- 入参：profileCode 方案编号。
-- 出参：编码后的整数。
-- 说明：这是插件和外部读取端约定的编码方式；改动会改变读取端解析结果，所以编号必须按原样保留，不能为了好看重排。
local function movementStateCode(profileCode)
  return MOVEMENT_STATE_BASE + profileCode * 16 + (15 - profileCode)
end
WowBuddyDev.isMoving = movementStateCode(0)
WowBuddyDev.movementBindingProfile = nil
WowBuddyDev.movementBindingSideMode = nil
-- 功能：取某个动作上绑定的所有按键。
-- 入参：action 动作名。
-- 出参：按键字符串数组；取不到返回 nil。
-- 说明：取绑定键会返回多个值、并且可能抛错，所以整体包保护调用，再把返回值收集起来过滤掉空串。
local function getBoundKeys(action)
  if type(GetBindingKey) ~= "function" then
    return nil
  end
  local bindingKeyResults = { pcall(GetBindingKey, action) }
  if not bindingKeyResults[1] then
    return nil
  end
  local bindingKeys = {}
  for i8 = 2, #bindingKeyResults, 1 do
    if type(bindingKeyResults[i8]) == "string" and bindingKeyResults[i8] ~= "" then
      bindingKeys[#bindingKeys + 1] = bindingKeyResults[i8]
    end
  end
  return bindingKeys
end
-- 功能：判断某个动作是否绑定了指定按键。
-- 入参：action 动作名；key 按键字符串。
-- 出参：true/false。
local function isActionBoundTo(action, key)
  local boundKeys = getBoundKeys(action)
  if not boundKeys then
    return false
  end
  for index21, boundKey in ipairs(boundKeys) do
    if boundKey == key then
      return true
    end
  end
  return false
end
-- 功能：判断一套移动键位里左右键是「转向」还是「平移」。
-- 入参：profile 键位方案（含左右键）。
-- 出参：转向或平移；两边都不匹配返回 nil。
-- 说明：同一个键在不同玩家那里可能绑转向也可能绑平移，必须实测按键上绑的动作才能确定，不能按方案名猜。
local function detectTurnStrafeMode(profile)
  local isTurnProfile = isActionBoundTo("TURNLEFT", profile.left) and isActionBoundTo("TURNRIGHT", profile.right)
  local isStrafeProfile = isActionBoundTo("STRAFELEFT", profile.left) and isActionBoundTo("STRAFERIGHT", profile.right)
  if isTurnProfile then
    return "turn"
  end
  if isStrafeProfile then
    return "strafe"
  end
  return nil
end
-- 功能：判断当前是不是「WSAD 移动 + QE 平移」这套经典键位。
-- 入参：无。
-- 出参：true/false。
local function isWsadQeProfile()
  return isActionBoundTo("MOVEFORWARD", "W") and (isActionBoundTo("MOVEBACKWARD", "S") and (isActionBoundTo("TURNLEFT", "A") and (isActionBoundTo("TURNRIGHT", "D") and (isActionBoundTo("STRAFELEFT", "Q") and isActionBoundTo("STRAFERIGHT", "E")))))
end
-- 功能：重新识别玩家用的是哪套移动键位，并算出表示「正在移动」的状态码。
-- 入参：无。
-- 出参：无；结果写进 P07483180.isMoving、P07483180.movementBindingProfile 和 P07483180.movementBindingSideMode。
-- 说明：先看是不是「WSAD 移动 + QE 平移」这套经典键位，是就用它专属的状态码；否则按 MOVEFORWARD/MOVEBACKWARD 去匹配预设档，再实测左右键绑的是转向还是平移，两种方向键用不同的状态码。一个档都没匹配上时用兜底状态码，并把档位名清空，表示「不认识这套键位」。状态码是插件和外部读取端约定好的编码，改动会影响读取端解析结果。
function WowBuddyDev.RefreshMovementBindingProfile()
  if isWsadQeProfile() then
    WowBuddyDev.isMoving = movementStateCode(MOVEMENT_STATE_WSAD_QE)
    WowBuddyDev.movementBindingProfile = "WSAD+QE"
    WowBuddyDev.movementBindingSideMode = "classic"
    return
  end
  for index22, profile in ipairs(MOVEMENT_BINDING_PROFILES) do
    if isActionBoundTo("MOVEFORWARD", profile.forward) and isActionBoundTo("MOVEBACKWARD", profile.backward) then
      local sideMode = detectTurnStrafeMode(profile)
      if sideMode then
        local movementCode = sideMode == "turn" and profile.turnCode or profile.strafeCode
        WowBuddyDev.isMoving = movementStateCode(movementCode)
        WowBuddyDev.movementBindingProfile = profile.name
        WowBuddyDev.movementBindingSideMode = sideMode
        return
      end
    end
  end
  WowBuddyDev.isMoving = movementStateCode(MOVEMENT_STATE_FALLBACK_SIDE)
  WowBuddyDev.movementBindingProfile = nil
  WowBuddyDev.movementBindingSideMode = nil
end
local movementBindingFrame = CreateFrame("Frame")
movementBindingFrame:RegisterEvent("BINDINGS_LOADED")
movementBindingFrame:RegisterEvent("UPDATE_BINDINGS")
movementBindingFrame:RegisterEvent("NOTIFY_TURN_STRAFE_CHANGE")
movementBindingFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
movementBindingFrame:SetScript("OnEvent", function()
  WowBuddyDev.isMoving = movementStateCode(0)
  WowBuddyDev.movementBindingProfile = nil
  WowBuddyDev.movementBindingSideMode = nil
  C_Timer.After(0, WowBuddyDev.RefreshMovementBindingProfile)
end)
C_Timer.After(0, WowBuddyDev.RefreshMovementBindingProfile)
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
