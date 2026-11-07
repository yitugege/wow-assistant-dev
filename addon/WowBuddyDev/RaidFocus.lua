-- ==========================================================================
-- 文件：a2842b.lua
-- 来源：P07483180.rar → P07483180/a2842b.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：a2842b.lua → RaidFocus.lua（按功能重命名）
-- 作用：团队焦点/焦点施法/血量图层与绑定
-- ==========================================================================
local MAX_RAID_SLOTS = 30
local MAX_RAID_INDEX = 40
local TICK_INTERVAL = .05
local RANGE_UPDATE_THROTTLE = .2
local UNAVAILABLE_REASON_NO_ASSIST = 102
local ACK_PIXEL_FOCUS = "focus_is_player"
local ACK_PIXEL_TANK = "party_tank_index"
WowBuddyDev.RAID_FOCUS_KEYS = {}
for slotIndex = 1, MAX_RAID_SLOTS, 1 do
  table.insert(WowBuddyDev.RAID_FOCUS_KEYS, WowBuddyDev.ACTION_KEY_ORDER[slotIndex])
end
local state = {
  lastUpdate = 0,
  frameSequence = 0,
  rosterEpoch = 0,
  rosterDirty = true,
  roleRefreshRequested = true,
  rolesNeedPostCombatRefresh = false,
  lastObservedRaidCount = nil,
  raidCount = 0,
  focusUnreachable = false,
  feedbackKind = 0,
  feedbackSequence = 0,
  lastRangeUpdate = 0,
  lastClassData = nil,
  ackPixel = ACK_PIXEL_FOCUS,
  healthColors = {},
  roleBySlot = {},
  tankBySlot = {},
  unavailableCodeBySlot = {},
  partyUnavailableByIndex = {},
}
local rangeCurves = nil
local unavailableColors = nil
-- 功能：清空整个团队焦点状态表里剩下的缓存数据：30 个槽位的「不可用原因」码、4 个小队位的不可用标记、上次测距时间戳。
-- 入参：无。
-- 出参：无。
-- 说明：只清「会过期」的那部分（血量颜色、名单、角色另有专门的清理函数）。测距时间戳归零是为了让下一拍立刻重新测距，不受 RANGE_UPDATE_THROTTLE 节流影响。
local function clearRangeData()
  for slotIndex = 1, MAX_RAID_SLOTS, 1 do
    state.unavailableCodeBySlot[slotIndex] = nil
  end
  for partyIndex = 1, 4, 1 do
    state.partyUnavailableByIndex[partyIndex] = nil
  end
  state.lastRangeUpdate = 0
end
-- 功能：把反馈通道（kind + sequence）复位成 0。
-- 入参：无。
-- 出参：无。
-- 说明：反馈是「一次一拍」的瞬时信号，读取端消费完就没人再读了；不复位会一直报同一个旧状态。
local function resetFeedback()
  state.feedbackKind = 0
  state.feedbackSequence = 0
end
-- 功能：查当前专精有没有开团队焦点功能。
-- 入参：无。
-- 出参：true 表示已开启；classData 还没建立或字段不是 true 都返回 false。
-- 说明：所有对外入口（打包、绑定、渲染）都先过这一关，关掉时连框架都不建。
local function isRaidFocusEnabled()
  return WowBuddyDev.classData and WowBuddyDev.classData.raidFocusEnabled == true
end
-- 功能：取「焦点回执」当前用的像素键：classData 指定 party_tank_index 就用它，否则退回 focus_is_player。
-- 入参：无。
-- 出参：像素键字符串（ACK_PIXEL_TANK 或 ACK_PIXEL_FOCUS）。
-- 说明：这个键决定回执里「坦克焦点」和「玩家焦点」落在哪个像素位，读取端按它反解，所以打包和渲染必须用同一个来源。
local function getAckPixelKey()
  if WowBuddyDev.classData and WowBuddyDev.classData.raidFocusAckPixel == ACK_PIXEL_TANK then
    return ACK_PIXEL_TANK
  end
  return ACK_PIXEL_FOCUS
end
-- 功能：把像素键换算成每帧使用的像素格子数（坦克键 31，其余 127）。
-- 入参：ackPixelKey 像素键。
-- 出参：数字，帧序号的取模基数。
-- 说明：两个键的格子容量不同，取模基数必须跟着变，否则帧序号会溢出到别的像素位上。
local function getAckFrameCount(ackPixelKey)
  return ackPixelKey == ACK_PIXEL_TANK and 31 or 127
