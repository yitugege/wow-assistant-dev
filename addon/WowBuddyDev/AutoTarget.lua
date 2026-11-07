-- ==========================================================================
-- 文件：f9fee1.lua
-- 来源：P07483180.rar → P07483180/f9fee1.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：f9fee1.lua → AutoTarget.lua（按功能重命名）
-- 作用：自动选目标按键绑定
-- ==========================================================================
local secureButtonName = "auto_target"
local autoTargetMacroText = "/targetenemy [combat,nochanneling,noexists][combat,nochanneling,dead]"
local packetBase = 13631488
WowBuddyDev.AUTO_TARGET_KEYS = {}
for index, v in ipairs(WowBuddyDev.ACTION_KEY_ORDER) do
  if index > 127 then
    break
  end
  table.insert(WowBuddyDev.AUTO_TARGET_KEYS, v)
end
local autoTargetState = { keyIndex = 0, key = nil, ack = 0, sequence = 0, bound = false }
-- 功能：安全调用一个返回 true/false 的接口，把结果归一成 true / false / nil。
-- 入参：apiFunc 要调用的函数；... 透传给它的参数。
-- 出参：true / false / nil（调用抛错、或返回值不是布尔时给 nil）。
-- 说明：这几个单位接口在目标不存在或被保护时可能直接抛错，所以一律 pcall；nil 表示「读不到」，调用方用它和 false（明确的否）区分开。
local function callBoolSafe(apiFunc, ...)
  if type(apiFunc) ~= "function" then
    return nil
  end
  local ok, value = pcall(function(...)
    local ret = apiFunc(...)
    if ret == true then
      return true
    end
    if ret == false then
      return false
    end
    return nil
  end, ...)
  if ok then
    return value
  end
  return nil
end
-- 功能：判断当前是否有编辑框等控件占着键盘焦点。
-- 入参：无。
-- 出参：布尔；客户端没有 GetCurrentKeyBoardFocus 时返回 false，调用失败时返回 nil。
-- 说明：玩家在打字时不能抢按键，所以闸门只放行 false —— 调用失败返回的 nil 也会被当成「不能动作」。
local function hasKeyboardFocus()
  if type(GetCurrentKeyBoardFocus) ~= "function" then
    return false
  end
  local ok, focusFrame = pcall(GetCurrentKeyBoardFocus)
  if not ok then
    return nil
  end
  return focusFrame ~= nil
end
local sessionReady = false
local lastSpecID = nil
-- 功能：把自动选目标的会话状态清零。
-- 入参：无。
-- 出参：无。
-- 说明：同时注册在 PLAYER_REGEN_ENABLED 和 PLAYER_ENTERING_WORLD 上，不读事件参数，纯粹当复位信号用。
local function resetSessionState()
  sessionReady = false
  lastSpecID = nil
end
-- 功能：判断当前目标是否已经可以直接开打：存在、没死，且玩家能攻击它。
-- 入参：无。
-- 出参：布尔。
-- 说明：三个接口都走 callBoolSafe，任何一个读到 nil 都会让整条表达式为假 —— 读不到就当不满足，不冒进。
local function hasAttackableTarget()
  return callBoolSafe(UnitExists, "target") == true and (callBoolSafe(UnitIsDeadOrGhost, "target") == false and callBoolSafe(UnitCanAttack, "player", "target") == true)
end
-- 功能：判断自动选目标的会话是否就绪：在战斗中、专精是远程输出，并且已经拿到过有效目标。
-- 入参：无。
-- 出参：布尔。
-- 说明：专精一变就把状态清掉重算；一旦确认拿到可攻击的目标就保持 true，避免目标被持续伤害打死之类的瞬时变化让按键跟着抖。
function WowBuddyDev.IsRemoteAutoTargetSessionReady()
  local inCombat = callBoolSafe(UnitAffectingCombat, "player")
  if inCombat == false or callBoolSafe(WowBuddyDev.IsRangedDamageSpec) ~= true then
    resetSessionState()
    return false
  end
  if inCombat ~= true then
    return false
  end
  -- 安全读取专精 ID：GetSpecialization / GetSpecializationInfo 在无限客户端上缺全局导出
  -- （由 ForeverCompat 垫片补回），且本函数每帧被调用、调用方不带 pcall，
  -- 所以这里不能裸调 —— 与 Core.lua 的 `GetSpecialization and GetSpecialization() or 0` 同口径。
  local specIndex = GetSpecialization and GetSpecialization() or 0
  local specID = nil
  if specIndex > 0 and type(GetSpecializationInfo) == "function" then
    local okInfo, resolvedID = pcall(GetSpecializationInfo, specIndex)
    if okInfo then
      specID = resolvedID
    end
  end
  if lastSpecID ~= specID then
    sessionReady = false
    lastSpecID = specID
  end
  if hasAttackableTarget() then
    sessionReady = true
  end
  return sessionReady
