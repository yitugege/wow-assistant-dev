-- ==========================================================================
-- 文件：d4c98a.lua
-- 来源：P07483180.rar → P07483180/d4c98a.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：d4c98a.lua → ChargeDisplay.lua（按功能重命名）
-- 作用：充能/层数直读（GetSpellChargeCount 等）
-- ==========================================================================
local getSpellDisplayCount = C_Spell and C_Spell.GetSpellDisplayCount
-- 功能：从候选法术 ID 里挑出客户端当前真正生效的那一个：优先取被替换后的法术，其次取已学会的。
-- 入参：spellID 首选法术 ID，可为 nil；spellIDs 候选列表，可为 nil。
-- 出参：挑中的法术 ID；都挑不出来时返回首选（或候选列表第一项）。
-- 说明：同一个技能可能有多个版本（专精替换、天赋替换），客户端只认当前生效的那个 ID —— 拿错了就读不到层数，所以先问 GetOverrideSpell，再问 IsSpellKnown。
function WowBuddyDev.ResolveChargeDisplaySpellID(spellID, spellIDs)
  local spellIDList = spellIDs or { spellID }
  local fallbackSpellID = spellID or spellIDList[1]
  if C_Spell and C_Spell.GetOverrideSpell then
    for index, candidateSpellID in ipairs(spellIDList) do
      local okOverride, overrideSpellID = pcall(C_Spell.GetOverrideSpell, candidateSpellID, 0, true)
      if okOverride and (type(overrideSpellID) == "number" and overrideSpellID ~= candidateSpellID) then
        return overrideSpellID
      end
    end
  end
  if C_SpellBook and C_SpellBook.IsSpellKnown then
    for index2, knownCandidateID in ipairs(spellIDList) do
      local okKnown, isKnown = pcall(C_SpellBook.IsSpellKnown, knownCandidateID)
      if okKnown and isKnown then
        return knownCandidateID
      end
    end
  end
  return fallbackSpellID
end
-- 功能：直读某个法术当前可用的充能/层数。
-- 入参：spellID 法术 ID；spellIDs 候选列表。
-- 出参：数字层数；接口不可用、ID 解析不出、或客户端给的值不是数字时返回 nil。
-- 说明：客户端给的可能是字符串形式的数字（受保护值），这时用 tonumber 确认它确实是个数之后「原样返回字符串」，不强行转成数字；确认不了就当读不到。
function WowBuddyDev.GetSpellChargeCount(spellID, spellIDs)
  if not getSpellDisplayCount then
    return nil
  end
  local resolvedSpellID = WowBuddyDev.ResolveChargeDisplaySpellID(spellID, spellIDs)
  if not resolvedSpellID then
    return nil
  end
  local ok, countValue = pcall(getSpellDisplayCount, resolvedSpellID)
  if ok then
    if type(countValue) == "number" then
      return countValue
    end
    if type(countValue) == "string" then
      local okNumber, numericValue = pcall(tonumber, countValue)
      if okNumber and type(numericValue) == "number" then
        return countValue
      end
    end
  end
  return nil
end
-- 功能：直读某个法术的充能显示原始值，不做任何转换。
-- 入参：spellID 法术 ID；spellIDs 候选列表。
-- 出参：true 加原始值；接口不可用、ID 解析不出、或调用失败时返回 false。
-- 说明：原始值用「不等于 nil」判断，所以字符串、表、受保护值都算读到了；这个函数是给调试命令看客户端到底吐了什么用的。
function WowBuddyDev.GetSpellChargeDisplayRaw(spellID, spellIDs)
  if not getSpellDisplayCount then
    return false
  end
  local resolvedSpellID = WowBuddyDev.ResolveChargeDisplaySpellID(spellID, spellIDs)
  if not resolvedSpellID then
    return false
  end
  local ok, rawValue = pcall(getSpellDisplayCount, resolvedSpellID)
  if ok and type(rawValue) ~= "nil" then
    return true, rawValue
  end
  return false
