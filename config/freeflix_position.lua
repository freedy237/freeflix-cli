-- AutoFlix position-tracking helper.
-- mpv is launched by autoflix with:
--   --script-opts=autoflix-key=<key>,autoflix-out=<path>
-- On shutdown / end-of-file, we write the current time-pos and duration
-- to <path>. autoflix reads it back and stores it in its tracker so
-- the next launch of the same episode can resume.

local mp = require 'mp'

local function get_opt(name)
    local opts_str = mp.get_property("options/script-opts")
    if not opts_str or opts_str == "" then return nil end
    for pair in string.gmatch(opts_str, "([^,]+)") do
        local k, v = string.match(pair, "([^=]+)=(.+)")
        if k == name then return v end
    end
    return nil
end

local key = get_opt("autoflix-key")
local out_path = get_opt("autoflix-out")

if not key or key == "" or not out_path or out_path == "" then
    return
end

local written = false

local function write_position(reason)
    if written then return end  -- only write once per run
    local pos = mp.get_property_number("time-pos")
    local dur = mp.get_property_number("duration")
    if pos == nil then return end

    local f = io.open(out_path, "w")
    if f then
        f:write(string.format("key=%s\n", key))
        f:write(string.format("pos=%.2f\n", pos))
        if dur then
            f:write(string.format("dur=%.2f\n", dur))
        end
        f:write(string.format("reason=%s\n", reason or ""))
        f:close()
        written = true
    end
end

mp.register_event("end-file", function(event)
    write_position(event.reason or "end-file")
end)

mp.register_event("shutdown", function()
    write_position("shutdown")
end)
