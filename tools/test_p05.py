#!/usr/bin/env python3
"""Tests for P05 (patches/p05_nation5_town_safety.py). Run: python tools/test_p05.py

Builds P01..P05 in order into _build/full5/PR2_nation.exe
(+ .manifest.json) with pe_patch.build. Never runs the game. Static checks:
  * every P05 site in the output decodes to the expected new instruction text,
    and the instruction after it is the untouched original;
  * every P05 stub decodes to exactly the expected instruction text;
  * the manifest holds exactly the P01..P04 patches plus the 10 P05 patches,
    and no two patches overlap;
  * no branch in .text lands inside any P05 patched range;
  * ebp (the town in 0x5B40D0) is not written between 0x5B4107 and 0x5B4405;
  * every byte outside the manifest's patches, header fields and the new
    section equals the base exe.
Equivalent CLI build:
  python tools/pe_patch.py _build/full5/PR2_nation.exe \\
      --patch-module patches/p01_isatwar_player.py \\
      --patch-module patches/p02_userflag_null.py \\
      --patch-module patches/p03_display_byte_reads.py \\
      --patch-module patches/p04_reputation_war.py \\
      --patch-module patches/p05_nation5_town_safety.py
"""
import struct
import sys
import unittest
from pathlib import Path

import capstone
from capstone import x86 as X

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import pe_patch  # noqa: E402

PATCH_DIR = pe_patch.NATION_DIR / "patches"
MODULES = ["p01_isatwar_player.py", "p02_userflag_null.py", "p03_display_byte_reads.py",
           "p04_reputation_war.py", "p05_nation5_town_safety.py"]
OUT = pe_patch.BUILD_DIR / "full5" / "PR2_nation.exe"

# displacement patches: (insn va, old text, new text, next insn text)
DISP = [
    (0x5B41B0, "movzx edx, byte ptr [ebp + 0x390]", "movzx edx, byte ptr [ebp + 0x391]", "cmp edx, 4"),
    (0x5B41DA, "movzx ecx, byte ptr [ebp + 0x390]", "movzx ecx, byte ptr [ebp + 0x391]", "cmp ecx, 4"),
    (0x5B42EB, "movzx eax, byte ptr [ebp + 0x390]", "movzx eax, byte ptr [ebp + 0x391]", "cmp eax, 4"),
    (0x5B438D, "movzx eax, byte ptr [ebp + 0x390]", "movzx eax, byte ptr [ebp + 0x391]", "cmp eax, 4"),
    (0x5E75C7, "movzx eax, byte ptr [eax + 0x390]", "movzx eax, byte ptr [eax + 0x391]", "cmp eax, 4"),
]
# detours: (site va, length, label, resume va, resume insn text)
DETOURS = [
    (0x5C86A5, 7, "p05_econ_share", 0x5C86AC, "cmp ecx, 4"),
    (0x5BC49E, 6, "p05_annex_viceroy", 0x5BC4A4, "mov dword ptr [esp + 0x3c], eax"),
    (0x5BC59D, 7, "p05_annex_count", 0x5BC5A4, "mov ebp, dword ptr [esp + 0x18]"),
    (0x5BC5D1, 7, "p05_annex_recount", 0x5BC5D8, "mov eax, dword ptr [ebp + 0x44]"),
    (0x5BC100, 6, "p05_nullthis_5bc100", 0x5BC106, "push -1"),
]


def stub_expect(label, s):
    """Expected (offset, text) of each stub placed at VA s."""
    return {
        "p05_econ_share": [
            (0x00, "movzx ecx, byte ptr [esi + 0x358]"),
            (0x07, "cmp ecx, 4"),
            (0x0A, "jae 0x5c8765"),
            (0x10, "jmp 0x5c86ac"),
        ],
        "p05_annex_viceroy": [
            (0x00, "movzx eax, cl"),
            (0x03, "cmp eax, 4"),
            (0x06, f"jb {s + 0x18:#x}"),
            (0x08, "movzx eax, byte ptr [edi + 0x391]"),
            (0x0F, "cmp eax, 4"),
            (0x12, "jae 0x5bcb6f"),
            (0x18, "jmp 0x5bc4a4"),
        ],
        "p05_annex_count": [
            (0x00, "test eax, eax"),
            (0x02, f"je {s + 0x0B:#x}"),
            (0x04, "inc word ptr [eax + 0x16c]"),
            (0x0B, "jmp 0x5bc5a4"),
        ],
        "p05_annex_recount": [
            (0x00, "test ecx, ecx"),
            (0x02, f"je {s + 0x0B:#x}"),
            (0x04, "push 1"),
            (0x06, "call 0x5bbb20"),
            (0x0B, "jmp 0x5bc5d8"),
        ],
        "p05_nullthis_5bc100": [
            (0x00, "test ecx, ecx"),
            (0x02, f"jne {s + 0x07:#x}"),
            (0x04, "xor eax, eax"),
            (0x06, "ret"),
            (0x07, "mov eax, dword ptr fs:[0]"),
            (0x0D, "jmp 0x5bc106"),
        ],
    }[label]


