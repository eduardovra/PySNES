-- mesen_oracle.lua — Tier 1 frame-level oracle for PySNES integration tests.
-- Invocation: Mesen --testrunner <rom> mesen_oracle.lua
-- Env vars: MESEN_PORT=<tcp_port>, MESEN_FRAMES=<n_frames>
--
-- Connects to a Python TCP server, sends one JSON line per frame with
-- CPU/SPC registers. Exits after MESEN_FRAMES frames.
--
-- Note: emu.getState() returns a flat table with dotted string keys,
-- e.g. state["cpu.pc"], state["spc.ps"], NOT nested tables.

local port = tonumber(os.getenv("MESEN_PORT"))
local n_frames = tonumber(os.getenv("MESEN_FRAMES")) or 60

if not port then emu.stop(1); return end

local socket = require("socket.core")
local tcp = socket.tcp()
tcp:settimeout(10)
local ok, err = tcp:connect("localhost", port)
if not ok then emu.stop(2); return end

local frame_count = 0

emu.addEventCallback(function()
    frame_count = frame_count + 1

    local state = emu.getState()
    local em = state["cpu.emulationMode"] and 1 or 0

    local line = string.format(
        '{"frame":%d,"cpu":{"pc":%d,"a":%d,"x":%d,"y":%d,"sp":%d,"ps":%d,"k":%d,"d":%d,"db":%d,"e":%d},"spc":{"pc":%d,"a":%d,"x":%d,"y":%d,"sp":%d,"ps":%d}}',
        frame_count,
        state["cpu.pc"], state["cpu.a"], state["cpu.x"], state["cpu.y"],
        state["cpu.sp"], state["cpu.ps"], state["cpu.k"],
        (state["cpu.d"] or 0), state["cpu.dbr"], em,
        state["spc.pc"], state["spc.a"], state["spc.x"], state["spc.y"],
        state["spc.sp"], state["spc.ps"]
    )
    tcp:send(line .. "\n")

    if frame_count >= n_frames then
        tcp:close()
        emu.stop(0)
    end
end, emu.eventType.endFrame)
