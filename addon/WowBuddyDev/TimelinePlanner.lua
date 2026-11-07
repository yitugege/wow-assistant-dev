-- ==========================================================================
-- 文件：2a88b8.lua
-- 来源：P07483180.rar → P07483180/2a88b8.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：2a88b8.lua → TimelinePlanner.lua（按功能重命名）
-- 作用：时间轴规划器主体（逐帧采集、预警）
-- ==========================================================================
local ALERT_SEAL_COLOR = 3260648
local COLOR_MASK_24BIT = 16777215
local GEN_WRAP_LIMIT = 8388607
local MAX_PENDING_QUEUE = 32
local ALERT_MIN_INTERVAL = .15
local STATE_SHIFT = 8192
local MECHANIC_SHIFT = 65536
local STAGE_SHIFT = 4096
local STATE_WAITING = 0
local STATE_ACTIVE = 1
local STATE_PAUSED = 2
local STATE_FINISHED = 3
local STATE_REMOVED = 4
local STATE_REMOVED_ALERT = 5
local alertFrame = nil
local alertCells = {}
local encounterFrame = CreateFrame("Frame")
local timelineFrame = CreateFrame("Frame")
local isArmed = false
local isManuallyArmed = false
local isSpecKnown, isManuallyDisarmed = false, false
local lastSpecID = nil
local displayGeneration = 0
local alertGeneration = 0
local encounterKey = nil
local encounterConfig = nil
local encounterState = nil
local mechanicOccurrences = {}
local flaggedEventIDs = {}
local publishedByEventID = {}
local pendingAlerts = {}
local lastAlert = nil
local lastAlertAt = 0
local pendingEvents, pendingEventByID = {}, {}
local batchDeadline = nil
local activeCapture = nil
local MAX_CAPTURE_RUNS = 3
local MAX_CAPTURE_EVENTS = 1024
local timelineEventNames = {
  "ENCOUNTER_TIMELINE_EVENT_ADDED",
  "ENCOUNTER_TIMELINE_EVENT_STATE_CHANGED",
  "ENCOUNTER_TIMELINE_EVENT_REMOVED",
  "ENCOUNTER_TIMELINE_VIEW_DEACTIVATED",
}
-- 功能：判断一个值是不是有限数（不是 nan、不是正负无穷）。
-- 入参：value 待判断的值。
-- 出参：布尔。
-- 说明：写法 `value == value` 是排除 nan（nan 不等于自身）；客户端把数值标记成机密（secret）时这里仍会返回真，所以调用方还要先过 isSecretValue。
local function isFiniteNumber(value)
  return value == value and (value ~= math.huge and value ~= -math.huge)
end
-- 功能：判断一个值是不是客户端「机密值」—— 直接读它会被 taint，必须用 pcall 包着读。
-- 入参：value 待判断的值。
-- 出参：布尔（真 = 可以安全读；客户端没有 issecretvalue 这个 API 时一律返回真）。
-- 说明：读之前必须 pcall：被标记的 table/function 一碰就抛错。只有明确返回 true 才算可读，其余（抛错、返回 false）都按不可读处理。
local function isSecretValue(value)
  if type(issecretvalue) ~= "function" then
    return true
  end
  local ok, result = pcall(issecretvalue, value)
  return not ok or result == true
end
-- 功能：把值规范成「整数且在区间内」的 ID，不合法就丢掉。
-- 入参：value 待校验的值；minValue 下限；maxValue 上限，省略时不查上限。
-- 出参：通过则返回原整数，否则返回 nil。
-- 说明：先查机密值和「是不是有限数」，再做 % 1 判整数；最大 24 位色值这种大整数也要能过，所以不设位宽限制。
local function toIntInRange(value, minValue, maxValue)
  if isSecretValue(value) or type(value) ~= "number" or not isFiniteNumber(value) or value % 1 ~= 0 or value < minValue or maxValue and value > maxValue then
    return nil
  end
  return value
end
-- 功能：把倒计时/持续时间的秒数规范到 0~600 秒，越界返回 nil。
-- 入参：value 待校验的秒数。
-- 出参：合法返回原数，否则返回 nil。
-- 说明：上限 600 对应客户端首领时间轴的单条事件最大时长；超上限说明读到的不是本插件的目标事件，当作无效丢弃，避免脏数据写进采集结果。
local function toSecondsOrNil(value)
  if isSecretValue(value) or type(value) ~= "number" or not isFiniteNumber(value) or value < 0 or value > 600 then
    return nil
  end
  return value
end
-- 功能：取当前时间（秒），优先用高精度时钟 GetTimePreciseSec，取不到就退回 GetTime。
-- 入参：无。
-- 出参：秒数；两个 API 都不可用、或读出来是机密值/非法数时返回 0。
-- 说明：时间轴事件间隔可能只有零点几秒，必须用高精度时钟；返回 0 是「读不到时间」的哨兵，调用方按 0 处理，不做比较意义上的假设。
local function nowSeconds()
  local clock = type(GetTimePreciseSec) == "function" and GetTimePreciseSec or GetTime
  if type(clock) ~= "function" then
    return 0
  end
  local ok, value = pcall(clock)
  if ok and (not isSecretValue(value) and (type(value) == "number" and (isFiniteNumber(value) and value >= 0))) then
    return value
  end
  return 0
