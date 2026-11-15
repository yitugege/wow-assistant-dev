-- ==========================================================================
-- 文件：Modules.lua
-- 来源：2026-11-15 新增。
-- 作用：模块注册表。各文件登记自身、声明加载期依赖，并通过导出表互相取用内部函数，
--       不再借助全局字段传递 Core 拆分文件之间的内部实现。
-- 加载：TOC 中位于 CoreSettings.lua 与 Core.lua 之前。
-- 接口：
--   WowBuddyDev.ModuleExports(name)        取（必要时创建）模块的导出表；模块在加载过程中向其中写入。
--   WowBuddyDev.RegisterModule(name, requires)  文件末尾调用：标记已加载，并检查 requires 中的模块均已加载。
--   WowBuddyDev.Require(name)              取已加载模块的导出表；未加载时记录错误并返回空表。
--   WowBuddyDev.IsModuleLoaded(name)
--   WowBuddyDev.Namespace(name, uses)      文件开头调用：取本模块的命名空间视图，按 uses 检查跨模块读写（见下文）。
--   WowBuddyDev.ModuleFields(name)         列出某模块拥有的命名空间字段。
--   WowBuddyDev.SetModuleAudit(enabled)    开关跨模块边界检查（默认开启，只记录不拦截）。
--   WowBuddyDev.CheckModuleUses()          核对 uses 中的模块是否都已加载。
-- 依赖缺失只记入 moduleErrors，不中断加载，保持原有容错行为；游戏内可用 /dump WowBuddyDev.moduleErrors 查看。
-- 公开 API（WowBuddyDev.GetPlayerClassSpec 等）仍挂在 WowBuddyDev 表上，与原插件及其他文件的调用方式一致。
-- ==========================================================================
_G.WowBuddyDev = _G.WowBuddyDev or {}
WowBuddyDev.modules = WowBuddyDev.modules or {}            -- name -> true（已加载）
WowBuddyDev.moduleExports = WowBuddyDev.moduleExports or {} -- name -> 导出表
WowBuddyDev.moduleErrors = WowBuddyDev.moduleErrors or {}

local function recordModuleError(message)
  table.insert(WowBuddyDev.moduleErrors, message)
end

function WowBuddyDev.ModuleExports(name)
  local exports = WowBuddyDev.moduleExports[name]
  if not exports then
    exports = {}
    WowBuddyDev.moduleExports[name] = exports
  end
  return exports
end

function WowBuddyDev.RegisterModule(name, requires)
  for _, dependency in ipairs(requires or {}) do
    if not WowBuddyDev.modules[dependency] then
      recordModuleError(tostring(name) .. " 加载时缺少依赖 " .. tostring(dependency))
    end
  end
  WowBuddyDev.ModuleExports(name)
  WowBuddyDev.modules[name] = true
end

function WowBuddyDev.Require(name)
  if not WowBuddyDev.modules[name] then
    recordModuleError("请求了未加载的模块 " .. tostring(name))
  end
  return WowBuddyDev.ModuleExports(name)
end

function WowBuddyDev.IsModuleLoaded(name)
  return WowBuddyDev.modules[name] == true
end

