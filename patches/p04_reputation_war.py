"""P04 -- a power at war with the player nation is hostile to the human player.

Depends on P01 (label "player_rel": byte[4], power 0..3 = England, Frankreich,
Holland, Spanien; 1 = war with the player nation, 0 = peace). Apply after P01.

Why (research/hostility_map.md section 2): a power treats the player as hostile
only through the player's reputation with it (rep < 25). P01's table changes
IsAtWar but not reputation, so without P04 a declared war leaves trade, harbour,
dialogs and the military "hunt the player" bit (attack mask 0x20) all friendly.

Targets [STATIC, disassembled from the pinned base exe]:

  GetReputation 0x5D2AC0  (thiscall: ecx = CPlayer*, one stack dword whose LOW
    BYTE is the power P, callee pops it: `ret 4`).
      5D2AC0 8A442404   mov al,[esp+4]
      5D2AC4 3C04       cmp al,4
      5D2AC6 7210       jb 5D2AD8
      ; P>=4: eax = (P==5) ? 100 : 0          (ecx is NOT dereferenced)
      5D2AD8 movzx edx,al ; eax = rep[P] = [ecx+edx*4+54h] (16.16 fixed)
      ; returns movsx(byte (rep>>16)) in eax: a plain int 0..100
    GetReputationLevel 0x5D2C10 (55 callers) calls it, so it inherits the patch.

  IsRepAtLeast25 0x5D2D90 (thiscall, same argument, `ret 4`, returns BOOL in AL
    only; the upper bytes of eax are whatever was there):
      5D2D90 66833900   cmp word [ecx],0     ; non-human player ...
      5D2D94 751A       jne 5D2DB0           ; ... always TRUE
      5D2D96 8A442404   mov al,[esp+4]
      5D2D9A 3C04       cmp al,4
      5D2D9C 7312       jae 5D2DB0           ; P>=4 -> TRUE
      5D2D9E movzx eax,al ; cmp [ecx+eax*4+54h],190000h ; jge -> TRUE
      5D2DAB 32C0 xor al,al ; ret 4          ; FALSE

Human player [STATIC]: word CPlayer+0 is the player kind. The CPlayer ctor
0x5A9E70 writes 0 (0x5A9EE4 `mov [esi],bx`, bx=0); the AI-trader factory
writes 3 (0x5A809E `mov word [esi],3`); the human creation path 0x5A86C0
leaves 0 and stores the handle in 0x701ED0 (the "local player" handle read by
0x402940). Vanilla itself uses `word [player]==0` as "human" in
IsRepAtLeast25, AddReputation 0x5D45F7, SubReputation 0x5D4846 and
letter-of-marque expiry 0x5D44C6. The getters DO serve AI traders: e.g.
0x5AABD7/0x5AACA7 pass the convoy owner's CPlayer (0x41C800 -> 0x5C29E0), and
0x5AB51A..0x6397B9 pass arbitrary CPlayer pointers. So P04 overrides only when
word [ecx] == 0, exactly like vanilla's own human test.

D1 detour at 0x5D2AC0 (displaced `mov al,[esp+4]; cmp al,4`, both PIC):
    push edx
    movzx edx, byte [esp+8]      ; P (the arg's low byte; arg is at +8 after push)
    cmp edx, 4
    jae orig                     ; P>=4: vanilla, and ecx is never touched
    cmp word [ecx], 0
    jne orig                     ; AI player: vanilla
    cmp byte [edx+player_rel], 0
    pop edx                      ; (pop leaves flags alone)
    je vanilla                   ; peace: vanilla
    xor eax, eax                 ; war: reputation 0 -> level 0 = hostile
    ret 4
  orig:    pop edx
  vanilla: mov al,[esp+4] ; cmp al,4 ; jmp 0x5D2AC6
Every vanilla path restores edx and leaves eax/ecx/flags/stack untouched before
the displaced instructions, so behaviour is bit-for-bit vanilla.

D2 detour at 0x5D2D96, NOT at 0x5D2D90: the entry's `jne 5D2DB0` is rel8, which
pe_patch refuses to displace. One instruction pair later the bytes are again
`mov al,[esp+4]; cmp al,4` (6 bytes, PIC), and vanilla's own human test
(0x5D2D90..0x5D2D95) has already run, so no displaced branch needs re-encoding.
No branch anywhere in .text lands on 0x5D2D97..0x5D2D9B (checked by test_p04).
    push edx
    movzx edx, byte [esp+8]
    cmp edx, 4
    jae orig
    cmp byte [edx+player_rel], 0
    pop edx
    je vanilla
    xor eax, eax                 ; war: FALSE (rep < 25)
    ret 4
  orig:    pop edx
  vanilla: mov al,[esp+4] ; cmp al,4 ; jmp 0x5D2D9C

Any non-zero player_rel byte counts as war (P01 returns the byte as a BOOL too).
"""
import struct