end
-- 功能：按 24 位整数给像素条纹理刷色。
-- 入参：texture 目标纹理；colorValue 24 位色值（取不到就按 0 当黑色）。
-- 出参：无。
-- 说明：客户端 SetColorTexture 收 0~1 小数，而采集回读端认的是整数色值，所以这里把整数按 16 位红 / 8 位绿 / 8 位蓝拆开再除以 255。
local function setBarColor(texture, colorValue)
  colorValue = math.max(0, math.min(COLOR_MASK_24BIT, math.floor(tonumber(colorValue) or 0)))
  local red = math.floor(colorValue / 65536) % 256
  local green = math.floor(colorValue / 256) % 256
  local blue = colorValue % 256
  texture:SetColorTexture(red / 255, green / 255, blue / 255, 1)
end
-- 功能：保证 8 格预警像素条存在、挂在插件像素容器上并归位到左上角。
-- 入参：无。
-- 出参：无。
-- 说明：父框从 P07483180.pixelContainer 退回 UIParent —— 面板还没建好时也得能画预警；父框换了要重新 SetParent 并清锚点，否则条会留在旧父框的坐标系里。
local function ensureAlertBars()
  local container = WowBuddyDev.pixelContainer or UIParent
  if not alertFrame then
    alertFrame = CreateFrame("Frame", nil, container)
    alertFrame:SetSize(8, 32)
    alertFrame:SetFrameStrata("TOOLTIP")
    alertFrame:SetFrameLevel(10000)
    for index = 0, 7, 1 do
      local cell = alertFrame:CreateTexture(nil, "OVERLAY")
      cell:SetSize(4, 4)
      cell:SetBlendMode("BLEND")
      cell:SetPoint("TOPLEFT", alertFrame, "TOPLEFT", 4, -index * 4)
      cell:SetColorTexture(0, 0, 0, 1)
      alertCells[index + 1] = cell
    end
  elseif alertFrame:GetParent() ~= container then
    alertFrame:SetParent(container)
  end
  alertFrame:ClearAllPoints()
  alertFrame:SetPoint("TOPLEFT", container, "TOPLEFT", 0, 0)
end
-- 功能：把「上次观测到的剩余时间」按已经过去的时间外推，得到此刻的剩余时间（不小于 0）。
-- 入参：alert 预警数据（state / remaining / observedAt）；now 当前时间。
-- 出参：剩余秒数。
-- 说明：只有等待状态（state = 0）才需要扣掉流逝时间；其余状态直接返回记录的剩余值，避免把已暂停/已结束的事件算成负数继续倒计时。
local function projectRemaining(alert, now)
  if alert.state == STATE_WAITING then
    return math.max(0, alert.remaining - math.max(0, now - alert.observedAt))
  end
  return math.max(0, alert.remaining)
end
-- 功能：把一次采集写入调用用 pcall 包起来，失败时给当前记录打 captureFailed 标记并停掉事件注册。
-- 入参：fn 要执行的采集函数；... 透传给它。
-- 出参：无。
-- 说明：采集本身出错不能让插件崩，所以吞掉异常；标记和停注册是给事后排查留证据 —— 出错后继续采集只会一直报错。
local function recordCapture(fn, ...)
  local ok = pcall(fn, ...)
  if not ok then
    local capture = activeCapture
    activeCapture = nil
    if capture then
      pcall(function()
        capture.captureFailed = true
      end)
    end
    if not isArmed then
      pcall(timelineFrame.UnregisterAllEvents, timelineFrame)
    end
  end
