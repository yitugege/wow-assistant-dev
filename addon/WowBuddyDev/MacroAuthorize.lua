-- ==========================================================================
-- 文件：dc4fac.lua
-- 来源：P07483180.rar → P07483180/dc4fac.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：dc4fac.lua → MacroAuthorize.lua（按功能重命名）
-- 作用：宏授权与编译校验（含中文客户端判断）
-- ==========================================================================
WowBuddyDev = WowBuddyDev or {}
local origRegisterClass = WowBuddyDev.RegisterClass
local origGetDefaultMacro = WowBuddyDev.GetDefaultMacro
local reportedLocalizeErrors = {}
-- 功能：去掉字符串首尾的空白字符。
-- 入参：text 待处理文本。
-- 出参：去掉首尾空白后的新字符串。
-- 说明：只剥首尾 —— 中间的空格是宏语法的一部分（命令和参数之间），不能一起删。
local function trimText(text)
  return (text:gsub("^%s+", ""):gsub("%s+$", ""))
end
-- 功能：按换行符把整段宏拆成行数组。
-- 入参：sourceText 多行文本。
-- 出参：行字符串数组，每行都不含换行符。
-- 说明：空行也会保留成空字符串，所以数组下标就是源码行号 —— 授权表里的 line 直接拿它索引，行号不能因为空行而错位。
local function splitLines(sourceText)
  local lines = {}
  local lineStart = 1
  while true do
    local lineBreakPos = sourceText:find("\n", lineStart, true)
    if not lineBreakPos then
      table.insert(lines, sourceText:sub(lineStart))
      break
    end
    table.insert(lines, sourceText:sub(lineStart, lineBreakPos - 1))
    lineStart = lineBreakPos + 1
  end
  return lines
end
-- 功能：把授权里写的命令名归一成宏前缀：showtooltip 用 #，其余用 /。
-- 入参：commandName 命令名（如 showtooltip、cast）。
-- 出参：归一后的前缀字符串。
local function commandPrefix(commandName)
  if commandName == "showtooltip" then
    return "#showtooltip"
  end
  return "/" .. commandName
