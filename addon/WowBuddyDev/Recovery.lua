-- 脱战恢复。只从背包读取配置物品，实际使用交给现有的安全宏按钮。
local addon = WowBuddyDev
local packetBase = 0xC00000
local conjureBase = 0x800000
local unavailable = 83
local retrying = 85
local consuming = 86
local bagFull = 87
local conjureReceiptWait = 6
local function packet(startPercent, resumePercent, code, conjuring)
  return (conjuring and conjureBase or packetBase) + (startPercent * 128 + resumePercent) * 128 + code
end

-- 《无限》1.60.1.70862 的 SpellEffect Create Item 行，最高等级在前。
local conjureRanks = {
  food = {{28612, 22895}, {10145, 8076}, {10144, 8075}, {6129, 1487}, {990, 1114}, {597, 1113}, {587, 5349}},
  water = {{468766, 231778}, {10140, 8079}, {10139, 8078}, {10138, 8077}, {6127, 3772},
           {5506, 2136}, {5505, 2288}, {5504, 5350}},
}
local bindings, hookedButtons = {}, {}
local knownRanks, missingConjureNames = {}, {}
local armed, failures, pending, consumed = {}, {}, nil, {}

local function reset()
  armed, failures, pending, consumed = {}, {}, nil, {}
end

local function read(func, ...)
  if type(func) ~= "function" then return nil end
  local ok, value = pcall(func, ...)
  if ok and (not issecretvalue or not issecretvalue(value)) then return value end
end

local function wholeNumber(value, minValue, maxValue)
  local n = tonumber(value)
  return n and n >= minValue and n <= maxValue and n % 1 == 0 and n or nil
end

function addon.GetGeneralBagFreeSlots()
  if not C_Container then return end
  local free = 0
  for bag = 0, NUM_BAG_SLOTS or 4 do
    local size = wholeNumber(read(C_Container.GetContainerNumSlots, bag), 0, 1023)
    if not size then return end
    if size > 0 then
      local ok, slots, family = pcall(C_Container.GetContainerNumFreeSlots, bag)
      if not ok or (issecretvalue and (issecretvalue(slots) or issecretvalue(family)))
          or type(family) ~= "number" or type(slots) ~= "number" or not wholeNumber(slots, 0, size) then return end
      if family == 0 then free = free + slots end
    end
  end
  return free
end

local function itemID(value)
  if value == nil or value == "" then return 0 end
  local text = tostring(value)
  local id = text:match("^%s*(%d+)%s*$") or text:match("|Hitem:(%d+):") or text:match("^item:(%d+)$")
  return wholeNumber(id, 0, 2147483647)
end

local function normalize(settings)
  local hs = wholeNumber(settings.healthStart, 0, 99)
  local hr = wholeNumber(settings.healthResume, 1, 100)
  local ms = wholeNumber(settings.manaStart, 0, 99)
  local mr = wholeNumber(settings.manaResume, 1, 100)
  if not (hs and hr and ms and mr and hs < hr and ms < mr) then
    return nil, "阈值必须是整数，且开始值小于继续值。开始填 0 可关闭对应检查。"
  end
  local food, water = itemID(settings.food), itemID(settings.water)
  if not food or not water then return nil, "请从背包拖入物品，或填写有效的物品 ID。" end
  return {enabled=settings.enabled == true, healthStart=hs, healthResume=hr, manaStart=ms, manaResume=mr,
    food=food, water=water}
end

local defaults = {enabled=false, healthStart=50, healthResume=90, manaStart=50, manaResume=90, food=0, water=0}
local lastSaved, loadedSettings
local function getSettings()
  local saved = addon.DB and addon.DB.recovery
  if saved ~= lastSaved or not loadedSettings then
    lastSaved = saved
    loadedSettings = type(saved) == "table" and normalize(saved) or defaults
  end
  return loadedSettings
end

function addon.GetRecoverySettings()
  local copy = {}
  for key, value in pairs(getSettings()) do copy[key] = value end
  return copy
