"""P05 -- a nation-5 town is safe in the 4 functions that index g_nations by its byte.

Spec: FND-01 / TER-01 (a town owned by the player nation must run the daily
economy, receive convoys, be annexable and produce letters without crashing).
Source: research/null_nation_census.md section 0 (12 TOWN-indexed sites in 4
functions) and research/nation5_index_safety.md (display byte). Apply AFTER
P01..P04; no range overlaps theirs (pe_patch refuses overlaps).

g_nations = dword[4] at 0x702B14. Every lookup below is the vanilla guarded
form `movzx r,[town+0x390]; cmp r,4; jae null; mov r,[r*4+0x702B14]`, so a
town byte >= 4 yields NULL, which the code then dereferences.

RUNTIME: Margarita (Gouverneur=1) set to nation 5 crashed in the daily economy
tick at 0x5C86BD `mov ebp,[edx+0x20]` (edx = NULL). STATIC below = capstone
text of the pinned base exe, re-checked by apply() before anything is patched.

Display-byte invariant (used by fixes 2 and 4, the same one P03 relies on).
All byte stores to the display byte CStadtLager+0x359 (= CStadt+0x391) and the
nation byte +0x358 found by a .text scan for the displacements:
    0x5C9EF7/0x5C9EFD  ctor:      nation = display = 0xFF
    0x5C9E54/0x5C9E5A  AddToNation(force=0): nation = display = bl
    0x5C9E1E           AddToNation: nation = 0xFF, overwritten by 0x5C9E54
    0x5C9DD1/0x5C9DD7  AddToNation(n, force=1), only if the town byte is >= 4
                       already (0x5C9DB1): display = n if n < 4 else n & 3
                       (always 0..3), nation = 5
    0x5C9AF8, 0x5C9B1B/0x5C9B39  load: raw saved bytes; saves < 0x3F4 use
                       display = nation & 3
(0x59FF92 / 0x5A212F `mov dword [esi+0x358]` are widget-pointer stores in a UI
class, +0x30C..+0x360, not CStadtLager.) So every nation 0..3 town has
display == nation, and every nation-5 town has display 0..3 (option C's flip
also writes the old power there). Reading +0x391 instead of +0x390 is
therefore identical for powers' towns and gives a nation-5 town its host power.

------------------------------------------------------------------------------
Fix 1  0x5C8650  CStadtLager per-good share (goods 12..18, admin seats only)
------------------------------------------------------------------------------
    5C868F xor eax,eax                   ; return value 0 from here on
    5C86A5 movzx ecx,byte [esi+0x358]    ; <- detour (7 bytes, whole insn)
    5C86AC cmp ecx,4 / 5C86AF jae 5C86BA / mov edx,[ecx*4+702B14] ... xor edx,edx
    5C86BD mov ebp,[edx+0x20]            ; NULL deref (observed crash)
    ... 5C86E1 / 5C8702 re-look-up the same ecx (also NULL)
    5C8765 pop ebx; pop esi; add esp,0x10; ret 4   ; vanilla "return 0" exit
  Stub: movzx ecx,[esi+0x358]; cmp ecx,4; jae 0x5C8765; jmp 0x5C86AC.
  Why this form: the `jae` at 0x5C86AF is rel8 and cannot reach 0x5C8765, and
  pe_patch will not displace a rel8 branch, so the detour takes exactly the
  one 7-byte load. Both paths into 0x5C86A5 (0x5C8697 jne, 0x5C869F fall-
  through) have eax = 0 from 0x5C868F, and `push ebp` (0x5C86BC) has not run,
  so 0x5C8765 is reached with the stack and eax it gets on vanilla's own
  "CNation+0x20 == 0" exit (0x5C86C3 je 0x5C8765): it returns 0.
  nation < 4: the stub re-executes the load and resumes at 0x5C86AC, which
  redoes `cmp ecx,4` -> identical registers, flags and memory.
  nation >= 4: share = 0 (the town takes no share of a power's demand for
  goods 12..18). Covers all three derefs 0x5C86BD, 0x5C86E1, 0x5C8702.

------------------------------------------------------------------------------
Fix 2  0x5B40D0  convoy at its town (0x635C40 -> ebp = CStadt*), 4 loads
------------------------------------------------------------------------------
  ebp is set at 0x5B4107 and not written again before 0x5B4405 (all 4 sites
  are in between). Each load's register is used ONLY as the g_nations index:
    A1 0x5B41B0 movzx edx,[ebp+0x390] -> 5B41C7 cmp [edx+0x20],0
    A2 0x5B41DA movzx ecx,[ebp+0x390] -> 5B41F1 mov ecx,[ecx+0x20]
       goods 12..15: amount = convoy-power demand * town pop / town-power
       admin population (CNation+0x20). Display byte: divide by the host
       power's admin population, i.e. what the town got before it changed
       hands -> semantically fine. (A2 is only reached through A1.)
    B1 0x5B42EB movzx eax,[ebp+0x390] -> 5B4331 lea esi,[eax+0xC4]; rep movsd
    B2 0x5B438D movzx eax,[ebp+0x390] -> 5B43AA mov ecx,[eax+ecx*4+0xC4]
       goods 0..11 (NOT 12..15 as the census table says): a good is listed for
       0x5B2D80 when the town can take it, it is not masked (+0x38C), and the
       owner power's CNation+0xC4[g] (sum of 0x5CACA0(g) over its towns,
       stats fn 0x5BA5A0) is <= 0 (`15*v <= v`, v copied from the same
       array). Display byte: the host power's aggregate -> semantically fine.
  Patch: 4 displacement changes 0x390 -> 0x391 (1 byte each, as in P03).
  nation < 4: display == nation (invariant above) -> identical.
  Not covered (census: latent, CONV-indexed): 0x5B411B/0x5B4144 copy the
  CONVOY nation's (+0xB8) CNation+0x24; only a convoy owned by nation >= 4
  reaches it.

------------------------------------------------------------------------------
Fix 3  0x5BC310  CNation(new owner)::annex town; old owner = town byte
------------------------------------------------------------------------------
  The census claim holds: 0x5BC476 cl = [edi+0x390] (edi = town), kept in
  [esp+0x28], used at four sites. Two different treatments:
  3a viceroy branch (town+0x44 & 0x2000), 0x5BC49E..0x5BC57D: collects the
     OLD owner's other admin-seat towns (old CNation+0x14 town list) as
     candidates to receive the viceroy seat (moved at 0x5BC5D8..), and aborts
     the annexation when there are none (0x5BC57D -> 0x5BCB6F, returns al=0).
     Derefs 0x5BC4B5 and 0x5BC4D4 (index re-read from [esp+0x3C] each loop).
     Detour 0x5BC49E (`movzx eax,cl; cmp eax,4`, 6 bytes):
         movzx eax,cl; cmp eax,4; jb back
         movzx eax,byte [edi+0x391]; cmp eax,4; jae 0x5BCB6F
       back: jmp 0x5BC4A4            ; mov [esp+0x3C],eax; jae 0x5BC4B3
     -> a nation-5 viceroy town's seat moves to one of its HOST power's admin
     towns (the power it was taken from); no candidates -> refused, exactly
     vanilla's rule for that power. display >= 4 (never produced for a 5-town)
     -> vanilla's own abort exit 0x5BCB6F (same stack as the `je 0x5BCB6F` at
     0x5BC470; only locals were written in between). For nation < 4 the
     flags reaching 0x5BC4A4 come from the same `cmp eax,4` -> identical.
  3b old-owner bookkeeping: 0x5BC59D `inc word [old+0x16C]` (annex counter)
     and 0x5BC5D1 `push 1; call 0x5BBB20` (old->recompute military budget
     +0x168 from that counter, then 0x5F1B30(old,0)). For a player-nation
     town there is no CNation to update; crediting the host would make it
     react to a town it did not lose, so these are SKIPPED, not redirected:
       0x5BC59D trampoline: test eax,eax; jz skip; inc word [eax+0x16C]; skip: jmp 0x5BC5A4
       0x5BC5D1 trampoline: test ecx,ecx; jz skip; push 1; call 0x5BBB20; skip: jmp 0x5BC5D8
     The pointer is NULL exactly when the old owner >= 4 (guarded lookups at
     0x5BC58D / 0x5BC5C1). Non-NULL (nation < 4): the original instructions
     run unchanged; the extra `test` only sets flags that the next
     instructions overwrite (0x5BC5A8 xor, 0x5BC5DB test). Skip path: stack
     balanced (push 1 is skipped with the call, 0x5BBB20 is `ret 4`); eax/
     ecx/edx are caller-saved after a call, 0x5BC5D8 reloads eax.
  The town transfer itself (0x5C9DA0 AddToNation(new,0)) is null-safe for an
  old owner >= 4 (0x5C9E1C test edi,edi). [esp+0x28] is otherwise only
  compared (0x5BC98E vs an event byte).

------------------------------------------------------------------------------
Fix 4  0x5E74B0  CLetterBuildingLost::Create
------------------------------------------------------------------------------
    5E75C7 movzx eax,byte [eax+0x390]  -> ... 5E75E8 call 0x5BB0F0
  0x5BB0F0 counts the power's admin-seat towns (mov edi,[ecx+0x14] derefs
  this); the letter stores (count == 0) at [letter+0x26]. Patch: displacement
  0x390 -> 0x391 (eax = town from [esp+0xC]; used only as the index). Identical
  for nation < 4 (invariant); a nation-5 town reports its host's count
  (cosmetic letter flag). The raw read at 0x5E7630 is a compare, left alone.

------------------------------------------------------------------------------
Optional hardening H1  0x5BC100 null `this`
------------------------------------------------------------------------------
  The event thunk 0x5EEA50 does `xor eax,eax; mov ecx,eax; call 0x5BC100`
  (0x5EEA6A..0x5EEA6E) when its nation byte is >= 4. 0x5BC100 is thiscall,
  no stack args, `ret` (0x5BC2F0 / 0x5BC306), and dereferences this at
  0x5BC19E (`mov edx,[esi+0x154]`). It calls no other CNation method on this
  (only 0x5F8020/0x5F8060 on 0x6E4D4C), so it is the only method reachable
  that way. Entry detour (displaces `mov eax,fs:[0]`, 6 bytes):
      test ecx,ecx; jnz go; xor eax,eax; ret; go: mov eax,fs:[0]; jmp 0x5BC106
  Non-NULL: the flags set by `test` are overwritten (0x5BC115 sub) before use.
  NULL: returns 0 instead of crashing; the thunk ignores the result (xor eax,eax).
  Skipped: the other CNation methods in the census list (no explicit NULL
  caller; only latent NPC/event/convoy-indexed paths reach them).
"""
import struct
import sys

