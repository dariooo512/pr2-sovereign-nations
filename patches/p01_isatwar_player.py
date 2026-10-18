"""P01 -- null-safe CNation::IsAtWar backed by a player-nation relations table.

Why (the private feasibility study E3/E4, research/hostility_map.md):
  * A town whose nation byte is 5 has no CNation. Code such as the AI route-cost
    function 0x63B840 fetches g_nations[town nation] (0 for >= 4) and calls
    IsAtWar on it -> null dereference at 0x5BA0AB (reproduced in-game 2026-10-11).
  * IsAtWar(other >= 4) always answers "war", so the powers can never be at
    peace with the player nation.

The stub at the head of IsAtWar (0x5BA0A0, thiscall, ret 4) adds two cases and
otherwise runs the original code:
  this == NULL   -> source is the player nation: player_rel[other] for powers,
                    war vs pirates (4), peace vs itself (5)
  other == 5     -> a power looks at the player nation: player_rel[this->index]
                    (power index byte at CNation+0x18, set by the ctor 0x5BBD39)
player_rel is 4 bytes (England, Frankreich, Holland, Spanien): 1 = war, 0 = peace.
"""
import struct

ISATWAR = 0x5BA0A0
ISATWAR_RESUME = 0x5BA0A6          # the original `jae 0x5ba0ba` after the displaced pair
DEFAULT_REL = bytes([0, 0, 0, 0])  # peace with all four powers


def stub(va, rel):
    def rel8(frm_next, to):
        d = to - frm_next
        assert -128 <= d <= 127
        return struct.pack("<b", d)
    code = bytearray()
    code += b"\x85\xC9"                                  # 00 test ecx, ecx
    code += b"\x74" + rel8(0x04, 0x2A)                   # 02 jz player_src
    code += b"\x8A\x44\x24\x04"                          # 04 mov al, [esp+4]
    code += b"\x3C\x05"                                  # 08 cmp al, 5
    code += b"\x74" + rel8(0x0C, 0x17)                   # 0A je power_vs_player
    code += b"\x8A\x44\x24\x04"                          # 0C mov al, [esp+4]   (displaced)
    code += b"\x3C\x04"                                  # 10 cmp al, 4         (displaced)
    code += b"\xE9" + struct.pack("<i", ISATWAR_RESUME - (va + 0x17))  # 12 jmp back
    # power_vs_player (0x17)
    code += b"\x0F\xB6\x41\x18"                          # 17 movzx eax, byte [ecx+0x18]
    code += b"\x83\xF8\x04"                              # 1B cmp eax, 4
    code += b"\x73" + rel8(0x20, 0x43)                   # 1E jae war
    code += b"\x0F\xB6\x80" + struct.pack("<I", rel)     # 20 movzx eax, byte [eax+rel]
    code += b"\xC2\x04\x00"                              # 27 ret 4
    # player_src (0x2A)
    code += b"\x0F\xB6\x44\x24\x04"                      # 2A movzx eax, byte [esp+4]
    code += b"\x83\xF8\x04"                              # 2F cmp eax, 4
    code += b"\x73" + rel8(0x34, 0x3E)                   # 32 jae notpower
    code += b"\x0F\xB6\x80" + struct.pack("<I", rel)     # 34 movzx eax, byte [eax+rel]
    code += b"\xC2\x04\x00"                              # 3B ret 4
    # notpower (0x3E)
    code += b"\x83\xF8\x05"                              # 3E cmp eax, 5
    code += b"\x74" + rel8(0x43, 0x4B)                   # 41 je peace
    # war (0x43)
    code += b"\xB8\x01\x00\x00\x00"                      # 43 mov eax, 1
    code += b"\xC2\x04\x00"                              # 48 ret 4
    # peace (0x4B)
    code += b"\x31\xC0"                                  # 4B xor eax, eax
    code += b"\xC2\x04\x00"                              # 4D ret 4
    assert len(code) == 0x50, hex(len(code))
    return bytes(code)


def apply(b):
    b.place("player_rel", DEFAULT_REL, align=4,
            desc="player-nation relations with powers 0..3 (1=war, 0=peace)")
    b.place("isatwar_hook", lambda va: stub(va, b.va_of("player_rel")), size=0x50,
            desc="null-safe IsAtWar + player-nation relations")
    b.detour(ISATWAR, ["mov al, byte ptr [esp + 4]", "cmp al, 4"], target="isatwar_hook",
             desc="CNation::IsAtWar -> isatwar_hook")