end
local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_REGEN_ENABLED")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:SetScript("OnEvent", resetSessionState)
-- 功能：判断自动选目标自己用的键，是否和玩家设置的主键/爆发键/AOE 键撞了。
-- 入参：无。
-- 出参：布尔。
-- 说明：比较前先经 NormalizeActionKey 归一（大小写、修饰键顺序、小键盘别名），否则 ctrl-f6 和 CTRL-F6 会被当成两个不同的键。
local function isKeyConflictWithUserKeys()
  if not autoTargetState.bound or type(autoTargetState.key) ~= "string" or type(WowBuddyDev.DB) ~= "table" then
    return false
  end
  local normalizedKey = WowBuddyDev.NormalizeActionKey(autoTargetState.key)
  -- 功能：判断某个键名归一后是否等于自动选目标当前用的键。
  -- 入参：keyName 待比较的键名。
  -- 出参：布尔。
  -- 说明：外层已经归一过一次，这里闭包直接复用那个值，不再重复归一。
  local function matchesNormalizedKey(keyName)
    return normalizedKey ~= nil and normalizedKey == WowBuddyDev.NormalizeActionKey(keyName)
  end
  return matchesNormalizedKey(WowBuddyDev.DB.masterKey) or matchesNormalizedKey(WowBuddyDev.DB.burstKey) or matchesNormalizedKey(WowBuddyDev.DB.aoeKey)
end
-- 功能：发现有按键冲突、且不在战斗中时，刷新一次宏绑定。
-- 入参：无。
-- 出参：无。
-- 说明：改安全按钮必须在战斗外，所以用 InCombatLockdown 挡一道；RefreshMacroBindings 由别的文件提供，用 pcall 包住，缺了也不报错。
local function refreshMacroBindingsIfNeeded()
  if not isKeyConflictWithUserKeys() or callBoolSafe(InCombatLockdown) ~= false then
    return
  end
  if type(WowBuddyDev.RefreshMacroBindings) == "function" then
    pcall(WowBuddyDev.RefreshMacroBindings)
  end
end
-- 功能：算出这一帧自动选目标该做什么，用状态码表示。
-- 入参：无。
-- 出参：状态码 —— 0 不动作；1 没有目标或目标已死；2 当前目标可攻击；3 当前目标是友方；4 状态读不到。
-- 说明：任何一处读到 nil（受保护值或接口缺失）都归到 4；只有明确读出来的 true / false 才用来下「没有目标」「目标没死」这类结论。
local function computeGateState()
  local sessionReadyNow = WowBuddyDev.IsRemoteAutoTargetSessionReady()
  -- 近战放行：Core.IsAutoTargetGateOpen 对「近战 + 附近有敌人」已放行 masterSwitch，
  -- 但近战 DB.autoTarget 默认关，这里若照旧硬性要求 GetAutoTargetEnabled==true，
  -- 两道闸门就会对近战给出相反结论 —— 目标死后 masterSwitch 仍亮、却永远不补
  -- /targetenemy，近战因此在战斗中站桩空转。战斗与 masterSwitch 已在同一条 if 里
  -- 各自要求过，故此处只需在「自动选目标关闭」时额外放行近战，宏本身仍受
  -- [combat,noexists/dead] 约束，有可攻击目标时不会乱切。远程/治疗口径不变。
  local autoTargetBlocked = callBoolSafe(WowBuddyDev.GetAutoTargetEnabled) ~= true and callBoolSafe(WowBuddyDev.IsMeleeSpec) ~= true
  if not autoTargetState.bound or isKeyConflictWithUserKeys() or type(WowBuddyDev.DB) ~= "table" or WowBuddyDev.DB.masterSwitch ~= true or autoTargetBlocked or callBoolSafe(UnitAffectingCombat, "player") ~= true or callBoolSafe(UnitIsDeadOrGhost, "player") ~= false or hasKeyboardFocus() ~= false then
    return 0
  end
  if callBoolSafe(WowBuddyDev.IsRangedDamageSpec) == true and not sessionReadyNow then
    return 0
  end
  local targetExists = callBoolSafe(UnitExists, "target")
  if targetExists == false then
    return 1
  end
  if targetExists ~= true then
    return 4
  end
  local targetDeadOrGhost = callBoolSafe(UnitIsDeadOrGhost, "target")
  if targetDeadOrGhost == true then
    return 1
  end
  if targetDeadOrGhost ~= false then
    return 4
  end
  local canAttackTarget = callBoolSafe(UnitCanAttack, "player", "target")
  if canAttackTarget == true then
    return 2
  end
  if canAttackTarget ~= false then
    return 4
  end
  if callBoolSafe(UnitCanAssist, "player", "target") == true then
    return 3
  end
  return 4