end

function addon.SaveRecoverySettings(settings)
  if read(InCombatLockdown) ~= false then return false, "请脱战后保存自动恢复设置。" end
  local checked, message = normalize(settings)
  if not checked then return false, message end
  addon.DB.recovery = checked
  reset()
  addon.RefreshMacroBindings()
  return true
end

local function itemCount(id)
  if C_Item and C_Item.GetItemCount then
    return read(C_Item.GetItemCount, id, false, false)
  end
  return read(GetItemCount, id)
end

local function trackClick(kind)
  if armed[kind] and not pending and read(UnitAffectingCombat, "player") == false then
    pending = armed[kind]
    armed = {}
    pending.deadline = GetTime() + (pending.conjure and conjureReceiptWait or 3)
  end
end

local function bestConjure(kind)
  local _, class = UnitClass("player")
  if class ~= "MAGE" then return end
  for _, rank in ipairs(conjureRanks[kind]) do
    if read(addon.IsSpellKnown, rank[1]) == true then return rank end
  end
end

local function conjureSpellName(spell)
  local name = read(C_Spell and C_Spell.GetSpellName, spell) or read(GetSpellInfo, spell)
  if type(name) ~= "string" or name == "" or name:find("[%c;]") then return nil end
  local subtext = read(C_Spell and C_Spell.GetSpellSubtext, spell)
  if type(subtext) == "string" and subtext ~= "" and not subtext:find("[%c;()]") then
    return name .. "(" .. subtext .. ")"
  end
  return name
end

local function bindRecovery(reserved, kind, id, body, spell, freeOnly)
  local action = "recovery_" .. kind
  local key, index = addon.FindFreeAutomationKey(reserved)
  while key and freeOnly and (read(GetBindingAction, key, false) ~= "" or read(GetBindingAction, key, true) ~= "") do
    reserved[key] = true
    key, index = addon.FindFreeAutomationKey(reserved)
  end
  if not key or index > 81 then return end
  local ok, bound = pcall(addon.CreateSecureButton, action, key, body)
  if not ok or not bound then
    if not ok and addon.ReportMacroBindingError then addon.ReportMacroBindingError(action, bound) end
    return
  end
  reserved[key] = true
  local button = addon.GetSecureButton(action)
  if not button or type(button.HookScript) ~= "function" then return end
  if hookedButtons[kind] ~= button then
    button:HookScript("OnClick", function() trackClick(kind) end)
    hookedButtons[kind] = button
  end
  bindings[kind] = {id=id, index=index, spell=spell, key=key, button=button, body=body, freeOnly=freeOnly}
end

local function bindItem(reserved, kind, id, freeOnly)
  bindRecovery(reserved, kind, id, "/use [nocombat,nochanneling] item:" .. id, nil, freeOnly)
end

function addon.ApplyRecoveryBindings()
  bindings, knownRanks, missingConjureNames = {}, {}, {}
  local config = getSettings()
  if not config.enabled then return end
  local reserved = {}
  for _, kind in ipairs({"food", "water"}) do
    local id = config[kind]
    local threshold = kind == "food" and config.healthStart or config.manaStart
    if id > 0 and threshold > 0 then bindItem(reserved, kind, id) end
  end
  for _, kind in ipairs({"food", "water"}) do
    local threshold = kind == "food" and config.healthStart or config.manaStart
    local rank = threshold > 0 and bestConjure(kind) or nil
    knownRanks[kind] = rank
    if rank then
      local spell, id = rank[1], rank[2]
      if id ~= config[kind] then bindItem(reserved, "conjured_" .. kind, id, true) end
      local name = conjureSpellName(spell)
      missingConjureNames[kind] = name == nil
      if name and bindings[id == config[kind] and kind or "conjured_" .. kind] then
        bindRecovery(reserved, "conjure_" .. kind, id, "/cast [nocombat,nochanneling] " .. name, spell, true)
      end
    end
  end
