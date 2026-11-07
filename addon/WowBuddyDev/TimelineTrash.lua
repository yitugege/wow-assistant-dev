-- ==========================================================================
-- 文件：cc3743.lua
-- 来源：P07483180.rar → P07483180/cc3743.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：cc3743.lua → TimelineTrash.lua（按功能重命名）
-- 作用：小怪阶段采集（TrashCapture）
-- ==========================================================================
local CHALLENGE_DUNGEONS = {
  [1762] = true,
  [1877] = true,
  [2521] = true,
  [2813] = true,
  [2825] = true,
  [2859] = true,
  [2923] = true,
  [2993] = true,
}
local MAX_CAPTURE_RUNS = 3
local MAX_CAPTURE_EVENTS = 1024
local MAX_UNIT_MAPPINGS = 200
local INT32_MAX = 2147483647
local MS_PER_SEC = 4294967295
local isArmed = false
local captureFrame = nil
local capture = nil
local isChallengeBoundary = false
local onCaptureEvent
local stopCapture
local onCaptureEventSafe
local zoneEventNames = {
  "ZONE_CHANGED_NEW_AREA",
  "PLAYER_ENTERING_WORLD",
  "CHALLENGE_MODE_START",
  "CHALLENGE_MODE_COMPLETED",
  "CHALLENGE_MODE_RESET",
}
local trashEventNames = {
  "NAME_PLATE_UNIT_ADDED",
  "NAME_PLATE_UNIT_REMOVED",
  "PLAYER_REGEN_DISABLED",
  "PLAYER_REGEN_ENABLED",
  "ENCOUNTER_START",
  "ENCOUNTER_END",
  "UNIT_SPELLCAST_START",
  "UNIT_SPELLCAST_SUCCEEDED",
  "UNIT_SPELLCAST_STOP",
  "UNIT_SPELLCAST_INTERRUPTED",
  "UNIT_SPELLCAST_FAILED",
  "UNIT_SPELLCAST_CHANNEL_START",
  "UNIT_SPELLCAST_CHANNEL_STOP",
  "UNIT_SPELLCAST_DELAYED",
}
local spellEventKinds = {
  UNIT_SPELLCAST_START = "spell_start",
  UNIT_SPELLCAST_SUCCEEDED = "spell_succeeded",
  UNIT_SPELLCAST_STOP = "spell_stop",
  UNIT_SPELLCAST_INTERRUPTED = "spell_interrupted",
  UNIT_SPELLCAST_FAILED = "spell_failed",
  UNIT_SPELLCAST_CHANNEL_START = "spell_channel_start",
  UNIT_SPELLCAST_CHANNEL_STOP = "spell_channel_stop",
  UNIT_SPELLCAST_DELAYED = "spell_delayed",
}
local captureEventKinds = {
  nameplate_added = true,
  nameplate_removed = true,
  combat_started = true,
  combat_ended = true,
  boss_started = true,
  boss_ended = true,
  spell_start = true,
  spell_succeeded = true,
  spell_stop = true,
  spell_interrupted = true,
  spell_failed = true,
  spell_channel_start = true,
  spell_channel_stop = true,
  spell_delayed = true,
}
local captureEndReasons = {
  disarmed = true,
  map_changed = true,
  left_instance = true,
  capture_error = true,
  registration_failed = true,
  challenge_completed = true,
  challenge_reset = true,
}
local readableFieldNames = {
  unitGuid = true,
  unitIsPlayer = true,
  npcId = true,
  eventSpellId = true,
  castSpellId = true,
  castStartedAt = true,
  castEndsAt = true,
  castBarId = true,
}
-- 功能：判断一个值是不是客户端「机密值」—— 直接读它会被 taint，必须用 pcall 包着读。
-- 入参：value 待判断的值。
-- 出参：布尔（真 = 可以安全读；客户端没有 issecretvalue 这个 API 时一律返回真）。
-- 说明：只有明确返回 true 才算可读，其余（抛错、返回 false）都按不可读处理，宁可丢字段也不能 taint。
local function isSecretValue(value)
  if type(issecretvalue) ~= "function" then
    return true
  end
  local ok, result = pcall(issecretvalue, value)
  return not ok or result == true
end
-- 功能：判断一个值是不是有限数（不是 nan、不是正负无穷）。
-- 入参：value 待判断的值。
-- 出参：布尔。
-- 说明：写法 `value == value` 是排除 nan（nan 不等于自身）。
local function isFiniteNumber(value)
  return type(value) == "number" and (value == value and (value ~= math.huge and value ~= -math.huge))
end
-- 功能：把值规范成「整数且在区间内」的 ID，不合法就丢掉。
-- 入参：value 待校验的值；minValue 下限；maxValue 上限，省略时不查上限。
-- 出参：通过则返回原整数，否则返回 nil。
local function toIntInRange(value, minValue, maxValue)
  if isSecretValue(value) or not isFiniteNumber(value) or value % 1 ~= 0 or value < minValue or maxValue and value > maxValue then
    return nil
  end
  return value
end
-- 功能：把值规范成「不超过指定长度的字符串」。
-- 入参：value 待校验的值；maxLength 最大长度。
-- 出参：通过则返回原字符串，否则返回 nil。
-- 说明：客户端版本串、区域名这类字段长度不定，截断不如丢弃 —— 半个版本号会让回读端判断错客户端版本。
local function toBoundedString(value, maxLength)
  if isSecretValue(value) or type(value) ~= "string" or #value > maxLength then
    return nil
  end
  return value
