"""Re-verify every binary fact the research notes rely on.

Each fact is an address plus the instructions (or data) we expect there in the
pinned build. Run this before trusting research/; a FAIL means either the
exe changed or a doc claim is wrong -- fix the doc, don't ignore the failure.

    python tools/check_facts.py [path/to/PR2.exe.unpacked.exe]      (default: setting SN_BASE_EXE)

Exit code 0 = all facts hold.
"""
import hashlib
import struct
import sys
from pathlib import Path

import capstone
import pefile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sn_paths import BASE_EXE as DEFAULT_EXE  # noqa: E402  (setting SN_BASE_EXE)
# Steam 1.1.2.3, SteamStub removed with Steamless (the modding kit's docs/getting-started.md step 5).
PINNED_SHA256 = "9c9250bc2b7a8068f658c0d9935bf2e7d8f9865bc31b875d9fb3b220d01cf448"

G_NATIONS = 0x702B14       # CNation* g_nations[4]
G_NATION_NAMES = 0x6E41E0  # char* g_nationNames[4]

# (id, va, expected instruction lines in order, meaning)
CODE_FACTS = [
    ("N1-isatwar", 0x5BA0A0, [
        "mov al, byte ptr [esp + 4]",
        "cmp al, 4",
        "jae 0x5ba0ba",
        "movzx eax, al",
        "mov al, byte ptr [eax + ecx]",
        "and al, 0x7f",
    ], "CNation::IsAtWar(other): rel[other]&0x7f, relation bytes at CNation+0; "
       "other>=4 jumps to 'mov al,1' => pirates/player are always hostile"),
    ("N1-isatwar-ge4", 0x5BA0BA, ["mov al, 1", "ret 4"],
     "IsAtWar returns TRUE for any nation index >= 4"),
    ("T1-getnation", 0x421D2E, [
        "mov cl, byte ptr [eax + 0x390]",
        "add eax, 0x38",
        "cmp cl, 4",
        "jae 0x421d40",
        "mov al, cl",
        "jmp 0x421d46",
        "mov al, byte ptr [eax + 0x359]",
    ], "Town_GetNation (Lua): town nation byte at CStadt+0x390 (=CStadtLager+0x358); "
       "if >=4 it reports the display nation at CStadtLager+0x359 instead"),
    ("T2-setnation-noforce", 0x4292B5, [
        "push 0",
        "push -1",
        "push eax",
        "call 0x64d822",
    ], "Town_SetNation (Lua) passes force=0 to AddToNation (push 0 = 2nd arg)"),
    ("T2-setnation-call", 0x4292D1, ["call 0x5c9da0"],
     "Town_SetNation calls CStadtLager::AddToNation"),
    ("T3-addtonation-force", 0x5C9DB1, [
        "cmp byte ptr [esi + 0x358], 4",
        "jb 0x5c9dde",
    ], "AddToNation force path only acts on towns whose nation is already >=4"),
    ("T3-addtonation-mark5", 0x5C9DD1, [
        "mov byte ptr [esi + 0x359], al",
        "mov byte ptr [esi + 0x358], 5",
    ], "force path: display nation := nation%4, nation := 5 (special/player marker)"),
    ("T3-addtonation-reject", 0x5C9E09, [
        "movzx eax, bl",
        "cmp eax, 4",
        "jae 0x5c9e69",
    ], "non-force path: new nation >= 4 skips the transfer"),
    ("T3-addtonation-silent", 0x5C9E69, ["test edi, edi", "jne 0x5c9dde"],
     "...and if the town had a valid owner the call silently returns (no error)"),
    ("N2-name-lookup", 0x61BD20, [
        "movzx ecx, al",
        "mov esi, dword ptr [ecx*4 + 0x6e41e0]",
    ], "nation-name parser (staedte.ini 'Nation=') walks g_nationNames"),
    ("T4-force-caller", 0x61BE85, [
        "push 1",
        "push ecx",
        "mov ecx, esi",
        "call 0x5c9da0",
    ], "the ONLY force=1 caller of AddToNation, inside fn 0x61BDE0 (called from 0x61C8A8): "
       "stamps a town as nation 5; hypothesis = new-settlement/colony creation"),
    ("T5-annex-caller", 0x5BC5AD, ["push 0", "lea esi, [ebp + 0x38]", "mov ecx, esi", "push eax",
                                   "call 0x5c9da0"],
     "annexation transfer (fn ~0x5BC310) moves a town between powers with force=0"),
    ("L1-lua-pirates", 0x43DCE6, ["push 4"], "Lua global PIRATEN_NATION = 4"),
    ("L1-lua-pirates-name", 0x43DCF5, ["push 0x684938"], "...name string 'PIRATEN_NATION'"),
    ("L2-lua-player", 0x43DD07, ["push 5"], "Lua global SPIELER_NATION = 5"),
    ("L2-lua-player-name", 0x43DD16, ["push 0x684928"], "...name string 'SPIELER_NATION'"),

    # ---- CR-: runtime crash sites seen in E3 (FEASIBILITY.md E3/E4) ----------------
    ("CR-ui-nullhandle", 0x4C1D9C, ["mov ecx, dword ptr [ebp - 0x14]", "mov eax, dword ptr [ecx]"],
     "[userflag.md] crash (a): in 0x4C1CD0 the image handle [ebp-0x14] stays null "
     "when the lookup fails, and 0x4C1D9F `mov eax,[ecx]` faults"),
    ("CR-ui-lookup-call", 0x4C1D0C, ["call 0x4c13b0", "test al, al", "je 0x4c1e6c"],
     "[userflag.md] 0x4C1CD0 trusts 0x4C13B0's bool; its clean failure exit is 0x4C1E6C"),
    ("CR-isatwar-rel-read", 0x5BA0A8, ["movzx eax, al", "mov al, byte ptr [eax + ecx]"],
     "[hostility_map.md] crash (b): IsAtWar reads rel[other] at 0x5BA0AB through `this` "
     "(ecx) with no null check -> AV when self is a NULL CNation"),
    ("CR-routecost-fetch", 0x63B8C7, [
        "movzx eax, byte ptr [esi + 0x390]",
        "cmp eax, 4",
        "jae 0x63b8e0",
        "mov ecx, dword ptr [eax*4 + 0x702b14]",
        "mov dword ptr [esp + 0x1c], ecx",
        "jmp 0x63b8e8",
        "mov dword ptr [esp + 0x1c], 0",
    ], "[hostility_map.md #16, vanilla_nation5_path.md 3.3] AI route cost 0x63B840: "
       "self = g_nations[town nation], stored as 0 (NULL) for nation >= 4"),
    ("CR-routecost-isatwar", 0x63BA36, ["mov ecx, dword ptr [esp + 0x1c]", "mov byte ptr [esp + 0x30], al",
                                        "mov edx, dword ptr [esp + 0x30]", "push edx", "call 0x5ba0a0"],
     "[hostility_map.md #16] ...and calls IsAtWar with that possibly-NULL self (crash b)"),

    # ---- UF-: '-userflag-' (research/userflag.md) -----------------------------------
    ("UF-lookup-je", 0x4C1407, ["call 0x64c7a4", "add esp, 0x10", "test eax, eax", "je 0x4c14eb"],
     "[userflag.md] 0x4C13B0: arc_CreateMemMapped thunk, then 0x4C1411 `je 0x4C14EB` on "
     "not-found (P02 retargets this je to 0x4C1525)"),
    ("UF-notfound-true", 0x4C14EB, [
        "mov ecx, dword ptr [ebp - 0x24]", "push ebx", "add ecx, 0xf8",
        "mov dword ptr [ebp - 4], 0xffffffff", "call dword ptr [0x67fa40]", "mov al, 1",
    ], "[userflag.md] the not-found path only stores the name at this+0xF8 and returns al=1"),
    ("UF-false-tail", 0x4C1525, [
        "mov ecx, dword ptr [ebp - 0xc]", "pop edi", "pop esi", "xor al, al",
        "mov dword ptr fs:[0], ecx", "pop ebx", "mov esp, ebp", "pop ebp", "ret 8",
    ], "[userflag.md] existing return-false tail of 0x4C13B0 = P02's new je target"),
    ("UF-topbar-bit22", 0x4A62F7, ["mov edx, dword ptr [esi + 0x40]", "shr edx, 0x16", "test dl, 1",
                                   "je 0x4a639f"],
     "[userflag.md] town top bar: bit 22 clear -> table path 0x4A639F"),
    ("UF-topbar-mod6", 0x4A639F, ["movzx eax, byte ptr [esi + 0x390]", "cdq", "mov ecx, 6", "idiv ecx",
                                  "lea ecx, [esp + 0x2c]", "mov edx, dword ptr [edx*4 + 0x6e12ec]"],
     "[userflag.md] top bar: icon = table[nation % 6] (P2a patch site)"),
    ("UF-topbar-setter", 0x4A63CA, ["call 0x4c1cd0"],
     "[userflag.md] top bar feeds the icon name to 0x4C1CD0 (return addr 0x4A63CF)"),
    ("UF-townlist-bit22", 0x4B7BC6, ["mov edx, dword ptr [edi + 0x40]", "shr edx, 0x16", "test dl, 1",
                                     "mov dword ptr [esp + 0x60], 5", "je 0x4b7c76"],
     "[userflag.md] town list: bit-22 test with the EH-state store interleaved"),
    ("UF-townlist-mod6", 0x4B7C76, ["movzx eax, byte ptr [edi + 0x390]", "cdq", "mov ecx, 6", "idiv ecx",
                                    "lea ecx, [esp + 0x1c]", "mov edx, dword ptr [edx*4 + 0x6e12ec]"],
     "[userflag.md] town list: icon = table[nation % 6] (P2a patch site)"),
    ("UF-townlist-setter", 0x4B7D00, ["call 0x4c1cd0"], "[userflag.md] town list -> 0x4C1CD0"),
    ("UF-selpanel-mod6", 0x485E84, ["movzx eax, byte ptr [eax + 0x390]", "cdq", "mov ecx, 6", "idiv ecx",
                                    "mov edx, dword ptr [edx*4 + 0x6e12ec]"],
     "[userflag.md] selection panel: icon = table[nation % 6]"),
    ("UF-selpanel-setter", 0x4860BA, ["call 0x4c1cd0"], "[userflag.md] selection panel -> 0x4C1CD0"),
    ("UF-battle-raw-idx", 0x4F6484, ["mov al, byte ptr [eax + 0x390]", "sub esp, 0xc",
                                     "lea edx, [esp + 0x1e]", "movzx eax, al"],
     "[userflag.md] battle dialog indexes the icon table with the raw byte (no %6, no bound)"),
    ("UF-display-accessor", 0x40FC70, ["mov al, byte ptr [ecx + 0x358]", "cmp al, 4", "jb 0x40fc80",
                                       "mov al, byte ptr [ecx + 0x359]", "ret"],
     "[userflag.md, nation5_index_safety.md] CStadtLager::GetEffectiveNation (P2a callee)"),

    # ---- HO-: hostility (research/hostility_map.md) ---------------------------------
    ("HO-getrep", 0x5D2AC0, [
        "mov al, byte ptr [esp + 4]", "cmp al, 4", "jb 0x5d2ad8", "xor ecx, ecx", "cmp al, 5",
        "setne cl", "dec ecx", "and ecx, 0x64", "mov eax, ecx", "ret 4",
        "movzx edx, al", "mov eax, dword ptr [ecx + edx*4 + 0x54]", "sar eax, 8",
        "mov word ptr [esp + 4], ax", "movsx eax, byte ptr [esp + 5]", "ret 4",
    ], "[hostility_map.md D1] CPlayer::GetReputation: n>=4 -> (n==5 ? 100 : 0), "
       "else (int8)(rep[n]>>16) from CPlayer+0x54"),
    ("HO-replevel", 0x5D2C10, ["mov eax, dword ptr [esp + 4]", "push eax", "call 0x5d2ac0"],
     "[hostility_map.md] GetReputationLevel 0x5D2C10 goes through GetReputation"),
    ("HO-isrep25", 0x5D2D90, [
        "cmp word ptr [ecx], 0", "jne 0x5d2db0", "mov al, byte ptr [esp + 4]", "cmp al, 4",
        "jae 0x5d2db0", "movzx eax, al", "cmp dword ptr [ecx + eax*4 + 0x54], 0x190000",
        "jge 0x5d2db0", "xor al, al", "ret 4", "mov al, 1", "ret 4",
    ], "[hostility_map.md D2] IsRepAtLeast25: word[this]!=0 or n>=4 -> 1, else rep[n]>=25 "
       "(reads rep inline, not via GetReputation)"),
    ("HO-siege-isatwar", 0x63C473, [
        "test esi, esi", "je 0x63c4c4", "test ecx, ecx", "je 0x63c4c4",
        "mov dl, byte ptr [esi + 0x390]", "mov byte ptr [esp + 0x18], dl",
        "mov eax, dword ptr [esp + 0x18]", "push eax", "call 0x5ba0a0",
        "test al, al", "je 0x63c4c4", "cmp byte ptr [esi + 0x58], 3", "jbe 0x63c4c4",
    ], "[hostility_map.md #18] siege flag 0x63C400: self NULL-checked, then "
       "IsAtWar(P, town+0x390) at 0x63C48A and town+0x58>3"),
    ("HO-targetpick-war5", 0x63B46B, ["mov edx, dword ptr [ebp + 0xc]", "push edx", "call 0x5d2c10"],
     "[hostility_map.md #15] target picker: war[5] from GetReputationLevel(P) at 0x63B46F"),
    ("HO-isatwar-ge4", 0x5BA0BA, ["mov al, 1", "ret 4", "int3"],
     "[hostility_map.md D3] IsAtWar >=4 branch is exactly 5 bytes + int3 pad"),
    ("HO-nation-index", 0x5BBD39, ["mov byte ptr [esi + 0x18], al"],
     "[hostility_map.md D3, P01] CNation ctor stores the power index byte at CNation+0x18"),
    ("HO-player-rep-inline", 0x5D35B7, [
        "mov al, byte ptr [ecx + 0x390]", "cmp al, 4", "jb 0x5d35ce", "xor ecx, ecx", "cmp al, 5",
        "setne cl", "dec ecx", "and ecx, 0x64",
    ], "[vanilla_nation5_path.md 3.1] the only explicit ==5 town test: nation 5 -> 100"),

    # ---- GF-: game flow on the session object 0x700500 (game_flow_entry_points.md) ---
    ("GF-app-accessor", 0x405A7A, ["mov dword ptr [0x6e5958], eax", "call 0x64dca3", "add esp, 4",
                                   "mov ecx, dword ptr [esp + 4]", "mov eax, 0x6e5958"],
     "[game_flow_entry_points.md] lazy accessor 0x405A20 stores the app at 0x6E5958 "
     "and returns &0x6E5958"),
    ("GF-app-ctor", 0x405A46, ["push 0x10c"],
     "[game_flow_entry_points.md] app object is 0x10C bytes (ctor 0x4056C0)"),
    ("GF-app-ctor-call", 0x405A6C, ["call 0x4056c0"], "[game_flow_entry_points.md] app ctor 0x4056C0"),
    ("GF-quicksave", 0x52274C, ["mov ecx, 0x700500", "call 0x57ee90"],
     "[game_flow_entry_points.md] menu QUICKSAVE slot 0x522730 -> QuickSave 0x57EE90, ecx=0x700500"),
    ("GF-quicksave-save", 0x57EF73, ["call 0x580e70"],
     "[game_flow_entry_points.md] QuickSave calls SaveGame 0x580E70"),
    ("GF-save-lua", 0x424E14, ["mov ecx, 0x700500", "call 0x580e70"],
     "[game_flow_entry_points.md] Lua Global_SaveGame -> SaveGame(std::string) on 0x700500"),
    ("GF-save-ret", 0x580F0C, ["ret 0xc"],
     "[game_flow_entry_points.md] SaveGame takes a 12-byte STLport string by value (ret 0xC)"),
    ("GF-load-call", 0x4EE1AA, ["mov ecx, dword ptr [esi + 0xe4]", "add ebx, 0x18", "push ebx",
                                "call 0x526470"],
     "[game_flow_entry_points.md] save list LOAD -> Menu::StartFromFile 0x526470, "
     "ecx = menu [screen+0xE4], arg = &entry->name (entry+0x18)"),
    ("GF-load-ret", 0x526991, ["ret 4"], "[game_flow_entry_points.md] StartFromFile is ret 4"),
    ("GF-speed", 0x57F550, [
        "mov al, byte ptr [esp + 4]", "cmp al, 5", "jb 0x57f55a", "mov al, 1", "movzx eax, al",
        "movzx edx, word ptr [eax*2 + 0x6a500c]", "mov dword ptr [ecx + 0x20], edx", "ret 4",
    ], "[game_flow_entry_points.md] SetGameSpeed(idx): idx>=5 -> 1; [this+0x20] = ms/tick "
       "from WORD table 0x6A500C"),
    ("GF-speed-lua", 0x41F524, ["mov ecx, 0x700500", "call 0x57f550"],
     "[game_flow_entry_points.md] Lua Global_SetGameSpeed -> 0x57F550 on 0x700500"),
    ("GF-unpause-hook", 0x402B70, ["mov ecx, 0x700500", "jmp 0x57efd0"],
     "[game_flow_entry_points.md] app focus hook 0x402B70 resumes via Unpause 0x57EFD0"),
    ("GF-unpause-set", 0x57F00D, ["mov byte ptr [esi + 0xe44], 1"],
     "[game_flow_entry_points.md] Unpause sets the sim-running flag +0xE44 = 1"),
    ("GF-pause-clear", 0x57EE08, ["mov byte ptr [ecx + 0xe44], 0"],
     "[game_flow_entry_points.md] Pause 0x57EDF0 clears +0xE44"),

    # ---- IX-: nation-5 index safety (research/nation5_index_safety.md) --------------
    ("IX-U1-milconvoy-leader", 0x6352B7, ["movzx eax, byte ptr [eax + 0x358]",
                                          "mov cl, byte ptr [eax + 0x6ac4b4]"],
     "[nation5_index_safety.md U1] P03 site: raw nation indexes byte[4] 0x6AC4B4"),
    ("IX-U1-milconvoy-bind", 0x426A1F, ["call 0x635270"],
     "[nation5_index_safety.md U1] Lua Global_CreateMilitaryConvoy reaches 0x635270"),
    ("IX-U1-shiptype-getter", 0x633550, ["mov eax, dword ptr [esp + 4]", "cmp eax, 4", "jb 0x63355c",
                                         "mov al, 7", "ret"],
     "[nation5_index_safety.md U1] the guarded getter returns 7 for >=4 (U1 inlines it unguarded)"),
    ("IX-U2-escort-nation", 0x634902, ["mov al, byte ptr [eax + 0x358]"],
     "[nation5_index_safety.md U2] P03 site: escort nation load"),
    ("IX-U2-escort-type", 0x63493B, ["movzx edi, byte ptr [esp + 0x14]", "xor eax, eax",
                                     "mov al, byte ptr [edi + 0x6ac4b4]"],
     "[nation5_index_safety.md U2] ...indexes 0x6AC4B4 unguarded"),
    ("IX-U3-township", 0x5C6A86, ["mov bl, byte ptr [edi + 0x390]", "mov ecx, 0x702140", "call 0x5c1cf0",
                                  "movzx edx, bl", "and eax, 7",
                                  "mov al, byte ptr [eax + edx*8 + 0x6a5174]"],
     "[nation5_index_safety.md U3] P03 site: per-tick ship spawn reads row(nation) of 0x6A5174"),
    ("IX-U3-tick-call1", 0x5EF931, ["call 0x5c6a40"], "[nation5_index_safety.md U3] tick 0x5EF7D0 -> 0x5C6A40"),
    ("IX-U3-tick-call2", 0x5EF944, ["call 0x5c6a40"], "[nation5_index_safety.md U3] tick 0x5EF7D0 -> 0x5C6A40"),
    ("IX-U3-later-guard", 0x5EF979, ["movzx eax, byte ptr [ebp + 0x390]", "cmp eax, 4", "jae 0x5f01c3"],
     "[nation5_index_safety.md U3] the tick's own guard comes after those calls"),
    ("IX-U3-shipcreate", 0x5C6AB2, ["call 0x63cfc0"], "[nation5_index_safety.md U3] ship get/create"),
    ("IX-U4-create-ships-a", 0x5A80B0, ["mov bl, byte ptr [ebx + 0x390]", "mov ecx, 0x702140",
                                        "call 0x5c1cf0", "movzx ecx, bl", "and eax, 7",
                                        "mov dl, byte ptr [eax + ecx*8 + 0x6a5174]"],
     "[nation5_index_safety.md U4] P03 site: initial ships (a)"),
    ("IX-U4-create-ships-b", 0x5A822C, ["mov bl, byte ptr [edi + 0x390]", "mov ecx, 0x702140",
                                        "call 0x5c1cf0", "movzx ecx, bl", "and eax, 7",
                                        "mov al, byte ptr [eax + ecx*8 + 0x6a5174]"],
     "[nation5_index_safety.md U4] P03 site: initial ships (b)"),
    ("IX-U4-caller", 0x61BAE2, ["call 0x5a7f40"], "[nation5_index_safety.md U4] only caller of 0x5A7F40"),
    ("IX-U4-caller2", 0x61C71F, ["call 0x61bab0"], "[nation5_index_safety.md U4] CStadtCreate -> 0x61BAB0"),
    ("IX-U5-welcome-voice", 0x57D0B6, ["mov al, byte ptr [eax + 0x358]", "movzx eax, al", "push edx",
                                       "lea ecx, [esp + eax + 0x20]", "lea edx, [ecx + eax*2]"],
     "[nation5_index_safety.md U5] P03 site: welcome voice indexes a 12-byte stack char[4][3]"),
    ("IX-U5-welcome-sprintf", 0x57D0CF, ["push 0x6a0034", "push eax", "call dword ptr [0x67f398]"],
     "[nation5_index_safety.md U5] ...sprintf 'music/voice/Willkommen_%s_%02d.mp3'"),
    ("IX-U6-setter-both", 0x5C9E54, ["mov byte ptr [esi + 0x358], bl", "mov byte ptr [esi + 0x359], bl"],
     "[nation5_index_safety.md U6] non-force AddToNation writes nation and display byte alike, "
     "so the +1 displacement patch is vanilla-neutral"),
    ("IX-shiptype-store", 0x63F93C, ["movzx eax, byte ptr [ecx + 0x703c0c]"],
     "[nation5_index_safety.md] per-type stat byte table indexed by ship type"),
    ("IX-shiptype-count", 0x559064, ["cmp edi, 0x12", "jl 0x558f70"],
     "[nation5_index_safety.md] 18 valid ship types (0..17)"),
    ("IX-S1-save-nation", 0x5C9883, ["mov cl, byte ptr [ebp + 0x358]", "mov byte ptr [eax], cl"],
     "[nation5_index_safety.md] save writes the nation byte raw"),
    ("IX-S1-load-nation", 0x5C9AF6, ["mov al, byte ptr [edx]", "mov byte ptr [ebp + 0x358], al"],
     "[nation5_index_safety.md] load restores it with no validation (H2)"),
    ("IX-S1-load-display", 0x5C9B02, ["cmp esi, 0x3f4", "mov dword ptr [ebx + 4], ecx", "jb 0x5c9b26"],
     "[nation5_index_safety.md] display byte read only for save version >= 0x3F4"),

    # ---- VP-: vanilla player-town path (research/vanilla_nation5_path.md) -----------
    ("VP-viceroy-slot14", 0x447520, ["push esi", "mov esi, ecx", "call 0x43ee40", "cmp eax, 6",
                                     "jne 0x447595"],
     "[vanilla_nation5_path.md 1.3] viceroy vtable slot 14: dialog state must be 6"),
    ("VP-viceroy-create", 0x44755A, ["call 0x61c7a0"],
     "[vanilla_nation5_path.md 1.3] viceroy slot 14 -> player-town create 0x61C7A0"),
    ("VP-create-guard", 0x61C7A0, ["movzx eax, byte ptr [esp + 0xc]", "sub esp, 0x10", "cmp eax, 4"],
     "[vanilla_nation5_path.md 1.2] 0x61C7A0 requires nation 0..3"),
    ("VP-create-call", 0x61C8A8, ["call 0x61bde0"],
     "[vanilla_nation5_path.md 1.2] 0x61C7A0 calls 0x61BDE0 at 0x61C8A8"),
    ("VP-lager-init-flag1", 0x61BE75, ["push 1", "lea esi, [edi + 0x38]", "push ebx", "mov ecx, esi",
                                       "call 0x61cce0"],
     "[vanilla_nation5_path.md 1.1] player create inits the Lager with flag=1"),
    ("VP-normal-init-flag0", 0x61C382, ["push 0"],
     "[vanilla_nation5_path.md 1.1] ...the normal create 0x61C320 passes flag=0"),
    ("VP-set-flags-call", 0x61BE8F, ["mov ecx, esi", "call 0x624d30"],
     "[vanilla_nation5_path.md 1.1] 0x61BDE0 then calls 0x624D30"),
    ("VP-set-flags", 0x624D30, ["sub esp, 8", "mov eax, dword ptr [ecx + 8]", "or eax, 0x600000",
                                "lea edx, [esp]", "mov dword ptr [ecx + 8], eax"],
     "[vanilla_nation5_path.md 1.1] 0x624D30 sets town flag bits 21+22 (Lager+8 = CStadt+0x40)"),
    ("VP-isplayertown", 0x427450, ["add eax, 0x38", "mov eax, dword ptr [eax + 8]", "shr eax, 0x16",
                                   "and eax, 1"],
     "[vanilla_nation5_path.md 3.5, userflag.md] Town_IsPlayerTown 0x4273E0 tests bit 22, not nation==5"),
    ("VP-isplayertown-reg", 0x43AFBC, ["push 0x4273e0"],
     "[vanilla_nation5_path.md 3.5] Lua binding registered with impl 0x4273E0"),
    ("VP-isplayertown-name", 0x43AFD8, ["push 0x686450"],
     "[vanilla_nation5_path.md 3.5] ...under the name 'Town_IsPlayerTown'"),

    # ---- P4-: P04 detour site not already pinned at its exact address -------------
    ("P4-isrep25-mid", 0x5D2D96, ["mov al, byte ptr [esp + 4]", "cmp al, 4", "jae 0x5d2db0"],
     "[p04_reputation_war.py] IsRepAtLeast25 detour site (after the human test): the "
     "displaced pair mov al,[esp+4]; cmp al,4 then the jae it resumes at 0x5D2D9C"),

    # ---- P5-: P05 nation-5 town safety sites (patches/p05_nation5_town_safety.py) ---
    ("P5-econ-seatgate", 0x5C8656, ["mov eax, dword ptr [esi + 0xc]", "mov ecx, 1", "test ecx, eax",
                                    "jne 0x5c866b"],
     "[null_nation_census.md 4, P05 fix1] 0x5C8650 tests Lager+0xC bit 0 (admin seat) "
     "before the per-good share"),
    ("P5-econ-load", 0x5C86A5, ["movzx ecx, byte ptr [esi + 0x358]", "cmp ecx, 4", "jae 0x5c86ba",
                                "mov edx, dword ptr [ecx*4 + 0x702b14]", "jmp 0x5c86bc", "xor edx, edx",
                                "push ebp"],
     "[P05 fix1] detour site: 7-byte town-nation load, guarded lookup -> edx NULL for >=4"),
    ("P5-econ-crash", 0x5C86BD, ["mov ebp, dword ptr [edx + 0x20]"],
     "[null_nation_census.md 4, P05 fix1] the observed runtime crash (edx = NULL)"),
    ("P5-econ-ret0", 0x5C8765, ["pop ebx", "pop esi", "add esp, 0x10", "ret 4"],
     "[P05 fix1] vanilla return-0 exit the stub jumps to"),
    ("P5-conv-A1", 0x5B41B0, ["movzx edx, byte ptr [ebp + 0x390]", "cmp edx, 4", "jae 0x5b41c5",
                              "mov edx, dword ptr [edx*4 + 0x702b14]", "jmp 0x5b41c7", "xor edx, edx"],
     "[P05 fix2 A1] convoy 0x5B40D0 goods 12..15: town byte load (disp 0x390 -> 0x391)"),
    ("P5-conv-A2", 0x5B41DA, ["movzx ecx, byte ptr [ebp + 0x390]", "cmp ecx, 4", "jae 0x5b41ef",
                              "mov ecx, dword ptr [ecx*4 + 0x702b14]", "jmp 0x5b41f1", "xor ecx, ecx",
                              "mov ecx, dword ptr [ecx + 0x20]"],
     "[P05 fix2 A2] convoy goods 12..15: town byte load -> CNation+0x20 deref"),
    ("P5-conv-B1", 0x5B42EB, ["movzx eax, byte ptr [ebp + 0x390]", "cmp eax, 4",
                              "mov dword ptr [esp + 0x9c], 0", "jae 0x5b432f",
                              "mov eax, dword ptr [eax*4 + 0x702b14]", "jmp 0x5b4331"],
     "[P05 fix2 B1] convoy goods 0..11 (not 12..15): town byte load -> CNation+0xC4 copy"),
    ("P5-conv-B2", 0x5B438D, ["movzx eax, byte ptr [ebp + 0x390]", "cmp eax, 4",
                              "lea edx, [esp + ecx*4 + 0x40]", "jae 0x5b43a6",
                              "mov eax, dword ptr [eax*4 + 0x702b14]", "jmp 0x5b43a8", "xor eax, eax",
                              "mov edx, dword ptr [edx]", "mov ecx, dword ptr [eax + ecx*4 + 0xc4]"],
     "[P05 fix2 B2] convoy goods 0..11: town byte load -> CNation+0xC4[g] read"),
    ("P5-annex-oldowner", 0x5BC476, ["mov cl, byte ptr [edi + 0x390]"],
     "[null_nation_census.md 2, P05 fix3] annexation 0x5BC310: old owner = town byte"),
    ("P5-annex-viceroy", 0x5BC49E, ["movzx eax, cl", "cmp eax, 4", "mov dword ptr [esp + 0x3c], eax",
                                    "jae 0x5bc4b3"],
     "[P05 fix3a] detour site (6 bytes displaced), resumes at 0x5BC4A4"),
    ("P5-annex-count", 0x5BC59D, ["inc word ptr [eax + 0x16c]", "mov ebp, dword ptr [esp + 0x18]"],
     "[P05 fix3b] old-owner annex counter (eax NULL for old owner >= 4)"),
    ("P5-annex-recount", 0x5BC5D1, ["push 1", "call 0x5bbb20", "mov eax, dword ptr [ebp + 0x44]"],
     "[P05 fix3b] old->0x5BBB20(1) (ecx NULL for old owner >= 4)"),
    ("P5-annex-abort", 0x5BCB6F, ["lea ecx, [esp + 0x14]", "mov dword ptr [esp + 0x70], 0xffffffff",
                                  "call 0x5a93e0", "mov ecx, dword ptr [esp + 0x68]"],
     "[P05 fix3a] vanilla annexation abort exit (returns al=0)"),
    ("P5-letter", 0x5E75C7, ["movzx eax, byte ptr [eax + 0x390]", "cmp eax, 4",
                             "mov dword ptr [esp + 0x24], 0xffffffff", "jae 0x5e75e4",
                             "mov eax, dword ptr [eax*4 + 0x702b14]", "jmp 0x5e75e6", "xor eax, eax",
                             "mov ecx, eax", "call 0x5bb0f0"],
     "[P05 fix4] CLetterBuildingLost::Create: town byte -> 0x5BB0F0 this (disp 0x390 -> 0x391)"),
    ("P5-nullthis-entry", 0x5BC100, ["mov eax, dword ptr fs:[0]", "push -1", "push 0x670418"],
     "[P05 H1] CNation 0x5BC100 entry (6-byte fs:[0] load displaced)"),
    ("P5-nullthis-thunk", 0x5EEA6A, ["xor eax, eax", "mov ecx, eax", "call 0x5bc100", "xor eax, eax",
                                     "ret"],
     "[P05 H1] event thunk 0x5EEA50 calls 0x5BC100 with this = NULL"),
    ("OF-reptier-entry", 0x5D2C10, ["mov eax, dword ptr [esp + 4]", "push eax", "call 0x5d2ac0"],
     "[officials.md] CPlayer::ReputationTier entry (5 bytes displaced by the officials hook)"),
    ("OF-rep-nation5", 0x5D2AC4, ["cmp al, 4", "jb 0x5d2ad8", "xor ecx, ecx", "cmp al, 5", "setne cl",
                                  "dec ecx", "and ecx, 0x64"],
     "[officials.md] CPlayer::Reputation: nation 5 -> 100, 4 / 0xFF -> 0"),
    ("OF-treasurer-site", 0x44485F, ["mov ecx, esi", "call 0x43edf0", "push eax",
                                     "mov eax, dword ptr [esi + 0x14]", "mov ecx, dword ptr [eax]",
                                     "call 0x5d2c10", "cmp al, 2"],
     "[officials.md] treasurer enter: tier with the NPC's nation < 2 -> state 1 (BAD_REP)"),
    ("OF-general-site", 0x417457, ["mov ecx, esi", "call 0x43edf0", "push eax",
                                   "mov eax, dword ptr [esi + 0x14]", "mov ecx, dword ptr [eax]",
                                   "call 0x5d2c10", "cmp al, 2"],
     "[officials.md] commander enter: tier with the NPC's nation < 2 -> state 1 (BAD_REP)"),
    ("OF-npc-nation-display", 0x444B71, ["mov al, byte ptr [ecx + 0x390]", "cmp al, 4", "jb 0x444b83",
                                         "xor eax, eax", "mov al, byte ptr [ecx + 0x391]"],
     "[officials.md] treasurer create: NPC nation = town byte, >= 4 -> display power"),
    # building permit (research/building_permit.md)
    ("BP-check", 0x61B51E, ["mov al, byte ptr [edi + 4]", "test al, al", "je 0x61b52f", "pop edi",
                            "mov al, 3"],
     "[building_permit.md] licence check 0x61B4C0: granted byte Licence+4 (Lager+0x9178) -> 3"),
    ("BP-grant-flag", 0x61B614, ["mov byte ptr [ebx + 4], 1"],
     "[building_permit.md] grant 0x61B570 sets Licence+4 = 1"),
    ("BP-sell-flag", 0x61B906, ["mov byte ptr [ecx + 4], 0"],
     "[building_permit.md] sale 0x61B770 clears Licence+4"),
    ("BP-lua-has", 0x423455, ["lea ecx, [esp + 4]", "call 0x5c2200", "mov ecx, dword ptr [esi]",
                              "add eax, 0x38", "movzx eax, byte ptr [eax + 0x9178]"],
     "[building_permit.md] Lua Player_HasLicence (0x4233F0) returns CStadt+0x38+0x9178 = CStadt+0x91B0"),
    ("BP-bmaster", 0x410A2B, ["mov al, byte ptr [ecx + 0x91b0]", "test al, al", "mov ecx, esi",
                              "je 0x410a5e"],
     "[building_permit.md] master builder: permit held (CStadt+0x91B0) -> sell page"),
    ("BP-bmaster-value", 0x410A48, ["lea ecx, [eax + 0x9174]", "call 0x61b1e0",
                                    "mov ecx, dword ptr [esi + 0x14]", "mov dword ptr [ecx + 8], eax"],
     "[building_permit.md] sale value 0x61B1E0 -> dialog+8; PR2Nation hooks 0x410A53 (6 bytes)"),
    ("BP-towninfo", 0x4A5119, ["mov al, byte ptr [ebx + 0x91b0]", "test al, al"],
     "[building_permit.md] town info (STADT_INFO) shows the permit from CStadt+0x91B0"),
    ("SM-reveal-site", 0x62C3E7, ["lea eax, [esp + 8]", "push eax", "call 0x402940"],
     "[sea_map_sight.md] visibility pass, after the reset loops: hook R (local player handle next)"),
    ("SM-reveal-player", 0x62C450, ["cmp byte ptr [eax + 0x3b], bl", "je 0x62c45e", "push 0x64",
                                    "mov ecx, eax", "call 0x62c760"],
     "[sea_map_sight.md] the player's convoys with +0x3B set reveal 100 units around them"),
    ("SM-setvisible", 0x5B2CA0, ["mov al, byte ptr [ecx + 0x1d]", "sub esp, 8", "test al, al",
                                 "mov byte ptr [ecx + 0x1c], 1"],
     "[sea_map_sight.md] convoy SetVisible: +0x1C = 1, signal 0x701EE4 if it was hidden"),
    ("SM-minimap-kind", 0x4804FF, ["mov eax, 2", "movsx edx, word ptr [edi + 0x12]", "push eax"],
     "[sea_map_sight.md] sea-map minimap dot kind in eax at 0x480504: hook M"),
    ("SM-goto-hotkey", 0x51DE0D, ["cmp dword ptr [esi + 0x6c], 2", "jne 0x51de1c", "push 1", "mov ecx, esi",
                                  "call 0x51caa0", "cmp dword ptr [esi + 0x6c], 1"],
     "[sea_map_sight.md] convoy key pressed twice: town view -> SetView(1), then CenterOnConvoy 0x516E30"),
    ("FL-name", 0x50C7C9, ['push 0x68db0c', 'lea ecx, [esp + 0x40]', 'mov byte ptr [esp + 0x54], 2'],
     "[flags.md 8] convoy flag name 0x50C740, nation-5 branch: hook 0x50C7CE swaps the pushed '0.bmp' for '7.bmp' (national ship)"),
    ("FL-select", 0x485C59, ['push 0x68db0c', 'lea ecx, [esp + 0x38]', 'mov byte ptr [esp + 0x4c], 2'],
     "[flags.md 8] selection panel 0x485BD0, convoy of nation 5: hook 0x485C5E (esi = convoy)"),
    ("FL-ifb1", 0x47D49B, ['push 0x68db0c', 'lea ecx, [esp + 0x5c]', 'mov dword ptr [esp + 0x7c], 0x15'],
     "[flags.md 8] interface bar 0x47C930, the player's own convoy: logo name compared; hook 0x47D4A0 (bar+0x1AC = convoy handle)"),
    ("FL-ifb2", 0x47D626, ['push 0x68db0c', 'lea ecx, [esp + 0x44]', 'mov dword ptr [esp + 0x7c], 0x1b'],
     "[flags.md 8] interface bar: the logo (bar+0x2C4) loaded from Run\\0.bmp; hook 0x47D62B"),
    ("FL-trade0", 0x463120, ['mov eax, dword ptr [esi + 0x6c]', 'test eax, eax', 'jne 0x463156'],
     "[flags.md 8] trade window caller 0x463120: +0x6C set or a bit-22 town -> push 5 (player logo); hook resets the town flag"),
    ("FL-trade1", 0x46314B, ['xor ecx, ecx', 'mov cl, byte ptr [eax + 0x358]', 'push ecx', 'jmp 0x463158'],
     "[flags.md 8] ... else the town's nation byte (lager+0x358); hook 0x46314B notes a nation-5 town"),
    ("FL-trade2", 0x594A0A, ['push 0x68db0c', 'lea ecx, [esp + 0x30]', 'mov byte ptr [esp + 0x44], 1'],
     "[flags.md 8] trade-window flag 0x5949C0 nation 5 -> Run\\0.bmp; hook 0x594A0F (nation-5 town -> 7.bmp)"),
    ("FL-seafeed", 0x5A2EE9, ['movzx edx, byte ptr [esi + 0xb8]', 'push edx', 'mov ecx, edi', 'call 0x5966c0'],
     "[flags.md 8] sea-map ship marker update: esi = convoy, edi = marker; hook 0x5A2EE9 (per-marker reload)"),
    ("FL-seaload", 0x59671C, ['push 0x68db0c', 'lea ecx, [esp + 0x40]', 'mov dword ptr [esp + 0x54], 1'],
     "[flags.md 8] sea-map ship marker 0x5966C0 nation 5 -> Run\\0.bmp; hook 0x596721"),
    ("FL-sea-cache", 0x5966DF, ['cmp dword ptr [esi + 0xa0], eax', 'je 0x59689f', 'cmp eax, 5', 'mov dword ptr [esi + 0xa0], eax', 'mov byte ptr [esi + 0x140], 0', 'jne 0x596806'],
     "[flags.md 8] the marker caches the nation at +0xA0 and loads the logo once (+0x141)"),
    ("FL-sail-scene", 0x63DED3, ['mov cl, byte ptr [edi + 0xb8]', 'cmp cl, 4', 'jae 0x63def5'],
     "[flags.md 8] port scene re-flag 0x63DE20 (edi = convoy): nation <4 -> sail 9"),
    ("FL-sail-scene2", 0x63DEF5, ['xor edx, edx', 'cmp cl, 5', 'sete dl', 'movzx ecx, cl', 'dec edx', 'and edx, 8', 'push edx', 'push ecx'],
     "[flags.md 8] ... nation 5 -> sail 0 (Player0.aim), else 8; jmp-hook 0x63DEF5 gives national ships 7"),
    ("FL-sail-new", 0x570EE1, ['cmp bl, 4', 'jae 0x570eed', 'mov ecx, 9', 'jmp 0x570ef9', 'xor ecx, ecx', 'cmp bl, 5', 'sete cl', 'dec ecx', 'and ecx, 8', 'push ecx', 'movzx ecx, bl'],
     "[flags.md 8] port scene ship creation 0x570D40: same sail index; jmp-hook 0x570EED (arg 1 = convoy handle)"),
    ("FL-battle", 0x4FAB7E, ['mov edx, dword ptr [eax*4 + 0x6e12ec]', 'mov dword ptr [esp + 0x28], 0', 'push edx', 'call dword ptr [0x67f9b8]', 'mov ecx, dword ptr [esp + 0x30]'],
     "[flags.md 8] battle dialog convoy flag 0x4FAA60: nation-icon table -> CFlag; hook 0x4FAB85 (player convoy -> -userflag-)"),
    ("FL-tinfo", 0x4A40CB, ['mov eax, dword ptr [esp + 0x1c]', 'mov ecx, dword ptr [eax + 0x40]', 'shr ecx, 0x16', 'test cl, 1', 'je 0x4a40e1', 'mov eax, 5', 'jmp 0x4a40e8', 'movzx eax, byte ptr [eax + 0x390]'],
     "[flags.md 8] town info dialog: bit-22 player town -> index 5; hook 0x4A40E8 notes it"),
    ("FL-tinfo-l", 0x4A413C, ['mov eax, dword ptr [ebp*4 + 0x6e12ec]', 'sub esp, 0xc', 'mov ecx, esp'],
     "[flags.md 8] town info dialog left flag from the nation-icon table; hook 0x4A4143"),
    ("FL-tinfo-r", 0x4A41BD, ['mov eax, dword ptr [ebp*4 + 0x6e12ec]', 'sub esp, 0xc', 'mov ecx, esp'],
     "[flags.md 8] town info dialog right flag; hook 0x4A41C4"),
    ("FL-marker", 0x590284, ['push 0x68db0c', 'lea ecx, [esp + 0x28]', 'mov dword ptr [esp + 0x68], 1'],
     "[flags.md 8] sea-map town marker of a nation-5 town loads Run\\0.bmp into holder+0x268; hook 0x590289 -> 7.bmp"),
    ("FL-holder", 0x590259, ['mov eax, dword ptr [0x701424]', 'mov ecx, dword ptr [eax + 0x268]', 'test ecx, ecx', 'jne 0x59034e', 'cmp dword ptr [esi + 0x190], 4', 'jne 0x59034e'],
     "[flags.md 8] the town-marker image is loaded once per holder [0x701424]+0x268 (dropped on a flag change)"),
    ("FL-logo-refresh", 0x5263ED, ['call 0x403360', 'mov eax, dword ptr [eax]', 'mov ecx, dword ptr [eax + 0xec]', 'call 0x5003d0'],
     "[flags.md 8] after a load the game refreshes the interface bar's logo: 0x5003D0(*(*0x403360())+0xEC)"),
    ("FL-ship-new", 0x570D40, ['push -1', 'push 0x66ab5b', 'mov eax, dword ptr fs:[0]'],
     "[flags.md 8] port scene ship creation 0x570D40(type, convoy handle, nation, ...): hook at the entry keeps the handle"),
    ("FL-ship-slot", 0x570DCD, ['mov dword ptr [esp + 0x28], eax'],
     "[flags.md 8] ... because the new ship object overwrites the handle's argument slot"),
    ("FL-infobar-update", 0x47D805, ['mov eax, dword ptr [esi + 0x1ac]', 'and eax, 0xffff', 'cmp eax, 0xffff', 'je 0x47d82f',
                                    'mov eax, dword ptr [esi + 0x2dc]', 'test eax, eax', 'je 0x47d826', 'cmp eax, 4',
                                    'jne 0x47d82f', 'mov ecx, esi', 'call 0x47c930'],
     "[flags.md 8] interface bar: a selected convoy (+0x1AC) in mode 0/4 is drawn by 0x47C930 (re-run after a load / designation)"),
    ("FL-scene-town", 0x635C40, ['push ecx', 'mov eax, dword ptr [esp]', 'mov ecx, dword ptr [ecx + 0x50]'],
     "[flags.md 8] 0x635C40(convoy+0x4C): the town the convoy lies in (handle at convoy+0x9C)"),
    ("TI-section-nation", 0x4A3DD8, ["movzx ebp, byte ptr [ebx + 0x390]", "shr eax, 0x16", "test al, 1",
                                     "mov dword ptr [esp + 0x10], ebp", "je 0x4a3df9", "lea ecx, [ebx + 0x38]",
                                     "call 0x40fc70", "movzx ebp, al", "mov dword ptr [esp + 0x10], ebp"],
     "[town_info_owner.md 1] town info dialog: the section's nation (ebp/[esp+0x10]); P07 turns +0x390 into +0x391"),
    ("TI-section-heading", 0x4A3E03, ["lea ecx, [esp + 0x24]", "push ebp", "push ecx",
                                      "mov dword ptr [esp + 0x68], 1", "call 0x4081b0"],
     "[town_info_owner.md 1] ... its name for the heading 'Your relationship with %1' (IDPR_SID_VERH...)"),
    ("TI-section-heading-set", 0x4A3E38, ["mov ecx, dword ptr [esi + 0xc0]", "push eax"],
     "[town_info_owner.md 1] ... into SID_VerhaeltnisZu (dialog+0xC0)"),
    ("TI-section-tier", 0x4A3FEB, ["mov ecx, dword ptr [esp + 0x10]", "push ecx", "push ecx"],
     "[town_info_owner.md 1] ... the player's reputation tier with it (0x5D2C10 at 0x4A400C)"),
    ("TI-section-tier-call", 0x4A400C, ["call 0x5d2c10"],
     "[town_info_owner.md 1] CPlayer::ReputationTier(nation)"),
    ("TI-section-word", 0x4A40A3, ["call 0x407330", "add esp, 8", "mov ecx, dword ptr [esi + 0xcc]"],
     "[town_info_owner.md 1] the relation word into SID_Verhaeltniss (dialog+0xCC)"),
    ("TI-section-natflags", 0x4A36B6, ["lea edx, [esi + 0x7c]"],
     "[town_info_owner.md 1] SID_Nat_00..03 are kept at dialog+0x7C.."),
    ("TI-role-set", 0x4A3F76, ["mov ecx, dword ptr [esi + 0xc4]", "push eax"],
     "[town_info_owner.md 1] the town type line (IDPR_SID_*_%02d) into SID_StadtTyp (dialog+0xC4)"),
    ("TI-name-invalid", 0x4081CC, ["cmp al, 4", "jae 0x408226"],
     "[town_info_owner.md 3] nation-name helper 0x4081B0: nation >= 4 ..."),
    ("TI-name-invalid2", 0x408226, ["mov ecx, dword ptr [esp + 0x1c]", "push 0x680e84",
                                    "call dword ptr [0x67fa24]"],
     "[town_info_owner.md 3] ... gets L\"Invalid\"; towninfo.c hooks the call at 0x40822F for nation 5"),
    ("TI-polmap-raw", 0x4D9C1B, ["mov cl, byte ptr [esi + 0x390]", "mov byte ptr [esp + 0x54], cl",
                                 "mov edx, dword ptr [esp + 0x54]", "push edx", "lea eax, [esp + 0x18]",
                                 "push eax", "call 0x4081b0"],
     "[town_info_owner.md 3] political map tooltip: a town's raw nation byte -> 0x4081B0"),
    ("TI-display-getter", 0x5BE072, ["mov al, byte ptr [ecx + 0x390]", "cmp al, 4", "jb 0x5be0a0",
                                     "mov al, byte ptr [ecx + 0x391]"],
     "[town_info_owner.md 4] a generic owner getter answers the display power for a nation-5 town"),
    ("TI-addrep-display", 0x5D5897, ["mov cl, byte ptr [eax + 0x390]", "add eax, 0x38", "cmp cl, 4",
                                     "jae 0x5d58a9", "mov al, cl", "jmp 0x5d58b0",
                                     "movzx eax, byte ptr [eax + 0x359]", "push eax"],
     "[town_info_owner.md 4] 0x5D5840: AddReputation (0x5D45F0) with a town's display power"),
    ("NV-harbour-task", 0x5B53CF, ["call 0x5ada80", "cmp dword ptr [esi + 0x1b8], ebp", "je 0x5b53ff",
                                   "mov ecx, esi", "call 0x5b0c70"],
     "[navy_operations.md 3.4] harbour AI: while an MTask runs it skips the harbour cycle (no sailing out)"),
    ("NV-task-replan", 0x5B0BB8, ["mov ecx, esi", "push edx", "push eax", "call 0x5ad9f0"],
     "[navy_operations.md 3.4] out of the circle the task is only re-planned (TaskCircle), no LeaveTown"),
    ("NV-sailtopos-leave", 0x5AE212, ["mov ecx, ebp", "mov edi, eax", "call 0x6374a0"],
     "[navy_operations.md 3.4] SailToPos 0x5AE1B0 (via SailToTown) leaves the town: LeaveTown 0x6374A0"),
    ("NV-docked-timer", 0x5B5D7D, ["mov eax, dword ptr [esi + 0x198]", "test eax, eax", "jne 0x5b5e40",
                                   "mov ecx, esi", "call 0x5b53c0"],
     "[navy_operations.md 3.4] state 2 (docked): timer +0x198, then the harbour AI"),
    ("NV-tasknone", 0x5ADAF0, ["push esi", "mov esi, ecx", "mov eax, dword ptr [esi + 0x1b8]", "test eax, eax"],
     "[navy_operations.md 3.4] TaskNone 0x5ADAF0 clears the MTask"),
    ("QT-quit-yes", 0x521B21, ["mov ecx, 0x700500", "call 0x57ecc0", "call 0x403360", "mov ecx, dword ptr [eax]",
                               "mov edx, dword ptr [ecx]", "call dword ptr [edx + 0xc]", "push 1",
                               "call dword ptr [0x67f7d8]"],
     "[quit_hang.md] Quit -> Yes: autosave, game state leave (0x4037A0), PostQuitMessage(1)"),
    ("QT-leave-clear", 0x4037D8, ["mov ecx, 0x700500", "call 0x5809a0"],
     "[quit_hang.md] the game state's leave 0x4037A0 runs Session::Clear"),
    ("QT-shutdown-leave", 0x40A9D3, ["mov ecx, dword ptr [edi + 0x44]", "test ecx, ecx", "je 0x40a9df",
                                     "mov eax, dword ptr [ecx]", "call dword ptr [eax + 0xc]"],
     "[quit_hang.md] app shutdown 0x40A9D0 leaves the current state again: the second Session::Clear"),
]

