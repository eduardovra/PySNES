-- Dump PPU state + VRAM at a target frame so we can compare against PySNES.
-- Produces two files:
--   $MESEN_STATE_OUT.json   selected PPU state fields as JSON-ish text
--   $MESEN_STATE_OUT.vram   full 64KB of VRAM as binary
--
-- Env vars:
--   MESEN_FRAMES      target frame (default 560)
--   MESEN_STATE_OUT   output base path (default /tmp/mesen_state)

local target = tonumber(os.getenv("MESEN_FRAMES")) or 560
local out_base = os.getenv("MESEN_STATE_OUT") or "/tmp/mesen_state"

local frame = 0

emu.addEventCallback(function()
    frame = frame + 1
    if frame ~= target then return end

    local state = emu.getState()

    -- Dump selected fields (anything whose key mentions bg/screen/layer/vram/mode)
    local f = io.open(out_base .. ".json", "w")
    f:write("{\n")
    local first = true
    local keys = {}
    for k, _ in pairs(state) do keys[#keys + 1] = k end
    table.sort(keys)
    for _, k in ipairs(keys) do
        local kl = k:lower()
        if kl:find("bg") or kl:find("screen") or kl:find("layer")
           or kl:find("vram") or kl:find("mode") or kl:find("priority")
           or kl:find("mosaic") or kl:find("window") or kl:find("color")
           or kl:find("obj") or kl:find("main") or kl:find("sub") then
            local v = state[k]
            if not first then f:write(",\n") end
            first = false
            if type(v) == "number" then
                f:write(string.format("  %q: %d", k, v))
            elseif type(v) == "boolean" then
                f:write(string.format("  %q: %s", k, tostring(v)))
            elseif type(v) == "string" then
                f:write(string.format("  %q: %q", k, v))
            end
        end
    end
    f:write("\n}\n")
    f:close()

    -- Dump full 64KB of VRAM
    local vf = io.open(out_base .. ".vram", "wb")
    for addr = 0, 0xFFFF do
        local b = emu.read(addr, emu.memType.snesVideoRam, false)
        vf:write(string.char(b & 0xFF))
    end
    vf:close()

    emu.stop(0)
end, emu.eventType.endFrame)