end
-- 功能：判断一行宏源码是不是以指定命令开头。
-- 入参：lineText 宏源码行；expectedCommand 期望的命令名。
-- 出参：布尔，true 表示这一行属于该命令。
-- 说明：只比前缀不够 —— 还要看命令名后面紧跟的字符必须是空白、方括号或行尾，否则 /cast 会把 /castsequence 那一行也认成自己。
local function lineStartsWithCommand(lineText, expectedCommand)
  local trimmedLine = lineText:gsub("^%s+", "")
  local lowerLine = trimmedLine:lower()
  local expectedPrefix = commandPrefix(expectedCommand)
  if lowerLine:sub(1, #expectedPrefix) ~= expectedPrefix then
    return false
  end
  local charAfterPrefix = lowerLine:sub(#expectedPrefix + 1, #expectedPrefix + 1)
  return charAfterPrefix == "" or charAfterPrefix == "[" or charAfterPrefix:match("%s") ~= nil
end
-- 功能：把文本中 startIndex 到 endIndex 这一段整体换成新内容。
-- 入参：text 原文本；startIndex 起始下标（含）；endIndex 结束下标（含）；replacement 替换内容。
-- 出参：替换后的新字符串。
-- 说明：两端下标都闭，和 string.find 返回的两个下标完全一致，可以直接配合使用。
local function replaceRange(text, startIndex, endIndex, replacement)
  return text:sub(1, startIndex - 1) .. replacement .. text:sub(endIndex + 1)
end
-- 功能：扫出文本里每一对方括号的起止下标。
-- 入参：sourceLine 宏源码行。
-- 出参：区间数组（每项是左括号下标和右括号下标）；出现没配对的左括号时返回 nil。
-- 说明：返回的区间专门用来判断某个位置是不是在条件块里面；不配对就返回 nil，让调用方放弃这次替换，免得把条件块改坏。
local function findBracketRanges(sourceLine)
  local ranges = {}
  local searchPos = 1
  while searchPos <= #sourceLine do
    local openPos = sourceLine:find("[", searchPos, true)
    if not openPos then
      break
    end
    local closePos = sourceLine:find("]", openPos + 1, true)
    if not closePos then
      return nil
    end
    table.insert(ranges, { openPos, closePos })
    searchPos = closePos + 1
  end
  return ranges
end
-- 功能：判断某个下标是否落在任一对方括号区间内。
-- 入参：position 待判断的下标；ranges 区间数组。
-- 出参：布尔。
local function isIndexInsideRanges(position, ranges)
  for index, range in ipairs(ranges) do
    if position >= range[1] and position <= range[2] then
      return true
    end
  end
  return false
end
-- 功能：把源值替换成授权后的值，只动方括号外面的第一处。
-- 入参：sourceLine 宏源码行；sourceValue 授权表里写的源值；authorizedValue 授权后要换成的值。
-- 出参：替换后的新字符串；找不到可替换处或括号不配对时返回 nil。
-- 说明：条件块里面的同名文本属于另一套语法，由 replaceConditionArgument 处理，这里必须跳过，否则会把条件判断误改成命令参数。
local function replaceOutsideBrackets(sourceLine, sourceValue, authorizedValue)
  local ranges = findBracketRanges(sourceLine)
  if not ranges then
    return nil
  end
  local searchPos = 1
  while searchPos <= #sourceLine do
    local matchStart, matchEnd = sourceLine:find(sourceValue, searchPos, true)
    if not matchStart then
      return nil
    end
    if not isIndexInsideRanges(matchStart, ranges) then
      return replaceRange(sourceLine, matchStart, matchEnd, authorizedValue)
    end
    searchPos = matchEnd + 1
  end
  return nil
end
-- 功能：在条件块里找到「条件名:条件值」那一段，把条件值替换成授权后的值。
-- 入参：sourceLine 宏源码行；ref 授权引用（读 condition_type / source_value）；authorizedValue 替换后的值。
-- 出参：替换后的新字符串；条件块里没有匹配的那一段时返回 nil。
-- 说明：按逗号切段、逐段比较条件名和条件值；替换位置是手工算出来的（段首空白 + 冒号偏移 + 值前空白），这些空白必须原样保留，位置算错就会改到别的字。
local function replaceConditionArgument(sourceLine, ref, authorizedValue)
  local ranges = findBracketRanges(sourceLine)
  if not ranges then
    return nil
  end
  local conditionType = ((ref.condition_type or "")):lower()
  for index2, range in ipairs(ranges) do
    local contentStart = range[1] + 1
    local contentEnd = range[2] - 1
    local scanPos = contentStart
    while scanPos <= contentEnd do
      local commaPos = sourceLine:find(",", scanPos, true)
      local segmentEnd = commaPos and math.min(commaPos - 1, contentEnd) or contentEnd
      local segmentText = sourceLine:sub(scanPos, segmentEnd)
      local segmentLeadingWs = segmentText:match("^(%s*)") or ""
      local trimmedSegment = trimText(segmentText)
      local segmentType, segmentValue = trimmedSegment:match("^([^:]+):(.*)$")
      if segmentType and (segmentValue and (trimText(segmentType):lower() == conditionType and trimText(segmentValue) == ref.source_value)) then
        local valueStartInSegment = trimmedSegment:find(":", 1, true) + 1
        local segmentValueText = trimmedSegment:sub(valueStartInSegment)
        local valueLeadingWs = segmentValueText:match("^(%s*)") or ""
        local valueStart = scanPos + #segmentLeadingWs + valueStartInSegment - 1 + #valueLeadingWs
        local valueEnd = valueStart + #ref.source_value - 1
        return replaceRange(sourceLine, valueStart, valueEnd, authorizedValue)
      end
      if not commaPos or commaPos > contentEnd then
        break
      end
      scanPos = commaPos + 1
    end
  end
  return nil
end
-- 功能：判断当前英雄天赋专精是否落在授权允许的列表里。
-- 入参：ref 授权引用（读 hero_applicability）。
-- 出参：布尔，true 表示允许编译这个引用。
-- 说明：列表为空表示不做限制；客户端没有 C_ClassTalents 这套接口时返回 false —— 查不出英雄天赋就不放行，宁可退回原版宏也不猜。
local function isHeroApplicable(ref)
  local heroApplicability = ref.hero_applicability or {}
  if #heroApplicability == 0 then
    return true
  end
  if not C_ClassTalents or not C_ClassTalents.GetActiveHeroTalentSpec then
    return false
  end
  local ok, activeHeroSpec = pcall(C_ClassTalents.GetActiveHeroTalentSpec)
  if not ok or not activeHeroSpec then
    return false
  end
  for index3, heroSpecID in ipairs(heroApplicability) do
    if heroSpecID == activeHeroSpec then
      return true
    end
  end
  return false
end
-- 功能：按法术 ID 取法术名，优先新接口 C_Spell.GetSpellInfo，取不到再退回旧全局 GetSpellInfo。
-- 入参：spellID 法术 ID。
-- 出参：法术名字符串；两代接口都取不到时返回 nil。
-- 说明：两个接口都套了 pcall —— 部分客户端上它们会抛错；取不到名字时由调用方按「客户端无法解析授权 SpellID」处理。
local function resolveSpellName(spellID)
  if C_Spell and C_Spell.GetSpellInfo then
    local okSpellInfo, spellInfo = pcall(C_Spell.GetSpellInfo, spellID)
    if okSpellInfo and spellInfo then
      return spellInfo.name
    end
  end
  if GetSpellInfo then
    local okLegacy, legacySpellName = pcall(GetSpellInfo, spellID)
    if okLegacy then
      return legacySpellName
    end
  end
  return nil
end
-- 功能：校验某一行宏源码的授权引用，并把源值替换成客户端认识的值。
-- 入参：sourceLine 宏源码行；ref 授权引用（kind / id / role / command / source_value 等字段）。
-- 出参：改写后的行文本；校验不过时返回 nil 加一句中文原因。
-- 说明：kind 只认 spell 和 item —— item 直接拼成 item:ID，spell 必须能在客户端解析出名字；命令前缀对不上、或条件参数/命令参数与授权源值不一致，都直接拒绝这一行。
local function authorizeMacroLine(sourceLine, ref)
  if ref.kind ~= "spell" and ref.kind ~= "item" then
    return nil, "宏授权包含未知引用类型"
  end
  if not lineStartsWithCommand(sourceLine, ref.command) then
    return nil, "宏命令与授权不一致"
  end
  if not isHeroApplicable(ref) then
    return sourceLine
  end
  local authorizedValue
  if ref.kind == "item" then
    authorizedValue = "item:" .. tostring(ref.id)
  else
    authorizedValue = resolveSpellName(ref.id)
    if not authorizedValue or authorizedValue == "" then
      return nil, "客户端无法解析授权 SpellID"
    end
  end
  if ref.role == "condition_argument" then
    local conditionResult = replaceConditionArgument(sourceLine, ref, authorizedValue)
    if not conditionResult then
      return nil, "条件参数与授权源值不一致"
    end
    return conditionResult
  end
  if ref.role == "command_argument" or ref.role == "sequence_entry" or ref.role == "tooltip_argument" then
    local argumentResult = replaceOutsideBrackets(sourceLine, ref.source_value, authorizedValue)
    if not argumentResult then
      return nil, "命令参数与授权源值不一致"
    end
    return argumentResult
  end
  return nil, "授权包含未知宏参数角色"
end
-- 功能：按授权表编译整段宏：逐条校验引用、替换授权值，最后拼回完整宏。
-- 入参：macroText 宏源码；refs 授权引用数组（每项带 line 行号）。
-- 出参：编译后的宏文本；空宏、没有授权表或校验失败时返回原宏或 nil 加中文原因。
-- 说明：中文客户端直接返回原宏 —— 那些宏本来就是中文写的，不需要本地化编译；refs 的 line 是源码行号，行号对不上说明宏被改过，这时拒绝而不是猜。
function WowBuddyDev.CompileAuthorizedMacro(macroText, refs)
  if not macroText or macroText == "" then
    return macroText
  end
  if WowBuddyDev.IsChineseClient() then
    return macroText
  end
  if type(refs) ~= "table" or #refs == 0 then
    return macroText
  end
  local macroLines = splitLines(macroText)
  for index4, refEntry in ipairs(refs) do
    if type(refEntry.line) ~= "number" or not macroLines[refEntry.line] then
      return nil, "授权宏行已从源码消失"
    end
    local compiledLine, errorText = authorizeMacroLine(macroLines[refEntry.line], refEntry)
    if not compiledLine then
      return nil, errorText
    end
    macroLines[refEntry.line] = compiledLine
  end
  return table.concat(macroLines, "\n")
end
-- 功能：在职业注册外面包一层：先把宏引用表挂到职业数据上，再调用原来的注册函数。
-- 入参：specID 专精 ID；classTable 职业数据表。
-- 出参：原注册函数的返回值。
-- 说明：origRegisterClass 是加载本文件时抓下来的原函数，必须走它 —— 直接调 P07483180.RegisterClass 会变成自己调自己，无限递归。
function WowBuddyDev.RegisterClass(specID, classTable)
  local macroRefs = WowBuddyDev.MacroRefsBySpec and WowBuddyDev.MacroRefsBySpec[specID]
  if macroRefs and macroRefs.schema_version == 1 then
    classTable.macro_refs = macroRefs
  end
  return origRegisterClass(specID, classTable)
end
-- 功能：取某个专精的默认宏：中文客户端或没有可用授权表时给原版宏，有授权表就给编译后的本地化版本。
-- 入参：specID 专精 ID。
-- 出参：宏文本。
-- 说明：编译失败会退回原版宏，并且每个专精只报一次错（reportedLocalizeErrors 去重），避免刷新时刷屏；失败细节写进错误日志的「宏本地化」分类。
function WowBuddyDev.GetDefaultMacro(specID)
  if WowBuddyDev.IsChineseClient() then
    return origGetDefaultMacro(specID)
  end
  local classData = WowBuddyDev.classData
  local defaultMacro = classData and (classData.DEFAULT_MACROS and classData.DEFAULT_MACROS[specID])
  if not defaultMacro then
    return origGetDefaultMacro(specID)
  end
  local actionRefs = classData.macro_refs and (classData.macro_refs.actions and classData.macro_refs.actions[specID])
  if not actionRefs or not actionRefs.complete then
    return defaultMacro
  end
  local refs = actionRefs.refs
  if type(refs) ~= "table" or #refs == 0 then
    return defaultMacro
  end
  local compiledText, compileError = WowBuddyDev.CompileAuthorizedMacro(defaultMacro, refs)
  if compiledText then
    return compiledText
  end
  if not reportedLocalizeErrors[specID] then
    reportedLocalizeErrors[specID] = true
    if WowBuddyDev.AddErrorLog then
      WowBuddyDev.AddErrorLog("宏本地化", tostring(specID) .. "：" .. tostring(compileError))
    end
  end
  return defaultMacro
end