end
-- 功能：解析本拍该用的像素键；只要 classData 或像素键相比上次变了，就整表复位（帧序号、时间戳、测距缓存、反馈、失败配对）。
-- 入参：无。
-- 出参：ackPixelKey 本拍使用的像素键。
-- 说明：classData 是专精切换时被换掉的整张表，所以用「引用不同」判变化就够。切专精/切像素键时旧缓存全都是脏的，必须一起清，否则读取端会读到上一套专精的残影。
local function resolveAckPixelState()
  local classData = WowBuddyDev.classData
  local ackPixelKey = getAckPixelKey()
  if state.lastClassData ~= classData or state.ackPixel ~= ackPixelKey then
    state.lastClassData = classData
    state.ackPixel = ackPixelKey
    state.frameSequence = 0
    state.lastUpdate = 0
    clearRangeData()
    resetFeedback()
    if WowBuddyDev.ClearFocusHealFailurePair then
      WowBuddyDev.ClearFocusHealFailurePair()
    end
  end
  return ackPixelKey
end
-- 功能：判断当前是否处于战斗锁定。
-- 入参：无。
-- 出参：true/false；InCombatLockdown 不存在时按 false 处理。
-- 说明：战斗中不能改安全框架的绑定，绑定的应用要跳过这一拍。
local function isInCombatLockdown()
  return InCombatLockdown and InCombatLockdown() or false
end
-- 功能：判断一个 pcall 拿到的返回值是不是「被保护、读不得」的值（12.1 的 secret value）。
-- 入参：maybeSecret 待检查的值。
-- 出参：true 表示不可读；客户端没有 issecretvalue 时返回 false（当作能读）。
-- 说明：这是全文件所有「宽容读 API」的公共兜底：pcall 本身成功不代表值能用，被保护的返回值连比较都会触发报错，所以宁可按「不知道」处理。
local function isSecretOrUnreadable(maybeSecret)
  if type(issecretvalue) ~= "function" then
    return false
  end
  local okCall, result = pcall(issecretvalue, maybeSecret)
  return not okCall or result == true
end
-- 功能：安全调用一个「单位 → 布尔」的客户端函数（UnitExists / UnitIsConnected / UnitIsDeadOrGhost 这类），把结果收敛成 true / false / nil。
-- 入参：probe 要调用的客户端函数；unit 单位 token。
-- 出参：true、false，或 nil 表示「函数不存在 / 调用失败 / 结果不可读」。
-- 说明：nil 是「不知道」，不是 false —— 上层拿这个区别决定要不要重试。为此这里连 `result == true` / `result == false` 的比较都各自套了一层 pcall，任何一步踩到保护值都退回 nil。
local function callUnitPredicate(probe, unit)
  if type(probe) ~= "function" then
    return nil
  end
  local okCall, result = pcall(probe, unit)
  if not okCall or isSecretOrUnreadable(result) then
    return nil
  end
  local okCompare, isTrue = pcall(function()
    return result == true
  end)
  if not okCompare or isSecretOrUnreadable(isTrue) then
    return nil
  end
  if isTrue == true then
    return true
  end
  local okCompare, isFalse = pcall(function()
    return result == false
  end)
  if not okCompare or isSecretOrUnreadable(isFalse) then
    return nil
  end
  if isFalse == true then
    return false
  end
  return nil
end
-- 功能：把名单纪元号 +1（回绕到 256 以内）。
-- 入参：无。
-- 出参：无。
-- 说明：读取端用纪元号判断「名单整表换了」，所以每次大清理都递增一次，好让读取端丢掉旧名单。
local function advanceRosterEpoch()
  state.rosterEpoch = (state.rosterEpoch + 1) % 256
end
-- 功能：清掉所有槽位的血量颜色缓存，并把坦克标记统一压成 false。
-- 入参：无。
-- 出参：无。
-- 说明：坦克标记是「非 false 即坦克」，所以这里必须写 false 而不是 nil，否则下一拍没重算的槽位会被当成坦克。
local function clearHealthAndTankState()
  for slotIndex = 1, MAX_RAID_SLOTS, 1 do
    state.healthColors[slotIndex] = nil
    state.tankBySlot[slotIndex] = false
  end
end
-- 功能：清血量/坦克缓存 + 清所有槽位的角色缓存。
-- 入参：无。
-- 出参：无。
-- 说明：名单变了（有人进出团）时用，角色缓存必须重查，不能沿用。
local function clearRosterState()
  clearHealthAndTankState()
  for slotIndex = 1, MAX_RAID_SLOTS, 1 do
    state.roleBySlot[slotIndex] = nil
  end
