-- Original project code. SPDX-License-Identifier: MIT
local P=dadcraft_platform
local file=io.open(core.get_worldpath().."/platform-locations.json","r")
if not file then return end
local catalog=core.parse_json(file:read("*a"));file:close()
assert(type(catalog)=="table" and type(catalog.locations)=="table","Invalid platform location catalogue")
local counts,elapsed={},0
core.register_globalstep(function(dt)
    elapsed=elapsed+dt;if elapsed<1 then return end;elapsed=0
    local players=core.get_connected_players()
    for _,location in ipairs(catalog.locations)do
        local count=0
        for _,player in ipairs(players)do
            local pos=player:get_pos()
            if pos then local dx,dz=pos.x-location.x,pos.z-location.z
                if dx*dx+dz*dz<=location.radius*location.radius then count=count+1 end
            end
        end
        if counts[location.id]~=count then
            local ok=pcall(P.emit,"location:"..location.id,count>0 and "entered" or "left",{players=count})
            if ok then
                P.set_region_active(location.id,count>0);counts[location.id]=count
            end
        end
    end
end)