import capstone

G_NATIONS = 0x702B14

# ---- fix 1 -----------------------------------------------------------------
ECON_LOAD = 0x5C86A5
ECON_RESUME = 0x5C86AC
ECON_RET0 = 0x5C8765

# ---- fix 2 / fix 4: (name, insn_va, disp_offset, old, new) ------------------
DISP_SITES = [
    ("C-A1 convoy goods 12..15 pop share", 0x5B41B0, 3, 0x390, 0x391),
    ("C-A2 convoy goods 12..15 pop share", 0x5B41DA, 3, 0x390, 0x391),
    ("C-B1 convoy goods 0..11 nation stock", 0x5B42EB, 3, 0x390, 0x391),
    ("C-B2 convoy goods 0..11 nation stock", 0x5B438D, 3, 0x390, 0x391),
    ("L1 building-lost letter admin count", 0x5E75C7, 3, 0x390, 0x391),
]

# ---- fix 3 -----------------------------------------------------------------
ANNEX_VICEROY = 0x5BC49E
ANNEX_VICEROY_RESUME = 0x5BC4A4
ANNEX_ABORT = 0x5BCB6F
ANNEX_COUNT = 0x5BC59D
ANNEX_RECOUNT = 0x5BC5D1

# ---- H1 --------------------------------------------------------------------
NULLTHIS_FN = 0x5BC100