end
-- 功能：整体复位：清缓存、清角色、清测距、清反馈、清失败配对，并把「名单脏 / 需重查角色 / 战后重查」三个标志摆正，最后推进纪元号。
-- 入参：无。
-- 出参：无。
-- 说明：进入世界、团队名单变更、战斗中解锁等事件都走这里。lastUpdate 归零是为了让下一拍立刻整表重算，不受 TICK_INTERVAL 节流。
local function resetRosterState()
  clearRosterState()
  clearRangeData()
  resetFeedback()
  if WowBuddyDev.ClearFocusHealFailurePair then
    WowBuddyDev.ClearFocusHealFailurePair()
  end
  state.rosterDirty = true
  state.roleRefreshRequested = true
  state.rolesNeedPostCombatRefresh = false
  state.lastUpdate = 0
  advanceRosterEpoch()
end
-- 功能：惰性初始化血量着色用的颜色曲线表（三条：红/绿/蓝通道各一条，按 0~100% 血量取色），以及「不可用原因码 → 颜色表」的映射。
-- 入参：无。
-- 出参：true 表示曲线可用；false 表示客户端缺 C_CurveUtil / UnitHealthPercent，血量着色只能退回默认曲线。
-- 说明：曲线只在第一次调用时建，之后直接返回（已建过 rangeCurves）。曲线用 Step 类型 + 101 个采样点，等价于查表。不可用色表按原因码 102（超距）和 103（无法协助）各存一组 RGB。
local function initHealthColorCurves()
  if rangeCurves then
    return true
  end
  if not (C_CurveUtil and (C_CurveUtil.CreateColorCurve and UnitHealthPercent)) then
    return false
  end
  local curves = {}
  local colorTable = {}
  for channelIndex = 1, 3, 1 do
    local colorCurve = C_CurveUtil.CreateColorCurve()
    colorCurve:SetType(Enum.LuaCurveType.Step)
    for percent = 0, 100, 1 do
      local channelValue = (percent + 1) / 255
      if channelIndex == 1 then
        colorCurve:AddPoint(percent / 100, CreateColor(channelValue, 0, 0, 1))
      elseif channelIndex == 2 then
        colorCurve:AddPoint(percent / 100, CreateColor(0, channelValue, 0, 1))
      else
        colorCurve:AddPoint(percent / 100, CreateColor(0, 0, channelValue, 1))
      end
    end
    curves[channelIndex] = colorCurve
    colorTable[UNAVAILABLE_REASON_NO_ASSIST] = colorTable[UNAVAILABLE_REASON_NO_ASSIST] or {}
    colorTable[103] = colorTable[103] or {}
    local channelValue2 = UNAVAILABLE_REASON_NO_ASSIST / 255
    local compactColor = .40392156862745
    if channelIndex == 1 then
      colorTable[UNAVAILABLE_REASON_NO_ASSIST][channelIndex] = CreateColor(channelValue2, 0, 0, 1)
      colorTable[103][channelIndex] = CreateColor(compactColor, 0, 0, 1)
    elseif channelIndex == 2 then
      colorTable[UNAVAILABLE_REASON_NO_ASSIST][channelIndex] = CreateColor(0, channelValue2, 0, 1)
      colorTable[103][channelIndex] = CreateColor(0, compactColor, 0, 1)
    else
      colorTable[UNAVAILABLE_REASON_NO_ASSIST][channelIndex] = CreateColor(0, 0, channelValue2, 1)
      colorTable[103][channelIndex] = CreateColor(0, 0, compactColor, 1)
    end
  end
  rangeCurves = curves
  unavailableColors = colorTable
  return true
end
-- 功能：取当前要处理的团队成员槽位数（不在团队里返回 0）。
-- 入参：无。
-- 出参：槽位数，已夹在 0 ~ MAX_RAID_INDEX 之间。
-- 说明：GetNumGroupMembers 返回负数或超上限时都要夹回来，避免后面按槽位循环时越界。
local function getRaidFocusSlotCount()
  if not (IsInRaid and IsInRaid()) then
    return 0
  end
  local memberCount = GetNumGroupMembers and GetNumGroupMembers() or 0
  if memberCount < 0 then
    memberCount = 0
  end
  if memberCount > MAX_RAID_INDEX then
    memberCount = MAX_RAID_INDEX
  end
  return memberCount
end
-- 功能：判断「焦点反馈」通道是否可用（直接转发 isRaidFocusEnabled）。
-- 入参：无。
-- 出参：true/false。
-- 说明：单独包一层是为了对齐对外 API IsRaidFocusFeedbackEnabled 的语义：反馈只在功能开启时才有效。
local function isFeedbackEnabled()
  return isRaidFocusEnabled()
