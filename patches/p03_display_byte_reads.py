"""P03 -- the six UNGUARDED nation-indexed table reads use the display nation byte.

Spec: FND-01 / TER-01 / MIL-01 (a nation-5 town must keep running its timers,
ship spawns and military convoys without producing invalid ship types).
Source: research/nation5_index_safety.md, sites U1..U5 and patch idea U6.

Background:
  A town's nation byte is CStadt+0x390 == CStadtLager(+0x38)+0x358; the display
  nation is the next byte, +0x391 / +0x359. The non-force setter writes the same
  value to both bytes (0x5C9E54 / 0x5C9E5A), so for every town owned by a power
  (0..3), and for 0xFF/4, display == nation and these patches change nothing.
  The force path that creates a nation-5 town (vanilla's "Your Own Town" offer,
  and our option C) sets display = host power (nation % 4) and nation = 5
  (the private feasibility study [T3-force, T3-mark5]). Reading the display byte therefore
  turns index 5 into the host power's row 0..3 instead of reading past a 4-row
  table. That also applies to vanilla's own nation-5 player towns, which hit the
  same out-of-range rows today.

Each patch changes only the 32-bit displacement of one byte load
(0x390 -> 0x391, 0x358 -> 0x359). apply() first re-disassembles the load and
the instructions that consume it (capstone, exact text) and refuses to patch if
anything differs from what is documented below.

  U3  0x5C6A86  fn 0x5C6A40 (town ship spawn, per-town timer 0x5EF7D0 calls it at
      0x5EF931/0x5EF944 BEFORE that function's own `cmp eax,4` guard at 0x5EF979)
      mov bl,[edi+0x390] -> movzx edx,bl -> [eax+edx*8+0x6A5174] (ship-type row,
      rand&7) -> 0x63CFC0 creates the ship. Row 5 = 32 00 00 00 05 0D 10 15:
      types 0x32 and 0x15 are >= 18 (invalid). bl is dead after (xor ebx,ebx).
      The live hazard. (The `cmp al,2` special case at 0x5C6A5D reads the raw
      byte and is a compare, not an index; left alone.)
  U4a 0x5A80B0  fn 0x5A7F40 (initial ships at town creation)
      mov bl,[ebx+0x390] -> movzx ecx,bl -> [eax+ecx*8+0x6A5174]; ebx is
      reloaded (0x5A81A1) before any other use.
  U4b 0x5A822C  same fn: mov bl,[edi+0x390] -> movzx ecx,bl -> [eax+ecx*8+0x6A5174]
      -> [edx+0x6A4F50]. The following raw read 0x5A8249 mov cl,[edi+0x390] feeds
      `shl edi,cl` (a bit mask, NO-INDEX) and is left alone.
  U1  0x6352B7  fn 0x635270 CConvoyCreate::NewKonvoiMilitary(city)
      movzx eax,[eax+0x358] -> mov cl,[eax+0x6AC4B4] (byte[4] leader ship type;
      index 5 = 0xF0, invalid). eax is overwritten right after (mov eax,esp).
  U2  0x634902  fn 0x6348E0 (military convoy escorts)
      mov al,[eax+0x358] -> [esp+0x14] -> movzx edi,[esp+0x14] ->
      [edi+0x6AC4B4] (index 5 = 0xF0) and [edi+eax*4+0x6AC4AC]. The same byte is
      also the 3rd arg of 0x633F50, which only does `test cl,cl / cmp cl,3` to cap
      the escort count at 2 for nations 0 and 3: a nation-5 town now gets its
      host power's cap (vanilla towns unchanged).
  U5  0x57D0B6  fn 0x578C10 (welcome voice)
      mov al,[eax+0x358] -> movzx eax,al -> lea edx,[esp+eax*3+0x20] (char[4][3]
      {"En","Fr","Ho","Sp"} on the stack) -> sprintf("music/voice/Willkommen_%s_%02d.mp3").
      Index 5 reads 3 bytes past the array (stack garbage for %s).

Not touched: every GUARDED / GUARDED-DISPLAY / ADMITS-5 / NO-INDEX site, and the
two UNGUARDED-BENIGN reads (0x5D57C4, 0x5C599F). Nothing in the research's
UNGUARDED list was skipped.
"""
import sys

import capstone