end
-- 功能：取出当前专精契约里所有 kind 为 charge_lua 的槽位。
-- 入参：无。
-- 出参：槽位数组 + 当前专精 ID；专精取不到时返回 nil, nil。
-- 说明：第二个返回值是专精 ID，只在打印时用来显示是哪个专精；契约表缺失时按空表处理，调用方会看到「无 charge_lua 字段」。
local function collectChargeSlots()
  local specIndex = GetSpecialization()
  if not specIndex then
    return nil, nil
  end
  local specID = GetSpecializationInfo(specIndex)
  local specSlots = WowBuddyDev._pixelStripV2BySpec and WowBuddyDev._pixelStripV2BySpec[specID]
  local chargeSlots = {}
  for index3, slot in ipairs(specSlots or {}) do
    if slot.kind == "charge_lua" then
      chargeSlots[#chargeSlots + 1] = slot
    end
  end
  return chargeSlots, specID
end
-- 功能：把某个契约槽位的充能数格式化成一行调试文本。
-- 入参：slot 契约槽位（读 spellID / spellIDs）。
-- 出参：文本 —— 能读到数字层数就给数字；否则给原始值加「(原值)」；连原始值都读不到时给一个破折号。
-- 说明：原始值可能是受保护的对象，tostring 会抛错，所以包了 pcall；抛错时退回字面量 secret。
local function formatChargeText(slot)
  local count = WowBuddyDev.GetSpellChargeCount(slot.spellID, slot.spellIDs)
  if count ~= nil then
    return tostring(count)
  end
  local okNumberRaw, rawValue = WowBuddyDev.GetSpellChargeDisplayRaw(slot.spellID, slot.spellIDs)
  if okNumberRaw then
    local okText, rawText = pcall(function()
      return tostring(rawValue) .. "(原值)"
    end)
    if okText then
      return rawText
    end
    return "secret"
  end
  return "—"
end
-- 功能：/pmscharge 的实现：把当前专精所有 charge_lua 槽位的候选 ID、当前 ID 和层数打到聊天框。
-- 入参：无。
-- 出参：无。
-- 说明：纯调试输出，契约里没有 charge_lua 字段时只打一行提示；只打印，不改任何状态。
function WowBuddyDev.DumpChargeValues()
  local slots, specID = collectChargeSlots()
  if not slots or #slots == 0 then
    print("当前专精契约无 charge_lua 字段")
    return
  end
  print(string.format("充能直读: 专精=%s API=%s 字段=%d", tostring(specID), getSpellDisplayCount and "可用" or "不可用", #slots))
  for index4, slot in ipairs(slots) do
    local spellIDList = slot.spellIDs or { slot.spellID }
    local idTexts = {}
    for index5, spellID in ipairs(spellIDList) do
      idTexts[#idTexts + 1] = tostring(spellID)
    end
    local resolvedSpellID = WowBuddyDev.ResolveChargeDisplaySpellID(slot.spellID, slot.spellIDs)
    print(string.format("%s 候选=[%s] 当前=%s 层数=%s", slot.name or slot.key or "?", table.concat(idTexts, ","), tostring(resolvedSpellID or "无"), formatChargeText(slot)))
  end
end
SLASH_PERMESCHARGE1 = "/pmscharge"
-- 功能：注册 /pmscharge 命令，转调 DumpChargeValues。
-- 入参：无。
-- 出参：无。
SlashCmdList.PERMESCHARGE = function()
  WowBuddyDev.DumpChargeValues()
end
SLASH_PERMESVARIANT1 = "/pmsvariant"
-- 功能：注册 /pmsvariant 命令：逐个列出 charge_lua 槽位的候选法术，并在客户端做过替换时显示替换后的 ID 和名字。
-- 入参：无。
-- 出参：无。
-- 说明：只打印，不改变任何状态；替换结果取 C_Spell.GetOverrideSpell，且只认数字。
SlashCmdList.PERMESVARIANT = function()
  local slots = collectChargeSlots()
  if not slots or #slots == 0 then
    print("当前专精契约无 charge_lua 字段")
    return
  end
  for index6, slot in ipairs(slots) do
    for index7, spellID in ipairs(slot.spellIDs or { slot.spellID }) do
      local currentSpellID = spellID
      if C_Spell and C_Spell.GetOverrideSpell then
        local ok, overrideSpellID = pcall(C_Spell.GetOverrideSpell, spellID, 0, true)
        if ok and type(overrideSpellID) == "number" then
          currentSpellID = overrideSpellID
        end
      end
      local spellInfo = C_Spell and (C_Spell.GetSpellInfo and C_Spell.GetSpellInfo(currentSpellID))
      print(string.format("%s 候选=%d 当前=[%s|%d]", slot.name or slot.key or "?", spellID, spellInfo and spellInfo.name or "?", currentSpellID))
    end
  end
end