end
-- 功能：对外接口：查焦点反馈通道是否可用。
-- 入参：无。
-- 出参：true/false。
-- 说明：转发 isFeedbackEnabled，实际判据就是专精有没有开团队焦点。
function WowBuddyDev.IsRaidFocusFeedbackEnabled()
  return isFeedbackEnabled()
end
local feedbackKindByReason = { range = 1, los = 2, success = 3 }
-- 功能：记录一次焦点反馈（超距 / 视线 / 成功），推进反馈序号。
-- 入参：kind 反馈类型字符串（range / los / success）。
-- 出参：true 表示已记录；反馈通道关闭或类型不认识时返回 false。
-- 说明：序号按 32 取模递增（读取端按取模反解）。通道关着的时候顺手清一次反馈状态，免得上一拍的旧值被当成新值读走。
function WowBuddyDev.RecordRaidFocusFeedback(kind)
  local byReason = feedbackKindByReason[kind]
  local feedbackEnabled = isFeedbackEnabled()
  if not byReason or not feedbackEnabled then
    if not feedbackEnabled then
      resetFeedback()
    end
    return false
  end
  state.feedbackKind = byReason
  state.feedbackSequence = (state.feedbackSequence + 1) % 32
  return true
end
-- 功能：查某个团队成员的队长分配角色，并归一成 true（坦克）/ false（治疗、输出）/ nil（查不到）。
-- 入参：unit 单位 token。
-- 出参：true、false 或 nil。
-- 说明：客户端函数不存在、调用失败、结果不可读一律返回 nil（不知道）。这里只关心「是不是坦克」，治疗和输出合并成 false，因为血量着色只需要区分坦克与否。
local function getAssignedRole(unit)
  if type(UnitGroupRolesAssigned) ~= "function" then
    return nil
  end
  local okRole, role = pcall(UnitGroupRolesAssigned, unit)
  if not okRole or isSecretOrUnreadable(role) then
    return nil
  end
  local okConvert, isTank = pcall(function()
    if role == "TANK" then
      return true
    end
    if role == "HEALER" or role == "DAMAGER" then
      return false
    end
    return nil
  end)
  if not okConvert or isSecretOrUnreadable(isTank) then
    return nil
  end
  if isTank == true then
    return true
  end
  if isTank == false then
    return false
  end
  return nil
end
-- 功能：刷新角色缓存：按当前人数逐槽查队长分配角色，槽位空缺或查不到就标成「名单还不完整」。
-- 入参：memberCount 当前团队人数。
-- 出参：无（结果写进 state，并更新 rolesNeedPostCombatRefresh）。
-- 说明：只补「缓存里是 nil」的槽位，已经查到的角色不重复查询——UnitGroupRolesAssigned 在战斗中可能被限制，所以查不到就留着下次再查。超过当前人数的槽位直接清空。
local function refreshRoleAssignments(memberCount)
  if not state.roleRefreshRequested then
    return
  end
  local rolesIncomplete = false
  local slotLimit = math.min(memberCount, MAX_RAID_SLOTS)
  for slotIndex = 1, MAX_RAID_SLOTS, 1 do
    if slotIndex <= slotLimit then
      if state.roleBySlot[slotIndex] == nil then
        local unitToken = "raid" .. slotIndex
        if callUnitPredicate(UnitExists, unitToken) == true then
          local role = getAssignedRole(unitToken)
          if role == nil then
            rolesIncomplete = true
          end
          state.roleBySlot[slotIndex] = role
        else
          rolesIncomplete = true
          state.roleBySlot[slotIndex] = nil
        end
      end
    else
      state.roleBySlot[slotIndex] = nil
    end
  end
  state.rosterDirty = false
  state.roleRefreshRequested = false
  state.rolesNeedPostCombatRefresh = rolesIncomplete
end
-- 功能：从专精数据里取用于测距的法术 ID 列表。
-- 入参：无。
-- 出参：法术 ID 列表；没配置（不是表或空表）时返回 nil。
-- 说明：只有配置过的专精才做超距检测，没配就直接不测。
local function collectRangeSpellIDs()
  local spellIDList = WowBuddyDev.classData and WowBuddyDev.classData.raidFocusRangeSpellIDs
  if type(spellIDList) ~= "table" or #spellIDList < 1 then
    return nil
  end
  return spellIDList