def txt(i):
    return f"{i.mnemonic} {i.op_str}".strip()


class P05Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b = pe_patch.PatchBuilder()
        for m in MODULES:
            pe_patch._load_module(str(PATCH_DIR / m))(b)
        cls.b = b
        cls.manifest = b.build(OUT)
        cls.base = pe_patch.BASE_EXE.read_bytes()
        cls.out = OUT.read_bytes()
        cls.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cls.md.detail = True

    # -- helpers -------------------------------------------------------------
    def at(self, va, n, data=None):
        data = self.out if data is None else data
        if va >= self.b.sec_va:
            off = self.b.sec_raw_ptr + va - self.b.sec_va
        else:
            off = self.b.file_offset(va)
        return data[off:off + n]

    def dis(self, va, n, data=None):
        return list(self.md.disasm(self.at(va, n, data), va))

    # -- sites ---------------------------------------------------------------
    def test_displacement_sites(self):
        for va, old, new, nxt in DISP:
            with self.subTest(va=hex(va)):
                b0 = self.dis(va, 16, self.base)[:2]
                b1 = self.dis(va, 16)[:2]
                self.assertEqual([txt(i) for i in b0], [old, nxt])
                self.assertEqual([txt(i) for i in b1], [new, nxt])
                self.assertEqual(b1[0].size, 7)

    def test_detour_sites(self):
        for va, n, label, resume, rtext in DETOURS:
            with self.subTest(va=hex(va)):
                s = self.b.va_of(label)
                got = [(i.address, txt(i)) for i in self.dis(va, n + 12)]
                want = [(va, f"jmp {s:#x}")] + [(va + 5 + k, "nop") for k in range(n - 5)]
                self.assertEqual(got[:len(want)], want)
                self.assertEqual(got[len(want)], (resume, rtext))

    def test_stub_texts(self):
        for _, _, label, _, _ in DETOURS:
            with self.subTest(label=label):
                lab = self.b.labels[label]
                s = self.b.va_of(label)
                insns = self.dis(s, lab.size)
                self.assertEqual(sum(i.size for i in insns), lab.size, "decodes cleanly")
                self.assertEqual([(i.address - s, txt(i)) for i in insns], stub_expect(label, s))

    def test_displaced_bytes_are_original(self):
        """Each stub's copy of the displaced code is byte-identical to the base."""
        for va, n, label, _, _ in DETOURS:
            with self.subTest(label=label):
                s = self.b.va_of(label)
                orig = self.at(va, n, self.base)
                body = self.at(s, self.b.labels[label].size)
                if label == "p05_annex_recount":   # push 1 raw + relocated call
                    self.assertEqual(body[4:6], orig[:2])
                    self.assertEqual(body[6], 0xE8)
                else:
                    self.assertIn(orig, body)

    # -- manifest ------------------------------------------------------------
    def test_patch_list(self):
        got = [(p["va"], p["kind"]) for p in self.manifest["patches"]]
        p05 = [("0x5c86a5", "detour"), ("0x5b41b3", "bytes"), ("0x5b41dd", "bytes"),
               ("0x5b42ee", "bytes"), ("0x5b4390", "bytes"), ("0x5e75ca", "bytes"),
               ("0x5bc49e", "detour"), ("0x5bc59d", "detour"), ("0x5bc5d1", "detour"),
               ("0x5bc100", "detour")]
        before = [("0x5ba0a0", "detour"), ("0x4c1411", "bytes"), ("0x5c6a88", "bytes"),
                  ("0x5a80b2", "bytes"), ("0x5a822e", "bytes"), ("0x6352ba", "bytes"),
                  ("0x634904", "bytes"), ("0x57d0b8", "bytes"), ("0x5d2ac0", "detour"),
                  ("0x5d2d96", "detour")]
        self.assertEqual(got, before + p05)
        for p in self.manifest["patches"]:
            if p["kind"] == "bytes" and p["desc"].startswith("P05"):
                self.assertEqual((p["old"], p["new"]), ("90030000", "91030000"))
        labels = [l["name"] for l in self.manifest["section"]["labels"]]
        self.assertEqual(labels[4:], [d[2] for d in DETOURS])

    def test_no_overlap(self):
        spans = sorted((int(p["file_offset"], 16), len(bytes.fromhex(p["new"])))
                       for p in self.manifest["patches"])
        for (a, al), (b, _) in zip(spans, spans[1:]):
            self.assertLessEqual(a + al, b, f"patch at file offset {a:#x} overlaps {b:#x}")

    def test_only_manifest_bytes_changed(self):
        base, out = self.base, self.out
        sec = self.manifest["section"]
        self.assertEqual(int(sec["raw_offset"], 16), len(base))
        self.assertEqual(len(out), len(base) + int(sec["raw_size"], 16))
        allowed = bytearray(len(base))
        for p in self.manifest["patches"]:
            o, n = int(p["file_offset"], 16), len(bytes.fromhex(p["new"]))
            self.assertEqual(base[o:o + n].hex(), p["old"])
            self.assertEqual(out[o:o + n].hex(), p["new"])
            allowed[o:o + n] = b"\x01" * n
        sizes = {"FILE_HEADER.NumberOfSections": 2, "OPTIONAL_HEADER.SizeOfImage": 4,
                 "OPTIONAL_HEADER.CheckSum": 4}
        for h in self.manifest["header_changes"]:
            o = h["file_offset"]
            n = 40 if h["field"].startswith("section header") else sizes[h["field"]]
            allowed[o:o + n] = b"\x01" * n
        diff = [i for i in range(len(base)) if base[i] != out[i] and not allowed[i]]
        self.assertEqual(diff, [], f"unexpected changed bytes at {[hex(d) for d in diff[:10]]}")

    # -- control flow ----------------------------------------------------------
    def test_no_branch_into_patched_interiors(self):
        bad = set()
        for va, n, _, _, _ in DETOURS:
            bad |= set(range(va + 1, va + n))
        for va, _, _, _ in DISP:
            bad |= set(range(va + 1, va + 7))
        text = self.b.pe.sections[0]
        self.assertEqual(text.Name.rstrip(b"\0"), b".text")
        data = self.base[text.PointerToRawData:text.PointerToRawData + text.SizeOfRawData]
        base = self.b.image_base + text.VirtualAddress
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
        real = []
        for h in hits:   # a raw byte scan over-approximates; keep real decoded branches only
            i = next(self.b.md.disasm(self.b.read(h, 8), h), None)
            if i is not None and (X.X86_GRP_JUMP in i.groups or X.X86_GRP_CALL in i.groups) \
                    and i.operands and i.operands[0].type == X.X86_OP_IMM \
                    and i.operands[0].imm in bad and self._is_insn_start(h):
                real.append(h)
        self.assertEqual(real, [], f"branches into patched interiors: {[hex(x) for x in real]}")

    def _is_insn_start(self, va):
        for start in range(va - 64, va - 48):
            a = start
            for i in self.b.md.disasm(self.b.read(start, va - start + 1), start):
                if i.address >= va:
                    break
                a = i.address + i.size
            if a == va:
                return True
        return False

    def test_town_register_stable_in_convoy_fn(self):
        """0x5B40D0: ebp = town after 0x5B4107 until 0x5B4405 (all 4 loads in between)."""
        self.assertEqual(txt(self.dis(0x5B4107, 4, self.base)[0]), "mov ebp, eax")
        insns = self.dis(0x5B4109, 0x5B4405 - 0x5B4109, self.base)
        self.assertEqual(insns[-1].address + insns[-1].size, 0x5B4405, "linear decode reaches 0x5B4405")
        for i in insns:
            _, written = i.regs_access()
            names = {i.reg_name(r) for r in written}
            self.assertFalse(names & {"ebp", "bp"}, f"{i.address:#x} {txt(i)} writes ebp")
        self.assertEqual(txt(self.dis(0x5B4405, 8, self.base)[0]), "mov ebp, dword ptr [esp + 0x10]")

    def test_stub_rel_targets(self):
        """Every exit of every stub goes back into the original function it came from."""
        exits = {
            "p05_econ_share": {0x5C8765, 0x5C86AC},
            "p05_annex_viceroy": {0x5BCB6F, 0x5BC4A4},
            "p05_annex_count": {0x5BC5A4},
            "p05_annex_recount": {0x5BC5D8, 0x5BBB20},
            "p05_nullthis_5bc100": {0x5BC106},
        }
        for label, want in exits.items():
            with self.subTest(label=label):
                s, size = self.b.va_of(label), self.b.labels[label].size
                ext = {i.operands[0].imm for i in self.dis(s, size)
                       if (X.X86_GRP_JUMP in i.groups or X.X86_GRP_CALL in i.groups)
                       and not s <= i.operands[0].imm < s + size}
                self.assertEqual(ext, want)


if __name__ == "__main__":
    unittest.main(verbosity=2)