# Exact capstone text the patches rely on (va -> instructions from va on).
CHECKS = [
    # fix 1: gate, eax=0, guarded lookup + deref, re-lookups, return-0 tail
    (0x5C8656, ["mov eax, dword ptr [esi + 0xc]", "mov ecx, 1", "test ecx, eax",
                "jne 0x5c866b"]),
    (0x5C868F, ["xor eax, eax", "test cl, cl", "mov dword ptr [esp + 0xc], eax",
                "jne 0x5c86a5", "mov cl, byte ptr [esp + 0x1c]", "test cl, cl",
                "je 0x5c8765", "movzx ecx, byte ptr [esi + 0x358]", "cmp ecx, 4",
                "jae 0x5c86ba", "mov edx, dword ptr [ecx*4 + 0x702b14]", "jmp 0x5c86bc",
                "xor edx, edx", "push ebp", "mov ebp, dword ptr [edx + 0x20]",
                "test ebp, ebp", "pop ebp", "je 0x5c8765", "cmp ecx, 4", "jae 0x5c86d7",
                "mov eax, dword ptr [ecx*4 + 0x702b14]"]),
    (0x5C86F2, ["cmp ecx, 4", "jae 0x5c8700", "mov ecx, dword ptr [ecx*4 + 0x702b14]",
                "jmp 0x5c8702", "xor ecx, ecx", "mov ecx, dword ptr [ecx + 0x20]"]),
    (ECON_RET0, ["pop ebx", "pop esi", "add esp, 0x10", "ret 4"]),
    # fix 2: ebp = town; each load feeds only the guarded lookup
    (0x5B4102, ["call 0x635c40", "mov ebp, eax"]),
    (0x5B41A2, ["mov ax, word ptr [ebp + 0x38a]", "test ax, ax", "mov esi, edx",
                "je 0x5b4202", "movzx edx, byte ptr [ebp + 0x390]", "cmp edx, 4",
                "jae 0x5b41c5", "mov edx, dword ptr [edx*4 + 0x702b14]", "jmp 0x5b41c7",
                "xor edx, edx", "cmp dword ptr [edx + 0x20], 0", "je 0x5b4202"]),
    (0x5B41DA, ["movzx ecx, byte ptr [ebp + 0x390]", "cmp ecx, 4", "jae 0x5b41ef",
                "mov ecx, dword ptr [ecx*4 + 0x702b14]", "jmp 0x5b41f1", "xor ecx, ecx",
                "mov ecx, dword ptr [ecx + 0x20]"]),
    (0x5B42EB, ["movzx eax, byte ptr [ebp + 0x390]", "cmp eax, 4",
                "mov dword ptr [esp + 0x9c], 0", "jae 0x5b432f",
                "mov eax, dword ptr [eax*4 + 0x702b14]", "jmp 0x5b4331"]),
    (0x5B432F, ["xor eax, eax", "lea esi, [eax + 0xc4]", "mov ecx, 0x14",
                "lea edi, [esp + 0x40]", "rep movsd dword ptr es:[edi], dword ptr [esi]"]),
    (0x5B438D, ["movzx eax, byte ptr [ebp + 0x390]", "cmp eax, 4",
                "lea edx, [esp + ecx*4 + 0x40]", "jae 0x5b43a6",
                "mov eax, dword ptr [eax*4 + 0x702b14]", "jmp 0x5b43a8", "xor eax, eax",
                "mov edx, dword ptr [edx]", "mov ecx, dword ptr [eax + ecx*4 + 0xc4]"]),
    (0x5B4405, ["mov ebp, dword ptr [esp + 0x10]"]),
    # fix 3: old owner byte, viceroy branch, bookkeeping, abort tail
    (0x5BC467, ["mov ecx, ebx", "call 0x5bb190", "test al, al", "je 0x5bcb6f",
                "mov cl, byte ptr [edi + 0x390]", "mov al, 0xff",
                "mov byte ptr [esp + 0x20], al", "mov byte ptr [esp + 0x78], al",
                "mov eax, dword ptr [edi + 0x44]", "test ah, 0x20",
                "mov byte ptr [esp + 0x28], cl", "mov dword ptr [esp + 0x24], 0x1ffff",
                "je 0x5bc58a", "movzx eax, cl", "cmp eax, 4",
                "mov dword ptr [esp + 0x3c], eax", "jae 0x5bc4b3",
                "mov eax, dword ptr [eax*4 + 0x702b14]", "jmp 0x5bc4b5", "xor eax, eax",
                "mov eax, dword ptr [eax + 0x14]", "mov edi, dword ptr [eax]"]),
    (0x5BC4C0, ["mov eax, dword ptr [esp + 0x3c]", "cmp eax, 4", "jae 0x5bc4d2",
                "mov eax, dword ptr [eax*4 + 0x702b14]", "jmp 0x5bc4d4", "xor eax, eax",
                "cmp dword ptr [eax + 0x14], edi"]),
    (0x5BC57D, ["cmp dword ptr [ebp], ebp", "je 0x5bcb6f", "mov cl, byte ptr [esp + 0x28]",
                "movzx edi, cl", "cmp edi, 4", "jae 0x5bc59b",
                "mov eax, dword ptr [edi*4 + 0x702b14]", "jmp 0x5bc59d", "xor eax, eax",
                "inc word ptr [eax + 0x16c]", "mov ebp, dword ptr [esp + 0x18]",
                "xor eax, eax", "mov al, byte ptr [ebx + 0x18]", "push 0",
                "lea esi, [ebp + 0x38]", "mov ecx, esi", "push eax", "call 0x5c9da0",
                "mov ecx, esi", "call 0x624f50", "cmp edi, 4", "jae 0x5bc5cf",
                "mov ecx, dword ptr [edi*4 + 0x702b14]", "jmp 0x5bc5d1", "xor ecx, ecx",
                "push 1", "call 0x5bbb20", "mov eax, dword ptr [ebp + 0x44]", "test ah, 0x20"]),
    (0x5BBB20, ["push ecx", "push esi", "mov esi, ecx", "mov ecx, dword ptr [esi + 8]"]),
    (0x5BBC4D, ["pop edi", "pop esi", "pop ecx", "ret 4"]),
    (ANNEX_ABORT, ["lea ecx, [esp + 0x14]", "mov dword ptr [esp + 0x70], 0xffffffff",
                   "call 0x5a93e0", "mov ecx, dword ptr [esp + 0x68]", "pop edi", "pop esi",
                   "pop ebp", "xor al, al", "mov dword ptr fs:[0], ecx", "pop ebx",
                   "add esp, 0x64", "ret 4"]),
    # fix 4
    (0x5E75BF, ["mov eax, dword ptr [esp + 0xc]", "mov word ptr [edi + 0x24], dx",
                "movzx eax, byte ptr [eax + 0x390]", "cmp eax, 4",
                "mov dword ptr [esp + 0x24], 0xffffffff", "jae 0x5e75e4",
                "mov eax, dword ptr [eax*4 + 0x702b14]", "jmp 0x5e75e6", "xor eax, eax",
                "mov ecx, eax", "call 0x5bb0f0"]),
    (0x5BB0F0, ["push ecx", "push esi", "push edi", "mov edi, dword ptr [ecx + 0x14]"]),
    # display-byte invariant (writers of +0x358/+0x359)
    (0x5C9DC2, ["movzx eax, al", "and eax, 0x80000003", "jns 0x5c9dd1", "dec eax",
                "or eax, 0xfffffffc", "inc eax", "mov byte ptr [esi + 0x359], al",
                "mov byte ptr [esi + 0x358], 5"]),
    (0x5C9DB1, ["cmp byte ptr [esi + 0x358], 4", "jb 0x5c9dde"]),
    (0x5C9E54, ["mov byte ptr [esi + 0x358], bl", "mov byte ptr [esi + 0x359], bl"]),
    (0x5C9EF5, ["mov al, 0xff", "mov byte ptr [esi + 0x358], al",
                "mov byte ptr [esi + 0x359], al"]),
    (0x5C9B19, ["mov dl, byte ptr [ecx]", "mov byte ptr [ebp + 0x359], dl"]),
    (0x5C9B26, ["movzx eax, byte ptr [ebp + 0x358]", "and eax, 0x80000003", "jns 0x5c9b39",
                "dec eax", "or eax, 0xfffffffc", "inc eax", "mov byte ptr [ebp + 0x359], al"]),
    # H1
    (0x5EEA6A, ["xor eax, eax", "mov ecx, eax", "call 0x5bc100", "xor eax, eax", "ret"]),
    (NULLTHIS_FN, ["mov eax, dword ptr fs:[0]", "push -1", "push 0x670418"]),
    (0x5BC19E, ["mov edx, dword ptr [esi + 0x154]"]),
    (0x5BC2EA, ["pop edi", "pop esi", "pop ebp", "add esp, 0x1c", "ret"]),
    (0x5BC302, ["pop ebp", "add esp, 0x1c", "ret"]),
]


