#!/usr/bin/env python3
"""Build P01+P02+P03 together and check every patched site.

Run: python tools/test_patches.py

Writes _build/p01_p03/PR2_nation.exe (+ .manifest.json). Never runs
the game. Checks:
  * each patched site re-disassembles to the expected new instruction text;
  * no two patches (from any module) overlap;
  * every byte of the output outside the manifest's patched ranges, its header
    fields and the new section header equals the base exe, and the file is the base
    plus exactly one appended section.
Equivalent CLI build:
  python tools/pe_patch.py _build/p01_p03/PR2_nation.exe \\
      --patch-module patches/p01_isatwar_player.py \\
      --patch-module patches/p02_userflag_null.py \\
      --patch-module patches/p03_display_byte_reads.py
"""
import struct
import sys
import unittest
from pathlib import Path

import capstone
import pefile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_patch  # noqa: E402

PATCH_DIR = pe_patch.NATION_DIR / "patches"
MODULES = ["p01_isatwar_player.py", "p02_userflag_null.py", "p03_display_byte_reads.py"]
OUT = pe_patch.BUILD_DIR / "p01_p03" / "PR2_nation.exe"
MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

# (instruction VA, old text, new text) for the in-place patches of P02 and P03
EXPECTED = [
    (0x4C1411, "je 0x4c14eb", "je 0x4c1525"),                                       # P02
    (0x5C6A86, "mov bl, byte ptr [edi + 0x390]", "mov bl, byte ptr [edi + 0x391]"),  # P03 U3
    (0x5A80B0, "mov bl, byte ptr [ebx + 0x390]", "mov bl, byte ptr [ebx + 0x391]"),  # P03 U4a
    (0x5A822C, "mov bl, byte ptr [edi + 0x390]", "mov bl, byte ptr [edi + 0x391]"),  # P03 U4b
    (0x6352B7, "movzx eax, byte ptr [eax + 0x358]", "movzx eax, byte ptr [eax + 0x359]"),  # U1
    (0x634902, "mov al, byte ptr [eax + 0x358]", "mov al, byte ptr [eax + 0x359]"),  # P03 U2
    (0x57D0B6, "mov al, byte ptr [eax + 0x358]", "mov al, byte ptr [eax + 0x359]"),  # P03 U5
]
# instructions right after each site must be unchanged
FOLLOW = {
    0x4C1411: "xor esi, esi",
    0x5C6A86: "mov ecx, 0x702140",
    0x5A80B0: "mov ecx, 0x702140",
    0x5A822C: "mov ecx, 0x702140",
    0x6352B7: "mov cl, byte ptr [eax + 0x6ac4b4]",
    0x634902: "jmp 0x63490e",
    0x57D0B6: "movzx eax, al",
}
ISATWAR = 0x5BA0A0


def text(i):
    return f"{i.mnemonic} {i.op_str}".strip()


class PatchSetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fns = [pe_patch._load_module(str(PATCH_DIR / m)) for m in MODULES]
        cls.manifest = pe_patch.build(OUT, fns)
        cls.base = pe_patch.BASE_EXE.read_bytes()
        cls.out = OUT.read_bytes()
        cls.pe = pefile.PE(data=cls.out, fast_load=True)
        cls.bpe = pefile.PE(data=cls.base, fast_load=True)

    def off(self, va):
        return self.pe.get_offset_from_rva(va - self.pe.OPTIONAL_HEADER.ImageBase)

    def insns(self, data, va, n=2):
        off = self.off(va)
        return list(MD.disasm(data[off:off + 32], va))[:n]

    def test_manifest_written(self):
        self.assertTrue(pe_patch.manifest_path(OUT).exists())
        self.assertEqual(self.manifest["output"]["sha256"], pe_patch.sha256(self.out))
        self.assertEqual(self.manifest["base"]["sha256"], pe_patch.BASE_SHA256)

    def test_sites_disassemble(self):
        for va, old, new in EXPECTED:
            with self.subTest(va=hex(va)):
                b0, b1 = self.insns(self.base, va), self.insns(self.out, va)
                self.assertEqual(b0[0].address, va)
                self.assertEqual(text(b0[0]), old)
                self.assertEqual(text(b1[0]), new)
                self.assertEqual(b1[0].size, b0[0].size)
                self.assertEqual(text(b1[1]), FOLLOW[va])
                self.assertEqual(text(b0[1]), FOLLOW[va])

    def test_p01_detour(self):
        i = self.insns(self.out, ISATWAR, 1)[0]
        hook = next(l for l in self.manifest["section"]["labels"] if l["name"] == "isatwar_hook")
        self.assertEqual(text(i), f"jmp {hook['va']}")

    def test_patch_list(self):
        got = sorted((int(p["va"], 16), p["kind"], p["old"], p["new"]) for p in self.manifest["patches"])
        want = sorted([
            (0x5BA0A0, "detour", "8a4424043c04", None),
            (0x4C1411, "bytes", "0f84d4000000", "0f840e010000"),
            (0x5C6A88, "bytes", "90030000", "91030000"),
            (0x5A80B2, "bytes", "90030000", "91030000"),
            (0x5A822E, "bytes", "90030000", "91030000"),
            (0x6352BA, "bytes", "58030000", "59030000"),
            (0x634904, "bytes", "58030000", "59030000"),
            (0x57D0B8, "bytes", "58030000", "59030000"),
        ])
        self.assertEqual([(v, k, o) for v, k, o, _ in got], [(v, k, o) for v, k, o, _ in want])
        for (v, k, o, n), (_, _, _, wn) in zip(got, want):
            if wn is not None:
                self.assertEqual(n, wn, hex(v))

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
        self.assertEqual(diff, [], f"unexpected changed bytes at file offsets {[hex(d) for d in diff[:10]]}")
        # sanity: P02+P03 together change exactly 2 + 6*1 bytes of code
        changed = sum(1 for p in self.manifest["patches"] if p["kind"] == "bytes"
                      for a, b in zip(bytes.fromhex(p["old"]), bytes.fromhex(p["new"])) if a != b)
        self.assertEqual(changed, 8)
        nsec = struct.unpack_from("<H", out, self.pe.FILE_HEADER.get_file_offset() + 2)[0]
        self.assertEqual(nsec, self.bpe.FILE_HEADER.NumberOfSections + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