end
-- 功能：判断一个数是不是落在闭区间内（含两端）。
-- 入参：value 待判断的值；minValue 下限；maxValue 上限。
-- 出参：布尔。
-- 说明：与 toIntInRange 不同，这里不做取整，用于时间戳这种小数；机密值一律判假。
local function isNumberInRange(value, minValue, maxValue)
  return not isSecretValue(value) and (isFiniteNumber(value) and (value >= minValue and value <= maxValue))
end
-- 功能：校验一个数组字段：是 table、长度不超过上限、下标是连续的 1..n、每一项都能过 predicate。
-- 入参：value 待校验的数组；maxLength 最大元素个数；predicate 逐项校验函数。
-- 出参：布尔。
-- 说明：逐项校验而不是只看长度 —— 存档可能是旧版本或被改过的，长度对但内容不对一样要拦下来。下标连续性也要查，带空洞的数组会让 `#` 的结果不可预期。
local function isValidRecordArray(record, maxLength, predicate)
  if type(record) ~= "table" or isSecretValue(record) then
    return false
  end
  local length = #record
  if length > maxLength then
    return false
  end
  for key in pairs(record) do
    if type(key) ~= "number" or key % 1 ~= 0 or key < 1 or key > length then
      return false
    end
  end
  for index = 1, length, 1 do
    if not predicate(record[index]) then
      return false
    end
  end
  return true
end
-- 功能：校验「哪些字段读得到」这张表：键必须在白名单里、值必须是布尔、且每个白名单字段都得出现。
-- 入参：presence 待校验的表。
-- 出参：布尔。
-- 说明：两轮循环缺一不可 —— 第一轮查出多出来的键，第二轮查漏掉的键。字段齐不齐直接决定回读端能不能区分「没读到」和「读到 0」。
local function isValidReadablePresence(presence)
  if type(presence) ~= "table" or isSecretValue(presence) then
    return false
  end
  for fieldName, flag in pairs(presence) do
    if not readableFieldNames[fieldName] or isSecretValue(flag) or type(flag) ~= "boolean" then
      return false
    end
  end
  for fieldName in pairs(readableFieldNames) do
    if type(presence[fieldName]) ~= "boolean" then
      return false
    end
  end
  return true
end
-- 功能：判断一个可选字段：nil 算通过，否则必须能过 toIntInRange。
-- 入参：value 待判断的值；minValue 下限；maxValue 上限。
-- 出参：布尔。
local function isOptionalInt(record, minValue, maxValue)
  return record == nil or toIntInRange(record, minValue, maxValue) ~= nil
end
-- 功能：判断一个可选的时间戳字段：nil 算通过，否则必须在区间内。
-- 入参：value 待判断的值；minValue 下限；maxValue 上限。
-- 出参：布尔。
local function isOptionalTimestamp(record, minValue, maxValue)
  return record == nil or isNumberInRange(record, minValue, maxValue)
end
-- 功能：校验一条采集事件（存档回读时的第一道闸门）。
-- 入参：record 事件数据。
-- 出参：布尔。
-- 说明：必填项（序号、类型、收到时间、战斗代次、可读字段表）全查；可选字段（npcId / spellId / 施法时间等）用 isOptionalInt / isOptionalTimestamp 放行 nil。施法时间戳允许为负 —— 时钟抖动会让客户端给的首尾时间比记录起点早几毫秒。
local function isValidCaptureEvent(record)
  if type(record) ~= "table" or isSecretValue(record) or not toIntInRange(record.sequence, 1, INT32_MAX) or not captureEventKinds[toBoundedString(record.kind, 64)] or not isNumberInRange(record.receivedAt, 0, MS_PER_SEC / 1000) or not toIntInRange(record.combatGeneration, 0, INT32_MAX) or not isValidReadablePresence(record.readable) then
    return false
  end
  return isOptionalInt(record.appearanceOrdinal, 1, INT32_MAX) and (isOptionalInt(record.npcId, 1, INT32_MAX) and (isOptionalInt(record.spellId, 1, INT32_MAX) and (isOptionalInt(record.castSpellId, 1, INT32_MAX) and (isOptionalInt(record.castBarId, 0, INT32_MAX) and (isOptionalTimestamp(record.castStartedAt, -MS_PER_SEC / 1000, MS_PER_SEC / 1000) and isOptionalTimestamp(record.castEndsAt, -MS_PER_SEC / 1000, MS_PER_SEC / 1000))))))
