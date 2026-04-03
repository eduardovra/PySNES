-- mesen_screenshot.lua
-- Runs a ROM for MESEN_FRAMES frames, then saves a 256x224 PNG to MESEN_OUTPUT_PNG.
-- Used by pysnes/ppu/test_ppu.py --update-refs to generate reference images.
--
-- Environment variables:
--   MESEN_FRAMES      number of frames to run before capturing (default: 5)
--   MESEN_OUTPUT_PNG  output PNG path

local n_frames  = tonumber(os.getenv("MESEN_FRAMES"))  or 5
local out_path  = os.getenv("MESEN_OUTPUT_PNG") or "ppu_reference.png"

local frame_count = 0

emu.addEventCallback(function()
    frame_count = frame_count + 1
    if frame_count >= n_frames then
        emu.takeScreenshot(out_path)
        emu.stop()
    end
end, emu.eventType.endFrame)