end
-- 功能：判断自动选目标的闸门是否打开：会话就绪，且要么已有合法目标，要么状态码不为 0。
-- 入参：无。
-- 出参：布尔。
-- 说明：状态码由 computeGateState 算出，非 0 说明有需要处理的动作，闸门才开。
function WowBuddyDev.IsRemoteAutoTargetGateOpen()
  if not WowBuddyDev.IsRemoteAutoTargetSessionReady() then
    return false
  end
  return hasAttackableTarget() or computeGateState() ~= 0
end
-- 功能：收集当前已经被占用的动作键集合。
-- 入参：无。
-- 出参：集合表 { [归一化键名] = true }。
-- 说明：来源有三处 —— 动作键映射表、DB 里的主键/爆发键/AOE 键、以及可选的团队焦点键；GetRaidFocusKeys 用 pcall 调，返回的不是表就跳过。
local function collectUsedKeys()
  local usedKeys = {}
  -- 功能：把一个键名归一化后记进「已占用」集合。
  -- 入参：keyName 键名，可为 nil。
  -- 出参：无。
  -- 说明：归一化失败（值为 nil 或不是字符串）时什么都不做。
  local function markKeyUsed(keyName)
    local normalizedKey = WowBuddyDev.NormalizeActionKey(keyName)
    if normalizedKey then
      usedKeys[normalizedKey] = true
    end
  end
  for _, keyName in ipairs(WowBuddyDev.GetClassMacroKeys and WowBuddyDev.GetClassMacroKeys() or {}) do
    markKeyUsed(keyName)
  end
  for k, boundKey in pairs(WowBuddyDev.ACTION_TO_KEY or {}) do
    markKeyUsed(boundKey)
  end
  if type(WowBuddyDev.DB) == "table" then
    markKeyUsed(WowBuddyDev.DB.masterKey)
    markKeyUsed(WowBuddyDev.DB.burstKey)
    markKeyUsed(WowBuddyDev.DB.aoeKey)
  end
  if WowBuddyDev.classData and (WowBuddyDev.classData.raidFocusEnabled == true and type(WowBuddyDev.GetRaidFocusKeys) == "function") then
    local ok, raidFocusKeys = pcall(WowBuddyDev.GetRaidFocusKeys)
    if ok and type(raidFocusKeys) == "table" then
      for index2, raidFocusKey in ipairs(raidFocusKeys) do
        markKeyUsed(raidFocusKey)
      end
    end
  end
  return usedKeys
end
-- 功能：在自动选目标的候选键里找第一个没被占用的键。
-- 入参：无。
-- 出参：键名 + 它在候选表里的下标；全被占用时返回 nil 加 0。
local function findFirstFreeKey()
  local usedKeySet = collectUsedKeys()
  for index3, candidateKey in ipairs(WowBuddyDev.AUTO_TARGET_KEYS) do
    if not usedKeySet[WowBuddyDev.NormalizeActionKey(candidateKey)] then
      return candidateKey, index3
    end
  end
  return nil, 0