end
-- 功能：安全地问「这个法术对那个单位够不够得着」。
-- 入参：spellID 法术 ID；unit 单位 token。
-- 出参：true（在射程）、false（不在射程）或 nil（问不出来）。
-- 说明：C_Spell.IsSpellInRange 在战斗中可能被保护，任何一步失败都返回 nil。nil 绝不当作「超距」——把不知道当超距会让整个团队焦点乱闪灰，所以只有明确的 false 才算超距。
local function isSpellInRange(spellID, unit)
  if not (C_Spell and type(C_Spell.IsSpellInRange) == "function") then
    return nil
  end
  local okRange, rangeResult = pcall(C_Spell.IsSpellInRange, spellID, unit)
  if not okRange or isSecretOrUnreadable(rangeResult) then
    return nil
  end
  local okCompare, isTrue = pcall(function()
    return rangeResult == true
  end)
  if not okCompare or isSecretOrUnreadable(isTrue) then
    return nil
  end
  if isTrue == true then
    return true
  end
  local okCompare, isFalse = pcall(function()
    return rangeResult == false
  end)
  if not okCompare or isSecretOrUnreadable(isFalse) then
    return nil
  end
  if isFalse == true then
    return false
  end
  return nil
end
-- 功能：用一串候选法术判断目标够不够得着：任一法术在射程算够得着，全部候选都明确不在射程才算超距。
-- 入参：spellIDList 候选法术 ID 列表；unit 单位 token。
-- 出参：true（够得着）、false（超距）或 nil（有候选问不出来）。
-- 说明：多候选是因为同一专精不同变体的射程法术不同（例如指向技与普通技）。只要有一个问不出来，就返回 nil 交给上层保持原状 —— 宁可少报超距，也不误报。
local function isSpellReachable(spellIDList, unit)
  local anyOutOfRange = false
  local anyUnknown = false
  for spellIndex, v in ipairs(spellIDList) do
    if type(v) == "number" and v > 0 then
      local inRange = isSpellInRange(v, unit)
      if inRange == true then
        return true
      end
      if inRange == false then
        anyOutOfRange = true
      else
        anyUnknown = true
      end
    end
  end
  if anyOutOfRange and not anyUnknown then
    return false
  end
  return nil
end
-- 功能：判断一个单位现在能不能当焦点：必须存在、在线、不是死亡/鬼魂状态。
-- 入参：unit 单位 token。
-- 出参：true/false。
-- 说明：三个查询都返回 nil（不知道）时按 false 处理 —— 焦点位宁可空着也不要挂一个状态不明的单位。
local function isFocusAvailable(unit)
  return callUnitPredicate(UnitExists, unit) == true and (callUnitPredicate(UnitIsConnected, unit) == true and callUnitPredicate(UnitIsDeadOrGhost, unit) == false)
end
-- 功能：安全地问「玩家能不能协助这个单位（治疗/上 buff 之类）」。
-- 入参：unit 单位 token。
-- 出参：true、false 或 nil（问不出来）。
-- 说明：用来区分「敌人」和「够不着」两种不可用原因：不能协助给 103 号颜色，能协助但超距给 102 号，读取端据此显示不同提示。
local function canAssistUnit(unit)
  if type(UnitCanAssist) ~= "function" then
    return nil
  end
  local okAssist, assistResult = pcall(UnitCanAssist, "player", unit)
  if not okAssist or isSecretOrUnreadable(assistResult) then
    return nil
  end
  local okConvert, isTrue = pcall(function()
    return assistResult == true
  end)
  if not okConvert or isSecretOrUnreadable(isTrue) then
    return nil
  end
  if isTrue == true then
    return true
  end
  local okCompare, isFalse = pcall(function()
    return assistResult == false
  end)
  if not okCompare or isSecretOrUnreadable(isFalse) then
    return nil
  end
  if isFalse == true then
    return false
  end
  return nil
end
-- 功能：取玩家自己在团队里的编号（1 ~ MAX_RAID_INDEX）。
-- 入参：无。
-- 出参：编号；不在团队里、编号不是正整数、或超出范围都返回 nil。
-- 说明：这个编号用来把玩家自己从超距检测里排除掉（自己永远「够得着」）。
local function getPlayerRaidIndex()
  if type(UnitInRaid) ~= "function" then
    return nil
  end
  local okRaid, raidIndex = pcall(UnitInRaid, "player")
  if not okRaid or isSecretOrUnreadable(raidIndex) then
    return nil
  end
  local okCheck, isValidIndex = pcall(function()
    return type(raidIndex) == "number" and (raidIndex % 1 == 0 and (raidIndex >= 1 and raidIndex <= MAX_RAID_INDEX))
  end)
  if not okCheck or isSecretOrUnreadable(isValidIndex) or isValidIndex ~= true then
    return nil
  end
  return raidIndex
