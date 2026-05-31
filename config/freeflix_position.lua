-- FreeFlix position-tracking helper.
-- mpv is launched by FreeFlix with :
--   --script-opts=freeflix-key=<key>,freeflix-out=<path>
-- We continuously track the playback position (time-pos is already nil
-- by the time the shutdown event fires, so we cannot read it there) and
-- write the LAST known position to <path> on end-of-file / shutdown.
-- FreeFlix reads it back and stores it in its tracker so the next launch
-- of the same episode resumes via --start=<seconds>.

local mp = require 'mp'

local function get_opt(name)
    local opts = mp.get_property_native("options/script-opts")
    if type(opts) == "table" then
        return opts[name]
    end
    return nil
end

local key = get_opt("freeflix-key")
local out_path = get_opt("freeflix-out")

if not key or key == "" or not out_path or out_path == "" then
    return
end

-- Continuously capture position + duration while playing. This is the
-- crux of the fix : at shutdown time-pos is already nil, so we persist
-- the last value we observed here instead of reading it at write time.
local last_pos = nil
local last_dur = nil
local written = false

mp.observe_property("time-pos", "number", function(_, value)
    if value ~= nil then
        last_pos = value
    end
end)

mp.observe_property("duration", "number", function(_, value)
    if value ~= nil then
        last_dur = value
    end
end)

local function write_position(reason)
    if written then return end
    if last_pos == nil then return end

    local f = io.open(out_path, "w")
    if f then
        f:write(string.format("key=%s\n", key))
        f:write(string.format("pos=%.2f\n", last_pos))
        if last_dur then
            f:write(string.format("dur=%.2f\n", last_dur))
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