end
-- 功能：校验一条采集记录（整条 run，含嵌套的 events 数组）。
-- 入参：run 采集记录。
-- 出参：布尔。
-- 说明：区域 ID 必须在 CHALLENGE_DUNGEONS 名单里、难度必须是 8（史诗钥石）—— 存档是玩家侧生成的，读之前先确认它确实是本插件认识的那种数据。另外还查计数自洽：eventsSeen 不能小于已存条数、也不能小于丢弃数。
local function isValidCaptureRun(run)
  if type(run) ~= "table" or isSecretValue(run) or not toIntInRange(run.runId, 1, INT32_MAX) or not toIntInRange(run.instanceId, 1, INT32_MAX) or not CHALLENGE_DUNGEONS[run.instanceId] or run.difficultyId ~= 8 or not isNumberInRange(run.startedAt, 0, MS_PER_SEC / 1000) or not toIntInRange(run.eventsSeen, 0, INT32_MAX) or not toIntInRange(run.eventsDropped, 0, INT32_MAX) or not toIntInRange(run.unitMappingsSeen, 0, MAX_UNIT_MAPPINGS) or not toIntInRange(run.unitMappingsDropped, 0, INT32_MAX) or not toIntInRange(run.apiQueriesSkipped, 0, INT32_MAX) or not isValidRecordArray(run.events, MAX_CAPTURE_EVENTS, isValidCaptureEvent) then
    return false
  end
  if run.eventsSeen < #run.events or run.eventsSeen < run.eventsDropped then
    return false
  end
  if run.build ~= nil and not toBoundedString(run.build, 32) then
    return false
  end
  if run.endedAt ~= nil and not isNumberInRange(run.endedAt, 0, MS_PER_SEC / 1000) then
    return false
  end
  return run.endReason == nil or captureEndReasons[toBoundedString(run.endReason, 64)] == true
end
-- 功能：取当前时间（秒），优先用高精度时钟 GetTimePreciseSec，取不到就退回 GetTime。
-- 入参：无。
-- 出参：秒数；两个 API 都不可用、或读出来是机密值/非法数/负数时返回 nil。
-- 说明：施法条的首尾时间是毫秒级精度，必须用高精度时钟；返回 nil 而不是 0，调用方才能区分「时钟不可用」和「时间真的到了 0」。
local function nowSeconds()
  local clock = type(GetTimePreciseSec) == "function" and GetTimePreciseSec or GetTime
  if type(clock) ~= "function" then
    return nil
  end
  local ok, value = pcall(clock)
  if not ok or isSecretValue(value) or not isFiniteNumber(value) or value < 0 then
    return nil
  end
  return value
end
-- 功能：造一张「哪些字段读得到」的新表，八个字段全部先写 false。
-- 入参：无。
-- 出参：新表。
-- 说明：必须把八个字段都列出来（而不是空表）—— 校验函数要求字段齐全，缺字段的记录会被回读端整条拒收。
local function newReadablePresence()
  return {
    unitGuid = false,
    unitIsPlayer = false,
    npcId = false,
    eventSpellId = false,
    castSpellId = false,
    castStartedAt = false,
    castEndsAt = false,
    castBarId = false,
  }
end
-- 功能：读当前副本信息，确认是「史诗钥石队伍副本」后返回它的标识。
-- 入参：无。
-- 出参：instanceID、difficultyID；不在钥石副本里、或读不到副本信息时返回 nil。
-- 说明：三个条件都要满足 —— 区域名是 party、难度是 8、区域 ID 在 CHALLENGE_DUNGEONS 名单里。后者是白名单，本插件只认这几张图，名单外的一律不采集，免得到处乱写存档。
local function getChallengeScope()
  if type(GetInstanceInfo) ~= "function" then
    return nil
  end
  local ok, zoneName, subZone, difficultyID, maxPlayers, dynamicDifficulty, isDynamic, instanceID, instanceID = pcall(GetInstanceInfo)
  if not ok then
    return nil
  end
  local subZone = toBoundedString(subZone, 16)
  local difficultyID = toIntInRange(difficultyID, 1, INT32_MAX)
  local instanceID = toIntInRange(instanceID, 1, INT32_MAX)
  if subZone ~= "party" or difficultyID ~= 8 or not instanceID or not CHALLENGE_DUNGEONS[instanceID] then
    return nil
  end
  return instanceID, difficultyID
end
-- 功能：取客户端版本号串（GetBuildInfo 的第三个返回值）。
-- 入参：无。
-- 出参：版本串；读不到或不全是数字时返回 nil。
-- 说明：只认纯数字版本串 —— 客户端在某些分支上会返回带后缀的版本号，那种写进存档会让回读端对不上格式。
local function getBuildString()
  if type(GetBuildInfo) ~= "function" then
    return nil
  end
  local ok, buildOk, version = pcall(GetBuildInfo)
  if not ok then
    return nil
  end
  local build = toBoundedString(version, 32)
  if build and build:match("^%d+$") then
    return build
  end
  return nil
end
-- 功能：问客户端当前有没有首领战在进行。
-- 入参：无。
-- 出参：布尔；API 不可用或读不到时返回 nil。
-- 说明：用来给小怪阶段的采集打「开跑时是否已在首领战中」的标记：首领战里读到的施法多半是首领的，不该混进小怪样本。
local function isEncounterActive()
  if type(IsEncounterInProgress) ~= "function" then
    return nil
  end
  local ok, inProgress = pcall(IsEncounterInProgress)
  if not ok or isSecretValue(inProgress) or type(inProgress) ~= "boolean" then
    return nil
  end
  return inProgress
