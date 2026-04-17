-- mesen_layers.lua
-- Captures a single frame's screen buffer with optional TM ($212C) and TS
-- ($212D) overrides, so the caller can expose individual BG/OBJ layers by
-- running this once per mask.
--
-- Strategy: enable the override starting at frame target-1. From that point:
--   * a memory write callback intercepts every CPU write to $212C/$212D
--     and replaces the value
--   * at the start of frame `target` we also write the desired mask via
--     emu.write, in case the game hadn't written that frame
-- The PPU then renders frame `target` with the overridden mask.
--
-- Environment variables:
--   MESEN_FRAMES       target frame to capture (default 560)
--   MESEN_TM_MASK      integer; if set, forces $212C = this value
--   MESEN_TS_MASK      integer; if set, forces $212D = this value
--   MESEN_OUTPUT_BIN   output binary path (default /tmp/mesen_layer.bin)
--   MESEN_LOG          if set, write a diagnostic log to this path
--
-- Buffer format: 256 x 239 u32 values, little-endian, 0x00RRGGBB.

local target     = tonumber(os.getenv("MESEN_FRAMES")) or 560
local tm_mask    = tonumber(os.getenv("MESEN_TM_MASK"))
local ts_mask    = tonumber(os.getenv("MESEN_TS_MASK"))
local out_path   = os.getenv("MESEN_OUTPUT_BIN") or "/tmp/mesen_layer.bin"
local log_path   = os.getenv("MESEN_LOG")

local frame = 0
local active = false
local overriding = false
local log_f = nil
if log_path then log_f = io.open(log_path, "w") end

local function logmsg(s)
    if log_f then log_f:write(s .. "\n"); log_f:flush() end
end

logmsg(string.format("init target=%d tm_mask=%s ts_mask=%s",
    target, tostring(tm_mask), tostring(ts_mask)))

local function install_override(addr, desired_value_fn, label)
    emu.addMemoryCallback(function(address, value)
        if overriding then return end
        if not active then
            logmsg(string.format("frame=%d (inactive) write %s=%02X", frame, label, value))
            return
        end
        local desired = desired_value_fn()
        logmsg(string.format("frame=%d write %s=%02X desired=%s",
            frame, label, value, tostring(desired)))
        if desired ~= nil and value ~= desired then
            overriding = true
            emu.write(addr, desired, emu.memType.snesMemory)
            overriding = false
            logmsg(string.format("  -> forced %s=%02X", label, desired))
        end
    end, emu.callbackType.write, addr, addr)
end

install_override(0x212C, function() return tm_mask end, "TM")
install_override(0x212D, function() return ts_mask end, "TS")

emu.addEventCallback(function()
    if tm_mask ~= nil then
        overriding = true
        emu.write(0x212C, tm_mask, emu.memType.snesMemory)
        overriding = false
        logmsg(string.format("frame=%d startFrame -> TM=%02X", frame + 1, tm_mask))
    end
    if ts_mask ~= nil then
        overriding = true
        emu.write(0x212D, ts_mask, emu.memType.snesMemory)
        overriding = false
        logmsg(string.format("frame=%d startFrame -> TS=%02X", frame + 1, ts_mask))
    end
end, emu.eventType.startFrame)

emu.addEventCallback(function()
    frame = frame + 1
    if frame == target - 1 then
        active = true
        logmsg(string.format("frame=%d activating override", frame))
    elseif frame == target then
        logmsg(string.format("frame=%d capturing screen", frame))
        local buf = emu.getScreenBuffer()
        local f = io.open(out_path, "wb")
        for i = 1, #buf do
            local v = buf[i]
            f:write(string.char(
                v & 0xFF,
                (v >> 8) & 0xFF,
                (v >> 16) & 0xFF,
                (v >> 24) & 0xFF
            ))
        end
        f:close()
        if log_f then log_f:close() end
        emu.stop(0)
    end
end, emu.eventType.endFrame)
