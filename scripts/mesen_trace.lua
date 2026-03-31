-- mesen_trace.lua — Tier 2 instruction-level CPU trace writer for PySNES integration tests.
-- Invocation: Mesen --testrunner <rom> mesen_trace.lua
-- Env vars: MESEN_PORT=<tcp_port>, MESEN_INSTRUCTIONS=<n_instructions>
--
-- Sends one trace line per CPU instruction over TCP in PySNES trace format.
-- Format: "xxxxxx ???                     A:XXXX X:XXXX Y:XXXX S:XXXX D:XXXX DB:XX NVMXDIZC"
--
-- Note: emu.getState() returns a flat table with dotted string keys,
-- e.g. state["cpu.pc"], NOT nested tables.

local port = tonumber(os.getenv("MESEN_PORT"))
local n_instructions = tonumber(os.getenv("MESEN_INSTRUCTIONS")) or 100000

if not port then
    emu.stop(1)
    return
end

local socket = require("socket.core")
local tcp = socket.tcp()
tcp:settimeout(10)
local ok, err = tcp:connect("localhost", port)
if not ok then
    emu.stop(1)
    return
end

local count = 0

local function flags_str(ps, em)
    local function bit(v, pos) return (v >> pos) & 1 end
    local n = bit(ps, 7) == 1 and "N" or "."
    local v = bit(ps, 6) == 1 and "V" or "."
    local m = bit(ps, 5) == 1 and (em == 1 and "1" or "M") or "."
    local x = bit(ps, 4) == 1 and (em == 1 and "B" or "X") or "."
    local d = bit(ps, 3) == 1 and "D" or "."
    local i = bit(ps, 2) == 1 and "I" or "."
    local z = bit(ps, 1) == 1 and "Z" or "."
    local c = bit(ps, 0) == 1 and "C" or "."
    return n .. v .. m .. x .. d .. i .. z .. c
end

emu.addMemoryCallback(function(address, value)
    if count >= n_instructions then
        return
    end
    count = count + 1

    local state = emu.getState()
    local em = state["cpu.emulationMode"] and 1 or 0
    local pc_full = (state["cpu.k"] << 16) | state["cpu.pc"]
    local disasm = string.format("%06x ???", pc_full)
    local line = string.format(
        "%-30s A:%04X X:%04X Y:%04X S:%04X D:%04X DB:%02X %s",
        disasm,
        state["cpu.a"], state["cpu.x"], state["cpu.y"],
        state["cpu.sp"], (state["cpu.d"] or 0), state["cpu.dbr"],
        flags_str(state["cpu.ps"], em)
    )
    tcp:send(line .. "\n")

    if count >= n_instructions then
        tcp:close()
        emu.stop(0)
    end
end, emu.callbackType.exec, 0x0000, 0xFFFF)