end
-- 功能：取出（必要时创建）存档里的采集区，并校验它的版本与结构。
-- 入参：无。
-- 出参：采集区表；插件还没加载完、DB 结构不对、或 schemaVersion 对不上时返回 nil。
-- 说明：schemaVersion 只认 1，对不上就整体不采集 —— 宁可少采，也不能把新格式的数据按旧格式写进去。这里对 DB 和记录表都做了机密值检查，避免读到被 taint 的表。
local function getCaptureDB()
  if type(WowBuddyDev) ~= "table" or isSecretValue(WowBuddyDev) or type(WowBuddyDev.DB) ~= "table" or isSecretValue(WowBuddyDev.DB) then
    return nil
  end
  local db = WowBuddyDev.DB.timelinePlannerTrashCapture
  if db == nil then
    db = { schemaVersion = 1, nextRunId = 1, droppedRuns = 0, runs = {} }
    WowBuddyDev.DB.timelinePlannerTrashCapture = db
  end
  if type(db) ~= "table" or isSecretValue(db) or db.schemaVersion ~= 1 or type(db.runs) ~= "table" or isSecretValue(db.runs) or not toIntInRange(db.nextRunId, 1, INT32_MAX) or not toIntInRange(db.droppedRuns, 0, INT32_MAX) or not isValidRecordArray(db.runs, MAX_CAPTURE_RUNS, isValidCaptureRun) then
    return nil
  end
  return db
end
-- 功能：把采集帧上的事件和 OnEvent 回调全摘掉。
-- 入参：无。
-- 出参：无。
-- 说明：每一步单独 pcall —— 采集帧可能处于半初始化状态（建好了但还没挂回调），一次失败不能挡住后面的清理。
local function unregisterCaptureEvents()
  if not captureFrame then
    return
  end
  if type(captureFrame.UnregisterAllEvents) == "function" then
    pcall(captureFrame.UnregisterAllEvents, captureFrame)
  end
  if type(captureFrame.SetScript) == "function" then
    pcall(captureFrame.SetScript, captureFrame, "OnEvent", nil)
  end
end
-- 功能：给当前采集记录写上结束时间和结束原因，然后把模块级变量摘掉。
-- 入参：reason 结束原因。
-- 出参：无。
-- 说明：先在闭包里读一次时钟再写 —— 记录可能已经被别处摘掉了，所以整体包在 pcall 里，写失败也不抛错。
local function finishCapture(reason)
  local finishedCapture = capture
  capture = nil
  if finishedCapture and finishedCapture.run then
    pcall(function()
      local nowSec = nowSeconds()
      if nowSec then
        finishedCapture.run.endedAt = nowSec
      end
      finishedCapture.run.endReason = reason
    end)
  end
end
-- 功能：保证采集帧存在并注册「区域级」事件（换图、进世界、钥石开始/结束/重置）。
-- 入参：无。
-- 出参：无。
-- 说明：先注销再注册，避免开关来回切之后重复注册；回调挂的是包了 pcall 的 onCaptureEventSafe，单次事件出错不会打断整个采集。
local function registerZoneEvents()
  unregisterCaptureEvents()
  if not captureFrame then
    captureFrame = CreateFrame("Frame")
  end
  for index, eventName in ipairs(zoneEventNames) do
    captureFrame:RegisterEvent(eventName)
  end
  captureFrame:SetScript("OnEvent", onCaptureEventSafe)
end
-- 功能：在区域级事件之外，再注册小怪阶段才需要的事件（姓名板、战斗开始结束、首领开始结束、施法系）。
-- 入参：无。
-- 出参：无。
-- 说明：分两组注册是为了让「不在钥石副本里」时能只摘掉重的一组、保留轻的区域级监听（换图事件必须一直挂着，否则出去了就回不来）。
local function registerTrashEvents()
  registerZoneEvents()
  for index, eventName in ipairs(trashEventNames) do
    captureFrame:RegisterEvent(eventName)
  end
end
-- 功能：停掉当前采集：写结束原因、摘掉武装标记、注销全部采集事件。
-- 入参：reason 结束原因（disarmed / capture_error / registration_failed 这类短词）。
-- 出参：无。
-- 说明：只要采集走过一次收尾路径（关闭开关、出错、注册失败）都从这里出去，保证事件注册不会留在半开状态。
stopCapture = function(reason)
  finishCapture(reason)
  isArmed = false
  isChallengeBoundary = false
  unregisterCaptureEvents()