end
-- 功能：刷新团队/小队的超距与不可协助状态：逐槽把原因码写进 state.unavailableCodeBySlot / partyUnavailableByIndex。
-- 入参：memberCount 当前团队人数；now 当前时间戳（秒）。
-- 出参：无。
-- 说明：按 RANGE_UPDATE_THROTTLE 节流，两拍之内不重复测距（IsSpellInRange 是每槽一次调用，太频繁会拖帧）。玩家自己的槽位跳过；小队只记布尔标记，因为小队位没有槽位编号。
local function updateRangeState(memberCount, now)
  if state.lastRangeUpdate > 0 and now - state.lastRangeUpdate < RANGE_UPDATE_THROTTLE then
    return
  end
  clearRangeData()
  state.lastRangeUpdate = now
  local spellIDList = collectRangeSpellIDs()
  if not spellIDList then
    return
  end
  if memberCount > 0 then
    local playerRaidIndex = getPlayerRaidIndex()
    local slotLimit = math.min(memberCount, MAX_RAID_SLOTS)
    if playerRaidIndex then
      for slotIndex = 1, slotLimit, 1 do
        if slotIndex ~= playerRaidIndex then
          local unitToken = "raid" .. slotIndex
          if isFocusAvailable(unitToken) then
            if canAssistUnit(unitToken) == false then
              state.unavailableCodeBySlot[slotIndex] = 103
            elseif isSpellReachable(spellIDList, unitToken) == false then
              state.unavailableCodeBySlot[slotIndex] = UNAVAILABLE_REASON_NO_ASSIST
            end
          end
        end
      end
    end
  end
  for partyIndex = 1, 4, 1 do
    local unitToken = "party" .. partyIndex
    local existsOk = callUnitPredicate(UnitExists, unitToken)
    local connectedOk = callUnitPredicate(UnitIsConnected, unitToken)
    local deadOk = callUnitPredicate(UnitIsDeadOrGhost, unitToken)
    local isUnavailable = existsOk == false or connectedOk == false or deadOk == true
    if existsOk == true and (connectedOk == true and deadOk == false) then
      if canAssistUnit(unitToken) == false or isSpellReachable(spellIDList, unitToken) == false then
        isUnavailable = true
      end
    end
    if isUnavailable then
      state.partyUnavailableByIndex[partyIndex] = true
    end
  end
end
-- 功能：按血量重算每个槽位的颜色：有不可用原因码就取对应的固定色，否则用曲线按血量百分比取色，并顺带刷新坦克标记。
-- 入参：memberCount 当前团队人数。
-- 出参：无。
-- 说明：每个槽位在三条通道曲线里轮转取一条（(槽位-1) % 3 + 1），这样相邻格子的颜色不会撞在一起，读取端还能从通道反推槽位。单位状态不确定时清掉该槽的原因码，让它下一拍重算。
local function refreshHealthColors(memberCount)
  clearHealthAndTankState()
  if memberCount < 1 or not initHealthColorCurves() then
    return
  end
  local slotLimit = math.min(memberCount, MAX_RAID_SLOTS)
  for slotIndex = 1, slotLimit, 1 do
    local unitToken = "raid" .. slotIndex
    local existsOk = callUnitPredicate(UnitExists, unitToken)
    local connectedOk = callUnitPredicate(UnitIsConnected, unitToken)
    local deadOk = callUnitPredicate(UnitIsDeadOrGhost, unitToken)
    if existsOk == true and (connectedOk == true and deadOk == false) then
      local channelIndex = (slotIndex - 1) % 3 + 1
      local healthColor = nil
      local reasonCode = state.unavailableCodeBySlot[slotIndex]
      if reasonCode then
        local reasonColors = unavailableColors and unavailableColors[reasonCode]
        healthColor = reasonColors and reasonColors[channelIndex]
      else
        local okPercent, percentResult = pcall(UnitHealthPercent, unitToken, true, rangeCurves[channelIndex])
        if okPercent then
          healthColor = percentResult
        end
      end
      if healthColor then
        state.healthColors[slotIndex] = healthColor
        state.tankBySlot[slotIndex] = state.roleBySlot[slotIndex] ~= false
      end
    else
      state.unavailableCodeBySlot[slotIndex] = nil
    end
  end
