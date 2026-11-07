-- Class-wide macro registration, independent of specialization detection.
local ADDON = WowBuddyDev
local definitions = {}
local collecting
local applying

local function currentDefinition()
  local _, classToken = UnitClass("player")
  return definitions[classToken]
end

function ADDON.BindKey(key, macroText)
  assert(type(key) == "string" and key ~= "", "Invalid class binding key")
  assert(type(macroText) == "string", "Invalid class macro text")
  if collecting then
    assert(collecting.byKey[key] == nil, "Duplicate class binding: " .. key)
    collecting.byKey[key] = macroText
    collecting.keys[#collecting.keys + 1] = key
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
