-- mesen_screenshot.lua
-- Runs a ROM for MESEN_FRAMES frames, then writes raw pixel data to MESEN_OUTPUT_BIN.
-- Buffer format: 256x239 u32 values, little-endian, format 0x00RRGGBB.
-- Visible 224-line content starts at row 7 (rows 7-230 inclusive).
--
-- Used by test_ppu.py --update-refs to generate reference images via Mesen.
--
-- Environment variables:
--   MESEN_FRAMES      number of frames to run before capturing (default: 5)
--   MESEN_OUTPUT_BIN  output raw binary path (default: /tmp/mesen_raw.bin)

local n_frames  = tonumber(os.getenv("MESEN_FRAMES"))  or 5
local out_path  = os.getenv("MESEN_OUTPUT_BIN") or "/tmp/mesen_raw.bin"

local frame_count = 0

emu.addEventCallback(function()
    frame_count = frame_count + 1
    if frame_count >= n_frames then
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
        emu.stop()
    end
end, emu.eventType.endFrame)
