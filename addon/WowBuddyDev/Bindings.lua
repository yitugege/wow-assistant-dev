-- Class-wide macro registration, independent of specialization detection.
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("Bindings", { "CoreLocale", "CoreButtons", "CoreControls" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local ADDON = WowBuddyDev
local definitions = {}
local collecting
local applying
-- 职业宏的 192 个槽位，按原插件各职业文件中的声明顺序；职业文件只为有宏的键调用 BindKey，
-- 未调用的槽位登记为空宏，继续留给玩家自己的按键绑定。
local CLASS_MACRO_SLOTS = {
  "NUMPAD1", "NUMPAD2", "NUMPAD3", "NUMPAD4", "NUMPAD5", "NUMPAD6", "NUMPAD7", "NUMPAD8",
  "NUMPAD9", "NUMPAD0", "CTRL-NUMPAD1", "CTRL-NUMPAD2", "CTRL-NUMPAD3", "CTRL-NUMPAD4", "CTRL-NUMPAD5", "CTRL-NUMPAD6",
  "CTRL-NUMPAD7", "CTRL-NUMPAD8", "CTRL-NUMPAD9", "CTRL-NUMPAD0", "ALT-NUMPAD1", "ALT-NUMPAD2", "ALT-NUMPAD3", "ALT-NUMPAD4",
  "ALT-NUMPAD5", "ALT-NUMPAD6", "ALT-NUMPAD7", "ALT-NUMPAD8", "ALT-NUMPAD9", "ALT-NUMPAD0", "ALT-CTRL-NUMPAD1", "ALT-CTRL-NUMPAD2",
  "ALT-CTRL-NUMPAD3", "ALT-CTRL-NUMPAD4", "ALT-CTRL-NUMPAD5", "ALT-CTRL-NUMPAD6", "ALT-CTRL-NUMPAD7", "ALT-CTRL-NUMPAD8", "ALT-CTRL-NUMPAD9", "ALT-CTRL-NUMPAD0",
  "SHIFT-F1", "SHIFT-F2", "SHIFT-F3", "SHIFT-F11", "SHIFT-F5", "SHIFT-F6", "SHIFT-F7", "SHIFT-F8",
  "SHIFT-F12", "SHIFT-F10", "CTRL-F1", "CTRL-F2", "CTRL-F3", "CTRL-F11", "CTRL-F5", "CTRL-F6",
  "CTRL-F7", "CTRL-F8", "CTRL-F12", "CTRL-F10", "ALT-CTRL-F1", "ALT-CTRL-F2", "ALT-CTRL-F3", "ALT-CTRL-F11",
  "ALT-CTRL-F5", "ALT-CTRL-F6", "ALT-CTRL-F7", "ALT-CTRL-F8", "ALT-CTRL-F12", "ALT-CTRL-F10", "CTRL-SHIFT-F1", "CTRL-SHIFT-F2",
  "CTRL-SHIFT-F3", "CTRL-SHIFT-F11", "CTRL-SHIFT-F5", "CTRL-SHIFT-F6", "CTRL-SHIFT-F7", "CTRL-SHIFT-F8", "CTRL-SHIFT-F12", "CTRL-SHIFT-F10",
  "ALT-CTRL-SHIFT-F1", "ALT-CTRL-SHIFT-F2", "ALT-CTRL-SHIFT-F3", "ALT-CTRL-SHIFT-F11", "ALT-CTRL-SHIFT-F5", "ALT-CTRL-SHIFT-F6", "ALT-CTRL-SHIFT-F7", "ALT-CTRL-SHIFT-F8",
  "ALT-CTRL-SHIFT-F12", "ALT-CTRL-SHIFT-F10", "ALT-F1", "ALT-F2", "ALT-F3", "ALT-F11", "ALT-F5", "ALT-F6",
  "ALT-F7", "ALT-F8", "ALT-F12", "ALT-F10", "ALT-SHIFT-F1", "ALT-SHIFT-F2", "ALT-SHIFT-F3", "ALT-SHIFT-F11",
  "ALT-SHIFT-F5", "ALT-SHIFT-F6", "ALT-SHIFT-F7", "ALT-SHIFT-F8", "ALT-SHIFT-F12", "ALT-SHIFT-F10", "ALT-CTRL-SHIFT--", "CTRL-SHIFT--",
  "ALT-CTRL--", "ALT-SHIFT--", "CTRL--", "SHIFT--", "ALT--", "ALT-CTRL-SHIFT-=", "CTRL-SHIFT-=", "ALT-CTRL-=",
  "ALT-SHIFT-=", "CTRL-=", "SHIFT-=", "ALT-=", "ALT-CTRL-SHIFT-[", "CTRL-SHIFT-[", "ALT-CTRL-[", "ALT-SHIFT-[",
  "CTRL-[", "SHIFT-[", "ALT-[", "ALT-CTRL-SHIFT-]", "CTRL-SHIFT-]", "ALT-CTRL-]", "ALT-SHIFT-]", "CTRL-]",
  "SHIFT-]", "ALT-]", "ALT-CTRL-SHIFT-\\", "CTRL-SHIFT-\\", "ALT-CTRL-\\", "ALT-SHIFT-\\", "CTRL-\\", "SHIFT-\\",
  "ALT-\\", "ALT-CTRL-SHIFT-,", "CTRL-SHIFT-,", "ALT-CTRL-,", "ALT-SHIFT-,", "CTRL-,", "SHIFT-,", "ALT-,",
  "ALT-CTRL-SHIFT-.", "CTRL-SHIFT-.", "ALT-CTRL-.", "ALT-SHIFT-.", "CTRL-.", "SHIFT-.", "ALT-.", "ALT-CTRL-SHIFT-/",
  "CTRL-SHIFT-/", "ALT-CTRL-/", "ALT-SHIFT-/", "CTRL-/", "SHIFT-/", "ALT-/", "ALT-CTRL-SHIFT-INSERT", "CTRL-SHIFT-INSERT",
  "ALT-CTRL-INSERT", "ALT-SHIFT-INSERT", "CTRL-INSERT", "SHIFT-INSERT", "ALT-INSERT", "ALT-CTRL-SHIFT-PAGEUP", "CTRL-SHIFT-PAGEUP", "ALT-CTRL-PAGEUP",
  "ALT-SHIFT-PAGEUP", "CTRL-PAGEUP", "SHIFT-PAGEUP", "ALT-PAGEUP", "ALT-CTRL-SHIFT-PAGEDOWN", "CTRL-SHIFT-PAGEDOWN", "ALT-CTRL-PAGEDOWN", "ALT-SHIFT-PAGEDOWN",
  "CTRL-PAGEDOWN", "SHIFT-PAGEDOWN", "ALT-PAGEDOWN", "ALT-CTRL-SHIFT-NUMPADDIVIDE", "ALT-CTRL-NUMPADDIVIDE", "CTRL-NUMPADDIVIDE", "ALT-NUMPADDIVIDE", "ALT-CTRL-NUMPADMULTIPLY",
}
local slotIndex = {}
for index, key in ipairs(CLASS_MACRO_SLOTS) do
  slotIndex[key] = index
end
ADDON.CLASS_MACRO_SLOTS = CLASS_MACRO_SLOTS

local function currentDefinition()
  local _, classToken = UnitClass("player")
  return definitions[classToken]
end

function ADDON.BindKey(key, macroText)
  assert(type(key) == "string" and key ~= "", "Invalid class binding key")
  assert(type(macroText) == "string", "Invalid class macro text")
  if collecting then
    assert(slotIndex[key], "Unknown class binding slot: " .. key)
    assert(collecting.byKey[key] == nil, "Duplicate class binding: " .. key)
    collecting.byKey[key] = macroText
    if macroText ~= "" then
      collecting.usedKeys[#collecting.usedKeys + 1] = key
    end
    return true
  end
  assert(applying, "BindKey must run inside RegisterClassMacros")
  -- Empty slots stay available to the player's normal bindings.
  if macroText == "" then
    return true
  end
  local body = ADDON.LocalizeMacroBody(macroText)
  local ok, bound = pcall(ADDON.CreateSecureButton, "class_" .. key, key, body)
  return ok and bound
end

function ADDON.RegisterClassMacros(classToken, initializer)
  assert(type(classToken) == "string" and type(initializer) == "function")
  local definition = {class = classToken, initializer = initializer, keys = {}, usedKeys = {}, byKey = {}}
  collecting = definition
  local ok, err = pcall(initializer)
  collecting = nil
  assert(ok, err)
  for _, key in ipairs(CLASS_MACRO_SLOTS) do
    definition.keys[#definition.keys + 1] = key
    if definition.byKey[key] == nil then
      definition.byKey[key] = ""
    end
  end
  assert(#definition.keys == 192, "Class macro table must declare 192 slots: " .. classToken)
  definitions[classToken] = definition
  if ADDON.InvalidateControlBindingConflicts then
    ADDON.InvalidateControlBindingConflicts()
  end
end

function ADDON.ApplyClassMacros()
  local definition = currentDefinition()
  if not definition then
    return false
  end
  applying = definition
  local ok, err = pcall(definition.initializer)
  applying = nil
  if not ok then
    error(err, 0)
  end
  return true
end

function ADDON.GetClassMacroKeys()
  local definition = currentDefinition()
  return definition and definition.usedKeys or {}
end

function ADDON.GetClassMacroInfo()
  local definition = currentDefinition()
  if definition then
    return definition.class, #definition.keys, #definition.usedKeys
  end
end

function ADDON.GetClassBindingAction(actionKey, bindingKey)
  local definition = currentDefinition()
  local macro = definition and definition.byKey[bindingKey]
  if macro and macro ~= "" then
    return "class_" .. bindingKey
  end
  return actionKey
end

function ADDON.GetClassDefaultMacro(bindingKey)
  local definition = currentDefinition()
  return definition and definition.byKey[bindingKey]
end