end
-- 功能：开一条新的采集记录：取存档、滚动旧记录、建 run、注册事件。
-- 入参：instanceID 副本 ID；difficultyID 难度 ID。
-- 出参：布尔（成功为真；注册事件失败时为假并写一条 registration_failed 记录）。
-- 说明：runs 只留最近 MAX_CAPTURE_RUNS 条，超了从头删并累加 droppedRuns；nextRunId 用完一圈回绕。bossActive 用「读不到时按在进行中处理」—— 宁可少采，也不能把首领战的施法记成小怪样本。注册失败要显式收尾，否则会留一个空壳采集状态一直报错。
local function beginCapture(instanceID, difficultyID)
  local db = getCaptureDB()
  local nowSec = nowSeconds()
  if not db or not nowSec then
    return false
  end
  while #db.runs >= MAX_CAPTURE_RUNS do
    table.remove(db.runs, 1)
    db.droppedRuns = db.droppedRuns + 1
  end
  local run = {
    runId = db.nextRunId,
    instanceId = instanceID,
    difficultyId = difficultyID,
    startedAt = nowSec,
    eventsSeen = 0,
    eventsDropped = 0,
    unitMappingsSeen = 0,
    unitMappingsDropped = 0,
    apiQueriesSkipped = 0,
    events = {},
  }
  local build = getBuildString()
  if build then
    run.build = build
  end
  db.nextRunId = db.nextRunId % INT32_MAX + 1
  db.runs[#db.runs + 1] = run
  local inProgress = isEncounterActive()
  capture = {
    run = run,
    instanceId = instanceID,
    difficultyId = difficultyID,
    bossActive = inProgress ~= false,
    combatGeneration = 0,
    unitSlots = 0,
    nextAppearanceOrdinal = 0,
    byUnit = {},
    ignoredByUnit = {},
  }
  isChallengeBoundary = false
  local ok = pcall(registerTrashEvents)
  if not ok then
    finishCapture("registration_failed")
    unregisterCaptureEvents()
    return false
  end
  return true
end
-- 功能：造一条采集事件：分配序号、记下相对时间、战斗代次和可读字段快照。
-- 入参：kind 事件类型名。
-- 出参：事件表；没有在采集中、事件数已满、或时钟不可读时返回 nil。
-- 说明：事件数满了只累加事件计数（让回读端知道数据被截断了）并丢弃内容；receivedAt 记的是相对本场开跑的秒数，不看绝对时间，方便回读端直接对齐。
local function newCaptureEvent(kind)
  if not capture then
    return nil
  end
  local run = capture.run
  run.eventsSeen = run.eventsSeen + 1
  if #run.events >= MAX_CAPTURE_EVENTS then
    run.eventsDropped = run.eventsDropped + 1
    return nil
  end
  local nowSec = nowSeconds()
  if not nowSec then
    error("采集时钟不可读")
  end
  return {
    sequence = run.eventsSeen,
    kind = kind,
    receivedAt = nowSec - run.startedAt,
    combatGeneration = capture.combatGeneration,
    readable = newReadablePresence(),
  }
end
-- 功能：问「当前这场采集还能不能再塞一条事件」。
-- 入参：无。
-- 出参：布尔。
-- 说明：事件上限是给存档体积兜底的 —— 一趟钥石的小怪施法可能上千条，不设上限会把玩家的 SavedVariables 撑爆。
local function hasCaptureCapacity()
  return capture and #capture.run.events < MAX_CAPTURE_EVENTS
end
-- 功能：记一次「事件被丢弃」：事件计数 +1、丢弃计数 +1。
-- 入参：无。
-- 出参：无。
-- 说明：与 hasCaptureCapacity 配套，丢弃必须留痕，否则回读端会把不完整的数据当成完整的。
local function dropCaptureEvent()
  capture.run.eventsSeen = capture.run.eventsSeen + 1
  capture.run.eventsDropped = capture.run.eventsDropped + 1
end
-- 功能：把一条采集事件追加进当前记录的事件数组。
-- 入参：event 事件表。
-- 出参：无。
local function storeCaptureEvent(event)
  capture.run.events[#capture.run.events + 1] = event
end
-- 功能：判断一个单位标识是不是姓名板单位（nameplate1、nameplate12 这种）。
-- 入参：unitToken 单位标识。
-- 出参：布尔。
local function isNameplateUnit(unitToken)
  if isSecretValue(unitToken) or type(unitToken) ~= "string" then
    return false
  end
  return unitToken:match("^nameplate%d+$") ~= nil
end
-- 功能：从单位 GUID 里解析出 NPC ID。
-- 入参：guid 单位 GUID 字符串。
-- 出参：NPC ID；不是生物/载具、或 GUID 格式对不上时返回 nil。
-- 说明：GUID 形如 `Creature-0-区域-实例-服务器-模板ID-出现序号-...`，这里取的是**模板 ID 那一段**（正数第 6 段），不是出现序号 —— 同一只小怪的不同个体要能归到同一个 NPC。只有 Creature / Vehicle 才算小怪，玩家和宠物一律不算。
local function parseNpcId(guid)
  local expansion, npcDigits = guid:match("^([^-]+)%-[^-]*%-[^-]*%-[^-]*%-[^-]*%-(%d+)%-")
  if expansion ~= "Creature" and expansion ~= "Vehicle" then
    return nil
  end
  return toIntInRange(tonumber(npcDigits), 1, INT32_MAX)
end
-- 功能：记一次「单位映射被丢弃」：映射丢弃计数 +1、API 查询跳过计数 +1、事件丢弃计数 +1。
-- 入参：无。
-- 出参：无。
local function dropUnitMapping()
  local run = capture.run
  run.unitMappingsDropped = run.unitMappingsDropped + 1
  run.apiQueriesSkipped = run.apiQueriesSkipped + 1
  dropCaptureEvent()
end
-- 功能：给一个单位建映射记录（NPC ID、是否玩家、出现序号），并给出是否要忽略它。
-- 入参：unitToken 单位标识。
-- 出参：mapping 映射记录；isNew 是否本次新建；isIgnored 是否该忽略（玩家或解析不出 NPC ID）。
-- 说明：映射数量有上限，超了直接丢弃并留痕。UnitGUID / UnitIsPlayer 两个查询分步做，每一步都要单独 pcall 并复查值 —— 姓名板回调可能对刚消失的单位触发，这时读出来是 nil/机密值，要按「读不到」处理而不是当成空字符串。
local function trackUnitMapping(unitToken)
  if capture.unitSlots >= MAX_UNIT_MAPPINGS then
    dropUnitMapping()
    return nil, true
  end
  capture.unitSlots = capture.unitSlots + 1
  capture.run.unitMappingsSeen = capture.unitSlots
  local mapping = { isNpc = false, readable = newReadablePresence() }
  local guidOk, guid = pcall(UnitGUID, unitToken)
  if not guidOk or isSecretValue(guid) or type(guid) ~= "string" then
    capture.nextAppearanceOrdinal = capture.nextAppearanceOrdinal + 1
    mapping.appearanceOrdinal = capture.nextAppearanceOrdinal
    capture.byUnit[unitToken] = mapping
    return mapping
  end
  mapping.readable.unitGuid = true
  local isPlayerOk, unitIsPlayer = pcall(UnitIsPlayer, unitToken)
  if not isPlayerOk or isSecretValue(unitIsPlayer) or type(unitIsPlayer) ~= "boolean" then
    capture.nextAppearanceOrdinal = capture.nextAppearanceOrdinal + 1
    mapping.appearanceOrdinal = capture.nextAppearanceOrdinal
    capture.byUnit[unitToken] = mapping
    return mapping
  end
  mapping.readable.unitIsPlayer = true
  if unitIsPlayer then
    capture.ignoredByUnit[unitToken] = true
    return nil, false, true
  end
  local npcID = parseNpcId(guid)
  if not npcID then
    capture.ignoredByUnit[unitToken] = true
    return nil, false, true
  end
  capture.nextAppearanceOrdinal = capture.nextAppearanceOrdinal + 1
  mapping.appearanceOrdinal = capture.nextAppearanceOrdinal
  mapping.isNpc = true
  mapping.npcId = npcID
  mapping.readable.npcId = true
  capture.byUnit[unitToken] = mapping
  return mapping
end
-- 功能：取一个单位的映射记录，没有就现建（会先查忽略表）。
-- 入参：unitToken 单位标识。
-- 出参：mapping 映射记录；isNew 是否本次新建；isIgnored 是否该忽略。
-- 说明：被忽略的单位不再走建表流程 —— 玩家和 NPC ID 解析不出来的单位每次施法都会来问一遍，不缓存忽略结果会反复白跑 UnitGUID。
local function ensureUnitMapping(unitToken)
  if capture.ignoredByUnit[unitToken] then
    return nil, false, true
  end
  local mapping = capture.byUnit[unitToken]
  if mapping then
    return mapping, false
  end
  return trackUnitMapping(unitToken)
end
-- 功能：把旧映射记录里的单位信息抄到新记录上，并更新事件里的 NPC ID。
-- 入参：event 采集事件；mapping 旧映射记录。
-- 出参：无。
-- 说明：姓名板消失事件发生时单位已经查不到了，只能拿之前缓存的身份来补 —— 但只补「身份」这几个字段，施法相关的字段得留给后面的施法查询填。
local function copyUnitMapping(event, mapping)
  if not mapping then
    return
  end
  event.appearanceOrdinal = mapping.appearanceOrdinal
  event.readable.unitGuid = mapping.readable.unitGuid
  event.readable.unitIsPlayer = mapping.readable.unitIsPlayer
  event.readable.npcId = mapping.readable.npcId
  if mapping.npcId then
    event.npcId = mapping.npcId
  end
end
-- 功能：把法术 ID 规范成合法整数（不合法返回 nil）。
-- 入参：spellID 待校验的法术 ID。
-- 出参：合法整数或 nil。
local function normalizeSpellID(spellID)
  return toIntInRange(spellID, 1, INT32_MAX)
end
-- 功能：把参数的毫秒时间戳换算成「相对本场开跑的秒数」。
-- 入参：value 毫秒时间戳；runStartedAt 本场开始时的秒数。
-- 出参：相对秒数；不是有限数、越界或读不到时返回 nil。
-- 说明：客户端给的是毫秒（0 ~ 4294967295 表示无值），统一换成相对秒数才能和事件里的其他时间对齐 —— 用绝对时间会让存档依赖玩家会话，回读时对不上。
local function toRunTime(value, runStartedAt)
  if isSecretValue(value) or not isFiniteNumber(value) or value < 0 or value > MS_PER_SEC then
    return nil
  end
  return value / 1000 - runStartedAt
end
-- 功能：把当前施法/引导的首尾时间、法术 ID 补进事件记录。
-- 入参：captureEvent 采集事件；unitToken 单位标识；eventName 事件名。
-- 出参：无。
-- 说明：引导（CHANNEL）和普通施法用的是两个不同的 API，且返回值位置不同 —— UnitChannelInfo 的法术 ID 在第 9 个返回值，UnitCastingInfo 在第 10 个，所以这里先按事件名分派、再按下标取。映射数量超限时直接跳过查询并留痕，不去打这些 API。
local function fillCastDetails(captureEvent, unitToken, eventName)
  if capture.unitSlots >= MAX_UNIT_MAPPINGS then
    capture.run.apiQueriesSkipped = capture.run.apiQueriesSkipped + 1
    return
  end
  local ok, unitName, castText, castTexture, castStartMS, castEndMS, notInterruptible, isTradeSkill, castBarID, spellID
  if eventName == "UNIT_SPELLCAST_CHANNEL_START" then
    ok, unitName, castText, castTexture, castStartMS, castEndMS, notInterruptible, isTradeSkill, castBarID = pcall(UnitChannelInfo, unitToken)
  else
    ok, unitName, castText, castTexture, castStartMS, castEndMS, notInterruptible, isTradeSkill, castBarID, spellID = pcall(UnitCastingInfo, unitToken)
  end
  if not ok then
    return
  end
  local v542
  if eventName == "UNIT_SPELLCAST_CHANNEL_START" then
    v542 = castBarID
  else
    v542 = spellID
  end
  local castStartedAt = toRunTime(castStartMS, capture.run.startedAt)
  local castEndsAt = toRunTime(castEndMS, capture.run.startedAt)
  local castSpellID = normalizeSpellID(v542)
  if castStartedAt then
    captureEvent.castStartedAt = castStartedAt
    captureEvent.readable.castStartedAt = true
  end
  if castEndsAt then
    captureEvent.castEndsAt = castEndsAt
    captureEvent.readable.castEndsAt = true
  end
  if castSpellID then
    captureEvent.castSpellId = castSpellID
    captureEvent.readable.castSpellId = true
  end
end
-- 功能：处理姓名板单位的出现与消失：建/取映射、造事件、补身份信息。
-- 入参：eventName 事件名；unitToken 单位标识。
-- 出参：无。
-- 说明：非姓名板单位、以及已被忽略的单位直接跳过。名字板消失时先把映射和忽略标记摘掉再判断（避免下一帧读到脏数据）；单位在事件处理过程中可能已经被销毁，所以身份信息一律从处理前取到的映射里抄。
local function onNameplateEvent(eventName, unitToken)
  if not isNameplateUnit(unitToken) then
    return
  end
  if eventName == "NAME_PLATE_UNIT_REMOVED" then
    local removedMapping = capture.byUnit[unitToken]
    local wasIgnored = capture.ignoredByUnit[unitToken]
    capture.byUnit[unitToken] = nil
    capture.ignoredByUnit[unitToken] = nil
    if wasIgnored or not removedMapping then
      return
    end
    if not hasCaptureCapacity() then
      dropCaptureEvent()
      return
    end
    local removedEvent = newCaptureEvent("nameplate_removed")
    if not removedEvent then
      return
    end
    copyUnitMapping(removedEvent, removedMapping)
    storeCaptureEvent(removedEvent)
    return
  end
  capture.byUnit[unitToken] = nil
  capture.ignoredByUnit[unitToken] = nil
  if not hasCaptureCapacity() then
    dropCaptureEvent()
    return
  end
  local currentMapping, isNew, isIgnored = trackUnitMapping(unitToken)
  if isNew or isIgnored then
    return
  end
  local addedEvent = newCaptureEvent("nameplate_added")
  if not addedEvent then
    return
  end
  copyUnitMapping(addedEvent, currentMapping)
  storeCaptureEvent(addedEvent)
end
-- 功能：处理单位的施法系事件：记事件类型、法术 ID、施法条 ID，并补上施法首尾时间。
-- 入参：eventName 事件名；unitToken 单位标识；eventSpellID 参数里的法术 ID；spellCastBarID 参数里的施法条 ID。
-- 出参：无。
-- 说明：首领战期间（bossActive）整个跳过 —— 首领的施法不属于小怪阶段样本。玩家单位、解析不出 NPC ID 的单位也跳过。只有 START / CHANNEL_START 才去查施法条详情，其余事件（成功、中断、失败等）只记一个类型名。
local function onSpellCastEvent(eventName, unitToken, spellID, eventSpellID, spellCastBarID)
  if not isNameplateUnit(unitToken) or capture.bossActive then
    return
  end
  if capture.ignoredByUnit[unitToken] then
    return
  end
  if not hasCaptureCapacity() then
    dropCaptureEvent()
    return
  end
  local mapping, isNew, isIgnored = ensureUnitMapping(unitToken)
  if isNew or isIgnored then
    return
  end
  local castEvent = newCaptureEvent(spellEventKinds[eventName])
  if not castEvent then
    return
  end
  copyUnitMapping(castEvent, mapping)
  if mapping and mapping.isNpc then
    local castSpellID = normalizeSpellID(eventSpellID)
    if castSpellID then
      castEvent.spellId = castSpellID
      castEvent.readable.eventSpellId = true
    end
    if eventName == "UNIT_SPELLCAST_START" then
      local spellCastBarID = toIntInRange(spellCastBarID, 0, INT32_MAX)
      if spellCastBarID then
        castEvent.castBarId = spellCastBarID
        castEvent.readable.castBarId = true
      end
    end
    if eventName == "UNIT_SPELLCAST_START" or eventName == "UNIT_SPELLCAST_CHANNEL_START" then
      fillCastDetails(castEvent, unitToken, eventName)
    end
  end
  storeCaptureEvent(castEvent)
end
-- 功能：采集帧的 OnEvent 主回调：按事件名分派到各处理分支。
-- 入参：事件帧自身；eventName 事件名；... 事件参数。
-- 出参：无。
-- 说明：未武装直接返回。钥石结束/重置走收尾并把 v5 置真（本次钥石不再重复采集）；换图和进世界都要重新判定副本范围，出本了就把事件收到最小集；战斗与首领开始结束只记事件不入样本；姓名板和施法系事件转给各自的处理函数。
onCaptureEvent = function(self, eventName, ...)
  if not isArmed then
    return
  end
  if eventName == "CHALLENGE_MODE_COMPLETED" or eventName == "CHALLENGE_MODE_RESET" then
    if capture then
      finishCapture(eventName == "CHALLENGE_MODE_COMPLETED" and "challenge_completed" or "challenge_reset")
    end
    isChallengeBoundary = true
    registerZoneEvents()
    return
  end
  if eventName == "CHALLENGE_MODE_START" then
    local instanceID, difficultyID = getChallengeScope()
    if not instanceID then
      return
    end
    if capture then
      finishCapture("map_changed")
    end
    if not beginCapture(instanceID, difficultyID) then
      stopCapture("registration_failed")
    end
    return
  end
  if eventName == "ZONE_CHANGED_NEW_AREA" or eventName == "PLAYER_ENTERING_WORLD" then
    local instanceID, difficultyID = getChallengeScope()
    if not instanceID then
      if capture then
        finishCapture("left_instance")
      end
      registerZoneEvents()
      return
    end
    if isChallengeBoundary then
      return
    end
    if capture and (capture.instanceId == instanceID and capture.difficultyId == difficultyID) then
      return
    end
    if capture then
      finishCapture("map_changed")
    end
    if not beginCapture(instanceID, difficultyID) then
      stopCapture("registration_failed")
    end
    return
  end
  if not capture then
    return
  end
  if eventName == "PLAYER_REGEN_DISABLED" then
    capture.combatGeneration = capture.combatGeneration % INT32_MAX + 1
    local startedEvent = newCaptureEvent("combat_started")
    if startedEvent then
      storeCaptureEvent(startedEvent)
    end
  elseif eventName == "PLAYER_REGEN_ENABLED" then
    local endedEvent = newCaptureEvent("combat_ended")
    if endedEvent then
      storeCaptureEvent(endedEvent)
    end
  elseif eventName == "ENCOUNTER_START" then
    capture.bossActive = true
    local bossStartedEvent = newCaptureEvent("boss_started")
    if bossStartedEvent then
      storeCaptureEvent(bossStartedEvent)
    end
  elseif eventName == "ENCOUNTER_END" then
    capture.bossActive = false
    local bossEndedEvent = newCaptureEvent("boss_ended")
    if bossEndedEvent then
      storeCaptureEvent(bossEndedEvent)
    end
  elseif eventName == "NAME_PLATE_UNIT_ADDED" or eventName == "NAME_PLATE_UNIT_REMOVED" then
    onNameplateEvent(eventName, ...)
  elseif spellEventKinds[eventName] then
    onSpellCastEvent(eventName, ...)
  end
end
-- 功能：采集帧 OnEvent 的 pcall 外壳：单次事件解析出错时记一条 capture_error 并收尾。
-- 入参：事件帧自身；eventName 事件名；... 事件参数。
-- 出参：无。
-- 说明：采集本身出错不能把插件带崩；出错的收尾也包在 pcall 里，避免收尾再抛错把错误吞掉一半。
onCaptureEventSafe = function(self, eventName, ...)
  local ok = pcall(onCaptureEvent, self, eventName, ...)
  if not ok then
    pcall(stopCapture, "capture_error")
  end
end
-- 功能：设置小怪采集的武装状态（插件对外开关的实际执行体）。
-- 入参：armed 是否武装（只有严格的 true 才算武装）。
-- 出参：布尔（最终是否处于武装状态）。
-- 说明：关掉时如果正在采集，要先写一条 disarmed 记录再停 —— 回读端靠这条记录判断「采集是被人关的」而不是「插件崩了」。武装后不在钥石副本里时只注册区域级事件、等待进本，不算失败。
local function setCaptureArmed(armed)
  if armed ~= true then
    if isArmed or capture then
      stopCapture("disarmed")
    end
    return false
  end
  isArmed = true
  local instanceID, difficultyID = getChallengeScope()
  if not instanceID then
    isChallengeBoundary = false
    registerZoneEvents()
    return true
  end
  if capture and (capture.instanceId == instanceID and capture.difficultyId == difficultyID) then
    return true
  end
  if capture then
    finishCapture("map_changed")
  end
  if beginCapture(instanceID, difficultyID) then
    return true
  end
  stopCapture("registration_failed")
  return false
end
if type(WowBuddyDev) == "table" then
  -- 功能：插件对外的「小怪采集开关」入口：把参数交给 setCaptureArmed，并保证不抛错。
  -- 入参：armed 是否武装。
  -- 出参：布尔（最终是否处于武装状态；出错时返回 false）。
  -- 说明：整个调用包在 pcall 里 —— 这个函数会被开关界面直接调用，读游戏状态失败时不能让界面报错；出错时还补一次 capture_error 收尾，避免留下半开的采集状态。注册失败也不算成功。
  WowBuddyDev.SetTimelinePlannerTrashCaptureArmed = function(armed)
    local ok, result = pcall(setCaptureArmed, armed)
    if ok then
      return result == true
    end
    pcall(stopCapture, "capture_error")
    return false
  end
end
