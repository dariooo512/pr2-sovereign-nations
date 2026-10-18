"""P02 -- a failed UI image lookup returns false instead of success with a null handle.

Spec: FND-01 / TER-01 (a nation-5 town must be displayable without crashing).
Source: research/userflag.md, fix "P1".

Why (the private feasibility study E3 crash (a), reproduced in-game 2026-10-11):
  * The nation-icon pointer table 0x6E12EC has six slots; slot 5 (SPIELER_NATION)
    is the sentinel string '-userflag-' (0x689970), which only the CFlag setter
    0x4C34A0 understands (it swaps in Run\\0.bmp).
  * Three UI sites (town top bar 0x4A63CA, town list 0x4B7D00, selection panel
    0x4860BA) index that table with `nation % 6` whenever the town lacks the
    player-town bit (CStadt+0x40 bit 22). A nation-5 town without that bit sends
    the raw '-userflag-' to the other widget setter 0x4C1CD0.
  * 0x4C1CD0 calls the loader 0x4C13B0(name, &handle). arc_CreateMemMapped
    (0x4C1407) fails for '-userflag-', and the not-found branch
    `0x4C1411 je 0x4C14EB` only caches the name at this+0xF8 and returns al=1
    with the handle still null. 0x4C1CD0 then does `0x4C1D9C mov ecx,[ebp-0x14]`
    (null) and `0x4C1D9F mov eax,[ecx]` -> access violation, within one frame
    of a nation-5 town being on screen.

Fix (6 bytes, rel32 of one jcc):
  0x4C1411  0F 84 D4 00 00 00  je 0x4C14EB   ->   0F 84 0E 01 00 00  je 0x4C1525

Re-verified by disassembly (asserted again in apply() before patching):
  * 0x4C1525 is the existing return-false tail of 0x4C13B0, today reached only as
    the catch continuation (the funclet at 0x4C151F does `mov eax,0x4C1525; ret`;
    no direct branch targets it):
        mov ecx,[ebp-0xC]; pop edi; pop esi; xor al,al; mov fs:[0],ecx;
        pop ebx; mov esp,ebp; pop ebp; ret 8
    It is the same epilogue as the success tail 0x4C1504 except `xor al,al`.
  * Stack: the prologue saves esp to [ebp-0x10] right after `push edi`
    (0x4C13D0). At 0x4C1411 the only pushes since were the four args of the cdecl
    call 0x4C1407, popped by `add esp,0x10` (0x4C140C); the two vtable calls
    before take no stack args. So esp == [ebp-0x10], exactly what the EH runtime
    restores before resuming at 0x4C1525. The pops are balanced.
  * EH: the tail restores fs:[0] from [ebp-0xC], so the EH state byte at
    [ebp-4] (1 here) does not matter. The original not-found path runs no
    destructor either (it just sets the state to -1), so nothing is skipped.
  * The only caller of 0x4C13B0 is 0x4C1D0C in 0x4C1CD0 (whole-.text rel32 scan):
        0x4C1D0C call 0x4C13B0; test al,al; je 0x4C1E6C
    0x4C1E6C releases [ebp-0x14] if non-null (`cmp ecx,ebx` with ebx=0;
    ebx is callee-saved by 0x4C13B0) and returns al=0. The widget keeps its old
    image (or none); its draw 0x4C1570 null-checks the image at +0x9C.
Side effect: on failure the name cache this+0xF8 is no longer updated. Callers
compare names before reloading, so a missing image is simply retried later.
Vanilla behaviour is otherwise unchanged: the patched branch was always followed
by a guaranteed null dereference.
"""
import sys

LOADER = 0x4C13B0
NOT_FOUND_JCC = 0x4C1411
OLD = bytes.fromhex("0f84d4000000")      # je 0x4c14eb
NEW = bytes.fromhex("0f840e010000")      # je 0x4c1525
RET_FALSE_TAIL = 0x4C1525

CHECKS = [
    (0x4C1407, ["call 0x64c7a4", "add esp, 0x10", "test eax, eax", "je 0x4c14eb"]),
    (0x4C14EB, ["mov ecx, dword ptr [ebp - 0x24]", "push ebx", "add ecx, 0xf8",
                "mov dword ptr [ebp - 4], 0xffffffff", "call dword ptr [0x67fa40]",
                "mov al, 1"]),
    (RET_FALSE_TAIL, ["mov ecx, dword ptr [ebp - 0xc]", "pop edi", "pop esi", "xor al, al",
                      "mov dword ptr fs:[0], ecx", "pop ebx", "mov esp, ebp", "pop ebp", "ret 8"]),
    (0x4C13C8, ["sub esp, 0x20", "push ebx", "push esi", "xor eax, eax", "push edi",
                "mov dword ptr [ebp - 0x10], esp"]),
    (0x4C1D0C, ["call 0x4c13b0", "test al, al", "je 0x4c1e6c"]),
    (0x4C1E6C, ["mov ecx, dword ptr [ebp - 0x14]", "cmp ecx, ebx", "mov byte ptr [ebp - 4], 0",
                "je 0x4c1e7c", "mov eax, dword ptr [ecx]", "call dword ptr [eax + 8]",
                "mov ecx, dword ptr [ebp - 0xc]", "pop edi", "pop esi", "xor al, al"]),
]


def _expect(b, va, want):
    err = sys.modules[type(b).__module__].PatchError
    got = [f"{i.mnemonic} {i.op_str}".strip() for i in b.decode(va, 64)][:len(want)]
    if got != want:
        raise err(f"P02 check at {va:#x}: expected {want}, found {got}")


def apply(b):
    for va, want in CHECKS:
        _expect(b, va, want)
    b.patch_bytes(NOT_FOUND_JCC, NEW, expected_old=OLD,
                  desc="0x4C13B0 not-found -> return-false tail 0x4C1525 (userflag null-handle crash)")
