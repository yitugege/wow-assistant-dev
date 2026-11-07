-- ==========================================================================
-- 文件：4047d4.lua
-- 来源：P07483180.rar → P07483180/4047d4.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：4047d4.lua → HealingNpcFocus.lua（按功能重命名）
-- 作用：治疗 NPC 鼠标指向判定（竖排字段）
-- ==========================================================================
local packetBase = 10485760
local eligibleBit = 524288
local sequenceMask = 1023
local epochMask = 256
local epochShift = 1024
local healingNpcState = { enabled = false, eligible = false, epoch = 0, sequence = 0, packet = 0 }
-- 功能：判断一个值是不是客户端的秘密值（受保护、插件不许读）。
-- 入参：value 待判断的值。
-- 出参：布尔，true 表示这个值不可信。
-- 说明：客户端没有 issecretvalue 时返回 false（老版本没这套机制）；连判断本身都抛错时返回 true —— 宁可当秘密值处理。
local function isSecretValue(value)
  if type(issecretvalue) ~= "function" then
    return false
  end
  local okSecret, isSecret = pcall(issecretvalue, value)
  return not okSecret or isSecret == true
end
-- 功能：安全调用一个返回 true/false 的单位接口，把结果归一成 true / false / nil。
-- 入参：apiFunc 要调用的函数；... 透传给它的参数。
-- 出参：true / false / nil（抛错、或返回值是秘密值/非布尔时给 nil）。
-- 说明：nil 是「读不到」，和 false 的「明确的否」区分开；受保护的值拿去判断真假会在后面的代码里炸掉，所以一并当读不到。
local function callBoolSafe(apiFunc, ...)
  if type(apiFunc) ~= "function" then
    return nil
  end
  local ok, value = pcall(apiFunc, ...)
  if not ok or isSecretValue(value) then
    return nil
  end
  if value == true then
    return true
  end
  if value == false then
    return false
  end
  return nil
end
-- 功能：检查像素数据里有没有 mouseover_npc_state 这个格子。
-- 入参：无。
-- 出参：布尔。
-- 说明：这是竖排字段用的契约格子，格子不在时后面的判定全都白算，所以先短路。
local function hasMouseoverNpcCell()
  if type(WowBuddyDev.pixelData) ~= "table" then
    return false
  end
  for index, cell in ipairs(WowBuddyDev.pixelData) do
    if type(cell) == "table" and cell.id == "mouseover_npc_state" then
      return true
    end
  end
  return false
end
-- 功能：判断鼠标指向的单位是不是可以帮忙的友方 NPC：存在、没死、能协助，而且不是玩家、不是宠物仆从、也不受玩家控制。
-- 入参：无。
-- 出参：布尔。
-- 说明：三个否定条件专门用来排除玩家和宠物 —— 治疗焦点只认真正的 NPC；单位代号固定是 mouseover。
local function isEligibleMouseoverNpc()
  local unitToken = "mouseover"
  return callBoolSafe(UnitExists, unitToken) == true and (callBoolSafe(UnitIsDeadOrGhost, unitToken) == false and (callBoolSafe(UnitCanAssist, "player", unitToken) == true and (callBoolSafe(UnitIsPlayer, unitToken) == false and (callBoolSafe(UnitIsMinion, unitToken) == false and callBoolSafe(UnitPlayerControlled, unitToken) == false))))
end
-- 功能：对外回答鼠标指向的友方 NPC 当前是否处于命中状态。
-- 入参：无。
-- 出参：布尔。
-- 说明：要求同时满足 enabled（格子存在）和 eligible（目标符合条件）—— 两者分开存，状态变化才能体现在包序号里。
function WowBuddyDev.HasHealingNpcMouseover()
  return healingNpcState.enabled == true and healingNpcState.eligible == true
end
-- 功能：刷新鼠标指向 NPC 的状态，并算出这一帧要发的包序号。
-- 入参：无。
-- 出参：包序号（数字）；格子不存在时返回 0。
-- 说明：状态从命中掉到未命中时 epoch 加一 —— 主程序靠 epoch 的变化知道该收手；是否命中还额外占一个位段（eligibleBit），序号本身每帧循环，用来区分新旧包。
function WowBuddyDev.UpdateHealingNpcMouseover()
  local wasEligible = healingNpcState.eligible == true
  healingNpcState.enabled = hasMouseoverNpcCell()
  local isEligibleNow = false
  if healingNpcState.enabled then
    isEligibleNow = isEligibleMouseoverNpc()
  end
  if wasEligible and not isEligibleNow then
    healingNpcState.epoch = (healingNpcState.epoch + 1) % epochMask
  end
  healingNpcState.eligible = isEligibleNow
  if not healingNpcState.enabled then
    healingNpcState.packet = 0
    return 0
  end
  healingNpcState.sequence = healingNpcState.sequence % sequenceMask + 1
  local packetValue = packetBase + healingNpcState.epoch * epochShift + healingNpcState.sequence
  if healingNpcState.eligible then
    packetValue = packetValue + eligibleBit
  end
  healingNpcState.packet = packetValue
  return packetValue
end
-- 功能：把一个格子控件的透明度设成 0。
-- 入参：cellFrame 目标控件，可为 nil。
-- 出参：无。
-- 说明：控件没有 SetAlpha、或调用失败都不报错 —— 这个格子是可选的渲染目标，不该因为它中断别的格子。
local function fadeFrame(cellFrame)
  if cellFrame and type(cellFrame.SetAlpha) == "function" then
    pcall(cellFrame.SetAlpha, cellFrame, 0)
  end
end
-- 功能：让某个格子显示「焦点是否就是当前鼠标指向的单位」。
-- 入参：renderCell 目标控件。
-- 出参：无。
-- 说明：UnitIsUnit 的结果也可能是秘密值，所以包 pcall；拿不到结果就直接返回，不改控件状态。
function WowBuddyDev.RenderHealingNpcFocusMatch(renderCell)
  fadeFrame(renderCell)
  if not WowBuddyDev.HasHealingNpcMouseover() or type(UnitIsUnit) ~= "function" or not renderCell or type(renderCell.SetAlphaFromBoolean) ~= "function" then
    return
  end
  local okUnitIsUnit, isFocusOnMouseover = pcall(UnitIsUnit, "focus", "mouseover")
  if not okUnitIsUnit then
    return
  end
  pcall(renderCell.SetAlphaFromBoolean, renderCell, isFocusOnMouseover, 255, 0)
end
local frame = CreateFrame("Frame")
frame:RegisterEvent("UPDATE_MOUSEOVER_UNIT")
frame:SetScript("OnEvent", function(self, event)
  if event == "UPDATE_MOUSEOVER_UNIT" then
    healingNpcState.epoch = (healingNpcState.epoch + 1) % epochMask
  end
end)
