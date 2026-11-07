-- ==========================================================================
-- 文件：68c604.lua
-- 来源：P07483180.rar → P07483180/68c604.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：68c604.lua → ActionKeyCheck.lua（按功能重命名）
-- 作用：动作键位规范化与校验（VERIFIED_ACTION_KEYS）
-- ==========================================================================
local verifiedFunctionKeys = { "F6", "F7", "F8", "F9", "F10", "F11", "F12" }
-- 功能：把各种写法的按键名归一成统一形式：全大写、修饰键按 CTRL-ALT-SHIFT 排序、小键盘别名换成客户端叫法。
-- 入参：rawKeyText 按键名，任意写法。
-- 出参：归一后的按键名；入参不是字符串时返回 nil。
-- 说明：只把 CTRL / ALT / SHIFT 当修饰键前缀，其余前缀（比如 NUMPAD）一律不切；小键盘的加号和减号客户端叫 NUMPADADD / NUMPADSUBTRACT，这里把常见写法换过去，否则同一个键会算出两个不同的名字。
function WowBuddyDev.NormalizeActionKey(rawKeyText)
  if type(rawKeyText) ~= "string" then
    return nil
  end
  local keyText = rawKeyText:upper()
  local modifierFlags = {}
  while true do
    local modifierPrefix, remainingKeyText = keyText:match("^(%a+)%-(.+)$")
    if modifierPrefix ~= "CTRL" and (modifierPrefix ~= "ALT" and modifierPrefix ~= "SHIFT") then
      break
    end
    modifierFlags[modifierPrefix] = true
    keyText = remainingKeyText
  end
  if keyText == "NUMPADPLUS" then
    keyText = "NUMPADADD"
  end
  if keyText == "NUMPADMINUS" then
    keyText = "NUMPADSUBTRACT"
  end
  return (modifierFlags.CTRL and "CTRL-" or "") .. (modifierFlags.ALT and "ALT-" or "") .. (modifierFlags.SHIFT and "SHIFT-" or "") .. keyText
end
local bindableKeyNames = {
  "F6",
  "F7",
  "F8",
  "F9",
  "F10",
  "F11",
  "F12",
  "8",
  "9",
  "0",
  "-",
  "=",
  "[",
  "]",
  ";",
  "'",
  ",",
  ".",
  "\\",
  "UP",
  "DOWN",
  "LEFT",
  "RIGHT",
  "INSERT",
  "DELETE",
  "HOME",
  "END",
}
WowBuddyDev.ACTION_KEY_ORDER = {}
WowBuddyDev.VERIFIED_ACTION_KEYS = {}
for index, bindableKeyName in ipairs(bindableKeyNames) do
  table.insert(WowBuddyDev.ACTION_KEY_ORDER, bindableKeyName)
end
for index2, modifierName in ipairs({ "CTRL", "ALT" }) do
  for index3, innerKeyName in ipairs(bindableKeyNames) do
    table.insert(WowBuddyDev.ACTION_KEY_ORDER, modifierName .. "-" .. innerKeyName)
  end
end
for index4, functionKeyName in ipairs(verifiedFunctionKeys) do
  table.insert(WowBuddyDev.VERIFIED_ACTION_KEYS, functionKeyName)
end
for i = 1, 23, 1 do
  table.insert(WowBuddyDev.VERIFIED_ACTION_KEYS, "CTRL-" .. bindableKeyNames[i])
end
for i2 = 7, 12, 1 do
  table.insert(WowBuddyDev.VERIFIED_ACTION_KEYS, "ALT-F" .. i2)
end
for index5, altKeyName in ipairs({ "8", "9", "0", ";", "'" }) do
  table.insert(WowBuddyDev.VERIFIED_ACTION_KEYS, "ALT-" .. altKeyName)
end
