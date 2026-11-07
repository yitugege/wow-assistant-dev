-- 接入原 DirectCast 的显式施法与占槽分支；所有 API 均受游戏自身权限约束。
-- 返回 true 沿用原 pcall 语义，只表示调用未抛错，不证明技能已经释放。
local ADDON = WowBuddyDev
local DC = ADDON.DirectCast
local autoSlotCache = {}

-- 仅标记同步调用期间的诊断上下文；保留pcall返回与原有执行顺序。
local function actionCall(api, fn, ...)
  local previous = DC.activeCall
  DC.activeCall = api
  local ok, result = pcall(fn, ...)
  DC.activeCall = previous
  return ok, result
end

local function macroForAction(actionKey)
  local macro = ADDON.classData and ADDON.classData.DEFAULT_MACROS
      and ADDON.classData.DEFAULT_MACROS[actionKey]
  if not macro and ADDON.macroBindingRegistry then
    local entry = ADDON.macroBindingRegistry[actionKey]
    if entry then macro = entry.macroText end
  end
  if not macro and type(ADDON.GetBoundMacro) == "function" then
    macro = ADDON.GetBoundMacro(actionKey)
  end
  return macro
end
DC.GetActionMacro = macroForAction

local function findEmptySlot()
  for slot = 1, 144 do
    local ok, kind = actionCall("GetActionInfo", GetActionInfo, slot)
    if ok and (kind == nil or kind == "empty") then return slot end
  end
end

function DC.EnsureSlotForSpell(spellID)
  if autoSlotCache[spellID] then return autoSlotCache[spellID] end
  local slot = DC.FindSlotForSpell(spellID)
  if slot then autoSlotCache[spellID] = slot; return slot end
  local empty = findEmptySlot()
  if empty and actionCall("PickupSpell", PickupSpell, spellID) then
    -- 保留原有缺陷：PlaceAction 即使抛错仍缓存槽位，不能据此报告放置成功。
    actionCall("PlaceAction", PlaceAction, empty)
    autoSlotCache[spellID] = empty
    return empty
  end
  autoSlotCache[spellID] = false
  return false
end

local function castFallback(actionKey, unitOverride)
  local macro = macroForAction(actionKey)
  if not macro then return nil, "no-macro" end
  local spellName, unit = DC.ResolveMacro(macro)
  if not spellName then return nil, "no-spell" end
  if unitOverride then unit = unitOverride end
  local sid = DC.SpellIDForName(spellName)
  if sid then
    local slot = DC.FindSlotForSpell(sid)
    if slot and actionCall("UseAction", UseAction, slot, unit) then return true, "slot" .. slot end
  end
  local manualSlot = DC.slots[actionKey]
  if manualSlot and actionCall("UseAction", UseAction, manualSlot, unit) then return true, "slot" .. manualSlot end
  if sid and actionCall("CastSpellByID", CastSpellByID, sid, unit) then return true, sid end
  return nil, "no-slot-绑槽位: /dcbind " .. actionKey .. " <动作条槽位号>"
end

function DC.Cast(actionKey, unitOverride)
  local macro = macroForAction(actionKey)
  if not macro then return nil, "no-macro" end
  local spellName, unit = DC.ResolveMacro(macro)
  if not spellName then return nil, "no-spell" end
  if unitOverride then unit = unitOverride end
  if DC.GuardBlocked(spellName) then return nil, "blocked-aura-present" end
  local sid = DC.SpellIDForName(spellName)
  if not sid then return castFallback(actionKey, unitOverride) end
  local slot = DC.FindSlotForSpell(sid) or DC.EnsureSlotForSpell(sid)
  if slot and actionCall("UseAction", UseAction, slot, unit) then return true, "slot" .. slot end
  local manualSlot = DC.slots[actionKey]
  if manualSlot and actionCall("UseAction", UseAction, manualSlot, unit) then return true, "slot" .. manualSlot end
  if actionCall("CastSpellByID", CastSpellByID, sid, unit) then return true, sid end
  return nil, "no-slot-自动占槽失败: /dcbind " .. actionKey .. " <动作条槽位号>"
end

DC.enabled = true
SLASH_DIRECTCAST1 = "/dc"
SlashCmdList.DIRECTCAST = function(msg)
  msg = string.lower(msg or "")
  local action = msg:match("^test%s+(.+)$")
  if action then
    local ok, result = DC.Cast(action)
    print(string.format("|cff00ff88[DirectCast]|r 测试 %s: %s %s",
      action, tostring(ok), type(result) == "number" and ("spellID=" .. result) or (result or "")))
    return
  end
  if msg == "off" then DC.enabled = false
  elseif msg == "on" then DC.enabled = true end
  print("[DirectCast] 开关: " .. (DC.enabled and "开启" or "关闭"))
  print("用法: /dc on|off；/dc test <动作键> 显式调用（返回值不代表施法生效）")
  print("移动意图补发与自Buff续挂已接入；尚无自动按钮挂钩。")
  print("沿用原行为：off不清除已有移动意图，也不禁止显式test命令。")
end