-- 各插件文件开头调用，取得本模块的命名空间视图；文件内所有 WowBuddyDev.* 访问都经这个视图，
-- 由注册表按模块边界中转，而不是直接访问全局表。
--   字段归属：以下方 staticOwners（静态分析生成：TOC 顺序中首个定义该字段的模块）为准，与 uses 声明使用同一标准；
--         表中没有的字段（如 WowBuddyDev[key] 动态写入）以运行时首次写入的模块为所属（moduleFieldOwners）。
--         ModuleFields(name) 列出某模块拥有的字段。
--   读：只应读取本模块、uses 中声明的模块以及 Modules 自身拥有的字段；读取其他模块的字段时记入 moduleErrors。
--   写：不检查。静态分析把写入视为定义而非依赖（多个模块可以写同一字段，例如重置时置空），写入只用于登记未知字段的归属。
--   越界只记录（同一组合只记一次）、照常返回原值，不改变插件行为：拒绝访问会在游戏内直接出错。
-- 全局表 _G.WowBuddyDev 只作为对外兼容面保留：按键绑定、斜杠命令、宏文本与发布包改名依赖它；插件内部不再直接访问。
-- uses 为该文件运行期用到的其他模块（由 tools/addon_module_deps.py 生成，见 tests/test_core_split.py）；只登记，不要求先加载，
-- 因为多数调用发生在登录后的事件与界面回调里。加载期依赖仍用 RegisterModule/Require 声明和检查。
WowBuddyDev.moduleUses = WowBuddyDev.moduleUses or {}
WowBuddyDev.moduleFieldOwners = WowBuddyDev.moduleFieldOwners or {}
local namespace = WowBuddyDev
local owners = WowBuddyDev.moduleFieldOwners
-- @@字段归属开始@@ 由 tools/addon_module_deps.py --write 生成，勿手改
local staticOwners = {
  ["ACTION_KEY_ORDER"] = "ActionKeyCheck",
  ["ACTION_LABELS"] = "CoreState",
  ["ACTION_TO_KEY"] = "CoreState",
  ["AUTO_TARGET_KEYS"] = "AutoTarget",
  ["AddErrorLog"] = "CoreLocale",
  ["ApplyAutoTargetBinding"] = "AutoTarget",
  ["ApplyClassMacros"] = "Bindings",
  ["ApplyDiscardTargetBinding"] = "CharacterState",
  ["ApplyRaidFocusBindings"] = "RaidFocus",
  ["ApplyRecoveryBindings"] = "Recovery",
  ["ApplyWandBinding"] = "WandShot",
  ["AttachCharacterState"] = "CharacterState",
  ["BindKey"] = "Bindings",
  ["BringToFront"] = "SettingsUI",
  ["CDMImportDataConfig"] = "CDMImport",
  ["CDMImportProfile"] = "CDMImport",
  ["CDMManager"] = "CDMImport",
  ["CLASS_MACRO_SLOTS"] = "Bindings",
  ["COMMON_PIXEL_DATA"] = "Core",
  ["CheckMacroBindings"] = "CoreButtons",
  ["CheckSpecChange"] = "CoreEvents",
  ["ClearErrorLogs"] = "CoreLocale",
  ["ClearFocusHealFailurePair"] = "CoreEvents",
  ["ClearPersistentCooldownsForGameReset"] = "CoreCooldownLedger",
  ["ClearUserMacro"] = "CoreSettings",
  ["CompileAuthorizedMacro"] = "MacroAuthorize",
  ["CreateMacroRow"] = "SettingsUI",
  ["CreateSecureButton"] = "CoreButtons",
  ["CreateSecureFocusButton"] = "CoreButtons",
  ["CreateStyledButton"] = "CoreControls",
  ["DB"] = "CoreSettings",
  ["DecisionBridge"] = "DecisionBridge",
  ["DescribeForeverCompat"] = "ForeverCompat",
  ["DescribeObservedSpecs"] = "ForeverCompat",
  ["DetectPaladinMainTree"] = "ForeverCompat",
  ["DirectCast"] = "DirectCastSlots",
  ["DumpChargeValues"] = "ChargeDisplay",
  ["DumpV2State"] = "PanelV2",
  ["ExportPixelBarCenters"] = "PixelBar",
  ["ExportPixelBarsAsRel"] = "PixelBar",
  ["FOREVER_SPEC_MAP"] = "ForeverCompat",
  ["FOREVER_SPEC_ROLES"] = "ForeverCompat",
  ["FillForeverExtraValues"] = "ForeverClassSupport",
  ["FindFreeAutomationKey"] = "AutoTarget",
  ["ForeverSpecSpells"] = "ForeverSpecSpells",
  ["ForeverTalentData"] = "ForeverTalentData",
  ["GetActiveHeroTalentSpecID"] = "CoreEvents",
  ["GetAuraDebugWindow"] = "DebugAuras",
  ["GetAutoTargetEnabled"] = "CoreEvents",
  ["GetAutoTargetPacket"] = "AutoTarget",
  ["GetBoundMacro"] = "CoreButtons",
  ["GetBurstAutoCloseSeconds"] = "CoreSettings",
  ["GetCapturedLuaErrors"] = "Core",
  ["GetClassBindingAction"] = "Bindings",
  ["GetClassDefaultMacro"] = "Bindings",
  ["GetClassMacroInfo"] = "Bindings",
  ["GetClassMacroKeys"] = "Bindings",
  ["GetClientLocale"] = "CoreLocale",
  ["GetConsumableCooldownFast"] = "CoreConsumables",
  ["GetConsumableCooldownRemaining"] = "CoreConsumables",
  ["GetControlBindingConflict"] = "CoreControls",
  ["GetDefaultMacro"] = "CoreLocale",
  ["GetErrorLogs"] = "CoreLocale",
  ["GetExtraValueByRule"] = "Core",
  ["GetFocusCastUnreachable"] = "CoreEvents",
  ["GetForeverSpecDisplayName"] = "ForeverTalents",
  ["GetForeverSpecRole"] = "ForeverCompat",
  ["GetForeverTalentState"] = "ForeverTalents",
  ["GetGeneralBagFreeSlots"] = "Recovery",
  ["GetHostileUnitCastingColor"] = "PixelBar",
  ["GetHunterTalentPacket"] = "ForeverTalents",
  ["GetHunterTalentState"] = "ForeverTalents",
  ["GetIdleAutoTargetKeyIndex"] = "AutoTarget",
  ["GetKeyDisplayText"] = "CoreControls",
  ["GetNearbyEnemiesCount"] = "PixelBar",
  ["GetPackedGameIdentity"] = "CoreEvents",
  ["GetPersistentChargeCount"] = "CoreCooldownLedger",
  ["GetPlayerCastState"] = "CoreCastState",
  ["GetPlayerChannelWindowState"] = "CoreCastState",
  ["GetPlayerClassSpec"] = "CoreEvents",
  ["GetPlayerEmpowerState"] = "CoreCastState",
  ["GetPlayerSucceededState"] = "CoreCastState",
  ["GetPostKillAutoTargetEnabled"] = "AutoTarget",
  ["GetRaidFocusKeys"] = "RaidFocus",
  ["GetRaidFocusPacket"] = "RaidFocus",
  ["GetReadyWandKey"] = "WandShot",
  ["GetRecoveryHandoffWord"] = "Recovery",
  ["GetRecoverySettings"] = "Recovery",
  ["GetSecureButton"] = "CoreButtons",
  ["GetSpecRole"] = "CoreEvents",
  ["GetSpellChargeCount"] = "ChargeDisplay",
  ["GetSpellChargeDisplayRaw"] = "ChargeDisplay",
  ["GetSpellCooldownRemaining"] = "Core",
  ["GetTrinketCooldownRemaining"] = "Core",
  ["GetTrinketSlotCooldownRemaining"] = "Core",
  ["GetUserMacro"] = "CoreSettings",
  ["HasHealingNpcMouseover"] = "HealingNpcFocus",
  ["HasInterruptedLootTarget"] = "CharacterState",
  ["InitDB"] = "CoreSettings",
  ["InvalidateControlBindingConflicts"] = "CoreControls",
  ["InvalidateForeverTalents"] = "ForeverTalents",
  ["IsActionOfCurrentSpec"] = "CoreEvents",
  ["IsAutoTargetCombatSettling"] = "AutoTarget",
  ["IsAutoTargetGateOpen"] = "CoreEvents",
  ["IsBindPressed"] = "CoreControls",
  ["IsChineseClient"] = "CoreLocale",
  ["IsForeverProtectionPaladin"] = "ForeverCompat",
  ["IsGcdActive"] = "Core",
  ["IsHealingSpec"] = "CoreEvents",
  ["IsMeleeSpec"] = "CoreEvents",
  ["IsPetSpell"] = "Core",
  ["IsPostKillAutoTargetReady"] = "AutoTarget",
  ["IsRaidFocusFeedbackEnabled"] = "RaidFocus",
  ["IsRangedDamageSpec"] = "CoreEvents",
  ["IsRecoveryActive"] = "Recovery",
  ["IsRemoteAutoTargetGateOpen"] = "AutoTarget",
  ["IsRemoteAutoTargetSessionReady"] = "AutoTarget",
  ["IsSpellKnown"] = "PixelBar",
  ["IsSpellOfCurrentSpec"] = "CoreEvents",
  ["IsSpellReady"] = "PixelBar",
  ["IsSpellReadyRaw"] = "PixelBar",
  ["IsSpellUsable"] = "Core",
  ["L"] = "CoreLocale",
  ["LANG"] = "CoreLocale",
  ["LibRangeCheck"] = "Core",
  ["LocalizeActionLabel"] = "CoreLocale",
  ["LocalizeMacroBody"] = "CoreLocale",
  ["LuaErrorCollectorActive"] = "Core",
  ["MacroRefsBySpec"] = "MacroRefsData",
  ["MacroRefsGeneration"] = "MacroRefsData",
  ["NormalizeActionKey"] = "ActionKeyCheck",
  ["NormalizeClassActionKey"] = "CoreButtons",
  ["ObservePlayerMoving"] = "ForeverClassSupport",
  ["OnSecureButtonBound"] = "DirectCastHook",
  ["PrintCooldownInfo"] = "DebugAuras",
  ["PrintUnitAuras"] = "DebugAuras",
  ["RAID_FOCUS_KEYS"] = "RaidFocus",
  ["RebuildPixelBars"] = "PixelBar",
  ["RecordAutoTargetAttempt"] = "AutoTarget",
  ["RecordPersistentChargeSuccess"] = "CoreCooldownLedger",
  ["RecordRaidFocusFeedback"] = "RaidFocus",
  ["RecordTargetSightError"] = "CharacterState",
  ["RefreshAllOverlayVisibility"] = "PixelBar",
  ["RefreshAuraDebugPanel"] = "DebugAuras",
  ["RefreshAuraView"] = "DebugAuras",
  ["RefreshAutoTargetSettingUI"] = "SettingsUI",
  ["RefreshBurstAutoCloseSettingUI"] = "SettingsUI",
  ["RefreshCVarPanel"] = "SettingsUI",
  ["RefreshControlKeySettingUI"] = "SettingsUI",
  ["RefreshCooldownView"] = "DebugAuras",
  ["RefreshDockButtonColors"] = "PixelBar",
  ["RefreshMacroBindings"] = "CoreButtons",
  ["RefreshMacroHelper"] = "SettingsUI",
  ["RefreshMovementBindingProfile"] = "CoreMovement",
  ["RefreshPanelDebugIcons"] = "PanelV2",
  ["RefreshPixelBarPositions"] = "PixelBar",
  ["RefreshStateLogo"] = "PixelBar",
  ["RefreshV2SurfaceVisibility"] = "PanelV2",
  ["RegisterClass"] = "CoreButtons",
  ["RegisterClassMacros"] = "Bindings",
  ["RegisterPixelStripV2"] = "PanelV2",
  ["RenderHealingNpcFocusMatch"] = "HealingNpcFocus",
  ["RenderRaidFocusAcknowledgement"] = "RaidFocus",
  ["ReportMacroBindingError"] = "CoreButtons",
  ["ResetBurstAutoCloseTimer"] = "CoreSettings",
  ["ResolveChargeDisplaySpellID"] = "ChargeDisplay",
  ["ResolveSpecID"] = "ForeverCompat",
  ["RestorePersistentConsumableCooldowns"] = "CoreCooldownLedger",
  ["RestorePersistentCooldowns"] = "CoreCooldownLedger",
  ["SafeNumber"] = "Core",
  ["SaveBurstAutoCloseSeconds"] = "CoreSettings",
  ["SaveRecoverySettings"] = "Recovery",
  ["SaveUserMacro"] = "CoreSettings",
  ["ScanVisibleHostileEnemies"] = "PixelBar",
  ["SetAutoTargetEnabled"] = "CoreEvents",
  ["SetBurstSwitch"] = "CoreSettings",
  ["SetPostKillAutoTargetEnabled"] = "AutoTarget",
  ["SetTimelinePlannerArmed"] = "TimelinePlanner",
  ["SetTimelinePlannerTrashCaptureArmed"] = "TimelineTrash",
  ["ShowTalentPicker"] = "SettingsUI",
  ["SnapshotRuntimeDiagnostics"] = "RuntimeDiagnostics",
  ["SwitchTab"] = "SettingsUI",
  ["TimelinePlannerEncounters"] = "TimelineData_1",
  ["ToggleAllOverlayVisibility"] = "PixelBar",
  ["ToggleDebugDock"] = "DebugDock",
  ["ToggleDock"] = "CoreControls",
  ["UpdateAoeModeUI"] = "PixelBar",
  ["UpdateBurstSwitchUI"] = "PixelBar",
  ["UpdateCVarEnvInfo"] = "SettingsUI",
  ["UpdateCharacterState"] = "CharacterState",
  ["UpdateDockLayout"] = "PixelBar",
  ["UpdateHealingNpcMouseover"] = "HealingNpcFocus",
  ["UpdateLogoToggleBtn"] = "SettingsUI",
  ["UpdateMasterSwitchUI"] = "PixelBar",
  ["UpdateRecovery"] = "Recovery",
  ["VERIFIED_ACTION_KEYS"] = "ActionKeyCheck",
  ["_lastCombatEnd"] = "Core",
  ["_localeEN"] = "Locale",
  ["_pixelBarPositions"] = "PixelBar",
  ["_pixelStripV2BySpec"] = "PanelV2",
  ["_spellNameToID"] = "CoreLocale",
  ["actionAvailSpellIDs"] = "CoreState",
  ["addonVersionCode"] = "Core",
  ["alertAoeMode"] = "PixelBar",
  ["aoeKeyPressed"] = "PixelBar",
  ["auraDebugFrame"] = "DebugAuras",
  ["auraDebugStatusText"] = "DebugAuras",
  ["burstAutoCloseGeneration"] = "CoreSettings",
  ["burstKeyPressed"] = "CoreControls",
  ["classData"] = "CoreClassData",
  ["classes"] = "Core",
  ["configFrame"] = "SettingsUI",
  ["consumableItems"] = "CoreState",
  ["cooldowns"] = "CoreState",
  ["debugFrame"] = "PixelBar",
  ["demonicFuryColorCurve"] = "PixelBar",
  ["energyColorCurve"] = "PixelBar",
  ["errorLogs"] = "CoreLocale",
  ["extraValueRules"] = "CoreState",
  ["fontFile"] = "Core",
  ["forceAvailableState"] = "CoreState",
  ["foreverCompat"] = "ForeverCompat",
  ["foreverTalentState"] = "ForeverTalents",
  ["gcdDiagnostic"] = "Core",
  ["healerMasterHealthLayers"] = "PixelBar",
  ["healingNpcFocusMatchLayer"] = "PixelBar",
  ["healthColorCurve"] = "PixelBar",
  ["highlightRules"] = "CoreState",
  ["hunterTalentState"] = "ForeverTalents",
  ["isClassActive"] = "CoreClassData",
  ["isMoving"] = "CoreMovement",
  ["lastCastSpellID"] = "Core",
  ["lastCastTime"] = "Core",
  ["macroBindingBackend"] = "CoreButtons",
  ["macroEditorFrame"] = "SettingsReset",
  ["mainFrame"] = "SettingsUI",
  ["manaDisplay"] = "ForeverClassSupport",
  ["masterKeyPressed"] = "CoreControls",
  ["minimapButton"] = "PixelBar",
  ["mklFrames"] = "SettingsUI",
  ["movementBindingProfile"] = "CoreMovement",
  ["movementBindingSideMode"] = "CoreMovement",
  ["persistentChargeTrackers"] = "CoreState",
  ["persistentCooldowns"] = "CoreState",
  ["pixelContainer"] = "PixelBar",
  ["pixelData"] = "CoreState",
  ["playerCastGeneration"] = "CoreCastState",
  ["playerSucceededGeneration"] = "CoreState",
  ["playerSucceededSpellID"] = "CoreState",
  ["rageDisplay"] = "classes/Warrior/class_forever",
  ["raidFocusAckCarrier"] = "PixelBar",
  ["raidFocusAckFrameSequence"] = "PixelBar",
  ["raidFocusAckLayers"] = "PixelBar",
  ["raidFocusHealthLayers"] = "PixelBar",
  ["raidFocusPartyUnavailableLayers"] = "PixelBar",
  ["rendFeedback"] = "classes/Warrior/class_forever",
  ["runicPowerColorCurve"] = "PixelBar",
  ["stateLogo"] = "PixelBar",
  ["tabFrames"] = "SettingsUI",
  ["talentPickerFrame"] = "SettingsUI",
  ["teamAvgIndex"] = "PixelBar",
  ["teamAvgLayers"] = "PixelBar",
  ["testData"] = "CoreState",
  ["testSpells"] = "CoreClassData",
  ["trinketItemID"] = "CoreState",
  ["waitingForKey"] = "CoreControls",
}
-- @@字段归属结束@@
local moduleViews = {}
local allowedByModule = {}
local reported = {}
local boundaryChecks = true