end
-- 功能：把自动选目标的执行回执加一。
-- 入参：无。
-- 出参：恒为 true。
-- 说明：回执照 32 取模循环，它是包序号的一个位段 —— 主程序靠它判断这次按键确实被执行过。
--       原先由宏体里的 /run 行调用，但保护宏带 /run 会让客户端弹「你正试图运行自定义脚本」
--       确认框，所以改由安全按钮的 OnClick 钩子调用：按键经 SetOverrideBindingClick 落到
--       按钮上就必然触发 OnClick，同样是「这次按键真被执行」的硬件事件证据。
function WowBuddyDev.RecordAutoTargetAttempt()
  autoTargetState.ack = (autoTargetState.ack + 1) % 32
  return true
end
local hookedButton = nil
-- 功能：把回执调用挂到自动选目标的安全按钮上，同一个按钮只挂一次。
-- 入参：button 安全按钮对象，可为 nil。
-- 出参：布尔，true 表示已有钩子盯着这个按钮。
-- 说明：CreateSecureButton 会复用同名按钮，每次重绑都 HookScript 就会层层叠加，
--       一次点击把回执加好几；所以记下已挂钩的按钮，只在按钮对象换了才重挂。
local function hookAutoTargetClick(button)
  if hookedButton == button then
    return true
  end
  if type(button) ~= "table" or type(button.HookScript) ~= "function" then
    return false
  end
  button:HookScript("OnClick", function()
    WowBuddyDev.RecordAutoTargetAttempt()
  end)
  hookedButton = button
  return true
end
-- 功能：算出这一帧要发出去的自动选目标包序号。
-- 入参：无。
-- 出参：包序号（整数）。
-- 说明：序号按位段拼出来：常量基址 + 按键下标 * 8192 + 状态码 * 1024 + 回执 * 32 + 递增序号；递增序号先取模再加一，保证相邻两帧的值不会重复。
function WowBuddyDev.GetAutoTargetPacket()
  autoTargetState.sequence = autoTargetState.sequence % 31 + 1
  refreshMacroBindingsIfNeeded()
  return packetBase + autoTargetState.keyIndex * 8192 + computeGateState() * 1024 + autoTargetState.ack * 32 + autoTargetState.sequence
end
-- 功能：给自动选目标挑一个没被占用的动作键并绑定安全按钮。
-- 入参：无。
-- 出参：布尔，true 表示绑定成功。
-- 说明：先清掉旧状态；战斗中直接放弃（InCombatLockdown 下不能改安全按钮）；找不到空闲键、或 pcall 建按钮失败都返回 false，等下次再试。
function WowBuddyDev.ApplyAutoTargetBinding()
  if callBoolSafe(InCombatLockdown) == true then
    return false
  end
  autoTargetState.keyIndex = 0
  autoTargetState.key = nil
  autoTargetState.bound = false
  if type(WowBuddyDev.classData) ~= "table" or type(WowBuddyDev.CreateSecureButton) ~= "function" or type(WowBuddyDev.NormalizeActionKey) ~= "function" then
    return false
  end
  local keyName, keyIndex = findFirstFreeKey()
  if not keyName then
    return false
  end
  local ok, bound = pcall(WowBuddyDev.CreateSecureButton, secureButtonName, keyName, autoTargetMacroText)
  if not ok or not bound then
    if not ok and type(WowBuddyDev.ReportMacroBindingError) == "function" then
      WowBuddyDev.ReportMacroBindingError(secureButtonName, bound)
    end
    return false
  end
  -- 回执钩子挂不上不算绑定失败：ack 只是包里的一个位段，桌面端对它的要求是落在 0..31，
  -- 恒为 0 一样能正常解码，只是日志里看不到回执递增。
  if type(WowBuddyDev.GetSecureButton) == "function" then
    local okButton, button = pcall(WowBuddyDev.GetSecureButton, secureButtonName)
    if okButton then
      hookAutoTargetClick(button)
    end
  end
  autoTargetState.keyIndex = keyIndex
  autoTargetState.key = keyName
  autoTargetState.bound = true
  return true
end
