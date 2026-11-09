-- Short physics-driven actions for any ordinary ObjectRef or Lua entity.
local P=...
local function object(body) return body.object or body end
local function finite(v) return type(v)=="number" and v==v and v~=math.huge and v~=-math.huge end
local function halt(body)
    local obj=object(body);local velocity=obj:get_velocity()
    if velocity then obj:set_velocity({x=0,y=velocity.y,z=0}) end
end
local definition={
    observe=function(body)
        local obj=object(body)
        return {position=obj:get_pos(),heading=obj:get_yaw(),velocity=obj:get_velocity()}
    end,
    stop=halt,
    actions={
        turn=function(body,args)
            if not finite(args.yaw) or math.abs(args.yaw)>1000000 then return {success=false,error_code="INVALID_ARGUMENT"} end
            object(body):set_yaw(args.yaw)
            return {success=true,data={}}
        end,
        move=function(body,args,context)
            local duration=args.duration_ms
            if not finite(args.x) or not finite(args.z) or not finite(args.speed) or args.speed<=0 or args.speed>8
                or not finite(duration) or duration%1~=0 or duration<100 or duration>5000 then
                return {success=false,error_code="INVALID_ARGUMENT"}
            end
            local length=math.sqrt(args.x*args.x+args.z*args.z)
            if not finite(length) or length<0.00001 then return {success=false,error_code="INVALID_ARGUMENT"} end
            local obj=object(body);local velocity=obj:get_velocity()
            context.duration_ms=duration
            obj:set_velocity({x=args.x/length*args.speed,y=velocity.y,z=args.z/length*args.speed})
            return P.PENDING
        end,
        wait=function(_,args,context)
            if not finite(args.duration_ms) or args.duration_ms%1~=0 or args.duration_ms<1 or args.duration_ms>5000 then
                return {success=false,error_code="INVALID_ARGUMENT"}
            end
            context.duration_ms=args.duration_ms
            return P.PENDING
        end,
    },
    step=function(body,_,context)
        if context.elapsed_ms>=context.duration_ms then
            halt(body);context.complete(true,{position=object(body):get_pos()})
        end
    end,
}
P.object_adapter_definition=function()
    local copy={};for k,v in pairs(definition)do copy[k]=v end
    copy.actions={};for k,v in pairs(definition.actions)do copy.actions[k]=v end
    return copy
end
P.register_adapter("platform.object",definition)