end
-- 功能：团队焦点的主节拍：检查人数变化、刷新角色/测距/血量颜色，推进帧序号，最后返回整表状态。
-- 入参：无。
-- 出参：state 状态表（也是本次要发给读取端的那张表）。
-- 说明：人数变化时整表复位（避免残影）。TICK_INTERVAL 之内直接返回上次的表、不重算，这是主循环的节流点。focusUnreachable 让读取端知道「焦点施法不可达」，帧序号按像素键的容量取模递增。
local function runRaidFocusTick()
  local now = GetTime and GetTime() or 0
  local slotCount = getRaidFocusSlotCount()
  if state.lastObservedRaidCount ~= slotCount then
    state.lastObservedRaidCount = slotCount
    if not state.rosterDirty then
      resetRosterState()
    end
  end
  if state.lastUpdate > 0 and now - state.lastUpdate < TICK_INTERVAL then
    return state
  end
  state.lastUpdate = now
  state.raidCount = slotCount
  refreshRoleAssignments(slotCount)
  updateRangeState(slotCount, now)
  refreshHealthColors(slotCount)
  state.focusUnreachable = WowBuddyDev.GetFocusCastUnreachable and WowBuddyDev.GetFocusCastUnreachable() == true or false
  local frameCount = getAckFrameCount(state.ackPixel)
  state.frameSequence = state.frameSequence % frameCount + 1
  return state
end
-- 功能：对外接口：取本拍要发给读取端的数据包。
-- 入参：无。
-- 出参：state 状态表（已带上本拍的 ackPixel）；功能关闭时返回 nil。
-- 说明：功能关闭时顺手清掉测距缓存和反馈，避免下次开启时读到旧值。这里不新建表，直接在 state 上盖 ackPixel 字段。
function WowBuddyDev.GetRaidFocusPacket()
  local ackPixelKey = resolveAckPixelState()
  if not isRaidFocusEnabled() then
    clearRangeData()
    resetFeedback()
    return nil
  end
  local packet = runRaidFocusTick()
  packet.ackPixel = ackPixelKey
  return packet
end
-- 功能：把一个回执框架的透明度设为 0（隐藏这个像素位）。
-- 入参：ackFrame 回执框架（可为 nil）。
-- 出参：无。
-- 说明：SetAlpha 全部走 pcall —— 回执框架是读取端建立的、可能已被回收或受保护，失败就跳过，绝不让它打断整轮渲染。
local function clearFrameAlpha(ackFrame)
  if ackFrame and type(ackFrame.SetAlpha) == "function" then
    pcall(ackFrame.SetAlpha, ackFrame, 0)
  end
end
-- 功能：按「这个单位是不是当前焦点」把框架亮度设成 255 或 0（用 SetAlphaFromBoolean 一次搞定）。
-- 入参：ackFrame 回执框架；visible 是否可见（true 亮、false 灭）。
-- 出参：无。
-- 说明：同样全程 pcall。用 SetAlphaFromBoolean 而不是自己算 alpha，是为了让读取端能直接读到位图。
local function applyUnitMatchAlpha(ackFrame, visible)
  if ackFrame and type(ackFrame.SetAlphaFromBoolean) == "function" then
    pcall(ackFrame.SetAlphaFromBoolean, ackFrame, visible, 255, 0)
  end
end
-- 功能：把回执渲染到各个框架上：团队成员按人数逐个设亮度，小队和玩家自己按像素键决定谁亮。
-- 入参：ackState 回执状态表（含 raid / party / self 三组框架）；packet 本拍的数据包（读 raidCount 与 ackPixelKey）。
-- 出参：无。
-- 说明：先用 clearFrameAlpha 全灭再点亮，避免上一拍亮着的位子残留。只有像素键是「玩家焦点」时才点亮 self 那一格 —— 坦克焦点模式下自己那格必须保持灭。
local function renderAckUnitFrames(unit, raidAckFrame, selfAckFrame)
  clearFrameAlpha(raidAckFrame)
  clearFrameAlpha(selfAckFrame)
  if type(UnitIsUnit) ~= "function" then
    return
  end
  local okUnitIsUnit, isFocusUnit = pcall(UnitIsUnit, "focus", unit)
  if not okUnitIsUnit then
    return
  end
  applyUnitMatchAlpha(raidAckFrame, isFocusUnit)
  applyUnitMatchAlpha(selfAckFrame, isFocusUnit)
end
-- 功能：对外接口：把回执渲染到读取端建立的那些框架上。
-- 入参：ackState 回执状态表（raid / party / self 三组框架）；packet 本拍数据包。
-- 出参：无。
-- 说明：功能关闭、或 ackState 不是表时直接返回（读取端还没建好框架时就属于这种情况）。人数同样要夹在 0 ~ MAX_RAID_SLOTS 之间，越界槽位一律灭灯。
function WowBuddyDev.RenderRaidFocusAcknowledgement(ackState, packet)
  if not isRaidFocusEnabled() or type(ackState) ~= "table" then
    return
  end
  local memberCount = packet and packet.raidCount or 0
  local slotLimit = math.min(tonumber(memberCount) or 0, MAX_RAID_SLOTS)
  local raidFrames = ackState.raid or {}
  for slotIndex = 1, MAX_RAID_SLOTS, 1 do
    if slotIndex <= slotLimit then
      renderAckUnitFrames("raid" .. slotIndex, raidFrames[slotIndex])
    else
      clearFrameAlpha(raidFrames[slotIndex])
    end
  end
  local partyFrames = ackState.party or {}
  local ackPixelKey = packet and packet.ackPixel or getAckPixelKey()
  local selfFrame = ackPixelKey == ACK_PIXEL_FOCUS and ackState.self or nil
  renderAckUnitFrames("player", partyFrames[1], selfFrame)
  for partyIndex = 1, 4, 1 do
    renderAckUnitFrames("party" .. partyIndex, partyFrames[partyIndex + 1])
  end
