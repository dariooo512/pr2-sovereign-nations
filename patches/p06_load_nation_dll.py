"""P06 -- load PR2Nation.dll at process start.

The nation feature's logic lives in a C DLL (dll/). This
patch makes the game load it before the CRT starts: the entry point
0x64E03F (VC7.1 CRT startup, `push 0x74; push 0x6ae380`) is detoured to

    push  "PR2Nation.dll"
    call  [LoadLibraryA]        ; IAT 0x67F5F4, already imported by the exe
    push  0x74                  ; displaced
    push  0x6ae380              ; displaced
    jmp   0x64E046

LoadLibraryA's result is ignored: without the DLL the game runs exactly as
the P01-P05 build. The DLL installs its own runtime hooks from DllMain.
"""
import struct

ENTRY = 0x64E03F
IAT_LOADLIBRARYA = 0x67F5F4
DLL_NAME = b"PR2Nation.dll\0"


def apply(b):
    b.place("nation_dll_name", DLL_NAME, align=4, desc="LoadLibraryA argument")
    d = b.detour(ENTRY, ["push 0x74", "push 0x6ae380"], target="dll_loader",
                 desc="entry point -> load PR2Nation.dll")

    def prologue(va):
        return (b"\x68" + struct.pack("<I", b.va_of("nation_dll_name"))     # push name
                + b"\xFF\x15" + struct.pack("<I", IAT_LOADLIBRARYA))        # call [LoadLibraryA]
    b.place_trampoline("dll_loader", d, prologue=prologue, prologue_size=11,
                       desc="LoadLibraryA(PR2Nation.dll), then CRT startup")
