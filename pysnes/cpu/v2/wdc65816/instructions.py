from .addressing_modes import WDC65816AddressingModes
from .opcodes import WDC65816Opcodes

INSTRUCTIONS = (
    (0xEA, WDC65816AddressingModes.NoOperation),
)