def _rel8(at_next, to):
    d = to - at_next
    assert -128 <= d <= 127, (at_next, to)
    return struct.pack("<b", d)


def _rel32(at_next, to):
    return struct.pack("<i", to - at_next)


def econ_stub(va, displaced):
    """Fix 1: [displaced movzx] cmp ecx,4; jae ret0; jmp resume."""
    c = bytearray(displaced)                              # 00 movzx ecx,[esi+0x358]
    c += b"\x83\xF9\x04"                                  # 07 cmp ecx, 4
    c += b"\x0F\x83" + _rel32(va + 0x10, ECON_RET0)       # 0A jae 0x5C8765
    c += b"\xE9" + _rel32(va + 0x15, ECON_RESUME)         # 10 jmp 0x5C86AC
    assert len(c) == 0x15, hex(len(c))
    return bytes(c)


def viceroy_stub(va, displaced):
    """Fix 3a: nation<4 ? nation : display (abort if display>=4)."""
    c = bytearray(displaced)                              # 00 movzx eax,cl ; 03 cmp eax,4
    c += b"\x72" + _rel8(0x08, 0x18)                      # 06 jb back
    c += b"\x0F\xB6\x87\x91\x03\x00\x00"                  # 08 movzx eax, byte [edi+0x391]
    c += b"\x83\xF8\x04"                                  # 0F cmp eax, 4
    c += b"\x0F\x83" + _rel32(va + 0x18, ANNEX_ABORT)     # 12 jae 0x5BCB6F
    c += b"\xE9" + _rel32(va + 0x1D, ANNEX_VICEROY_RESUME)  # 18 back: jmp 0x5BC4A4
    assert len(c) == 0x1D, hex(len(c))
    return bytes(c)