local function reportOnce(id, message)
  if not reported[id] then
    reported[id] = true
    recordModuleError(message)
  end
end

local function ownerOf(key)
  return staticOwners[key] or owners[key]
end

local function boundaryIndex(name, allowed)
  return function(_, key)
    local owner = ownerOf(key)
    if owner and not allowed[owner] then
      reportOnce(name .. ">" .. owner, name .. " 读取了未声明依赖 " .. owner .. " 的字段 " .. tostring(key))
    end
    return namespace[key]
  end
end

local function registeringNewIndex(name)
  return function(_, key, value)
    if staticOwners[key] == nil and owners[key] == nil then
      owners[key] = name
    end
    namespace[key] = value
  end
end

function WowBuddyDev.Namespace(name, uses)
  WowBuddyDev.moduleUses[name] = uses or {}
  WowBuddyDev.ModuleExports(name)
  WowBuddyDev.modules[name] = true
  local allowed = { [name] = true, Modules = true }
  for _, used in ipairs(uses or {}) do
    allowed[used] = true
  end
  allowedByModule[name] = allowed
  local view = setmetatable({}, {
    __index = boundaryChecks and boundaryIndex(name, allowed) or namespace,
    __newindex = registeringNewIndex(name),
  })
  moduleViews[name] = view
  return view