STRING_FACTS = [
    ("L1-str", 0x684938, b"PIRATEN_NATION"),
    ("L2-str", 0x684928, b"SPIELER_NATION"),
    ("VP-str-isplayertown", 0x686450, b"Town_IsPlayerTown"),
    ("IX-U5-str", 0x6A0034, b"music/voice/Willkommen_%s_%02d.mp3"),
    ("BP-str-has", 0x6869AC, b"Player_HasLicence"),
    ("BP-str-set", 0x6860AC, b"Player_SetLicence"),
    ("FL-str-logo", 0x68DB0C, b"0.bmp"),
    ("FL-str-userflag", 0x689970, b"-userflag-"),
]

# (id, va, expected raw bytes, meaning)
DATA_FACTS = [
    ("UF-icon-table", 0x6E12EC,
     bytes.fromhex("009a6800 e0996800 c0996800 a0996800 7c996800 70996800"),
     "[userflag.md] nation icon pointer table[6]; slot 5 (0x6E1300) -> 0x689970"),
    ("IX-D1-milconvoy-types", 0x6AC4B4, bytes.fromhex("0f0d0c0e00f0"),
     "[nation5_index_safety.md D1] byte[4] military ship types; index 5 reads 0xF0"),
    ("IX-D2-row0", 0x6A5174, bytes.fromhex("000102030507080a"),
     "[nation5_index_safety.md D2] per-nation ship-type row 0"),
    ("IX-D2-row4-5", 0x6A5194, bytes.fromhex("646464644a326432 32000000050d1015"),
     "[nation5_index_safety.md D2] rows 4 and 5 (0x6A519C: types 50 and 21 invalid)"),
    ("IX-D3-voice-abbr", 0x6A0058, b"Sp\0\0Ho\0\0Fr\0\0En\0\0",
     "[nation5_index_safety.md D3] welcome-voice nation abbreviations"),
    ("IX-U6-bytes-5C6A86", 0x5C6A86, bytes.fromhex("8a9f90030000"), "[nation5_index_safety.md U6] P03 bytes"),
    ("IX-U6-bytes-5A80B0", 0x5A80B0, bytes.fromhex("8a9b90030000"), "[nation5_index_safety.md U6] P03 bytes"),
    ("IX-U6-bytes-5A822C", 0x5A822C, bytes.fromhex("8a9f90030000"), "[nation5_index_safety.md U6] P03 bytes"),
    ("IX-U6-bytes-6352B7", 0x6352B7, bytes.fromhex("0fb68058030000"), "[nation5_index_safety.md U6] P03 bytes"),
    ("IX-U6-bytes-634902", 0x634902, bytes.fromhex("8a8058030000"), "[nation5_index_safety.md U6] P03 bytes"),
    ("IX-U6-bytes-57D0B6", 0x57D0B6, bytes.fromhex("8a8058030000"), "[nation5_index_safety.md U6] P03 bytes"),
    ("UF-P02-bytes", 0x4C1411, bytes.fromhex("0f84d4000000"),
     "[userflag.md P1/P02] je 0x4C14EB; P02 writes 0f84 0e010000 (je 0x4C1525)"),
    ("GF-speed-table", 0x6A500C, struct.pack("<7H", 8000, 800, 160, 80, 40, 0, 8),
     "[game_flow_entry_points.md] ms-per-tick table: 8000, 800, 160, 80, 40, 0, 8"),
    ("VP-viceroy-vtable", 0x688A90, struct.pack("<I", 0x447520),
     "[vanilla_nation5_path.md 1.3] viceroy vtable 0x688A58 slot 14 = 0x447520"),
]

