#!/usr/bin/env python3
"""Tests for P04 (patches/p04_reputation_war.py). Run: python tools/test_p04.py

Builds P01 + P04 into _build/p04_test/PR2_nation.exe. Never runs
the game. Checks, all static (no emulation):
  * both detour sites decode as `jmp <stub>; nop` followed by the untouched
    original instruction;
  * both stubs decode to the exact expected instruction text;
  * the player_rel read: one byte load at exactly va_of("player_rel"), base
    register edx, no index/scale, and edx was loaded with the argument byte
    (`movzx edx, byte ptr [esp + 8]` right after `push edx`, so [esp+8] is the
    caller's [esp+4]) with nothing in between that writes edx or esp;
  * every control-flow path through each stub: balanced stack, the exact
    branch decisions that lead to "return hostile" vs "run vanilla";
  * no branch in .text lands inside either overwritten range;
  * every byte outside the patched ranges and the new section is unchanged.
"""
import importlib.util
import struct
import sys
import unittest
from pathlib import Path

import capstone
from capstone import x86 as X

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import pe_patch  # noqa: E402

PATCHES = TOOLS.parent / "patches"
OUT = pe_patch.BUILD_DIR / "p04_test" / "PR2_nation.exe"

GET_REP, GET_REP_RESUME = 0x5D2AC0, 0x5D2AC6
IS_REP25, IS_REP25_MID, IS_REP25_RESUME = 0x5D2D90, 0x5D2D96, 0x5D2D9C