end

-- 列出某模块拥有的命名空间字段（静态归属，加上运行时首次写入的未知字段），按名称排序。
function WowBuddyDev.ModuleFields(name)
  local fields = {}
  for key, owner in pairs(staticOwners) do
    if owner == name then
      table.insert(fields, tostring(key))
    end
  end
  for key, owner in pairs(owners) do
    if owner == name and staticOwners[key] == nil then
      table.insert(fields, tostring(key))
    end
  end
  table.sort(fields)
  return fields
end

-- 边界检查默认开启。关闭后读取直接回落到全局表（C 层查找，无额外函数调用），写入仍登记字段归属；
-- 只在需要排除检查开销时使用，例如排查帧率问题。
function WowBuddyDev.SetModuleAudit(enabled)
  boundaryChecks = enabled and true or false
  for name, view in pairs(moduleViews) do
    getmetatable(view).__index = boundaryChecks and boundaryIndex(name, allowedByModule[name]) or namespace
  end
end

-- 加载完成后核对：声明使用的模块是否都已加载。结果写入 moduleErrors，不影响插件运行。
function WowBuddyDev.CheckModuleUses()
  local missing = 0
  for name, uses in pairs(WowBuddyDev.moduleUses) do
    for _, used in ipairs(uses) do
      if not WowBuddyDev.modules[used] then
        recordModuleError(tostring(name) .. " 使用的模块未加载 " .. tostring(used))
        missing = missing + 1
      end
    end
  end
  return missing
end

WowBuddyDev.RegisterModule("Modules")
