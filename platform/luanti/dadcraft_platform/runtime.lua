-- Engine-neutral lifecycle and transport; project adapters own game rules.
local core, storage, config = ...
local P = {world_id=config.world_id, clock_ms=0, paused=false, connected=false, PENDING={}}
local adapters, actors, completions, completion_order = {}, {}, {}, {}
local signals, signal_order, regions, watches = {}, {}, {}, {}
local pending, pending_data, inflight, frame_id, elapsed_ms, poll_elapsed = nil, nil, false, 0, 0, 0
local rejected, rejection_handlers = {}, {}
local enabled = config.http and #config.token >= 24
local function now() return core.get_us_time() / 1000 end
local function identifier(id)
    return type(id)=="string" and #id>=1 and #id<=128 and id:match("^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
end
local function finite(v) return type(v)=="number" and v==v and v~=math.huge and v~=-math.huge end
local function integer(v) return finite(v) and v>=0 and v<=9007199254740991 and v%1==0 end
local function object_table(value)
    if type(value)~="table" then return false end
    for key in pairs(value) do if type(key)~="string" then return false end end
    return true
end
local function json(value, limit)
    local ok, data=pcall(core.write_json,value)
    if ok and type(data)=="string" and #data<=limit then return data end
    return nil
end
local function save(entry) storage:set_string("actor:"..entry.id, core.serialize(entry.receipts)) end
local function enqueue(receipt)
    if not completions[receipt.action_id] then
        if #completion_order>=64 then return false end
        completion_order[#completion_order+1]=receipt.action_id
    end
    completions[receipt.action_id]=receipt
    return true
end
local function remember(entry, receipt)
    local records=entry.receipts
    if not records.values[receipt.action_id] then records.order[#records.order+1]=receipt.action_id end
    records.values[receipt.action_id]=receipt
    while #records.order>64 do records.values[table.remove(records.order,1)]=nil end
    save(entry)
end
local function stop(entry, reason)
    local ok, err=pcall(entry.adapter.stop,entry.body,reason)
    if not ok then
        entry.blocked=true
        core.log("error","[dadcraft_platform] Adapter stop failed for "..entry.id..": "..tostring(err))
    end
    return ok
end
local function notify_control(entry, reason)
    local active=entry.deadline>now() and not entry.blocked and not P.paused
    entry.control_active=active
    if not entry.adapter.control then return end
    local ok,err=pcall(entry.adapter.control,entry.body,{
        actor_id=entry.id,generation=entry.generation,active=active,
        granted=entry.deadline>now(),paused=P.paused,blocked=entry.blocked,
    },reason)
    if not ok then
        entry.blocked=true;stop(entry,"CONTROL_HOOK_FAILED")
        core.log("error","[dadcraft_platform] Control hook failed for "..entry.id..": "..tostring(err))
    end
end
local function finish(entry, context, result, status)
    if entry.running~=context or context.done then return false end
    assert(type(result)=="table" and type(result.success)=="boolean", "Action result requires boolean success")
    if not json(result,8192) then
        status="unknown";result={success=false,error_code="INVALID_OR_OVERSIZED_RESULT",data={}}
    end
    context.done=true; entry.running=nil
    if not stop(entry, result.error_code or "COMPLETE") then
        status="unknown";result={success=false,error_code="STOP_FAILED",data={}}
    end
    local receipt={actor_id=entry.id,action_id=context.command.action_id,sequence=context.command.sequence,
        generation=context.command.generation,status=status or "complete",result=result}
    local ok=pcall(remember,entry,receipt)
    if not ok then
        entry.blocked=true;receipt.status="unknown";receipt.result={success=false,error_code="PERSISTENCE_FAILED",data={}}
    end
    enqueue(receipt)
    return true
end
local function interrupt(entry, reason)
    if entry.running then
        finish(entry,entry.running,{success=false,error_code=reason,data={}})
    else stop(entry,reason) end
end

function P.register_adapter(name, def)
    assert(identifier(name) and not adapters[name], "Adapter name must be unique")
    assert(type(def)=="table" and type(def.observe)=="function" and type(def.stop)=="function"
        and type(def.actions)=="table", "Adapter requires observe, stop and actions")
    assert(def.control==nil or type(def.control)=="function","Adapter control hook must be a function")
    local capabilities, actions={}, {}
    for operation, action in pairs(def.actions) do
        assert(identifier(operation) and type(action)=="function", "Invalid adapter action")
        capabilities[operation]=(def.capabilities or {})[operation] or {description=operation}
        actions[operation]=action
    end
    local count=0;for _ in pairs(capabilities) do count=count+1 end
    assert(count>0 and count<=64,"Adapter requires 1..64 capabilities")
    assert(json(capabilities,16384),"Invalid or oversized capability metadata")
    capabilities=core.deserialize(core.serialize(capabilities))
    adapters[name]={observe=def.observe,stop=def.stop,step=def.step,control=def.control,actions=actions,capabilities=capabilities}
end

function P.new_id(prefix)
    prefix=prefix or "actor"; assert(identifier(prefix),"Invalid ID prefix")
    local sequence=(tonumber(storage:get_string("identity_sequence")) or 0)+1
    assert(integer(sequence),"Identity sequence exhausted")
    storage:set_string("identity_sequence",tostring(sequence))
    local id=prefix.."-"..sequence
    assert(identifier(id),"Generated identity exceeds its bound")
    return id
end

function P.attach(body, id, adapter_name)
    assert(identifier(id) and adapters[adapter_name],"A stable actor ID and registered adapter are required")
    assert(not actors[id],"Actor ID is already attached")
    local count=0;for _ in pairs(actors) do count=count+1 end
    assert(count<256,"Attached actor limit reached")
    local raw=storage:get_string("actor:"..id)
    local receipts
    if raw=="" then receipts={highest_sequence=0,values={},order={}}
    else receipts=core.deserialize(raw) end
    assert(type(receipts)=="table" and integer(receipts.highest_sequence) and type(receipts.values)=="table"
        and type(receipts.order)=="table", "Invalid saved actor receipts; data preserved")
    actors[id]={id=id,body=body,adapter=adapters[adapter_name],receipts=receipts,
        generation=0,deadline=0,blocked=false}
    return id
end

function P.detach(id, reason)
    local entry=actors[id];if not entry then return false end
    interrupt(entry,reason or "ACTOR_UNLOADED");entry.deadline=0
    notify_control(entry,reason or "ACTOR_UNLOADED");actors[id]=nil
    return true
end

function P.control_state(id)
    local entry=actors[id]
    if not entry then return nil end
    return {active=entry.deadline>now() and not entry.blocked and not P.paused,
        granted=entry.deadline>now(),paused=P.paused,blocked=entry.blocked,generation=entry.generation}
end

function P.cancel_current(id, reason)
    local entry=actors[id];if not entry then return false end
    interrupt(entry,reason or "PROJECT_INTERRUPTED");return true
end

function P.is_controlled(id)
    local entry=actors[id]
    return entry~=nil and (entry.blocked or P.paused or entry.deadline>now())
end

function P.emit(instance_id, event, payload, event_id, due_ms)
    assert(identifier(instance_id) and identifier(event),"Invalid script instance or event")
    assert(type(payload or {})=="table","Signal payload must be an object")
    for key in pairs(payload or {}) do assert(type(key)=="string","Signal payload must be an object") end
    assert(json(payload or {},65536),"Invalid or oversized signal payload")
    event_id=event_id or (config.session_id..":"..P.new_id("signal"))
    local prior=signals[event_id]
    due_ms=due_ms or (prior and prior.due_ms) or P.clock_ms
    assert(identifier(event_id) and integer(due_ms),"Invalid signal ID or due time")
    if prior then
        local function equal(a,b)
            if type(a)~=type(b) then return false end
            if type(a)~="table" then return a==b end
            for key,value in pairs(a) do if not equal(value,b[key]) then return false end end
            for key in pairs(b) do if a[key]==nil then return false end end
            return true
        end
        assert(prior.instance_id==instance_id and prior.event==event and prior.due_ms==due_ms
            and equal(prior.payload,payload or {}),"Signal ID has a different immutable definition")
        return event_id
    end
    assert(#signal_order<64,"Signal queue is full")
    signals[event_id]={instance_id=instance_id,event_id=event_id,event=event,
        payload=core.deserialize(core.serialize(payload or {})),due_ms=due_ms or P.clock_ms}
    signal_order[#signal_order+1]=event_id
    return event_id
end

function P.set_region_active(id, active)
    assert(identifier(id) and type(active)=="boolean","Invalid region")
    regions[id]={region_id=id,active=active}
end

function P.watch_script(id, callback)
    assert(identifier(id) and type(callback)=="function","Invalid script watch")
    local count=0;for _ in pairs(watches) do count=count+1 end
    assert(watches[id] or count<8,"Script watch limit reached")
    watches[id]={callback=callback,revision=-1}
end

function P.unwatch_script(id) watches[id]=nil end

function P.register_rejection_handler(callback)
    assert(type(callback)=="function","Rejection handler must be a function")
    rejection_handlers[#rejection_handlers+1]=callback
end

function P.rejections() return core.deserialize(core.serialize(rejected)) end

local function command(entry, value)
    if entry.blocked or P.paused or entry.deadline<=now() or value.generation~=entry.generation then return end
    assert(identifier(value.action_id) and integer(value.sequence) and value.sequence>0,"Invalid command identity")
    local records=entry.receipts
    if value.sequence<=records.highest_sequence then
        if entry.running and entry.running.command.action_id==value.action_id then return end
        local old=records.values[value.action_id]
        if old and old.sequence==value.sequence and old.generation==value.generation and old.status~="reserved" then
            enqueue(old)
        else
            enqueue({actor_id=entry.id,action_id=value.action_id,sequence=value.sequence,generation=value.generation,
                status="unknown",result={success=false,error_code="OUTCOME_UNKNOWN",data={}}})
        end
        return
    end
    if entry.running or #completion_order>=64 then return end
    records.highest_sequence=value.sequence
    local saved=pcall(remember,entry,{actor_id=entry.id,action_id=value.action_id,sequence=value.sequence,generation=value.generation,status="reserved"})
    if not saved then
        entry.blocked=true;stop(entry,"PERSISTENCE_FAILED")
        enqueue({actor_id=entry.id,action_id=value.action_id,sequence=value.sequence,generation=value.generation,
            status="unknown",result={success=false,error_code="PERSISTENCE_FAILED",data={}}})
        return
    end
    local context={command=value,elapsed_ms=0,done=false}
    context.is_current=function()
        return actors[entry.id]==entry and entry.running==context and not context.done
            and not entry.blocked and not P.paused and entry.deadline>now() and entry.generation==value.generation
    end
    context.complete=function(success,data,error_code)
        if entry.running==context and not context.is_current() then
            return finish(entry,context,{success=false,error_code="CONTROL_EXPIRED",data={}},"unknown")
        end
        return finish(entry,context,{success=success,data=data or {},error_code=error_code})
    end
    context.world_id=P.world_id; context.actor_id=entry.id
    entry.running=context
    local handler=entry.adapter.actions[value.operation]
    if not handler then context.complete(false,{},"UNSUPPORTED_CAPABILITY");return end
    local ok,result=pcall(handler,entry.body,value.args,context)
    if not ok then
        finish(entry,context,{success=false,error_code="ADAPTER_ERROR",data={}},"unknown")
        core.log("warning","[dadcraft_platform] Action handler failed for "..entry.id..": "..tostring(result))
    elseif not context.done and result~=P.PENDING then
        if not context.is_current() then context.complete(false,{},"CONTROL_EXPIRED")
        elseif type(result)=="table" and type(result.success)=="boolean" then finish(entry,context,result)
        else finish(entry,context,{success=false,error_code="INVALID_ADAPTER_RESULT",data={}},"unknown") end
    end
end

local function frame()
    local value={protocol_version=1,world_id=config.world_id,session_id=config.session_id,frame_id=frame_id+1,
        delta_ms=math.min(60000,math.floor(elapsed_ms)),poll_interval_ms=math.floor(config.interval*1000),
        actors={},completions={},signals={},regions={},watch_scripts={}}
    elapsed_ms=elapsed_ms-value.delta_ms
    local ids={};for id in pairs(actors) do ids[#ids+1]=id end;table.sort(ids)
    for _,id in ipairs(ids) do
        local entry=actors[id]
        local ok,observation=pcall(entry.adapter.observe,entry.body,{world_id=P.world_id,actor_id=id})
        if not ok or not object_table(observation) or not json(observation,16384) then
            interrupt(entry,"OBSERVATION_ERROR");observation={error_code="OBSERVATION_ERROR"}
        end
        value.actors[#value.actors+1]={actor_id=id,capabilities=entry.adapter.capabilities,observation=observation,
            running_action_id=entry.running and entry.running.command.action_id or nil}
    end
    for _,id in ipairs(completion_order) do value.completions[#value.completions+1]=completions[id] end
    for _,id in ipairs(signal_order) do value.signals[#value.signals+1]=signals[id] end
    for _,region in pairs(regions) do
        if #value.regions>=512 then break end
        value.regions[#value.regions+1]=region
    end
    for id in pairs(watches) do value.watch_scripts[#value.watch_scripts+1]=id end
    return value
end

local function receive(sent, response, started)
    if pending~=sent then return end
    inflight=false
    if not response.succeeded or response.code~=200 then P.connected=false;return end
    local value=core.parse_json(response.data)
    if type(value)~="table" or value.protocol_version~=1 or value.world_id~=P.world_id
        or value.session_id~=config.session_id or value.frame_id~=sent.frame_id
        or not integer(value.clock_ms) or type(value.paused)~="boolean"
        or type(value.grants)~="table" or type(value.commands)~="table" then P.connected=false;return end
    for _,grant in ipairs(value.grants or {}) do
        if not identifier(grant.actor_id) or not integer(grant.generation) or not integer(grant.remaining_ms) then
            P.connected=false;return
        end
    end
    P.connected=true; P.clock_ms=value.clock_ms; P.paused=value.paused==true
    local delay=math.max(0,now()-started)+100
    for _,grant in ipairs(value.grants or {}) do
        local entry=actors[grant.actor_id]
        if entry then
            local ownership_changed=entry.generation~=grant.generation
            if ownership_changed then interrupt(entry,"CONTROL_CHANGED")
            elseif entry.running and (P.paused
                or grant.action_id~=entry.running.command.action_id or grant.remaining_ms<=delay) then
                interrupt(entry,"CONTROL_INTERRUPTED")
            end
            entry.generation=grant.generation
            entry.deadline=now()+math.max(0,grant.remaining_ms-delay)
            notify_control(entry,"GRANT_UPDATED")
        end
    end
    for _,receipt in ipairs(sent.completions) do
        if completions[receipt.action_id]==receipt then completions[receipt.action_id]=nil end
    end
    local retained={};for _,id in ipairs(completion_order) do if completions[id] then retained[#retained+1]=id end end
    completion_order=retained
    for _,signal in ipairs(sent.signals) do if signals[signal.event_id]==signal then signals[signal.event_id]=nil end end
    retained={};for _,id in ipairs(signal_order) do if signals[id] then retained[#retained+1]=id end end;signal_order=retained
    for _,region in ipairs(sent.regions) do if regions[region.region_id]==region then regions[region.region_id]=nil end end
    frame_id=sent.frame_id;pending=nil;pending_data=nil
    for _,rejection in ipairs(value.rejections or {}) do
        rejected[#rejected+1]=rejection
        while #rejected>64 do table.remove(rejected,1) end
        local body=actors[rejection.item_id] and actors[rejection.item_id].body or nil
        if rejection.kind=="actor" then P.detach(rejection.item_id,rejection.error_code) end
        for _,callback in ipairs(rejection_handlers) do
            local ok,err=pcall(callback,rejection,body)
            if not ok then core.log("warning","[dadcraft_platform] Rejection handler failed: "..tostring(err)) end
        end
    end
    for _,value_command in ipairs(value.commands or {}) do
        local entry=actors[value_command.actor_id]
        if entry then
            local ok,err=pcall(command,entry,value_command)
            if not ok then entry.blocked=true;stop(entry,"COMMAND_ERROR");core.log("error","[dadcraft_platform] "..tostring(err)) end
        end
    end
    for _,state in ipairs(value.scripts or {}) do
        local watch=watches[state.instance_id]
        if watch and watch.revision~=state.revision then
            local ok,err=pcall(watch.callback,state)
            if ok then watch.revision=state.revision else core.log("warning","[dadcraft_platform] Script watch failed: "..tostring(err)) end
        end
    end
end

core.register_globalstep(function(dt)
    if not finite(dt) or dt<0 then return end
    elapsed_ms=elapsed_ms+dt*1000;poll_elapsed=poll_elapsed+dt
    for _,entry in pairs(actors) do
        local active=entry.deadline>now() and not entry.blocked and not P.paused
        if active~=entry.control_active then notify_control(entry,"CONTROL_STATE_CHANGED") end
        if entry.running then
            if entry.deadline<=now() or P.paused or entry.blocked then interrupt(entry,"CONTROL_EXPIRED")
            elseif entry.adapter.step then
                local context=entry.running;context.elapsed_ms=context.elapsed_ms+dt*1000
                local ok=pcall(entry.adapter.step,entry.body,dt,context)
                if not ok and entry.running==context then
                    finish(entry,context,{success=false,error_code="ADAPTER_ERROR",data={}},"unknown")
                end
            end
        end
    end
    if not enabled or inflight or poll_elapsed<config.interval then return end
    poll_elapsed=0
    if not pending then
        pending=frame();pending_data=json(pending,1048576)
        if not pending_data then
            elapsed_ms=elapsed_ms+pending.delta_ms;pending=nil;pending_data=nil;P.connected=false
            core.log("error","[dadcraft_platform] Exchange frame exceeds 1 MiB or contains invalid JSON")
            return
        end
    end
    local sent,started=pending,now();inflight=true
    local ok=pcall(config.http.fetch,{url=config.url.."/v1/engine/exchange",method="POST",data=pending_data,timeout=2,
        extra_headers={"Authorization: Bearer "..config.token,"Content-Type: application/json"}},
        function(response) receive(sent,response,started) end)
    if not ok then inflight=false;P.connected=false end
end)

core.register_on_shutdown(function()
    for _,entry in pairs(actors) do
        interrupt(entry,"ENGINE_SHUTDOWN");entry.deadline=0;notify_control(entry,"ENGINE_SHUTDOWN")
    end
end)
return P