def load(name):
    spec = importlib.util.spec_from_file_location(name, PATCHES / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P01 = load("p01_isatwar_player")
P04 = load("p04_reputation_war")


def txt(i):
    return f"{i.mnemonic} {i.op_str}".strip()


class P04Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b = pe_patch.PatchBuilder()
        P01.apply(b)
        P04.apply(b)
        cls.b = b
        cls.manifest = b.build(OUT)
        cls.base = pe_patch.BASE_EXE.read_bytes()
        cls.out = OUT.read_bytes()
        cls.rel = b.va_of("player_rel")
        cls.d1 = b.va_of("getrep_hook")
        cls.d2 = b.va_of("isrep25_hook")
        cls.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cls.md.detail = True

    # -- helpers -------------------------------------------------------------
    def at(self, va, n):
        """Bytes of the OUTPUT exe at va (the new section lies past the base image)."""
        if va >= self.b.sec_va:
            off = self.b.sec_raw_ptr + va - self.b.sec_va
        else:
            off = self.b.file_offset(va)
        return self.out[off:off + n]

    def dis(self, va, n):
        return list(self.md.disasm(self.at(va, n), va))

    def stub(self, label):
        lab = self.b.labels[label]
        va = self.b.va_of(label)
        insns = self.dis(va, lab.size)
        self.assertEqual(sum(i.size for i in insns), lab.size, f"{label} decodes cleanly")
        return va, insns

    # -- detour sites ----------------------------------------------------------
    def test_detour_sites(self):
        got = [(i.address, txt(i)) for i in self.dis(GET_REP, 8)][:3]
        self.assertEqual(got, [(0x5D2AC0, f"jmp {self.d1:#x}"), (0x5D2AC5, "nop"),
                               (0x5D2AC6, "jb 0x5d2ad8")])
        got = [(i.address, txt(i)) for i in self.dis(IS_REP25, 14)][:5]
        self.assertEqual(got, [(0x5D2D90, "cmp word ptr [ecx], 0"),
                               (0x5D2D94, "jne 0x5d2db0"),
                               (0x5D2D96, f"jmp {self.d2:#x}"), (0x5D2D9B, "nop"),
                               (0x5D2D9C, "jae 0x5d2db0")])

    # -- stub text ---------------------------------------------------------------
    def test_getrep_stub_text(self):
        va, insns = self.stub("getrep_hook")
        r = self.rel
        exp = [
            (0x00, "push edx"),
            (0x01, "movzx edx, byte ptr [esp + 8]"),
            (0x06, "cmp edx, 4"),
            (0x09, f"jae {va + 0x20:#x}"),
            (0x0B, "cmp word ptr [ecx], 0"),
            (0x0F, f"jne {va + 0x20:#x}"),
            (0x11, f"cmp byte ptr [edx + {r:#x}], 0"),
            (0x18, "pop edx"),
            (0x19, f"je {va + 0x21:#x}"),
            (0x1B, "xor eax, eax"),
            (0x1D, "ret 4"),
            (0x20, "pop edx"),
            (0x21, "mov al, byte ptr [esp + 4]"),
            (0x25, "cmp al, 4"),
            (0x27, f"jmp {GET_REP_RESUME:#x}"),
        ]
        self.assertEqual([(i.address - va, txt(i)) for i in insns], exp)

    def test_isrep25_stub_text(self):
        va, insns = self.stub("isrep25_hook")
        r = self.rel
        exp = [
            (0x00, "push edx"),
            (0x01, "movzx edx, byte ptr [esp + 8]"),
            (0x06, "cmp edx, 4"),
            (0x09, f"jae {va + 0x1A:#x}"),
            (0x0B, f"cmp byte ptr [edx + {r:#x}], 0"),
            (0x12, "pop edx"),
            (0x13, f"je {va + 0x1B:#x}"),
            (0x15, "xor eax, eax"),
            (0x17, "ret 4"),
            (0x1A, "pop edx"),
            (0x1B, "mov al, byte ptr [esp + 4]"),
            (0x1F, "cmp al, 4"),
            (0x21, f"jmp {IS_REP25_RESUME:#x}"),
        ]
        self.assertEqual([(i.address - va, txt(i)) for i in insns], exp)

    # -- player_rel read: right VA, right index register ---------------------------
    def check_rel_read(self, label):
        _, insns = self.stub(label)
        reads = [i for i in insns for op in i.operands
                 if op.type == X.X86_OP_MEM and (op.mem.disp & 0xFFFFFFFF) == self.rel]
        self.assertEqual(len(reads), 1, f"{label}: exactly one player_rel access")
        rd = reads[0]
        mem = [op for op in rd.operands if op.type == X.X86_OP_MEM][0]
        self.assertEqual(rd.mnemonic, "cmp")
        self.assertEqual(mem.size, 1, "byte access")
        self.assertEqual(rd.reg_name(mem.mem.base), "edx", "index register is edx (base)")
        self.assertEqual(mem.mem.index, 0, "no SIB index")
        self.assertEqual(mem.mem.segment, 0)
        self.assertEqual(mem.mem.disp & 0xFFFFFFFF, self.rel, "disp == va_of('player_rel')")
        imm = [op for op in rd.operands if op.type == X.X86_OP_IMM]
        self.assertEqual([op.imm for op in imm], [0], "compared against 0 (peace)")
        # player_rel is P01's 4-byte table, so [edx+rel] with edx in 0..3 stays inside it
        lab = self.b.labels["player_rel"]
        self.assertEqual(lab.size, 4)
        # edx = zero-extended argument byte; nothing between redefines edx or moves esp
        k = insns.index(rd)
        self.assertEqual(txt(insns[0]), "push edx")
        self.assertEqual(txt(insns[1]), "movzx edx, byte ptr [esp + 8]")
        for i in insns[2:k]:
            _, written = i.regs_access()
            names = {i.reg_name(r) for r in written}
            self.assertFalse(names & {"edx", "dx", "dl", "dh", "esp"},
                             f"{label}: {txt(i)} clobbers the index between load and use")
        # bounds guard: `cmp edx, 4; jae` precedes the read on the only path to it
        self.assertEqual(txt(insns[2]), "cmp edx, 4")
        self.assertEqual(insns[3].mnemonic, "jae")

    def test_getrep_reads_player_rel(self):
        self.check_rel_read("getrep_hook")

    def test_isrep25_reads_player_rel(self):
        self.check_rel_read("isrep25_hook")

    # -- every path through the stub (static path enumeration, no emulation) ------
    def paths(self, label):
        va, insns = self.stub(label)
        by = {i.address: i for i in insns}
        out = []

        def walk(addr, depth, decisions, seen):
            self.assertNotIn(addr, seen, "no loops")
            i = by[addr]
            seen = seen | {addr}
            nxt = addr + i.size
            if i.mnemonic == "push":
                depth += 4
            elif i.mnemonic == "pop":
                depth -= 4
            if i.mnemonic == "ret":
                out.append((decisions, depth, "ret", txt(i), [txt(x) for x in insns
                                                             if x.address < addr]))
                return
            if i.mnemonic == "jmp":
                tgt = i.operands[0].imm
                self.assertNotIn(tgt, by, "only jmp is the jump back")
                out.append((decisions, depth, "vanilla", tgt, None))
                return
            if X.X86_GRP_JUMP in i.groups:
                tgt = i.operands[0].imm
                self.assertIn(tgt, by, f"{txt(i)} stays inside the stub")
                walk(tgt, depth, decisions + [(i.mnemonic, True)], seen)
                walk(nxt, depth, decisions + [(i.mnemonic, False)], seen)
                return
            walk(nxt, depth, decisions, seen)

        walk(va, 0, [], frozenset())
        return va, insns, out

    def check_paths(self, label, resume, table):
        va, insns, paths = self.paths(label)
        got = {tuple(d): (kind, depth, end) for d, depth, kind, end, _ in paths}
        self.assertEqual(set(got), {tuple(k) for k in table}, f"{label}: decision set")
        for dec, kind in table.items():
            k, depth, end = got[tuple(dec)]
            self.assertEqual(depth, 0, f"{label} {dec}: stack balanced")
            self.assertEqual(k, kind, f"{label} {dec}")
            if kind == "vanilla":
                self.assertEqual(end, resume)
            else:
                self.assertEqual(end, "ret 4")
        # hostile return value: the instruction right before `ret 4` zeroes eax
        ret = [i for i in insns if i.mnemonic == "ret"]
        self.assertEqual(len(ret), 1)
        prev = insns[insns.index(ret[0]) - 1]
        self.assertEqual(txt(prev), "xor eax, eax")
        # vanilla tail = the original displaced bytes, then jmp resume
        tail = self.at(resume - 6, 6)
        self.assertEqual(self.base[self.b.file_offset(resume - 6):][:6], bytes.fromhex("8a4424043c04"))
        disp = [i for i in insns if txt(i) == "mov al, byte ptr [esp + 4]"]
        self.assertEqual(len(disp), 1)
        self.assertEqual(self.at(disp[0].address, 6), bytes.fromhex("8a4424043c04"))
        self.assertEqual(tail[:1], b"\xE9")  # site itself now holds the detour jmp

    def test_getrep_paths(self):
        # jae (P>=4)  jne (AI player)  je (peace)  -> outcome
        self.check_paths("getrep_hook", GET_REP_RESUME, {
            (("jae", True),): "vanilla",
            (("jae", False), ("jne", True)): "vanilla",
            (("jae", False), ("jne", False), ("je", True)): "vanilla",
            (("jae", False), ("jne", False), ("je", False)): "ret",
        })

    def test_isrep25_paths(self):
        self.check_paths("isrep25_hook", IS_REP25_RESUME, {
            (("jae", True),): "vanilla",
            (("jae", False), ("je", True)): "vanilla",
            (("jae", False), ("je", False)): "ret",
        })

    def test_flags_from_rel_reach_je(self):
        """`pop edx` between the cmp and the je does not touch flags."""
        for label in ("getrep_hook", "isrep25_hook"):
            _, insns = self.stub(label)
            k = [n for n, i in enumerate(insns) if f"{self.rel:#x}" in i.op_str][0]
            self.assertEqual(txt(insns[k + 1]), "pop edx")
            self.assertEqual(insns[k + 2].mnemonic, "je")
            self.assertEqual(insns[k + 1].eflags, 0, "pop modifies no flags")

    # -- no branch lands inside the overwritten ranges -----------------------------
    def test_no_branch_into_patched_interiors(self):
        pe = self.b.pe
        text = pe.sections[0]
        self.assertEqual(text.Name.rstrip(b"\0"), b".text")
        data = self.base[text.PointerToRawData:text.PointerToRawData + text.SizeOfRawData]
        base = pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress
        bad = set(range(GET_REP + 1, GET_REP + 6)) | set(range(IS_REP25_MID + 1, IS_REP25_MID + 6))
        hits = []
        for o in range(len(data) - 6):
            op = data[o]
            if op in (0xE8, 0xE9):
                t = base + o + 5 + struct.unpack_from("<i", data, o + 1)[0]
            elif op == 0xEB or 0x70 <= op <= 0x7F:
                t = base + o + 2 + struct.unpack_from("<b", data, o + 1)[0]
            elif op == 0x0F and 0x80 <= data[o + 1] <= 0x8F:
                t = base + o + 6 + struct.unpack_from("<i", data, o + 2)[0]
            else:
                continue
            if (t & 0xFFFFFFFF) in bad:
                hits.append(base + o)
        # a raw byte scan over-approximates; confirm any hit is a real decoded branch
        real = []
        for h in hits:
            for i in self.b.md.disasm(self.b.read(h, 8), h):
                if X.X86_GRP_JUMP in i.groups or X.X86_GRP_CALL in i.groups:
                    if i.operands and i.operands[0].type == X.X86_OP_IMM \
                            and i.operands[0].imm in bad and self._is_insn_start(h):
                        real.append(h)
                break
        self.assertEqual(real, [], f"branches into patched interiors: {[hex(x) for x in real]}")

    def _is_insn_start(self, va):
        """va is an instruction boundary in a linear decode from 64 bytes earlier."""
        for start in range(va - 64, va - 48):
            a = start
            for i in self.b.md.disasm(self.b.read(start, va - start + 1), start):
                if i.address >= va:
                    break
                a = i.address + i.size
            if a == va:
                return True
        return False

    # -- nothing else changed ---------------------------------------------------------
    def test_only_expected_bytes_changed(self):
        sec_raw = self.b.sec_raw_ptr
        patched = {GET_REP: "e9", IS_REP25_MID: "e9"}
        ranges = [(self.b.file_offset(va), 6) for va in patched]
        ranges.append((self.b.file_offset(P01.ISATWAR), 6))
        diffs = [o for o in range(0x400, sec_raw) if self.base[o] != self.out[o]
                 and not any(s <= o < s + n for s, n in ranges)]
        self.assertEqual(diffs, [], "unexpected byte changes in the base image")
        kinds = [(p["va"], p["kind"]) for p in self.manifest["patches"]]
        self.assertEqual(kinds, [(f"{P01.ISATWAR:#x}", "detour"), (f"{GET_REP:#x}", "detour"),
                                 (f"{IS_REP25_MID:#x}", "detour")])
        labels = [l["name"] for l in self.manifest["section"]["labels"]]
        self.assertEqual(labels, ["player_rel", "isatwar_hook", "getrep_hook", "isrep25_hook"])
        self.assertEqual(self.at(self.rel, 4), bytes(4), "player_rel defaults to peace")


if __name__ == "__main__":
    unittest.main(verbosity=2)
