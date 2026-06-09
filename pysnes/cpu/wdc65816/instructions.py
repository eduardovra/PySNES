"""WDC 65816 opcode dispatch table — fully code-generated.

Every opcode (0x00-0xFF) maps to a generated handler that takes only `cpu`.
The handlers are produced from a compact spec:

    opcodes_spec.py      — the human-maintained spec (SPEC + MISC_SPEC)
    scripts/gen_opcodes.py — generator:  uv run scripts/gen_opcodes.py
    opcodes_generated.py — the committed generated handlers + HANDLERS

Memory/modify families are emitted as inlined literal handlers (index register,
width flag, and operation/source baked in, so PyPy folds them per opcode — ~2x
faster dispatch than the old decorator+string-table). The irregular ops (control
flow, flags, transfers, push/pull, block move, interrupt, exchanges) are emitted
as thin handlers that delegate to the tested addressing functions. Edit the
spec, not this file or the generated one.
"""
from .opcodes_generated import HANDLERS

# load_instructions() consumes (opcode, handler) rows; each handler takes only
# cpu, so it becomes a nargs=0 instruction slot.
INSTRUCTIONS = tuple((opcode, HANDLERS[opcode]) for opcode in sorted(HANDLERS))