SKIP_IF_NULL_EAX = b"\x85\xC0\x74\x07"                    # test eax,eax; jz +7 (over 7 bytes)
SKIP_IF_NULL_ECX = b"\x85\xC9\x74\x07"                    # test ecx,ecx; jz +7
NULLTHIS_PROLOGUE = b"\x85\xC9\x75\x03\x31\xC0\xC3"       # test ecx,ecx; jnz +3; xor eax,eax; ret


def _texts(b, va, n):
    return [f"{i.mnemonic} {i.op_str}".strip() for i in b.decode(va, 160)][:n]


def apply(b):
    err = sys.modules[type(b).__module__].PatchError
    for va, want in CHECKS:
        got = _texts(b, va, len(want))
        if got != want:
            raise err(f"P05 check at {va:#x}: expected {want}, found {got}")

    # fix 1
    d = b.detour(ECON_LOAD, ["movzx ecx, byte ptr [esi + 0x358]"], target="p05_econ_share",
                 desc="P05 fix1 0x5C8650 lager share: nation>=4 -> return 0 (0x5C8765)")
    b.place("p05_econ_share", lambda va, d=d: econ_stub(va, d.relocated(va)), size=0x15,
            desc="P05 fix1: town nation>=4 takes the return-0 exit")

    # fix 2 + fix 4
    for name, va, doff, old, new in DISP_SITES:
        insn = b.decode(va, 16)[0]
        src = insn.operands[1] if len(insn.operands) == 2 else None
        if insn.mnemonic != "movzx" or src is None or src.type != capstone.x86.X86_OP_MEM \
                or src.mem.disp != old or src.size != 1 or insn.size != 7:
            raise err(f"P05 {name}: {va:#x} is not a 7-byte movzx from +{old:#x}")
        b.patch_bytes(va + doff, new.to_bytes(4, "little"), expected_old=old.to_bytes(4, "little"),
                      desc=f"P05 {name}: town nation +{old:#x} -> display +{new:#x}")

    # fix 3a
    d = b.detour(ANNEX_VICEROY, ["movzx eax, cl", "cmp eax, 4"], target="p05_annex_viceroy",
                 desc="P05 fix3a 0x5BC310 viceroy candidates: nation>=4 -> display power")
    b.place("p05_annex_viceroy", lambda va, d=d: viceroy_stub(va, d.relocated(va)), size=0x1D,
            desc="P05 fix3a: old owner >= 4 -> display byte (abort if still >= 4)")
    # fix 3b
    d = b.detour(ANNEX_COUNT, ["inc word ptr [eax + 0x16c]"], target="p05_annex_count",
                 desc="P05 fix3b 0x5BC310 old-owner annex counter: skip if no CNation")
    b.place_trampoline("p05_annex_count", d, prologue=SKIP_IF_NULL_EAX,
                       desc="P05 fix3b: skip inc word [old+0x16C] for NULL old owner")
    d = b.detour(ANNEX_RECOUNT, ["push 1", "call 0x5bbb20"], target="p05_annex_recount",
                 desc="P05 fix3b 0x5BC310 old->0x5BBB20(1): skip if no CNation")
    b.place_trampoline("p05_annex_recount", d, prologue=SKIP_IF_NULL_ECX,
                       desc="P05 fix3b: skip old-owner 0x5BBB20 for NULL old owner")

    # H1
    d = b.detour(NULLTHIS_FN, ["mov eax, dword ptr fs:[0]"], target="p05_nullthis_5bc100",
                 desc="P05 H1 0x5BC100 null this (event thunk 0x5EEA50) -> return 0")
    b.place_trampoline("p05_nullthis_5bc100", d, prologue=NULLTHIS_PROLOGUE,
                       desc="P05 H1: CNation 0x5BC100 returns 0 for this == NULL")