end

local function bindingAvailable(binding)
  local button = binding.button
  local name = read(button.GetName, button)
  return type(name) == "string" and name ~= ""
      and (not binding.freeOnly or read(GetBindingAction, binding.key, false) == "")
      and read(GetBindingAction, binding.key, true) == "CLICK " .. name .. ":LeftButton"
      and read(button.GetAttribute, button, "type") == "macro"
      and read(button.GetAttribute, button, "macrotext") == binding.body
end

local function retryWaiting(kind, id, count, now)
  local failure = failures[kind]
  if not failure then return false end
  if id ~= failure.id or count ~= failure.inventory then
    failures[kind] = nil
    return false
  end
  return now < failure.retryAt
end

local function itemStatus(kind, id, now, producedBy, resource)
  if id == 0 then return 0 end
  local count = itemCount(id)
  if type(count) ~= "number" then return unavailable end
  if count <= 0 then failures[kind] = nil; return 0 end
  if producedBy then failures[producedBy] = nil end
  if retryWaiting(kind, id, count, now) then return retrying end
  local binding = bindings[kind]
  if not binding or binding.id ~= id or not bindingAvailable(binding) then return unavailable end
  armed[kind] = {kind=kind, id=id, count=count, resource=resource}
  return binding.index
end

local function supplyStatus(kind, id, now)
  if pending then return 82 end
  local rank = knownRanks[kind]
  local other = consumed[kind == "food" and "water" or "food"]
  if consumed[kind] or (other and (other.id == id or (rank and other.id == rank[2]))) then return consuming end
  local action = "conjure_" .. kind
  local status = itemStatus(kind, id, now, rank and rank[2] == id and action, kind)
  -- 配置物品不可用或等待重试时，也可以使用已确认有库存的最高等级补给。
  if status ~= 0 and (not rank or rank[2] == id or (status ~= retrying and status ~= unavailable)) then return status end
  if rank and rank[2] ~= id then
    local alternate = itemStatus("conjured_" .. kind, rank[2], now, action, kind)
    if alternate ~= 0 then return alternate end
  end
  if status == unavailable then return status end
  local binding = bindings[action]
  if not binding then return status end
  -- 此处已确认最高等级制造品没有库存，配置物品正在退避时也需要腾出空位。
  if addon.GetGeneralBagFreeSlots() == 0 then return bagFull end
  if retryWaiting(action, binding.id, 0, now) then return retrying end
  if not bindingAvailable(binding) then return unavailable end
  if read(addon.IsSpellUsable, binding.spell) ~= true then return status == 0 and 82 or status end
  armed[action] = {kind=action, id=binding.id, count=0, conjure=true, spell=binding.spell}
  return binding.index, true
end