# (id, call target, exact list of E8 call sites, meaning)
CALLER_FACTS = [
    ("QT-autosave-callers", 0x57ECC0, [0x424DC7, 0x521B26, 0x521DBF],
     "[quit_hang.md] Autosave: Lua Global_SaveGame(\"\") (scenarios), Quit -> Yes, the Leave dialog; no timer"),
    ("CR-lookup-callers", 0x4C13B0, [0x4C1D0C],
     "[userflag.md] 0x4C13B0 has one caller, so P02's return-false change only reaches 0x4C1CD0"),
    ("UF-setter-callers", 0x4C1CD0,
     [0x4860BA, 0x4A63CA, 0x4B3436, 0x4B7D00, 0x4DB73F, 0x4E138D, 0x4E13B3, 0x52A9B0, 0x52AA0B],
     "[userflag.md] 0x4C1CD0 callers: 3 %6 icon sites + 6 non-nation ones"),
    ("HO-isatwar-callers", 0x5BA0A0,
     [0x41BE75, 0x41D479, 0x448161, 0x4482FA, 0x44863F, 0x448811, 0x4B1A51, 0x5AD937, 0x5B5195,
      0x5D10A4, 0x5D10C2, 0x5D3419, 0x5D4578, 0x5F5395, 0x63B407, 0x63BA43, 0x63C345, 0x63C48A],
     "[hostility_map.md 1] IsAtWar has exactly 18 direct callers"),
    ("HO-getrep-callers", 0x5D2AC0,
     [0x41D5CB, 0x5A7355, 0x5B6BA6, 0x5B6D83, 0x5D2C15, 0x5D44FE, 0x5F5531, 0x5F5544, 0x61134F],
     "[hostility_map.md 2.2] GetReputation: 9 direct callers (incl. GetReputationLevel)"),
    ("GF-quicksave-callers", 0x57EE90, [0x500432, 0x522751],
     "[game_flow_entry_points.md] QuickSave callers (both with ecx=0x700500)"),
    ("GF-load-callers", 0x526470, [0x4EE1B4],
     "[game_flow_entry_points.md] StartFromFile has one direct call"),
    ("VP-create-callers", 0x61C7A0, [0x44755A],
     "[vanilla_nation5_path.md 1.2] 0x61C7A0's only caller is the viceroy slot 14"),
    ("VP-stamp-callers", 0x61BDE0, [0x61C8A8],
     "[vanilla_nation5_path.md 1.1] 0x61BDE0's only caller is 0x61C8A8"),
    ("VP-setflags-callers", 0x624D30, [0x61BE91],
     "[vanilla_nation5_path.md 1.1] 0x624D30's only caller is the player-town stamp"),
    ("BP-grant-callers", 0x6211A0, [0x4107E6, 0x428F77, 0x5A874C, 0x61C8B8],
     "[building_permit.md] licence grant: master builder purchase, Lua Player_SetLicence, start town, "
     "town creation; nothing revokes a permit except the sale"),
    ("BP-sell-callers", 0x61B770, [0x40FCAA, 0x410823],
     "[building_permit.md] licence sale: Lua Player_SetLicence(.., false) and the master builder"),
]

