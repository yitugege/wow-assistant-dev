-- 接入原 DirectCast 的显式施法与占槽分支；所有 API 均受游戏自身权限约束。
-- 返回 true 沿用原 pcall 语义，只表示调用未抛错，不证明技能已经释放。
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("DirectCastActions", { "CoreClassData", "CoreButtons", "DirectCastSlots" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local ADDON = WowBuddyDev
local DC = ADDON.DirectCast

-- 仅标记同步调用期间的诊断上下文；保留pcall返回与原有执行顺序。
local function actionCall(api, fn, ...)
  local previous = DC.activeCall
  DC.activeCall = api
  local ok, result = pcall(fn, ...)
  DC.activeCall = previous
  return ok, result
end

local function macroForAction(actionKey)
  if type(ADDON.GetBoundMacro) == "function" then
    return ADDON.GetBoundMacro(actionKey)
  end
  local macro = ADDON.classData and ADDON.classData.DEFAULT_MACROS
      and ADDON.classData.DEFAULT_MACROS[actionKey]
  if not macro and ADDON.macroBindingRegistry then
    local entry = ADDON.macroBindingRegistry[actionKey]
    if entry then macro = entry.macroText end
  end
  return macro
end
DC.GetActionMacro = macroForAction

local function slotIsEmpty(slot)
  local ok, kind = actionCall("GetActionInfo", GetActionInfo, slot)
  return ok and (not issecretvalue or not issecretvalue(kind)) and (kind == nil or kind == "empty")
end

local function findEmptySlot()
  for slot = 1, 144 do
    if slotIsEmpty(slot) then return slot end
  end
end

local function cursorAction()
  local ok, kind, _, _, spellID = pcall(GetCursorInfo)
  if not ok or (issecretvalue and (issecretvalue(kind) or issecretvalue(spellID))) then return false end
  return true, kind, spellID
end

local function cursorHasSpell(spellID)
  local known, kind, cursorID = cursorAction()
  return known and kind == "spell" and cursorID == spellID
end

function DC.EnsureSlotForSpell(spellID)
  local slot = DC.FindSlotForSpell(spellID)
  if slot then return slot end
  local known, kind = cursorAction()
  if not known or kind ~= nil then return false end
  local empty = findEmptySlot()
  if not empty then return false end
  local picked, result = actionCall("PickupSpell", PickupSpell, spellID)
  if not cursorHasSpell(spellID) then return false end
  local confirmed = false
  if picked and (not issecretvalue or not issecretvalue(result)) and result ~= false and slotIsEmpty(empty) then
    actionCall("PlaceAction", PlaceAction, empty)
    confirmed = DC.IsSpellInSlot(empty, spellID)
  end
  if cursorHasSpell(spellID) then actionCall("ClearCursor", ClearCursor) end
  return confirmed and empty or false
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
  local manualSlot = DC.GetManualSlot(actionKey)
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
  local slot = DC.EnsureSlotForSpell(sid)
  if slot and actionCall("UseAction", UseAction, slot, unit) then return true, "slot" .. slot end
  local manualSlot = DC.GetManualSlot(actionKey)
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
  elseif msg == "on" then DC.enabled = true
  elseif msg == "hook off" then DC.hookEnabled = false
  elseif msg == "hook on" then DC.hookEnabled = true
  elseif msg == "log clear" and type(DC.ClearHookLog) == "function" then
    DC.ClearHookLog()
    print("[DirectCast] 按键记录已清空；/reload 后写入存档。")
  end
  print("[DirectCast] 开关: " .. (DC.enabled and "开启" or "关闭"))
  print("用法: /dc on|off；/dc test <动作键> 显式调用（返回值不代表施法生效）")
  if type(DC.HookStatus) == "function" then
    local hook = DC.HookStatus()
    print(string.format("按钮挂钩: %s，已挂 %d 个，拦下 %d 次，战斗中未拦 %d 次，出错 %d 次（/dc hook on|off）",
      hook.enabled and "开启" or "关闭", hook.installed, hook.swallowed, hook.combatSkipped, hook.errors))
    print(string.format("按键记录 %d 条（/reload 后写入存档；/dc log clear 清空）", hook.logged or 0))
    print("挂钩只在脱战时拦下移动中的读条技能和光环仍在的自Buff，不直接施法。")
  else
    print("移动意图补发与自Buff续挂已接入；按钮挂钩模块未加载。")
  end
  print("沿用原行为：off不清除已有移动意图，也不禁止显式test命令。")
end