local function update(allowed, config)
  if addon.DB.masterSwitch ~= true then reset(); return 0, 0 end
  if not config.enabled then
    reset()
    if allowed and (config ~= defaults or addon.DB.recovery == nil)
        and read(UnitAffectingCombat, "player") == false and read(UnitIsDeadOrGhost, "player") == false
        and read(InCombatLockdown) == false then
      return 0, 0, 0xB08000 + config.healthStart * 128 + config.manaStart
    end
    return 0, 0
  end
  local combat, dead = read(UnitAffectingCombat, "player"), read(UnitIsDeadOrGhost, "player")
  if combat == true or dead == true then reset(); return 0, 0 end
  local now = GetTime()
  local speed = read(GetUnitSpeed, "player")
  if type(speed) == "number" and speed > 0 then
    consumed = {}
    if pending and not pending.conjure then pending.interrupted = true end
  end
  for kind, effect in pairs(consumed) do
    if now >= effect.untilTime then consumed[kind] = nil end
  end
  if pending then
    local remaining = itemCount(pending.id)
    if type(remaining) == "number" and (pending.conjure and remaining > pending.count
        or not pending.conjure and remaining < pending.count) then
      if pending.conjure then
        consumed = {}
      elseif not pending.interrupted then
        consumed[pending.resource] = {id=pending.id, untilTime=now + 35}
      end
      failures[pending.kind] = nil
      pending = nil
    elseif now >= pending.deadline then
      local previous = failures[pending.kind]
      local attempts = math.min(5, (previous and previous.attempts or 0) + 1)
      local delay = attempts < 2 and 0 or 15 * 2 ^ (attempts - 2)
      failures[pending.kind] = {attempts=attempts, id=pending.id, inventory=pending.count, retryAt=now + delay}
      pending = nil
    end
  end
  local focusOK, focus = true, nil
  if GetCurrentKeyBoardFocus then focusOK, focus = pcall(GetCurrentKeyBoardFocus) end
  local code = 82
  if combat ~= false or dead ~= false or read(InCombatLockdown) ~= false then
    code = unavailable
  elseif allowed and focusOK and focus == nil and speed == 0
      and read(IsMounted) ~= true and read(UnitOnTaxi, "player") ~= true
      and read(addon.GetPlayerCastState, true) == false and read(addon.IsGcdActive) ~= true then
    code = nil
  end
  local food, water, conjureFood, conjureWater = code, code
  if not code then
    food, conjureFood = supplyStatus("food", config.food, now)
    water, conjureWater = supplyStatus("water", config.water, now)
    -- 仅在造物可能打断另一项恢复时，才需要桌面区分消耗中与普通等待。
    if food == consuming and not conjureWater and water ~= bagFull then food = 82 end
    if water == consuming and not conjureFood and food ~= bagFull then water = 82 end
  end
  return packet(config.healthStart, config.healthResume, food, conjureFood),
         packet(config.manaStart, config.manaResume, water, conjureWater)
end

function addon.UpdateRecovery(allowed)
  armed = {}
  local config = getSettings()
  local ok, food, water, disabled = pcall(update, allowed, config)
  if ok then return food, water, disabled end
  if not config.enabled then return 0, 0 end
  return packet(config.healthStart, config.healthResume, unavailable),
         packet(config.manaStart, config.manaResume, unavailable)
end

function addon.IsRecoveryActive()
  local now = GetTime()
  if pending and now < pending.deadline then return true end
  for _, effect in pairs(consumed) do
    if now < effect.untilTime then return true end
  end
  return false
end

function addon.GetRecoveryHandoffWord()
  local config = getSettings()
  if not config.enabled or not addon.IsAutoTargetCombatSettling() then return 0 end
  -- 战斗计时仍由原字段上报。仅用战斗中闲置的 TTF 传两个开始阈值。
  return 0xB00000 + config.healthStart * 128 + config.manaStart
end

local frame = CreateFrame("Frame")
local function conjureBindingNeedsRefresh(kind)
  local rank = bestConjure(kind)
  return rank ~= knownRanks[kind] or (rank and missingConjureNames[kind] and conjureSpellName(rank[1]) ~= nil)
end

frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("SPELLS_CHANGED")
frame:RegisterUnitEvent("UNIT_SPELLCAST_SUCCEEDED", "player")
frame:SetScript("OnEvent", function(_, event, _unit, _castGUID, spell)
  if event == "PLAYER_ENTERING_WORLD" then reset(); return end
  if event == "UNIT_SPELLCAST_SUCCEEDED" then
    if pending and pending.conjure and not pending.castConfirmed and type(spell) == "number"
        and (not issecretvalue or not issecretvalue(spell)) and spell == pending.spell then
      local now = GetTime()
      if now < pending.deadline then
        pending.castConfirmed = true
        pending.deadline = now + conjureReceiptWait
      end
    end
    return
  end
  local config = getSettings()
  if not config.enabled then return end
  if (config.healthStart > 0 and conjureBindingNeedsRefresh("food"))
      or (config.manaStart > 0 and conjureBindingNeedsRefresh("water")) then
    addon.RefreshMacroBindings()
  end
end)
