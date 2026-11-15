-- ==========================================================================
-- 文件：CoreEvents.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 2717-3360 行），语句与顺序未改。
-- 作用：专精识别与切换检测、施法失败与焦点治疗失败配对、核心事件注册与分发、登录初始化。
-- 加载：TOC 中位于 CoreLocale.lua 之后、CoreControls.lua 之前（原文件中的相对顺序）。
--       Core.lua 的文件级函数经 WowBuddyDev.Require("Core") 取得；带 @@拆分新增@@ 的行不属于原文件。
-- ==========================================================================
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreEvents", { "ForeverCompat", "ForeverTalents", "ForeverSpecSpells", "CoreSettings", "CoreCooldownLedger", "CoreClassData", "CoreLocale", "HealingNpcFocus", "RaidFocus", "AutoTarget", "CharacterState", "SettingsUI", "PixelBar" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local addonName = ... -- @@拆分新增@@
local shared = WowBuddyDev.Require("Core") -- @@拆分新增@@
local eventFrame = shared.eventFrame -- @@拆分新增@@
local onItemDataLoaded = WowBuddyDev.Require("CoreConsumables").onItemDataLoaded -- @@拆分新增@@
local shouldResetCooldownsOnEvent = shared.shouldResetCooldownsOnEvent -- @@拆分新增@@
local reloadClassData = WowBuddyDev.Require("CoreClassData").reloadClassData -- @@拆分新增@@
local refreshMacroBindings = WowBuddyDev.Require("CoreButtons").refreshMacroBindings -- @@拆分新增@@
local coreState = WowBuddyDev.Require("CoreState") -- @@拆分新增@@
-- 以下两项原在 Core.lua 第 88-89 行声明，只有本文件读写。
local lastSpecID = nil -- @@拆分新增@@
local lastHeroSpecID = nil -- @@拆分新增@@
-- ---- 以下为原 Core.lua 内容 ----
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
  if WowBuddyDev.IsPostKillAutoTargetReady and WowBuddyDev.IsPostKillAutoTargetReady() then
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
        WowBuddyDev.classData.OnSpellCastFailed(failedSpellID, coreState.consumableByItemSpell[failedSpellID])
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
          if failureKind == "los" and WowBuddyDev.RecordTargetSightError then
            WowBuddyDev.RecordTargetSightError()
          end
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
WowBuddyDev.RegisterModule("CoreEvents", { "CoreState", "CoreConsumables", "CoreClassData", "Core", "CoreLocale", "CoreButtons" })
