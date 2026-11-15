-- ==========================================================================
-- 文件：CoreMovement.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 3617-3730 行（不含注册表）），语句与顺序未改。
-- 作用：移动键位方案识别与 isMoving 编码（读取端约定，数值不可改）。
-- 加载：TOC 中位于 Core.lua 之后；只使用 WowBuddyDev 全局表。
-- ==========================================================================
-- ---- 以下为原 Core.lua 内容 ----
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreMovement", {  }) or _G.WowBuddyDev -- @@注册表命名空间@@
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
WowBuddyDev.RegisterModule("CoreMovement", { "Core" })