# (name, insn_va, disp_offset_in_insn, old_disp, new_disp, checks)
# checks: list of (va, [exact capstone texts from va on])
SITES = [
    ("U3 town ship spawn 0x5C6A40", 0x5C6A86, 2, 0x390, 0x391, [
        (0x5C6A86, ["mov bl, byte ptr [edi + 0x390]", "mov ecx, 0x702140", "call 0x5c1cf0",
                    "movzx edx, bl", "and eax, 7", "mov al, byte ptr [eax + edx*8 + 0x6a5174]",
                    "mov byte ptr [esp + 0x10], al", "mov ecx, dword ptr [esp + 0x10]",
                    "push esi", "push 1", "push ecx", "lea ecx, [edi + 0x20]", "call 0x63cfc0",
                    "xor ebx, ebx"]),
        (0x5EF931, ["call 0x5c6a40"]),
        (0x5EF944, ["call 0x5c6a40"]),
        (0x5EF979, ["movzx eax, byte ptr [ebp + 0x390]", "cmp eax, 4", "jae 0x5f01c3"]),
    ]),
    ("U4a initial ships 0x5A7F40", 0x5A80B0, 2, 0x390, 0x391, [
        (0x5A80B0, ["mov bl, byte ptr [ebx + 0x390]", "mov ecx, 0x702140", "call 0x5c1cf0",
                    "movzx ecx, bl", "and eax, 7", "mov dl, byte ptr [eax + ecx*8 + 0x6a5174]",
                    "mov byte ptr [esp + 0x20], dl"]),
        (0x5A81A1, ["mov ebx, 0xc8"]),
    ]),
    ("U4b initial ships 0x5A7F40", 0x5A822C, 2, 0x390, 0x391, [
        (0x5A822C, ["mov bl, byte ptr [edi + 0x390]", "mov ecx, 0x702140", "call 0x5c1cf0",
                    "movzx ecx, bl", "and eax, 7", "mov al, byte ptr [eax + ecx*8 + 0x6a5174]",
                    "mov cl, byte ptr [edi + 0x390]", "movzx edx, al",
                    "movzx edx, byte ptr [edx + 0x6a4f50]", "mov edi, 1", "shl edi, cl"]),
    ]),
    ("U1 military convoy leader 0x635270", 0x6352B7, 3, 0x358, 0x359, [
        (0x6352AD, ["call 0x5c2200", "xor ecx, ecx", "add eax, 0x38",
                    "movzx eax, byte ptr [eax + 0x358]", "mov cl, byte ptr [eax + 0x6ac4b4]",
                    "push ecx", "push ecx", "mov eax, esp"]),
    ]),
    ("U2 military convoy escorts 0x6348E0", 0x634902, 2, 0x358, 0x359, [
        (0x6348FA, ["call 0x5c2200", "add eax, 0x38", "mov al, byte ptr [eax + 0x358]",
                    "jmp 0x63490e"]),
        (0x63490E, ["mov byte ptr [esp + 0x14], al", "mov eax, dword ptr [esp + 0x14]", "push eax"]),
        (0x63493B, ["movzx edi, byte ptr [esp + 0x14]", "xor eax, eax",
                    "mov al, byte ptr [edi + 0x6ac4b4]"]),
        (0x634A35, ["movzx edi, byte ptr [esp + 0x14]"]),
        (0x634A4D, ["movzx eax, byte ptr [edi + eax*4 + 0x6ac4ac]"]),
    ]),
    ("U5 welcome voice 0x578C10", 0x57D0B6, 2, 0x358, 0x359, [
        (0x57D0A8, ["call 0x5c2200", "mov edx, dword ptr [0x701e78]", "add eax, 0x38",
                    "mov al, byte ptr [eax + 0x358]", "movzx eax, al", "push edx",
                    "lea ecx, [esp + eax + 0x20]", "lea edx, [ecx + eax*2]", "push edx",
                    "lea eax, [esp + 0x150]", "push 0x6a0034", "push eax",
                    "call dword ptr [0x67f398]"]),
    ]),
]


def _texts(b, va, n):
    return [f"{i.mnemonic} {i.op_str}".strip() for i in b.decode(va, 96)][:n]


def apply(b):
    err = sys.modules[type(b).__module__].PatchError
    for name, va, doff, old, new, checks in SITES:
        for cva, want in checks:
            got = _texts(b, cva, len(want))
            if got != want:
                raise err(f"P03 {name}: check at {cva:#x} expected {want}, found {got}")
        insn = b.decode(va, 16)[0]
        src = insn.operands[1] if len(insn.operands) == 2 else None
        if insn.mnemonic not in ("mov", "movzx") or src is None or src.mem.disp != old \
                or src.type != capstone.x86.X86_OP_MEM or src.size != 1:
            raise err(f"P03 {name}: {va:#x} is not a byte load from +{old:#x}")
        b.patch_bytes(va + doff, new.to_bytes(4, "little"), expected_old=old.to_bytes(4, "little"),
                      desc=f"P03 {name}: nation +{old:#x} -> display +{new:#x}")