GET_REP = 0x5D2AC0
IS_REP25_MID = 0x5D2D96
DISPLACED = ["mov al, byte ptr [esp + 4]", "cmp al, 4"]


def _rel8(at_next, to):
    d = to - at_next
    assert -128 <= d <= 127, (at_next, to)
    return struct.pack("<b", d)


def getrep_prologue(rel):
    """D1 prologue; falls through into the relocated displaced instructions."""
    c = bytearray()
    c += b"\x52"                                    # 00 push edx
    c += b"\x0F\xB6\x54\x24\x08"                    # 01 movzx edx, byte [esp+8]
    c += b"\x83\xFA\x04"                            # 06 cmp edx, 4
    c += b"\x73" + _rel8(0x0B, 0x20)                # 09 jae orig
    c += b"\x66\x83\x39\x00"                        # 0B cmp word [ecx], 0
    c += b"\x75" + _rel8(0x11, 0x20)                # 0F jne orig
    c += b"\x80\xBA" + struct.pack("<I", rel) + b"\x00"  # 11 cmp byte [edx+rel], 0
    c += b"\x5A"                                    # 18 pop edx
    c += b"\x74" + _rel8(0x1B, 0x21)                # 19 je vanilla
    c += b"\x31\xC0"                                # 1B xor eax, eax
    c += b"\xC2\x04\x00"                            # 1D ret 4
    c += b"\x5A"                                    # 20 orig: pop edx
    assert len(c) == 0x21, hex(len(c))              # 21 vanilla: displaced insns
    return bytes(c)


def isrep25_prologue(rel):
    """D2 prologue (human check already done by vanilla at 0x5D2D90)."""
    c = bytearray()
    c += b"\x52"                                    # 00 push edx
    c += b"\x0F\xB6\x54\x24\x08"                    # 01 movzx edx, byte [esp+8]
    c += b"\x83\xFA\x04"                            # 06 cmp edx, 4
    c += b"\x73" + _rel8(0x0B, 0x1A)                # 09 jae orig
    c += b"\x80\xBA" + struct.pack("<I", rel) + b"\x00"  # 0B cmp byte [edx+rel], 0
    c += b"\x5A"                                    # 12 pop edx
    c += b"\x74" + _rel8(0x15, 0x1B)                # 13 je vanilla
    c += b"\x31\xC0"                                # 15 xor eax, eax
    c += b"\xC2\x04\x00"                            # 17 ret 4
    c += b"\x5A"                                    # 1A orig: pop edx
    assert len(c) == 0x1B, hex(len(c))              # 1B vanilla: displaced insns
    return bytes(c)


def apply(b):
    rel = b.va_of("player_rel")                     # placed by P01
    d1 = b.detour(GET_REP, DISPLACED, target="getrep_hook",
                  desc="CPlayer::GetReputation -> getrep_hook (war => 0)")
    b.place_trampoline("getrep_hook", d1, prologue=getrep_prologue(rel),
                       desc="GetReputation: player_rel[P]=1 and human => 0")
    d2 = b.detour(IS_REP25_MID, DISPLACED, target="isrep25_hook",
                  desc="CPlayer::IsRepAtLeast25 (after human test) -> isrep25_hook")
    b.place_trampoline("isrep25_hook", d2, prologue=isrep25_prologue(rel),
                       desc="IsRepAtLeast25: player_rel[P]=1 => FALSE")