# (id, call target, expected number of E8 call sites, meaning)
CALL_COUNT_FACTS = [
    ("HO-replevel-count", 0x5D2C10, 55, "[hostility_map.md] GetReputationLevel has 55 call sites"),
    ("HO-isrep25-count", 0x5D2D90, 13, "[hostility_map.md] IsRepAtLeast25 has 13 call sites"),
]


class Image:
    def __init__(self, path):
        self.data = path.read_bytes()
        self.pe = pefile.PE(data=self.data, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.text = next(s for s in self.pe.sections if s.Name.rstrip(b"\0") == b".text")

    def read(self, va, n):
        rva = va - self.base
        for s in self.pe.sections:
            size = max(s.Misc_VirtualSize, s.SizeOfRawData)
            if s.VirtualAddress <= rva < s.VirtualAddress + size:
                off = rva - s.VirtualAddress + s.PointerToRawData
                return self.data[off:off + n]
        raise ValueError(f"VA {va:#x} not in any section")

    def cstr(self, va):
        return self.read(va, 64).split(b"\0")[0]

    def _text_raw(self):
        return self.data[self.text.PointerToRawData:self.text.PointerToRawData + self.text.SizeOfRawData]

    def text_refs(self, va):
        return self._text_raw().count(struct.pack("<I", va))

    def call_sites(self, target):
        raw, tva = self._text_raw(), self.base + self.text.VirtualAddress
        return [tva + i for i in range(len(raw) - 5)
                if raw[i] == 0xE8
                and (tva + i + 5 + struct.unpack("<i", raw[i + 1:i + 5])[0]) & 0xFFFFFFFF == target]


def classify_nation_refs(img, md):
    """Bucket every code reference to g_nations by how it's bounded."""
    raw, tva = img._text_raw(), img.base + img.text.VirtualAddress
    key, counts = struct.pack("<I", G_NATIONS), {}
    i = raw.find(key)
    while i != -1:
        site = tva + i
        insns = []
        # x86 decoding self-synchronises; find a start that lands on the site.
        for back in range(80, 40, -1):
            decoded = []
            for ins in md.disasm(img.read(site - back, back + 8), site - back):
                decoded.append(ins)
                if ins.address <= site < ins.address + ins.size:
                    break
            if decoded and decoded[-1].address <= site < decoded[-1].address + decoded[-1].size:
                insns = decoded
                break
        prev = [f"{p.mnemonic} {p.op_str}" for p in insns[-9:-1]]
        here = f"{insns[-1].mnemonic} {insns[-1].op_str}" if insns else ""
        if any(p.startswith("cmp ") and p.endswith((", 4", ", 5")) for p in prev):
            kind = "guard<4"
        elif any(p.startswith("cmp ") and p.endswith(", 0x10") for p in prev[-2:]):
            kind = "loop4"
        elif ", 0x702b14" in here and "[" not in here.split(",", 1)[1]:
            kind = "basewalk"
        else:
            kind = f"UNGUARDED@{site:#x}"
        counts[kind] = counts.get(kind, 0) + 1
        i = raw.find(key, i + 1)
    return counts


def main():
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EXE
    if not exe.exists():
        raise SystemExit(f"no DRM-free exe at {exe}: set SN_BASE_EXE or pass the path (python tools/sn_paths.py)")
    img = Image(exe)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    results = []

    def check(fid, ok, meaning, detail=""):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {fid:<24} {meaning}")
        if not ok and detail:
            print(f"      {detail}")

    sha = hashlib.sha256(img.data).hexdigest()
    check("B0-build", sha == PINNED_SHA256, f"exe is the pinned build ({exe.name})",
          f"got {sha}")

    names = [img.cstr(p) for p in struct.unpack("<4I", img.read(G_NATION_NAMES, 16))]
    check("N0-names", names == [b"England", b"Frankreich", b"Holland", b"Spanien"],
          "g_nationNames[4] @0x6E41E0 = England, Frankreich, Holland, Spanien (ids 0..3)",
          f"got {names}")

    refs = {va: img.text_refs(va) for va in range(G_NATIONS, G_NATIONS + 0x14, 4)}
    check("N0-table", refs[G_NATIONS] == 109 and refs[G_NATIONS + 0x10] == 0,
          "g_nations[4] @0x702B14: 109 code refs, none to slot [4] (array is exactly 4)",
          f"refs {[(hex(k), v) for k, v in refs.items()]}")

    guards = classify_nation_refs(img, md)
    check("N0-guards", guards == {"guard<4": 100, "loop4": 6, "basewalk": 3},
          "every g_nations access is either guarded by cmp x,4 (100), a fixed 4-slot "
          "loop cmp i,0x10 (6) or a base-pointer walk (3): no unguarded index, so "
          "nation 5 can never read past the array via a direct reference",
          f"got {guards}")

    callers = img.call_sites(0x5C9DA0)
    check("T0-setter-callers", callers == [0x4292D1, 0x5BC5B5, 0x61BE8A, 0x61C3C6],
          "CStadtLager::AddToNation @0x5C9DA0 has exactly 4 direct callers "
          "(Lua Town_SetNation, annexation, force-path 0x61BDE0, CStadtCreate)",
          f"got {[hex(c) for c in callers]}")

    for fid, va, want, meaning in CODE_FACTS:
        got = []
        for ins in md.disasm(img.read(va, 16 * len(want)), va):
            got.append(f"{ins.mnemonic} {ins.op_str}".strip())
            if len(got) == len(want):
                break
        check(fid, got == want, f"@{va:#x} {meaning}", f"got {got}")

    for fid, va, want in STRING_FACTS:
        got = img.cstr(va)
        check(fid, got == want, f"@{va:#x} string {want.decode()}", f"got {got!r}")

    for fid, va, want, meaning in DATA_FACTS:
        got = img.read(va, len(want))
        check(fid, got == want, f"@{va:#x} bytes {meaning}", f"got {got.hex()}")

    icons = [img.cstr(p) for p in struct.unpack("<6I", img.read(0x6E12EC, 24))]
    check("UF-icon-strings", icons == [
        b"images\\interface\\nation00.aim", b"images\\interface\\nation01.aim",
        b"images\\interface\\nation02.aim", b"images\\interface\\nation03.aim",
        b"images\\interface\\nation_piraten.aim", b"-userflag-"]
          and img.text_refs(0x6E12EC) == 11,
          "[userflag.md] icon table: [0..3] nation0N.aim, [4] nation_piraten.aim, "
          "[5] '-userflag-'; 11 code refs to the table", f"got {icons}, refs {img.text_refs(0x6E12EC)}")

    for fid, target, want, meaning in CALLER_FACTS:
        got = img.call_sites(target)
        check(fid, got == want, f"{target:#x} {meaning}", f"got {[hex(c) for c in got]}")

    for fid, target, want, meaning in CALL_COUNT_FACTS:
        got = len(img.call_sites(target))
        check(fid, got == want, f"{target:#x} {meaning}", f"got {got}")

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} facts hold")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
