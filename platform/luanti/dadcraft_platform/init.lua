-- Original code. SPDX-License-Identifier: MIT
local path = core.get_modpath(core.get_current_modname())
local storage = core.get_mod_storage()
local url = core.settings:get("dadcraft_platform_url") or "http://127.0.0.1:8775"
assert(url:match("^http://127%.0%.0%.1:%d+$"), "Platform URL must be an IPv4 loopback HTTP origin")
local configured = core.settings:get("dadcraft_platform_world_id")
local world = storage:get_string("world_id")
if configured and configured ~= "" then
    assert(configured:match("^[A-Za-z0-9][A-Za-z0-9_.:-]*$") and #configured <= 128, "Invalid platform world ID")
    assert(world == "" or world == configured, "Platform world ID differs from the saved namespace")
    world = configured
elseif world == "" then
    world = "world-" .. core.sha1(core.get_worldpath()):sub(1, 24)
end
storage:set_string("world_id", world)
local token_file = core.settings:get("dadcraft_platform_token_file")
if not token_file or token_file == "" then token_file = core.get_worldpath() .. "/platform-engine.token" end
local token = ""
local file = io.open(token_file, "r")
if file then token = file:read("*a"):match("^%s*(.-)%s*$"); file:close() end
local http = core.request_http_api()
local interval = tonumber(core.settings:get("dadcraft_platform_poll_interval")) or 0.2
interval = math.max(0.05, math.min(5, interval))
local P = assert(loadfile(path .. "/runtime.lua"))(core, storage, {
    world_id = world, url = url, token = token, http = http, interval = interval,
    session_id = "engine-" .. core.sha1(world .. tostring(core.get_us_time()) .. tostring(os.time())),
})
dadcraft_platform = P
assert(loadfile(path .. "/object_adapter.lua"))(P)
if not http or #token < 24 then
    core.log("warning", "[dadcraft_platform] Transport disabled: grant HTTP access and supply the world engine token")
end
