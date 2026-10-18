#!/usr/bin/env python3
"""Export patches/p01..p07 as patch data for the in-memory loader (loader/, the player setup).

    python tools/export_patches.py [--out FILE] [--version V] [--check]

The patch modules stay the single source: this runs them through pe_patch.py's
PatchBuilder exactly like the file build does, but instead of writing an exe it
records what the patched image must look like in memory:

  * every image patch: VA, expected original bytes, new bytes (the loader checks the
    original bytes of ALL patches first and patches nothing on any mismatch);
  * the new section's contents (code caves and data), normally placed at its file
    VA 0x9F7000;
  * relocations: the 4-byte fields whose value depends on where the section lands.
    They are found, not hand-written: the patch set is built at three section
    addresses (A, A+d, A+2d) and every field that moves by +d/+2d (absolute address
    or rel32 into the section) or -d/-2d (rel32 from the section back into the
    image) is recorded. Anything else that changes means the set is not
    relocatable, and the export fails.
  * the trigger: the IAT slot the loader hooks (MSVCR71!__set_app_type, called by the
    CRT startup right after the original entry point) and the return address that
    identifies the CRT's call, both verified by disassembly here.

Default output: _build/loader/PR2Nation.patches (text, one record per
line; format in loader/README.md). --check also verifies that applying the data to the
base image gives exactly the image of the file build (pe_patch.build), so memory and
file route run the same bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import struct
import subprocess
import sys
from pathlib import Path

import capstone
import pefile

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import pe_patch  # noqa: E402
from pe_patch import PatchBuilder, PatchError  # noqa: E402

NATION = TOOLS.parent
PATCH_DIR = NATION / "patches"
OUT = NATION / "_build" / "loader" / "PR2Nation.patches"
DLL_NAME = "PR2Nation.dll"
SECTION_SIZE = 0x1000
MAGIC = "PR2NATION-PATCHDATA 1"

# trigger: the CRT startup's first call through an import nobody else uses this early
TRIGGER_CALL = 0x64E0B0           # call dword ptr [0x67f6f0]  ; MSVCR71.dll!__set_app_type
TRIGGER_IAT = 0x67F6F0
TRIGGER_IMPORT = ("MSVCR71.dll", "__set_app_type")
DELTA = 0x00123457                # odd low byte: every moved field differs in its first byte
M32 = 0xFFFFFFFF


def patch_modules():
    mods = []
    for path in sorted(PATCH_DIR.glob("p0*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        mods.append((path.name, m.apply))
    return mods


def materialize(rva=None, base=pe_patch.BASE_EXE):
    b = PatchBuilder(base, pe_patch.BASE_SHA256, SECTION_SIZE, section_rva=rva)
    for _, apply in patch_modules():
        apply(b)
    sec, recs = b.materialize()
    return b, sec, recs


def fields(a: bytes, b: bytes, c: bytes, what: str):
    """4-byte fields that differ between a (at A), b (A+d), c (A+2d) -> [(offset, sign)]."""
    out, i = [], 0
    while i < len(a):
        if a[i] == b[i]:
            if a[i] != c[i]:
                raise PatchError(f"{what}+{i:#x}: changes between A+d and A+2d only")
            i += 1
            continue
        if i + 4 > len(a):
            raise PatchError(f"{what}+{i:#x}: moved bytes at the end")
        va, vb, vc = (struct.unpack_from("<I", x, i)[0] for x in (a, b, c))
        if (vb - va) & M32 == DELTA and (vc - va) & M32 == (2 * DELTA) & M32:
            out.append((i, +1))
        elif (va - vb) & M32 == DELTA and (va - vc) & M32 == (2 * DELTA) & M32:
            out.append((i, -1))
        else:
            raise PatchError(f"{what}+{i:#x}: not a relocatable 32-bit field "
                             f"({va:#x}, {vb:#x}, {vc:#x})")
        i += 4
    return out


def trigger_check(base_path):
    pe = pefile.PE(str(base_path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    names = {i.address: (e.dll.decode(), i.name.decode() if i.name else None)
             for e in pe.DIRECTORY_ENTRY_IMPORT for i in e.imports}
    if names.get(TRIGGER_IAT) != TRIGGER_IMPORT:
        raise PatchError(f"IAT {TRIGGER_IAT:#x} is {names.get(TRIGGER_IAT)}, expected {TRIGGER_IMPORT}")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    code = pe.get_data(TRIGGER_CALL - pe.OPTIONAL_HEADER.ImageBase, 16)
    ins = next(md.disasm(code, TRIGGER_CALL))
    if f"{ins.mnemonic} {ins.op_str}" != f"call dword ptr [{TRIGGER_IAT:#x}]":
        raise PatchError(f"trigger call at {TRIGGER_CALL:#x} is {ins.mnemonic} {ins.op_str}")
    # nothing between the entry point and the trigger may be a patch target that runs first;
    # the entry detour (P06) is applied anyway (it already ran when the trigger fires)
    return TRIGGER_CALL + ins.size


def git_version():
    r = subprocess.run(["git", "-C", str(NATION), "rev-parse", "--short=8", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() or "nogit"


def export(version: str, base=pe_patch.BASE_EXE) -> tuple[str, dict]:
    b1, s1, r1 = materialize(None, base)
    a = b1.sec_rva
    _, s2, r2 = materialize(a + DELTA, base)
    _, s3, r3 = materialize(a + 2 * DELTA, base)
    if [(r["va"], r["old"]) for r in r1] != [(r["va"], r["old"]) for r in r2] \
            or [r["va"] for r in r1] != [r["va"] for r in r3]:
        raise PatchError("patch list depends on the section address")
    sec_relocs = fields(s1, s2, s3, "section")
    patch_relocs = []
    for n, (x, y, z) in enumerate(zip(r1, r2, r3)):
        for off, sign in fields(x["new"], y["new"], z["new"], f"patch {x['va']:#x}"):
            patch_relocs.append((n, off, sign))
    ret = trigger_check(base)
    sec_va = b1.sec_va
    used = max((l.offset + l.size for l in b1.labels.values()), default=0)

    lines = [MAGIC,
             "# Sovereign Nations patch data, generated by tools/export_patches.py",
             "# from patches/p01..p07 through pe_patch.py. Do not edit: re-export instead.",
             f"mod {version}",
             f"base {b1.base_sha256}",
             f"hook {TRIGGER_IAT:08X} {ret:08X} {TRIGGER_IMPORT[0]} {TRIGGER_IMPORT[1]}",
             f"section {sec_va:08X} {SECTION_SIZE:08X} {hashlib.sha256(s1).hexdigest()}"]
    for off in range(0, used, 32):
        chunk = s1[off:min(off + 32, used)]
        if any(chunk):
            lines.append(f"data {off:04X} {chunk.hex().upper()}")
    for r in r1:
        desc = " ".join(r["desc"].split())
        lines.append(f"patch {r['va']:08X} {r['old'].hex().upper()} {r['new'].hex().upper()} ; {desc}")
    for off, sign in sec_relocs:
        lines.append(f"reloc S {off:04X} {'+' if sign > 0 else '-'}")
    for n, off, sign in patch_relocs:
        lines.append(f"reloc P {n} {off:X} {'+' if sign > 0 else '-'}")
    lines.append(f"dll {DLL_NAME}")
    body = "\n".join(lines) + "\n"
    lines.append(f"end {hashlib.sha256(body.encode('ascii')).hexdigest()}")
    text = "\n".join(lines) + "\n"
    info = {"patches": len(r1), "section_va": sec_va, "section_used": used,
            "section_relocs": len(sec_relocs), "patch_relocs": len(patch_relocs), "trigger_ret": ret}
    return text, info


# ---- a Python model of the loader (used by --check and the tests) -------------------------
def parse(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0] != MAGIC:
        raise PatchError("not patch data")
    if not lines[-1].startswith("end "):
        raise PatchError("truncated (no end line)")
    body = "\n".join(lines[:-1]) + "\n"
    if hashlib.sha256(body.encode("ascii")).hexdigest() != lines[-1].split()[1]:
        raise PatchError("checksum mismatch")
    d = {"data": [], "patches": [], "sreloc": [], "preloc": []}
    for ln in lines[1:-1]:
        if not ln or ln.startswith("#"):
            continue
        k, *f = ln.split(" ;")[0].split()
        if k == "section":
            d["section"] = (int(f[0], 16), int(f[1], 16))
        elif k == "data":
            d["data"].append((int(f[0], 16), bytes.fromhex(f[1])))
        elif k == "patch":
            d["patches"].append((int(f[0], 16), bytes.fromhex(f[1]), bytes.fromhex(f[2])))
        elif k == "reloc":
            if f[0] == "S":
                d["sreloc"].append((int(f[1], 16), 1 if f[2] == "+" else -1))
            else:
                d["preloc"].append((int(f[1]), int(f[2], 16), 1 if f[3] == "+" else -1))
        elif k == "hook":
            d["hook"] = (int(f[0], 16), int(f[1], 16))
        elif k in ("mod", "base", "dll"):
            d[k] = f[0] if f else ""
    return d


def apply_model(d: dict, read, sec_at: int | None = None):
    """What the loader writes: [(va, bytes)], or raises on an original-bytes mismatch.
    read(va, n) -> bytes of the current image."""
    va0, size = d["section"]
    at = va0 if sec_at is None else sec_at
    delta = (at - va0) & M32
    for va, old, _ in d["patches"]:
        if read(va, len(old)) != old:
            raise PatchError(f"original bytes differ at {va:#x}")
    sec = bytearray(size)
    for off, chunk in d["data"]:
        sec[off:off + len(chunk)] = chunk

    def fix(buf, off, sign):
        v = struct.unpack_from("<I", buf, off)[0]
        struct.pack_into("<I", buf, off, (v + sign * delta) & M32)
    for off, sign in d["sreloc"]:
        fix(sec, off, sign)
    news = [bytearray(n) for _, _, n in d["patches"]]
    for n, off, sign in d["preloc"]:
        fix(news[n], off, sign)
    return [(at, bytes(sec))] + [(va, bytes(n)) for (va, _, _), n in zip(d["patches"], news)]


def check(text: str, base=pe_patch.BASE_EXE) -> str:
    """Applying the data to the base image == the file build's image (pe_patch.build)."""
    out = pe_patch.BUILD_DIR / "loader" / "check" / "PR2_nation.exe"
    pe_patch.build(out, [a for _, a in patch_modules()], SECTION_SIZE, base)
    built = pefile.PE(str(out), fast_load=True)
    basepe = pefile.PE(str(base), fast_load=True)
    img = bytearray(basepe.get_memory_mapped_image())
    d = parse(text)
    writes = apply_model(d, lambda va, n: bytes(img[va - 0x400000:va - 0x400000 + n]))
    sec_va, size = d["section"]
    img += b"\0" * (sec_va + size - 0x400000 - len(img))
    for va, data in writes:
        img[va - 0x400000:va - 0x400000 + len(data)] = data
    want = built.get_memory_mapped_image()
    # headers differ (one more section); compare from the first section on
    first = basepe.sections[0].VirtualAddress
    if bytes(img[first:]) != want[first:first + len(img) - first]:
        bad = next(i for i in range(first, len(img)) if img[i] != want[i])
        raise PatchError(f"memory image differs from the file build at {bad + 0x400000:#x}")
    # relocated placement is consistent too: a second copy at another address
    other = apply_model(d, lambda va, n: bytes(basepe.get_memory_mapped_image()[va - 0x400000:va - 0x400000 + n]),
                        sec_at=0x12340000)
    _, s_other, _ = materialize(0x12340000 - 0x400000, base)
    if other[0][1][:len(s_other)] != s_other:
        raise PatchError("relocated section differs from a build at that address")
    return f"memory image == file build {out.name} (sha256 {pe_patch.sha256(out.read_bytes())[:16]}); relocation ok"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--version", default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    try:
        text, info = export(a.version or git_version())
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="ascii", newline="\n")
        print(f"wrote {a.out}: {info['patches']} patches, section {info['section_va']:#x} "
              f"({info['section_used']:#x} bytes used), relocs {info['section_relocs']}+{info['patch_relocs']}")
        if a.check:
            print(check(text))
    except PatchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
