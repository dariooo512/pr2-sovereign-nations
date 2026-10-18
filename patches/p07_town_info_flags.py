"""P07 -- the town info dialog's four mini flags read the display nation byte.

Spec: TER-01 / UI (a nation-5 town's info dialog must not index past the
4-entry mini-flag table). Source: research/flags.md, PF1.

fn 0x4A3610 (town info dialog) loads the town's nation into ebp/[esp+0x10]:
  0x4A3DD8 movzx ebp, byte ptr [ebx+0x390]      raw nation byte
  0x4A3DDF shr eax, 0x16 / test al, 1 / je      bit 22 (vanilla "Your Own Town")
  0x4A3DED call 0x40FC70 / movzx ebp, al        ... then the display byte instead
and later indexes the anim-name table with it:
  0x4A4030 mov ecx, [esp+0x10]
  0x4A4034 mov edx, [ecx*4+0x6E1A40]            4 entries; index 5 is the string
                                                "imagesSD\\Pr2_Progress_Small_Rot.aim"
Our nation towns are nation 5 without bit 22, so they take the raw byte. Reading
+0x391 (display = host power 0..3) makes them show the host's mini flags, the
same row vanilla's bit-22 branch would pick. For every town owned by a power,
display == nation, so nothing changes there.
"""
import sys

VA = 0x4A3DD8
CHECKS = [
    (0x4A3DD8, ["movzx ebp, byte ptr [ebx + 0x390]", "shr eax, 0x16", "test al, 1",
                "mov dword ptr [esp + 0x10], ebp", "je 0x4a3df9", "lea ecx, [ebx + 0x38]",
                "call 0x40fc70", "movzx ebp, al", "mov dword ptr [esp + 0x10], ebp"]),
    (0x4A4030, ["mov ecx, dword ptr [esp + 0x10]", "mov edx, dword ptr [ecx*4 + 0x6e1a40]"]),
]


def _texts(b, va, n):
    return [f"{i.mnemonic} {i.op_str}".strip() for i in b.decode(va, 96)][:n]


def apply(b):
    err = sys.modules[type(b).__module__].PatchError
    for cva, want in CHECKS:
        got = _texts(b, cva, len(want))
        if got != want:
            raise err(f"P07: check at {cva:#x} expected {want}, found {got}")
    b.patch_bytes(VA + 3, (0x391).to_bytes(4, "little"), expected_old=(0x390).to_bytes(4, "little"),
                  desc="P07 town info mini flags: nation +0x390 -> display +0x391")
