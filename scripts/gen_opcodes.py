"""Generate literal opcode handlers from opcodes_spec.py -> opcodes_generated.py.

Reads the compact spec (SPEC for memory/modify families, MISC_SPEC for the
irregular ops) and emits one straight-line handler per opcode. For the
memory/modify families the index register, width flag, and operation/source are
baked in as literals, so PyPy folds them per-opcode trace (the decorator+string
table dispatch could not — ~2x faster on hot reads/writes; see bench_cpu.py).
The irregular ops are emitted as thin handlers that delegate to the tested
addressing functions, with lambda args hoisted to module level.

Build tool: edit opcodes_spec.py, rerun, commit the regenerated output.

    uv run scripts/gen_opcodes.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

GEN_OUT = ROOT / "pysnes" / "cpu" / "wdc65816" / "opcodes_generated.py"

# AM addressing-mode name -> (family, kind). kind: read/write/modify/implied.
FAMILY = {
    "ImmediateRead": ("immediate_read", "read"),
    "BankRead": ("bank_read", "read"),
    "DirectRead": ("direct_read", "read"),
    "LongRead": ("long_read", "read"),
    "IndirectRead": ("indirect_read", "read"),
    "IndexedIndirectRead": ("indexed_indirect_read", "read"),
    "IndirectIndexedRead": ("indirect_indexed_read", "read"),
    "IndirectLongRead": ("indirect_long_read", "read"),
    "StackRead": ("stack_read", "read"),
    "IndirectStackRead": ("indirect_stack_read", "read"),
    "BankWrite": ("bank_write", "write"),
    "DirectWrite": ("direct_write", "write"),
    "LongWrite": ("long_write", "write"),
    "IndirectWrite": ("indirect_write", "write"),
    "IndexedIndirectWrite": ("indexed_indirect_write", "write"),
    "IndirectIndexedWrite": ("indirect_indexed_write", "write"),
    "IndirectLongWrite": ("indirect_long_write", "write"),
    "StackWrite": ("stack_write", "write"),
    "IndirectStackWrite": ("indirect_stack_write", "write"),
    "BankModify": ("bank_modify", "modify"),
    "BankIndexedModify": ("bank_indexed_modify", "modify"),
    "DirectModify": ("direct_modify", "modify"),
    "DirectIndexedModify": ("direct_indexed_modify", "modify"),
    "ImpliedModify": ("implied_modify", "implied"),
}

# --- code templates -------------------------------------------------------
def _flag(f):
    return "cpu.MFlag" if f == "M" else "cpu.XFlag"


def _idx(index):
    return {"": "", "X": " + cpu.X.w", "Y": " + cpu.Y.w"}[index]


def body_read(family, op, index, flag):
    iw = _idx(index)
    f = _flag(flag)
    L = []
    if family == "immediate_read":
        return [f"    if {f}:",
                "        cpu.W.l = cpu.fetch()",
                f"        {op}(cpu, True, cpu.W.l)",
                "    else:",
                "        cpu.W.l = cpu.fetch()",
                "        cpu.W.h = cpu.fetch()",
                f"        {op}(cpu, False, cpu.W.w)"]
    if family == "bank_read":
        L += ["    cpu.V.l = cpu.fetch()", "    cpu.V.h = cpu.fetch()"]
        if index:
            L.append(f"    cpu.idle4(cpu.V.w, cpu.V.w{iw})")
        return L + _read_tail("cpu.readBank", f"cpu.V.w{iw}", op, f)
    if family == "direct_read":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()"]
        if index:
            L.append("    cpu.idle()")
        return L + _read_tail("cpu.readDirect", f"cpu.U.l{iw}", op, f)
    if family == "long_read":
        L += ["    cpu.V.l = cpu.fetch()", "    cpu.V.h = cpu.fetch()", "    cpu.V.b = cpu.fetch()"]
        return L + _read_tail("cpu.readLong", f"cpu.V.d{iw}", op, f)
    if family == "indirect_read":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()",
              "    cpu.V.l = cpu.readDirect(cpu.U.l + 0)",
              "    cpu.V.h = cpu.readDirect(cpu.U.l + 1)"]
        return L + _read_tail("cpu.readBank", "cpu.V.w", op, f)
    if family == "indexed_indirect_read":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()", "    cpu.idle()",
              "    cpu.V.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)",
              "    cpu.V.h = cpu.readDirect(cpu.U.l + cpu.X.w + 1)"]
        return L + _read_tail("cpu.readBank", "cpu.V.w", op, f)
    if family == "indirect_indexed_read":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()",
              "    cpu.V.l = cpu.readDirect(cpu.U.l + 0)",
              "    cpu.V.h = cpu.readDirect(cpu.U.l + 1)",
              "    cpu.idle4(cpu.V.w, cpu.V.w + cpu.Y.w)"]
        return L + _read_tail("cpu.readBank", "cpu.V.w + cpu.Y.w", op, f)
    if family == "indirect_long_read":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()",
              "    cpu.V.l = cpu.readDirectN(cpu.U.l + 0)",
              "    cpu.V.h = cpu.readDirectN(cpu.U.l + 1)",
              "    cpu.V.b = cpu.readDirectN(cpu.U.l + 2)"]
        return L + _read_tail("cpu.readLong", f"cpu.V.d{iw}", op, f)
    if family == "stack_read":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle()"]
        return L + _read_tail("cpu.readStack", "cpu.U.l", op, f)
    if family == "indirect_stack_read":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle()",
              "    cpu.V.l = cpu.readStack(cpu.U.l + 0)",
              "    cpu.V.h = cpu.readStack(cpu.U.l + 1)", "    cpu.idle()"]
        return L + _read_tail("cpu.readBank", "cpu.V.w + cpu.Y.w", op, f)
    raise ValueError(family)


def _read_tail(rd, addr, op, f):
    return [f"    if {f}:",
            f"        cpu.W.l = {rd}({addr} + 0)",
            f"        {op}(cpu, True, cpu.W.l)",
            "    else:",
            f"        cpu.W.l = {rd}({addr} + 0)",
            f"        cpu.W.h = {rd}({addr} + 1)",
            f"        {op}(cpu, False, cpu.W.w)"]


def body_write(family, src, index, flag):
    iw = _idx(index)
    f = _flag(flag)
    s = f"cpu.{src}" if src else "cpu.A"
    L = []
    if family == "bank_write":
        L += ["    cpu.V.l = cpu.fetch()", "    cpu.V.h = cpu.fetch()"]
        if index:
            L.append("    cpu.idle()")
        return L + _write_tail("cpu.writeBank", f"cpu.V.w{iw}", s, f)
    if family == "direct_write":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()"]
        if index:
            L.append("    cpu.idle()")
        return L + _write_tail("cpu.writeDirect", f"cpu.U.l{iw}", s, f)
    if family == "long_write":
        L += ["    cpu.V.l = cpu.fetch()", "    cpu.V.h = cpu.fetch()", "    cpu.V.b = cpu.fetch()"]
        return L + _write_tail("cpu.writeLong", f"cpu.V.d{iw}", s, f)
    if family == "indirect_write":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()",
              "    cpu.V.l = cpu.readDirect(cpu.U.l + 0)",
              "    cpu.V.h = cpu.readDirect(cpu.U.l + 1)"]
        return L + _write_tail("cpu.writeBank", "cpu.V.w", s, f)
    if family == "indexed_indirect_write":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()", "    cpu.idle()",
              "    cpu.V.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)",
              "    cpu.V.h = cpu.readDirect(cpu.U.l + cpu.X.w + 1)"]
        return L + _write_tail("cpu.writeBank", "cpu.V.w", s, f)
    if family == "indirect_indexed_write":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()",
              "    cpu.V.l = cpu.readDirect(cpu.U.l + 0)",
              "    cpu.V.h = cpu.readDirect(cpu.U.l + 1)", "    cpu.idle()"]
        return L + _write_tail("cpu.writeBank", "cpu.V.w + cpu.Y.w", s, f)
    if family == "indirect_long_write":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()",
              "    cpu.V.l = cpu.readDirectN(cpu.U.l + 0)",
              "    cpu.V.h = cpu.readDirectN(cpu.U.l + 1)",
              "    cpu.V.b = cpu.readDirectN(cpu.U.l + 2)"]
        return L + _write_tail("cpu.writeLong", f"cpu.V.d{iw}", s, f)
    if family == "stack_write":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle()"]
        return L + _write_tail("cpu.writeStack", "cpu.U.l", s, f)
    if family == "indirect_stack_write":
        L += ["    cpu.U.l = cpu.fetch()", "    cpu.idle()",
              "    cpu.V.l = cpu.readStack(cpu.U.l + 0)",
              "    cpu.V.h = cpu.readStack(cpu.U.l + 1)", "    cpu.idle()"]
        return L + _write_tail("cpu.writeBank", "cpu.V.w + cpu.Y.w", s, f)
    raise ValueError(family)


def _write_tail(wr, addr, s, f):
    return [f"    if {f}:",
            f"        {wr}({addr} + 0, {s}.l)",
            "    else:",
            f"        {wr}({addr} + 0, {s}.l)",
            f"        {wr}({addr} + 1, {s}.h)"]


def body_modify(family, op, index, flag):
    """RMW families. EF=1 replays a dummy write-back in place of the native idle."""
    f = _flag(flag)
    if family == "implied_modify":
        # `index` carries the target register here.
        reg = f"cpu.{index}"
        return [f"    cpu.idleIRQ()",
                f"    if {f}:",
                f"        {reg}.l = {op}(cpu, True, {reg}.l)",
                "    else:",
                f"        {reg}.w = {op}(cpu, False, {reg}.w)"]
    if family in ("bank_modify", "bank_indexed_modify"):
        ix = " + cpu.X.w" if family == "bank_indexed_modify" else ""
        addr = f"cpu.V.w{ix}"
        L = ["    cpu.V.l = cpu.fetch()", "    cpu.V.h = cpu.fetch()"]
        if family == "bank_indexed_modify":
            L.append("    cpu.idle()")
        L += [f"    if {f}:",
              f"        cpu.W.l = cpu.readBank({addr} + 0)",
              "        if cpu.EF:",
              f"            cpu.writeBank({addr} + 0, cpu.W.l)",
              "        else:",
              "            cpu.idle()",
              f"        cpu.W.l = {op}(cpu, True, cpu.W.l)",
              f"        cpu.writeBank({addr} + 0, cpu.W.l)",
              "    else:",
              f"        cpu.W.l = cpu.readBank({addr} + 0)",
              f"        cpu.W.h = cpu.readBank({addr} + 1)",
              "        cpu.idle()",
              f"        cpu.W.w = {op}(cpu, False, cpu.W.w)",
              f"        cpu.writeBank({addr} + 1, cpu.W.h)",
              f"        cpu.writeBank({addr} + 0, cpu.W.l)"]
        return L
    if family in ("direct_modify", "direct_indexed_modify"):
        ix = " + cpu.X.w" if family == "direct_indexed_modify" else ""
        addr = f"cpu.U.l{ix}"
        L = ["    cpu.U.l = cpu.fetch()", "    cpu.idle2()"]
        if family == "direct_indexed_modify":
            L.append("    cpu.idle()")
        L += [f"    if {f}:",
              f"        cpu.W.l = cpu.readDirect({addr} + 0)",
              "        if cpu.EF:",
              f"            cpu.writeDirect({addr} + 0, cpu.W.l)",
              "        else:",
              "            cpu.idle()",
              f"        cpu.W.l = {op}(cpu, True, cpu.W.l)",
              f"        cpu.writeDirect({addr} + 0, cpu.W.l)",
              "    else:",
              f"        cpu.W.l = cpu.readDirect({addr} + 0)",
              f"        cpu.W.h = cpu.readDirect({addr} + 1)",
              "        cpu.idle()",
              f"        cpu.W.w = {op}(cpu, False, cpu.W.w)",
              f"        cpu.writeDirect({addr} + 1, cpu.W.h)",
              f"        cpu.writeDirect({addr} + 0, cpu.W.l)"]
        return L
    raise ValueError(family)


def gen_body(family, kind, target, index, reg, flag):
    if kind == "read":
        return body_read(family, target, index, flag)
    if kind == "write":
        return body_write(family, target, index, flag)
    if kind == "modify":
        return body_modify(family, target, index, flag)
    if kind == "implied":
        return body_modify(family, target, reg, flag)  # reg passed as index slot
    raise ValueError(kind)


def misc_body(func, flag, args):
    """Delegating handler for an irregular op: bake args, call the tested fn.

    Returns (preamble_lines, body_line). Lambda args are hoisted to a module
    level _arg_NN so they're built once, not per call.
    """
    call = ["cpu"]
    if flag:
        call.append("cpu.MFlag" if flag == "M" else "cpu.XFlag")
    if args:
        call.append(args)
    return [f"    AM.{func}({', '.join(call)})"]


def write_generated(spec, misc):
    # Only read/modify/implied families call an operation (OP.xxx); writes don't.
    ops = sorted({tgt for op, fam, tgt, idx, reg, fl in spec
                  if FAMILY_KIND(fam) in ("read", "modify", "implied") and tgt})
    out = [
        "# AUTO-GENERATED by scripts/gen_opcodes.py from opcodes_spec.py.",
        "# Do not edit by hand — change the spec/generator and regenerate.",
        "",
        "from . import addressing_modes as AM",
        "from .opcodes import " + ", ".join(sorted(ops)),
        "",
        "",
    ]
    names = {}
    # Memory / modify families: inlined literal handlers.
    for op, fam, tgt, idx, reg, flag in spec:
        kind = FAMILY_KIND(fam)
        name = f"op_{op:02X}"
        names[op] = name
        label = f"{fam} {tgt}{(' ,' + idx) if idx else ''}{(' ' + reg) if reg else ''} ({flag})"
        out.append(f"def {name}(cpu):  # {label}")
        out += gen_body(fam, kind, tgt, idx, reg, flag)
        out += ["", ""]
    # Irregular ops: delegating handlers (args baked; lambdas hoisted).
    for op, func, flag, args in misc:
        name = f"op_{op:02X}"
        names[op] = name
        if "lambda" in args:
            argname = f"_arg_{op:02X}"
            out.append(f"{argname} = {args}")
            args = argname
        out.append(f"def {name}(cpu):  # {func}")
        out += misc_body(func, flag, args)
        out += ["", ""]
    out.append("HANDLERS = {")
    for op in sorted(names):
        out.append(f"    0x{op:02X}: {names[op]},")
    out.append("}")
    GEN_OUT.write_text("\n".join(out) + "\n")
    return len(names)


def FAMILY_KIND(family):
    for fam, kind in FAMILY.values():
        if fam == family:
            return kind
    raise ValueError(family)


def main():
    from pysnes.cpu.wdc65816.opcodes_spec import SPEC, MISC_SPEC
    n = write_generated(SPEC, MISC_SPEC)
    print(f"read {len(SPEC)} + {len(MISC_SPEC)} spec rows; "
          f"wrote {GEN_OUT.relative_to(ROOT)} ({n} handlers)")


if __name__ == "__main__":
    main()
