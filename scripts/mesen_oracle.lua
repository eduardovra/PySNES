-- mesen_oracle.lua — Tier 1 frame-level oracle for PySNES integration tests.
-- Invocation: Mesen --testrunner <rom> mesen_oracle.lua
-- Env vars: MESEN_PORT=<tcp_port>, MESEN_FRAMES=<n_frames>
--
-- Connects to a Python TCP server, sends one JSON line per frame containing
-- CPU/SPC registers and WRAM CRC32. Exits after MESEN_FRAMES frames.

local port = tonumber(os.getenv("MESEN_PORT"))
local n_frames = tonumber(os.getenv("MESEN_FRAMES")) or 60

if not port then
    emu.stop(1)
    return
end

-- CRC32 table (IEEE polynomial)
local crc32_table = {}
for i = 0, 255 do
    local c = i
    for _ = 1, 8 do
        if c & 1 == 1 then
            c = (c >> 1) ~ 0xEDB88320
        else
            c = c >> 1
        end
    end
    crc32_table[i] = c
end

local function crc32(bytes_fn, len)
    local crc = 0xFFFFFFFF
    for i = 0, len - 1 do
        local byte = bytes_fn(i)
        crc = (crc >> 8) ~ crc32_table[(crc ~ byte) & 0xFF]
    end
    return (~crc) & 0xFFFFFFFF
end

-- Connect to Python TCP server
local socket = require("socket.core")
local tcp = socket.tcp()
tcp:settimeout(10)
local ok, err = tcp:connect("localhost", port)
if not ok then
    emu.stop(1)
    return
end

local frame_count = 0

emu.addEventCallback(function()
    frame_count = frame_count + 1

    local state = emu.getState()
    local cpu = state.cpu
    local spc = state.spc

    -- Read first 16 bytes of WRAM for fast triage
    local wram_head = {}
    for i = 0, 15 do
        wram_head[i + 1] = emu.read(i, emu.memType.wram)
    end

    -- CRC32 over full 128KB WRAM ($7E:0000–$7F:FFFF = 131072 bytes)
    local wram_crc = crc32(function(i) return emu.read(i, emu.memType.wram) end, 131072)

    -- Build wram_head JSON array
    local head_parts = {}
    for i = 1, 16 do
        head_parts[i] = tostring(wram_head[i])
    end

    -- Emulation mode: bool → int
    local em = cpu.emulationMode and 1 or 0

    local line = string.format(
        '{"frame":%d,"cpu":{"pc":%d,"a":%d,"x":%d,"y":%d,"sp":%d,"ps":%d,"k":%d,"d":%d,"db":%d,"e":%d},"spc":{"pc":%d,"a":%d,"x":%d,"y":%d,"sp":%d,"ps":%d},"wram_crc32":%d,"wram_head":[%s]}',
        frame_count,
        cpu.pc, cpu.a, cpu.x, cpu.y, cpu.sp, cpu.ps, cpu.k, cpu.d, cpu.dbr, em,
        spc.pc, spc.a, spc.x, spc.y, spc.sp, spc.ps,
        wram_crc,
        table.concat(head_parts, ",")
    )
    tcp:send(line .. "\n")

    if frame_count >= n_frames then
        tcp:close()
        emu.stop(0)
    end
end, emu.eventType.endFrame)
