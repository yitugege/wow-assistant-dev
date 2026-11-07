-- 进入世界后的单次计时器宿主；不执行周期计时器/OnUpdate/光环引擎。
pendingAfter={}; executedAfter={}
fixtureCVars={useUiScale='1',uiScale='0.75'}; fixtureCVarWrites={}; fixturePopups={}
function GetCVar(key) return fixtureCVars[key] end
function SetCVar(key,value)
  if key=='useUiScale' and fixtureRejectScale then return false end
  fixtureCVars[key]=tostring(value)
  table.insert(fixtureCVarWrites,{key=key,value=tostring(value)})
  EmitFixtureEvent('CVAR_UPDATE',key,tostring(value))
end
C_CVar={GetCVar=GetCVar,SetCVar=SetCVar}
function StaticPopup_Show(key,text) fixturePopups[key]=text end
function StaticPopup_Hide(key) fixturePopups[key]=nil end
function C_Timer.After(delay,callback)
  assert(type(delay)=='number' and delay>=0 and type(callback)=='function')
  table.insert(pendingAfter,{due=now+delay,callback=callback})
end
function AdvanceFixtureTime(seconds)
  local finish=now+seconds
  local count=0
  while true do
    local index=nil
    for i,timer in ipairs(pendingAfter) do
      if timer.due<=finish and (not index or timer.due<pendingAfter[index].due) then index=i end
    end
    if not index then break end
    count=count+1; assert(count<=1000,'单次计时器未收敛')
    local timer=table.remove(pendingAfter,index)
    now=timer.due
    timer.callback()
    table.insert(executedAfter,timer)
  end
  now=finish
  return count
end
local methods=getmetatable(UIParent).__index
function methods:SetFont(path,size,flags) self.font={path,size,flags} end
function methods:GetFont() if self.font then return unpack(self.font) end end
function methods:SetUnit(unit)
  assert(self.kind=='AuraContainer')
  self.unit=unit
end
function methods:UpdateAllAuras()
  assert(self.kind=='AuraContainer')
  self.auraUpdates=(self.auraUpdates or 0)+1
end
function methods:AddAuraSlot(key,filter,options)
  assert(self.kind=='AuraContainer')
  self.auraSlots=self.auraSlots or {}
  self.auraSlots[key]={filter=filter,options=options}
end