end
-- 功能：算出 30 个团队焦点键位：从 ACTION_KEY_ORDER 里按顺序挑出还没被别的动作占用的键。
-- 入参：无。
-- 出参：30 个动作键的列表；挑不满 30 个就返回空表（宁可不绑定，也不绑一半）。
-- 说明：已被占用的键来自 ACTION_TO_KEY 的归一化结果。顺序必须严格跟 ACTION_KEY_ORDER 一致，读取端按下标反推槽位。
function WowBuddyDev.GetRaidFocusKeys()
  if type(WowBuddyDev.ACTION_KEY_ORDER) ~= "table" or type(WowBuddyDev.NormalizeActionKey) ~= "function" then
    return {}
  end
  local usedActionKeys = {}
  for _, key in ipairs(WowBuddyDev.GetClassMacroKeys and WowBuddyDev.GetClassMacroKeys() or {}) do
    usedActionKeys[WowBuddyDev.NormalizeActionKey(key)] = true
  end
  if type(WowBuddyDev.ACTION_TO_KEY) == "table" then
    for actionName, actionName in pairs(WowBuddyDev.ACTION_TO_KEY) do
      local actionKey = WowBuddyDev.NormalizeActionKey(actionName)
      if actionKey then
        usedActionKeys[actionKey] = true
      end
    end
  end
  local raidFocusKeys = {}
  -- 功能：把动作键加进结果列表，但要去重且不超过 MAX_RAID_SLOTS 个。
  -- 入参：candidateKey 动作键。
  -- 出参：无。
  -- 说明：去重看的是归一化之后的键（NormalizeActionKey），因为同一个物理键可能有多种写法；已经建议过的键放在外层的 usedActionKeys 里。
  local function addUniqueActionKey(candidateKey)
    local actionKey = WowBuddyDev.NormalizeActionKey(candidateKey)
    if actionKey and (#raidFocusKeys < MAX_RAID_SLOTS and not usedActionKeys[actionKey]) then
      raidFocusKeys[#raidFocusKeys + 1] = candidateKey
    end
  end
  for keyIndex, actionKey in ipairs(WowBuddyDev.ACTION_KEY_ORDER) do
    addUniqueActionKey(actionKey)
  end
  if #raidFocusKeys ~= MAX_RAID_SLOTS then
    return {}
  end
  return raidFocusKeys
end
-- 功能：对外接口：把团队焦点键位真正绑到安全按钮上。
-- 入参：无。
-- 出参：无。
-- 说明：战斗中（战斗锁定）不绑定 —— 改安全框架绑定会被客户端拒绝；CreateSecureFocusButton 不存在也跳过。键位绑成 raid_focus_<序号>，对 raid<序号>。
function WowBuddyDev.ApplyRaidFocusBindings()
  if not isRaidFocusEnabled() or isInCombatLockdown() or not WowBuddyDev.CreateSecureFocusButton then
    return
  end
  local raidFocusKeys = WowBuddyDev.GetRaidFocusKeys()
  for keyIndex, actionKey in ipairs(raidFocusKeys) do
    local id = "raid_focus_" .. keyIndex
    local ok, err = pcall(WowBuddyDev.CreateSecureFocusButton, id, actionKey, "raid" .. keyIndex)
    if not ok and type(WowBuddyDev.ReportMacroBindingError) == "function" then
      WowBuddyDev.ReportMacroBindingError(id, err)
    end
  end
end
local raidFocusEventFrame = CreateFrame("Frame")
raidFocusEventFrame:RegisterEvent("GROUP_ROSTER_UPDATE")
raidFocusEventFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
raidFocusEventFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
raidFocusEventFrame:SetScript("OnEvent", function(self, event)
  if event == "PLAYER_REGEN_ENABLED" then
    if state.rolesNeedPostCombatRefresh then
      state.roleRefreshRequested = true
      state.lastUpdate = 0
    end
    return
  end
  resetRosterState()
end)
