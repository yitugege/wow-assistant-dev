-- 登录事件离线宿主；不执行宏，不投递按键，不代表游戏安全授权。
fixtureClass=fixtureClass or 'MAGE'
fixtureClassID=fixtureClassID or 8
fixtureSpecID=fixtureSpecID or 1482
function UnitClass() return fixtureClass,fixtureClass,fixtureClassID end
function GetSpecializationInfo() return fixtureSpecID end
function EmitFixtureEvent(event,...)
  local unit=select(1,...)
  local function receives(frame)
    if frame.events and frame.events[event] then return true end
    local units=frame.unitEvents and frame.unitEvents[event]
    if units then
      for _,registered in ipairs(units) do if registered==unit then return true end end
    end
    return false
  end
  -- 固定本次分发的接收者；回调新建帧留给下一次事件。
  local recipients={}
  for _,frame in ipairs(frames) do
    if receives(frame) then table.insert(recipients,frame) end
  end
  for _,frame in ipairs(recipients) do
    if receives(frame) and frame.scripts.OnEvent then frame.scripts.OnEvent(frame,event,...) end
  end
end
function date(format)
  assert(format=='%H:%M:%S')
  return '12:00:00'
end
local methods=getmetatable(UIParent).__index
function methods:UnregisterEvent(event)
  if self.events then self.events[event]=nil end
  if self.unitEvents then self.unitEvents[event]=nil end
end
function methods:UnregisterAllEvents() self.events={};self.unitEvents={} end
function methods:SetAttribute(key,value)
  self.attributes=self.attributes or {};self.attributes[key]=value
end
function methods:GetAttribute(key) return self.attributes and self.attributes[key] end
function ClearOverrideBindings(owner) owner.bindings={} end
function SetOverrideBindingClick(owner,priority,key,button,mouse)
  owner.bindings=owner.bindings or {}
  owner.bindings[key]={button=button,mouse=mouse,priority=priority}
  return true
end