end
-- 功能：在 DB.timelinePlannerCapture 里开一条新采集记录，并记下客户端版本。
-- 入参：encounterID 首领 ID；difficultyID 难度 ID；observationOnly 是否为「只观察不发布」模式。
-- 出参：无（成功时把记录同时挂到模块级 activeCapture）。
-- 说明：DB 不是 table、或 schemaVersion 对不上就直接放弃，绝不动玩家的存档。runs 只留最近 MAX_CAPTURE_RUNS 条，超了从头删并累加 droppedRuns；nextRunId 用完一圈回绕，不越 24 位上限。
local function beginCapture(encounterID, difficultyID, observationOnly)
  if type(WowBuddyDev.DB) ~= "table" then
    return
  end
  local capture = WowBuddyDev.DB.timelinePlannerCapture
  if capture == nil then
    capture = { schemaVersion = 1, nextRunId = 1, droppedRuns = 0, runs = {} }
    WowBuddyDev.DB.timelinePlannerCapture = capture
  end
  if type(capture) ~= "table" or capture.schemaVersion ~= 1 or type(capture.runs) ~= "table" or not toIntInRange(capture.nextRunId, 1, COLOR_MASK_24BIT) or not toIntInRange(capture.droppedRuns, 0, COLOR_MASK_24BIT) then
    return
  end
  while #capture.runs >= MAX_CAPTURE_RUNS do
    table.remove(capture.runs, 1)
    capture.droppedRuns = capture.droppedRuns + 1
  end
  activeCapture = {
    runId = capture.nextRunId,
    encounterId = encounterID,
    difficultyId = difficultyID,
    observationOnly = observationOnly,
    startedAt = nowSeconds(),
    eventsSeen = 0,
    eventsDropped = 0,
    events = {},
  }
  capture.nextRunId = capture.nextRunId % COLOR_MASK_24BIT + 1
  capture.runs[#capture.runs + 1] = activeCapture
  if type(GetBuildInfo) == "function" then
    local ok, build, version = pcall(GetBuildInfo)
    if ok and (not isSecretValue(version) and (type(version) == "string" and (#version <= 32 and version:match("^%d+$")))) then
      activeCapture.build = version
    end
  end
end
-- 功能：采集计数 +1 后执行一次日志写入；超过单条记录的事件上限就只累加丢弃计数。
-- 入参：fn 真正写日志的函数；... 透传给它。
-- 出参：无。
-- 说明：eventsSeen 与 eventsDropped 一起看才能判断采到的数据完不完整 —— 写满了还继续往里塞会让存档膨胀，所以宁可丢。
local function logCaptureEvent(fn, ...)
  activeCapture.eventsSeen = activeCapture.eventsSeen + 1
  if #activeCapture.events >= MAX_CAPTURE_EVENTS then
    activeCapture.eventsDropped = activeCapture.eventsDropped + 1
    return
  end
  fn(...)
end
-- 功能：给一条事件数据补上序号、时间戳和类型，追加进当前采集记录。
-- 入参：kindName 事件类型名；record 事件数据（本函数直接改它）。
-- 出参：无。
-- 说明：eventsSeen 是自增计数，在入库那一刻取作 index，保证序号连续且与 eventsDropped 对得上。
local function appendCaptureEvent(kindName, record)
  record.index, record.at, record.kind = activeCapture.eventsSeen, nowSeconds(), kindName
  activeCapture.events[#activeCapture.events + 1] = record
end
-- 功能：给当前采集记录写上结束时间与结束原因，然后把它从模块级变量摘掉。
-- 入参：reason 结束原因（nil 时记成 stopped）。
-- 出参：无。
-- 说明：先落盘再置 nil —— 反过来的话 recordCapture 出错路径会拿不到记录，结束信息就丢了。
local function endCapture(reason)
  activeCapture.endedAt, activeCapture.endReason = nowSeconds(), reason or "stopped"
  activeCapture = nil
end
-- 功能：记一条「表面事件」日志，用于回读端还原预警条的发布序列。
-- 入参：alert 预警数据；sequence 该次预警的序号；mechanicWord 机制词；stateWord 状态词。
-- 出参：无。
-- 说明：同时带上当前遭遇战 scope 与显示代次（generation），回读端靠这两项把日志归到同一场战斗。
local function logSurfaceEvent(alert, sequence, mechanicWord, stateWord)
  appendCaptureEvent("surface", {
    sequence = sequence,
    encounterScope = encounterKey,
    generation = displayGeneration,
    eventId = alert.eventID,
    mechanicWord = mechanicWord,
    stateWord = stateWord,
  })
end
-- 功能：把一条预警发布到 8 格像素条上（写入各格的色值 + 整数编码字段），并更新当前预警状态。
-- 入参：alert 预警数据（eventID / mechanicCode / stageCode / occurrence / state / remaining / observedAt）；now 当前时间。
-- 出参：无。
-- 说明：条上只能放整数色值，所以把「机制码、阶段码、出现次数、状态、剩余时间（0.1 秒精度）」压进几个格子的整数里；格 1 固定写 ALERT_SEAL_COLOR 当帧头，回读端认出这个色值才认为这一帧有效。ALERT_MIN_INTERVAL 内的连续两次发布只发后者，避免条上闪帧。
local function publishAlert(alert, now)
  ensureAlertBars()
  alertGeneration = alertGeneration % GEN_WRAP_LIMIT + 1
  local sealValue = alertGeneration * 2
  local remainingTenths = math.max(0, math.min(6000, math.floor(projectRemaining(alert, now) * 10 + .5)))
  local mechanicField = alert.mechanicCode * MECHANIC_SHIFT + alert.stageCode * STAGE_SHIFT + alert.occurrence
  local timeField = alert.state * STATE_SHIFT + remainingTenths + 1
  setBarColor(alertCells[2], 0)
  setBarColor(alertCells[1], ALERT_SEAL_COLOR)
  setBarColor(alertCells[3], encounterKey)
  setBarColor(alertCells[4], displayGeneration)
  setBarColor(alertCells[5], alert.eventID)
  setBarColor(alertCells[6], mechanicField)
  setBarColor(alertCells[7], timeField)
  setBarColor(alertCells[8], sealValue)
  setBarColor(alertCells[2], sealValue)
  lastAlert = alert
  lastAlertAt = now
  if activeCapture then
    recordCapture(logCaptureEvent, logSurfaceEvent, alert, sealValue, mechanicField, timeField)
  end
end
-- 功能：按事件 ID 把还在排队等待发布的预警从队列里删掉。
-- 入参：eventID 事件 ID（非正数直接返回）。
-- 出参：无。
-- 说明：从尾部往前删 —— 正向删会让后面的元素前移而漏掉重复项。
local function removeQueuedAlert(eventID)
  if eventID <= 0 then
    return
  end
  for index = #pendingAlerts, 1, -1 do
    if pendingAlerts[index].eventID == eventID then
      table.remove(pendingAlerts, index)
    end
  end
end
local onUpdate, flushQueuedEvents, stopCapture
-- 功能：按队列里还有没有待处理项，决定挂上还是摘掉逐帧回调 OnUpdate。
-- 入参：无。
-- 出参：无。
-- 说明：队列空了必须摘回调，否则每帧空转白耗；两个队列（预警队列、事件队列）任一非空都得保持开启。
local function scheduleUpdate()
  if #pendingAlerts > 0 or #pendingEvents > 0 then
    timelineFrame:SetScript("OnUpdate", onUpdate)
  else
    timelineFrame:SetScript("OnUpdate", nil)
  end
end
-- 功能：逐帧驱动：到点先冲刷待解析的事件队列，再从预警队列取一条发布到像素条。
-- 入参：无（挂在 frame3 的 OnUpdate 上）。
-- 出参：无。
-- 说明：分三处提前返回 —— 未武装、预警队列为空、距上次发布不足 ALERT_MIN_INTERVAL。发布节流是必须的：时间轴事件可能一瞬间来十几条，不节流回读端会丢帧。事件队列冲刷失败就整体停掉采集，不能让坏数据继续往里灌。
onUpdate = function()
  local now = nowSeconds()
  if batchDeadline and now >= batchDeadline then
    local ok = pcall(flushQueuedEvents)
    if not ok then
      stopCapture()
      return
    end
  end
  if not isArmed or #pendingAlerts == 0 then
    scheduleUpdate()
    return
  end
  if now - lastAlertAt < ALERT_MIN_INTERVAL then
    return
  end
  publishAlert(table.remove(pendingAlerts, 1), now)
  scheduleUpdate()
end
-- 功能：把一条客户端时间轴事件状态变化整理进预警队列 / 已发布表，并立即发布或排队。
-- 入参：event 客户端事件数据；publish 是否立即发布（nil 按「不立即」处理）。
-- 出参：无。
-- 说明：state = 4（事件被移除）时整条队列作废并假装发一条「清空帧」，回读端据此判定战斗结束。同一个事件 ID 的重启要先撤掉旧的那条，否则同一事件会在条上叠两条。
local function handleEventRecord(event, publish)
  local now = nowSeconds()
  if event.state == STATE_REMOVED_ALERT then
    wipe(pendingAlerts)
  else
    removeQueuedAlert(event.eventID)
  end
  if #pendingAlerts >= MAX_PENDING_QUEUE then
    wipe(pendingAlerts)
    wipe(publishedByEventID)
    displayGeneration = displayGeneration % COLOR_MASK_24BIT + 1
    publishAlert({
      eventID = 0,
      mechanicCode = 0,
      stageCode = 0,
      occurrence = 0,
      state = STATE_REMOVED_ALERT,
      remaining = 0,
      observedAt = now,
    }, now)
    scheduleUpdate()
    return
  end
  local recentAlert = lastAlert ~= nil and now - lastAlertAt < ALERT_MIN_INTERVAL
  if publish then
    if event.state == STATE_REMOVED_ALERT then
      publishAlert(event, now)
      scheduleUpdate()
      return
    end
    if recentAlert and lastAlert.state >= STATE_PAUSED then
      table.insert(pendingAlerts, 1, event)
      scheduleUpdate()
      return
    end
    if recentAlert and (lastAlert.eventID ~= event.eventID and lastAlert.state <= STATE_ACTIVE) then
      removeQueuedAlert(lastAlert.eventID)
      table.insert(pendingAlerts, 1, lastAlert)
    end
    publishAlert(event, now)
    scheduleUpdate()
    return
  end
  if not recentAlert and #pendingAlerts == 0 then
    publishAlert(event, now)
    scheduleUpdate()
    return
  end
  table.insert(pendingAlerts, event)
  scheduleUpdate()
end
-- 功能：把散装的（事件 ID、状态、剩余时间、时间戳）拼成一条预警记录后交给 handleEventRecord。
-- 入参：event 带 eventID 的原始事件；state 状态码；remaining 剩余秒数；publish 是否立即发布；observedAt 观测时间（省略时取当前时间）。
-- 出参：无。
-- 说明：机制码从 encounterConfig.mechanicCodes 按机制的键查出来，查不到就是 nil —— 这一步只整理数据，不做发布判断。
local function handleEventByFields(event, state, remaining, publish, observedAt)
  handleEventRecord({
    eventID = event.eventID,
    mechanicCode = encounterConfig.mechanicCodes[event.mechanicKey],
    stageCode = event.stageCode,
    occurrence = event.occurrence,
    state = state,
    remaining = remaining,
    observedAt = observedAt or nowSeconds(),
  }, publish)
end
-- 功能：往预警队列里压一条「空事件」，让像素条整条清掉。
-- 入参：无。
-- 出参：无。
-- 说明：事件 ID 和各类编码全写 0，状态写 4（已被移除）。换首领、重置视图都要先清条，否则上一次战斗的残留数字会被回读端当成新数据。
local function resetAlerts()
  handleEventRecord({
    eventID = 0,
    mechanicCode = 0,
    stageCode = 0,
    occurrence = 0,
    state = STATE_REMOVED_ALERT,
    remaining = 0,
    observedAt = nowSeconds(),
  }, true)
end
-- 功能：读一个时间轴事件对象的 id / source / duration，三个字段全读得到才认。
-- 入参：event 客户端时间轴事件对象。
-- 出参：eventID、duration；字段读不到、或 source 不是 0（0 = 首领机制，别的来源不是本插件要的）时返回 nil。
-- 说明：三个字段都各自 pcall 单独读、单独判 ok —— 客户端把机密字段混在同一张表里，一次 pcall 读多个字段的话一个坏字段会拖掉其余好字段。
local function parseTimelineEvent(event)
  local ok, eventID = pcall(function()
    return event.id
  end)
  local sourceOk, source = pcall(function()
    return event.source
  end)
  local durationOk, duration = pcall(function()
    return event.duration
  end)
  if not ok or not sourceOk or not durationOk then
    return nil
  end
  local eventID = toIntInRange(eventID, 1, COLOR_MASK_24BIT)
  local source = toIntInRange(source, 0, 2)
  local duration = toSecondsOrNil(duration)
  if not eventID or source ~= 0 or not duration then
    return nil
  end
  return eventID, duration
end
-- 功能：查一个时间轴事件当前的状态码。
-- 入参：eventID 事件 ID。
-- 出参：状态码；API 不可用、或返回值不合法时返回 nil。
-- 说明：不同客户端版本 C_EncounterTimeline 的可用性不一样，所以每次调用都重新查 API 在不在，不做缓存。
local function getEventState(eventID)
  if type(C_EncounterTimeline) ~= "table" or type(C_EncounterTimeline.GetEventState) ~= "function" then
    return nil
  end
  local ok, state = pcall(C_EncounterTimeline.GetEventState, eventID)
  return ok and toIntInRange(state, STATE_WAITING, STATE_FINISHED) or nil
end
-- 功能：查一个时间轴事件的剩余时间（秒）。
-- 入参：eventID 事件 ID。
-- 出参：秒数；API 不可用或值不合法时返回 nil。
-- 说明：与 getEventState 同理，先查 API 再用，避免老客户端上报错。
local function getEventRemaining(eventID)
  if type(C_EncounterTimeline) ~= "table" or type(C_EncounterTimeline.GetEventTimeRemaining) ~= "function" then
    return nil
  end
  local ok, remaining = pcall(C_EncounterTimeline.GetEventTimeRemaining, eventID)
  return ok and toSecondsOrNil(remaining) or nil
end
-- 功能：一次取到事件的状态码和剩余时间。
-- 入参：eventID 事件 ID。
-- 出参：state、remaining；状态读不到返回 nil；已经进入暂停及以后的状态时只返回 state、remaining 记 0。
-- 说明：状态 >= 2 之后客户端不再提供剩余时间，这里返回 0 而不是 nil，调用方才能区分「没有剩余时间」和「读不到事件」。
local function getEventStateAndRemaining(eventID)
  local state = getEventState(eventID)
  if state == nil then
    return nil
  end
  if state >= STATE_PAUSED then
    return state, 0
  end
  local remaining = getEventRemaining(eventID)
  return state, remaining
end
-- 功能：把一条客户端时间轴事件转成采集日志条目（按事件名分别取字段）。
-- 入参：eventName 事件名；... 事件的原始参数。
-- 出参：无（日志直接进当前采集记录）。
-- 说明：四种事件各自要的字段不同 —— ADDED 要 id/source/duration/spellID，STATE_CHANGED 和 REMOVED 只要 id，VIEW_DEACTIVATED 什么都不带。每个字段单独 pcall 读，任何一个读数失败只丢那一个字段，不影响整条日志；只有 source = 0 才补查状态和剩余时间。
local function recordTimelineEvent(eventName, ...)
  local payload = ...
  local eventData, kindName = {}, nil
  if eventName == "ENCOUNTER_TIMELINE_EVENT_ADDED" then
    kindName = "added"
    local eventIdOk, eventID = pcall(function()
      return payload.id
    end)
    local sourceOk2, source = pcall(function()
      return payload.source
    end)
    local durationOk, duration = pcall(function()
      return payload.duration
    end)
    local spellIdOk, spellID = pcall(function()
      return payload.spellID
    end)
    eventData.eventId = eventIdOk and toIntInRange(eventID, 1, COLOR_MASK_24BIT) or nil
    eventData.source = sourceOk2 and toIntInRange(source, 0, 2) or nil
    eventData.duration = durationOk and toSecondsOrNil(duration) or nil
    eventData.spellId = spellIdOk and toIntInRange(spellID, 1, COLOR_MASK_24BIT) or nil
    if eventData.eventId and eventData.source == 0 then
      eventData.state = getEventState(eventData.eventId)
      eventData.remaining = getEventRemaining(eventData.eventId)
    end
  elseif eventName == "ENCOUNTER_TIMELINE_EVENT_STATE_CHANGED" then
    kindName, eventData.eventId = "state_changed", toIntInRange(payload, 1, COLOR_MASK_24BIT)
    if eventData.eventId then
      eventData.state = getEventState(eventData.eventId)
      if eventData.state and eventData.state < STATE_PAUSED then
        eventData.remaining = getEventRemaining(eventData.eventId)
      end
    end
  elseif eventName == "ENCOUNTER_TIMELINE_EVENT_REMOVED" then
    kindName, eventData.eventId = "removed", toIntInRange(payload, 1, COLOR_MASK_24BIT)
  elseif eventName == "ENCOUNTER_TIMELINE_VIEW_DEACTIVATED" then
    kindName = "view_reset"
  else
    kindName, eventData.event = "unit_event", eventName
  end
  appendCaptureEvent(kindName, eventData)
end
-- 功能：记一条「已解析」日志（事件 ID、时长、机制键、阶段、出现次数、是否请求发布）。
-- 入参：event 原始事件；mechanicKey 机制键；stage 阶段码；occurrence 出现次数；publish 是否请求发布。
-- 出参：无。
-- 说明：publishRequested 只在「机制键有效且 publish 不是明确的 false」时为真 —— 采集时用它区分「确实不该发」和「发了但没发出去」。
local function logResolvedEvent(event, mechanicKey, stageCode, occurrence, publish)
  appendCaptureEvent("resolved", {
    eventId = event.eventID,
    duration = event.duration,
    mechanicKey = mechanicKey,
    stage = stageCode,
    occurrence = occurrence,
    publishRequested = mechanicKey ~= nil and publish ~= false,
  })
end
-- 功能：给某个机制的出现次数 +1，返回新计数。
-- 入参：mechanicKey 机制键。
-- 出参：该机制本次的出现序号（从 1 开始）。
-- 说明：计数按机制键分开记，同一个首领的多个机制互不干扰。
local function bumpOccurrence(event)
  mechanicOccurrences[event] = (mechanicOccurrences[event] or 0) + 1
  return mechanicOccurrences[event]
end
-- 功能：把一个还没进入暂停状态的事件标记成「已被替换」。
-- 入参：event 事件记录。
-- 出参：无。
-- 说明：状态 < 2（还在等待或进行中）时先按「已移除」发一条，再把它的已发布记录删掉 —— 不清掉的话下一步新事件的剩余时间会被旧记录挡住。
local function retireEvent(event)
  if event.state < STATE_PAUSED then
    handleEventByFields(event, STATE_REMOVED, 0, true)
  end
  publishedByEventID[event.eventID] = nil
end
-- 功能：解析一条事件记录的机制归属（机制键 + 阶段码 + 出现次数），必要时先退掉被它顶替的同类事件，然后发布到像素条。
-- 入参：event 事件记录；publish 是否发布（false 表示只做身份识别）。
-- 出参：无。
-- 说明：机制解析失败只写一条失败日志就返回，不发布。同一个机制键、状态 <= 1 的旧事件会被新事件顶掉（retireEvent）—— 首领重复读同一条机制时条上要显示最新的那次。
local function resolveEvent(event, publish)
  local mechanicKey, stageCode, previous = encounterState.Resolve(event.duration, event.eventID, event.observedAt, event.state)
  if not mechanicKey then
    if activeCapture then
      recordCapture(logCaptureEvent, logResolvedEvent, event, nil, stageCode, nil, false)
    end
    return
  end
  local previous = previous and publishedByEventID[previous]
  if previous and (previous.eventID ~= event.eventID and (previous.mechanicKey == mechanicKey and previous.state <= STATE_ACTIVE)) then
    retireEvent(previous)
  end
  local resolved = { eventID = event.eventID, mechanicKey = mechanicKey, stageCode = stageCode, occurrence = bumpOccurrence(mechanicKey), state = event.state }
  if activeCapture then
    recordCapture(logCaptureEvent, logResolvedEvent, event, mechanicKey, stageCode, resolved.occurrence, publish)
  end
  if publish == false then
    return
  end
  if not event.removed then
    publishedByEventID[resolved.eventID] = resolved
  end
  handleEventByFields(resolved, event.state, event.remaining, event.state >= STATE_PAUSED, event.observedAt)
end
-- 功能：把事件队列整批冲刷：先交给 encounterState.PrepareBatch，再逐条解析发布。
-- 入参：publish 是否发布（队列项自带 identityOnly 时强制只做身份识别）。
-- 出参：无。
-- 说明：先把队列和 ID 索引整体换出来再处理，处理过程中新到的事件会落在新队列里，不会被这一轮的清空误删；batchDeadline 也在同一处复位，否则下一次排队会立刻再次触发冲刷。
flushQueuedEvents = function(publish)
  if #pendingEvents == 0 then
    return
  end
  local queued = pendingEvents
  pendingEvents, pendingEventByID, batchDeadline = {}, {}, nil
  encounterState.PrepareBatch(queued)
  for index, value in ipairs(queued) do
    resolveEvent(value, publish ~= false and not value.identityOnly)
  end
end
-- 功能：把一条事件记录放进待解析队列，并定下这一批的冲刷时刻。
-- 入参：event 事件记录（带 observedAt）。
-- 出参：无。
-- 说明：到点先冲刷上一批；队列满了（MAX_PENDING_QUEUE）就整体作废并停采集 —— 时间轴事件是逐帧来的，堆满说明已经跟不上，继续堆只会越拖越久。冲刷时刻 = 首次入队时间 + encounterConfig.batchSeconds，同一批共用。
local function queueEvent(event)
  local queuedAt = event.observedAt or nowSeconds()
  if batchDeadline and queuedAt >= batchDeadline then
    flushQueuedEvents()
  end
  if #pendingEvents >= MAX_PENDING_QUEUE then
    stopCapture()
    return
  end
  pendingEvents[#pendingEvents + 1] = event
  pendingEventByID[event.eventID] = event
  batchDeadline = batchDeadline or queuedAt + encounterConfig.batchSeconds
  scheduleUpdate()
end
-- 功能：处理「时间轴事件新增」：识别事件身份，按配置决定排队等批次还是立刻记录/发布。
-- 入参：eventID 客户端事件 ID。
-- 出参：无。
-- 说明：已经有记录的事件（flaggedEventIDs）直接跳过，避免重复计数。source != 0 的事件不算首领机制。只观察不发布的模式（v10.countIdentifiableAdds）下状态已进入暂停及以后就只调 OnEventClosed，不再往条上发。
local function onEventAdded(eventID)
  local eventID, duration = parseTimelineEvent(eventID)
  if not eventID or flaggedEventIDs[eventID] then
    return
  end
  local state, remaining = getEventStateAndRemaining(eventID)
  if state == nil or remaining == nil or state >= STATE_PAUSED then
    if encounterConfig.batchSeconds and (encounterState.IsPhaseMarker and encounterState.IsPhaseMarker(duration)) then
      flaggedEventIDs[eventID] = true
      queueEvent({ eventID = eventID, duration = duration, identityOnly = true, observedAt = nowSeconds() })
    elseif encounterConfig.countIdentifiableAdds then
      flaggedEventIDs[eventID] = true
      resolveEvent({ eventID = eventID, duration = duration, state = state, observedAt = nowSeconds() }, false)
      if state and (state >= STATE_PAUSED and encounterState.OnEventClosed) then
        encounterState.OnEventClosed(eventID, state, "added")
      end
    end
    return
  end
  flaggedEventIDs[eventID] = true
  local now = nowSeconds()
  local eventRecord = { eventID = eventID, duration = duration, state = state, remaining = remaining, observedAt = now }
  if encounterConfig.batchSeconds then
    queueEvent(eventRecord)
    return
  end
  resolveEvent(eventRecord)
end
-- 功能：处理「事件状态变化」：刷新待解析队列项或已发布记录的状态与剩余时间，必要时补发结束回调。
-- 入参：rawEventID 客户端事件 ID。
-- 出参：无。
-- 说明：先查状态机有没有这条事件、再看有没有待解析的队列项，两条路各管一套刷新逻辑。已经进入暂停及以后、或已经被移除的事件不再刷新；状态和剩余时间读不出来时按「已移除」处理并写回记录，不能留着旧值继续倒计时。
local function onEventStateChanged(rawEventID)
  local eventID = toIntInRange(rawEventID, 1, COLOR_MASK_24BIT)
  local state
  if eventID and encounterState.OnEventClosed then
    state = getEventState(eventID)
    if state and state >= STATE_PAUSED then
      encounterState.OnEventClosed(eventID, state, "state_changed")
    end
  end
  local pending = eventID and pendingEventByID[eventID] or nil
  if pending then
    if pending.identityOnly or pending.removed or pending.state >= STATE_PAUSED then
      return
    end
    if not encounterState.OnEventClosed then
      state = getEventState(eventID)
    end
    local remaining = 0
    if state and state < STATE_PAUSED then
      remaining = getEventRemaining(eventID)
    end
    if state == nil or remaining == nil then
      state, remaining, pending.removed = STATE_REMOVED, 0, true
    end
    pending.state, pending.remaining, pending.observedAt = state, remaining, nowSeconds()
    return
  end
  local published = eventID and publishedByEventID[eventID] or nil
  if not published then
    return
  end
  if not encounterState.OnEventClosed then
    state = getEventState(eventID)
  end
  if state == nil then
    retireEvent(published)
    return
  end
  local remaining = 0
  if state < STATE_PAUSED then
    remaining = getEventRemaining(eventID)
    if remaining == nil then
      retireEvent(published)
      return
    end
  end
  published.state = state
  handleEventByFields(published, state, remaining, true)
end
-- 功能：处理「时间轴事件移除」：把对应的队列项或已发布记录标记为已移除。
-- 入参：rawEventID 客户端事件 ID。
-- 出参：无。
-- 说明：状态还没到暂停的事件要先按「已移除」发一条再清理记录，让像素条立刻反映真实情况；已经在队列里的（identityOnly）只需打标记，不再重复发布。
local function onEventRemoved(rawEventID)
  local eventID = toIntInRange(rawEventID, 1, COLOR_MASK_24BIT)
  if eventID and encounterState.OnEventClosed then
    encounterState.OnEventClosed(eventID, STATE_REMOVED, "removed")
  end
  local pending = eventID and pendingEventByID[eventID] or nil
  if pending then
    if pending.identityOnly then
      return
    end
    pending.removed = true
    if pending.state < STATE_PAUSED then
      pending.state, pending.remaining, pending.observedAt = STATE_REMOVED, 0, nowSeconds()
    end
    return
  end
  local published = eventID and publishedByEventID[eventID] or nil
  if not published then
    return
  end
  if published.state < STATE_PAUSED then
    handleEventByFields(published, STATE_REMOVED, 0, true)
  end
  publishedByEventID[eventID] = nil
end
-- 功能：把时间轴相关事件（含配置里的单位事件）注册到 frame3 上。
-- 入参：无。
-- 出参：无。
-- 说明：单位事件按 encounterConfig.unitEventUnits 逐单位注册，没配就退回 boss1 —— 有的机制只在特定首领单位上才有施法事件。
local function registerTimelineEvents()
  for index, eventName in ipairs(timelineEventNames) do
    timelineFrame:RegisterEvent(eventName)
  end
  if encounterConfig then
    for index, unitEvent in ipairs(encounterConfig.unitEvents) do
      local units = encounterConfig.unitEventUnits and encounterConfig.unitEventUnits[unitEvent]
      if units then
        timelineFrame:RegisterUnitEvent(unitEvent, unpack(units))
      else
        timelineFrame:RegisterUnitEvent(unitEvent, "boss1")
      end
    end
  end
end
-- 功能：结束当前采集并整体复位：落盘结束信息、注销事件、清空所有队列与状态。
-- 入参：reason 结束原因。
-- 出参：无。
-- 说明：这里是唯一的「整体复位」入口，六个队列表 + 批处理截止时间 + 遭遇战上下文全清，漏一个都会让下一场战斗带着上一场的残留数据。
stopCapture = function(reason)
  if activeCapture then
    recordCapture(endCapture, reason)
  end
  isArmed = false
  timelineFrame:UnregisterAllEvents()
  timelineFrame:SetScript("OnUpdate", nil)
  wipe(publishedByEventID)
  wipe(mechanicOccurrences)
  wipe(flaggedEventIDs)
  wipe(pendingAlerts)
  wipe(pendingEvents)
  wipe(pendingEventByID)
  batchDeadline = nil
  lastAlert = nil
  lastAlertAt = 0
  encounterKey, encounterConfig, encounterState = nil, nil, nil
  if alertFrame then
    alertFrame:Hide()
  end
end
-- 功能：按首领 ID + 难度启动一场战斗的采集与时间轴跟踪。
-- 入参：encounterID 首领 ID；difficultyID 难度 ID。
-- 出参：无。
-- 说明：先停掉上一场（reason = replaced），再到 P07483180.TimelinePlannerEncounters 里查配置；查不到首领就只开一条 recaptureOnly 记录 —— 这样即使这个首领还没有机制数据，回读端也能收到原始事件用于补数据。encounterKey 用「首领 ID * 100 + 难度」拼，与数据文件的键一致。
local function startCapture(encounterID, difficultyID)
  stopCapture("replaced")
  local encounterLookup = encounterID * 100 + difficultyID
  local config = WowBuddyDev.TimelinePlannerEncounters[encounterLookup]
  recordCapture(beginCapture, encounterID, difficultyID, config == nil)
  if not config then
    if activeCapture then
      registerTimelineEvents()
    end
    return
  end
  encounterKey, encounterConfig = encounterLookup, config
  encounterState = config.Create()
  displayGeneration = displayGeneration % COLOR_MASK_24BIT + 1
  isArmed = true
  ensureAlertBars()
  alertFrame:SetShown(not (WowBuddyDev.DB and WowBuddyDev.DB.allOverlaysHidden))
  registerTimelineEvents()
  resetAlerts()
end
-- 功能：把客户端时间轴事件分派给对应的处理函数。
-- 入参：eventName 事件名；... 事件的原始参数。
-- 出参：无。
-- 说明：未武装时直接返回。四种已知事件各走一路，其余交给 encounterState.OnUnitEvent；视图停用（VIEW_DEACTIVATED）时先把待解析队列冲刷掉再重置，免得丢掉最后一批数据。
local function dispatchTimelineEvent(eventName, ...)
  if not isArmed then
    return
  end
  if eventName == "ENCOUNTER_TIMELINE_EVENT_ADDED" then
    onEventAdded(...)
  elseif eventName == "ENCOUNTER_TIMELINE_EVENT_STATE_CHANGED" then
    onEventStateChanged(...)
  elseif eventName == "ENCOUNTER_TIMELINE_EVENT_REMOVED" then
    onEventRemoved(...)
  elseif eventName == "ENCOUNTER_TIMELINE_VIEW_DEACTIVATED" then
    flushQueuedEvents(false)
    wipe(publishedByEventID)
    displayGeneration = displayGeneration % COLOR_MASK_24BIT + 1
    resetAlerts()
  elseif encounterState.OnUnitEvent then
    encounterState.OnUnitEvent(eventName, nowSeconds(), ...)
  end
end
encounterFrame:SetScript("OnEvent", function(self, event, ...)
  if not isManuallyArmed and not (isSpecKnown and not isManuallyDisarmed) then
    return
  end
  if event == "ENCOUNTER_START" then
    local encounterID, encounterName, difficultyID = ...
    local encounterID = toIntInRange(encounterID, 1, 10000)
    local difficultyID = toIntInRange(difficultyID, 1, 99)
    if not isManuallyArmed and not (encounterID and (difficultyID and WowBuddyDev.TimelinePlannerEncounters[encounterID * 100 + difficultyID])) then
      stopCapture("outside_catalog")
      return
    end
    if encounterID and difficultyID then
      local ok = pcall(startCapture, encounterID, difficultyID)
      if not ok then
        stopCapture("start_error")
      end
    else
      stopCapture("invalid_start")
    end
  elseif event == "ENCOUNTER_END" then
    stopCapture("encounter_end")
  end
end)
-- 功能：按「手动武装」或「专精已知且未被手动关掉」决定要不要注册首领事件，并同步注册状态。
-- 入参：无。
-- 出参：无。
-- 说明：先全部注销再按条件注册，保证开关来回切之后不会留下重复注册。
local function ensureEventsRegistered()
  encounterFrame:UnregisterAllEvents()
  if isManuallyArmed or isSpecKnown and not isManuallyDisarmed then
    encounterFrame:RegisterEvent("ENCOUNTER_START")
    encounterFrame:RegisterEvent("ENCOUNTER_END")
  end
end
-- 功能：设置时间轴规划器的武装状态（手动开关），并立刻刷新事件注册。
-- 入参：armed 是否武装（只有严格的 true 才算武装）。
-- 出参：武装后的状态。
-- 说明：true 会同时清掉「手动关闭」标志，false 则置上 —— 手动开关的优先级高于「专精已知」。关掉时如果之前是武装的，要走一次停采集把状态清干净。
function WowBuddyDev.SetTimelinePlannerArmed(armed)
  local wanted = armed == true
  isManuallyArmed = wanted
  isManuallyDisarmed = not wanted
  ensureEventsRegistered()
  if not isManuallyArmed then
    stopCapture("disarmed")
  end
  return isManuallyArmed
end
local frame4 = CreateFrame("Frame")
-- 功能：读当前专精 ID，专精变了就停掉当前采集，然后刷新「专精已知」标志和事件注册。
-- 入参：无。
-- 出参：无。
-- 说明：专精信息读不到（pcall 失败）就按「未知专精」处理并停采集 —— 换专精后机制表整个不同，带着旧专精的配置继续跑出来的数据是错的。
local function refreshSpecAndArmed()
  local ok, specID = pcall(function()
    return GetSpecializationInfo(GetSpecialization())
  end)
  local specID = ok and toIntInRange(specID, 1, 10000) or nil
  if specID ~= lastSpecID then
    stopCapture("spec_changed")
  end
  lastSpecID, isSpecKnown = specID, specID ~= nil
  ensureEventsRegistered()
end
frame4:RegisterEvent("PLAYER_ENTERING_WORLD")
frame4:RegisterEvent("PLAYER_SPECIALIZATION_CHANGED")
frame4:SetScript("OnEvent", function(self2, event2, unitTarget)
  if event2 == "PLAYER_SPECIALIZATION_CHANGED" and unitTarget ~= "player" then
    return
  end
  refreshSpecAndArmed()
end)
refreshSpecAndArmed()
timelineFrame:SetScript("OnEvent", function(self3, event3, ...)
  if activeCapture then
    recordCapture(logCaptureEvent, recordTimelineEvent, event3, ...)
  end
  local ok = pcall(dispatchTimelineEvent, event3, ...)
  if not ok then
    stopCapture("event_error")
  end
end)
