/* PR2Nation loader: version.dll in the game folder (the player setup, research/user_install.md).
 *
 * The game imports VERSION.dll (GetFileVersionInfoA, GetFileVersionInfoSizeA, VerQueryValueA),
 * which is not a KnownDLL, so Windows loads this file from the game folder first. Every
 * export forwards to the real version.dll from the system folder (loaded on first use).
 *
 * The mod: PR2.exe stays untouched on disk, the Steam DRM runs as always. In DllMain the
 * loader only hooks one import slot, MSVCR71!__set_app_type (the `hook` record of the patch
 * data). The C runtime calls it right after the program's entry point, i.e. after the game
 * code is in memory in its final form. At that call (identified by its return address) the
 * loader
 *   1. checks the original bytes of EVERY patch site in the patch data
 *      (PR2Nation.patches, exported from patches/p01..p07 by tools/export_patches.py);
 *   2. on any mismatch patches nothing, logs why and lets the game start without the mod;
 *   3. else puts the patch section at its file address 0x9F7000 if that memory is free,
 *      otherwise anywhere (applying the data's relocations and telling PR2Nation.dll where
 *      in PR2NATION_SECTION), writes the patches, and loads PR2Nation.dll as patch P06 does;
 *   4. puts the import slot back and calls the real __set_app_type.
 * An exe that already carries the patches (PR2_nation.exe, the file route) is left alone.
 * PR2NATION_OFF=1 in the environment starts the game without the mod. Log: PR2Loader.log.
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "sha256.h"

/* ---- the real version.dll ---------------------------------------------------------- */
static const char *const k_names[17] = {
    "GetFileVersionInfoA", "GetFileVersionInfoByHandle", "GetFileVersionInfoExA", "GetFileVersionInfoExW",
    "GetFileVersionInfoSizeA", "GetFileVersionInfoSizeExA", "GetFileVersionInfoSizeExW", "GetFileVersionInfoSizeW",
    "GetFileVersionInfoW", "VerFindFileA", "VerFindFileW", "VerInstallFileA", "VerInstallFileW",
    "VerLanguageNameA", "VerLanguageNameW", "VerQueryValueA", "VerQueryValueW"};
FARPROC g_real[17];

void ensure_real(void)
{
    static HMODULE h;
    if (h) return;
    char path[MAX_PATH];
    UINT n = GetSystemDirectoryA(path, MAX_PATH);           /* SysWOW64 for this 32-bit process */
    lstrcpynA(path + n, "\\version.dll", MAX_PATH - (int)n);
    h = LoadLibraryA(path);
    for (int i = 0; i < 17; i++) g_real[i] = h ? GetProcAddress(h, k_names[i]) : NULL;
}

/* each export: make sure the real DLL is there, then jump to its function (arguments untouched) */
#define STUB(i, name) __asm__(".globl _" #name "_proxy\n_" #name "_proxy:\n\tcall _ensure_real\n" \
                              "\tjmp *_g_real+" #i "*4\n");
STUB(0, GetFileVersionInfoA) STUB(1, GetFileVersionInfoByHandle) STUB(2, GetFileVersionInfoExA)
STUB(3, GetFileVersionInfoExW) STUB(4, GetFileVersionInfoSizeA) STUB(5, GetFileVersionInfoSizeExA)
STUB(6, GetFileVersionInfoSizeExW) STUB(7, GetFileVersionInfoSizeW) STUB(8, GetFileVersionInfoW)
STUB(9, VerFindFileA) STUB(10, VerFindFileW) STUB(11, VerInstallFileA) STUB(12, VerInstallFileW)
STUB(13, VerLanguageNameA) STUB(14, VerLanguageNameW) STUB(15, VerQueryValueA) STUB(16, VerQueryValueW)

/* ---- log ----------------------------------------------------------------------------- */
static char g_dir[MAX_PATH];

static void lg(const char *fmt, ...)
{
    char path[MAX_PATH + 32], line[600];
    snprintf(path, sizeof path, "%sPR2Loader.log", g_dir);
    SYSTEMTIME t;
    GetLocalTime(&t);
    int n = snprintf(line, sizeof line, "%02d:%02d:%02d ", t.wHour, t.wMinute, t.wSecond);
    va_list ap;
    va_start(ap, fmt);
    n += vsnprintf(line + n, sizeof line - n, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof line - 3) n = (int)sizeof line - 3;
    line[n++] = '\r';
    line[n++] = '\n';
    HANDLE f = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return;
    DWORD w;
    WriteFile(f, line, (DWORD)n, &w, NULL);
    CloseHandle(f);
}

/* ---- the patch data (format: tools/export_patches.py, loader/README.md) ---------------- */
#define MAX_PATCHES 64
#define MAX_RELOCS  64
typedef struct { uint32_t va; uint8_t old[16], neu[16]; int n; } Patch;
static struct {
    uint32_t sec_va, sec_size, hook_slot, hook_ret;
    uint8_t *sec;
    Patch p[MAX_PATCHES];
    int np;
    struct { uint32_t off; int sign; } sr[MAX_RELOCS];
    int nsr;
    struct { int patch; uint32_t off; int sign; } pr[MAX_RELOCS];
    int npr;
    char dll[64];
} g_d;

static int hexbytes(const char *h, uint8_t *out, int cap)
{
    int n = 0;
    while (h[0] && h[1] && n < cap) {
        unsigned v;
        if (sscanf(h, "%2x", &v) != 1) return -1;
        out[n++] = (uint8_t)v;
        h += 2;
    }
    return *h ? -1 : n;
}

static int load_data(void)
{
    char path[MAX_PATH + 32];
    snprintf(path, sizeof path, "%sPR2Nation.patches", g_dir);
    FILE *f = fopen(path, "rb");
    if (!f) { lg("no PR2Nation.patches next to the game: the game starts without the mod"); return 0; }
    static char text[64 * 1024];
    size_t len = fread(text, 1, sizeof text - 1, f);
    fclose(f);
    text[len] = 0;
    /* normalise line ends, find the end line, check the body's checksum */
    size_t w = 0;
    for (size_t i = 0; i < len; i++) if (text[i] != '\r') text[w++] = text[i];
    text[w] = 0;
    while (w && text[w - 1] == '\n') text[--w] = 0;
    char *end = strrchr(text, '\n');
    if (!end || strncmp(end + 1, "end ", 4) || strncmp(text, "PR2NATION-PATCHDATA 1\n", 22)) {
        lg("PR2Nation.patches is not patch data version 1");
        return 0;
    }
    char hex[65];
    sha256_hex(text, (size_t)(end - text) + 1, hex);
    if (strncmp(end + 5, hex, 64)) { lg("PR2Nation.patches is damaged (checksum)"); return 0; }
    *end = 0;
    g_d.sec = NULL;
    for (char *ln = strtok(text, "\n"); ln; ln = strtok(NULL, "\n")) {
        char *semi = strstr(ln, " ;");
        if (semi) *semi = 0;
        char k[16] = "", a[80] = "", b[80] = "", c[80] = "", d[16] = "";
        int nf = sscanf(ln, "%15s %79s %79s %79s %15s", k, a, b, c, d);
        if (nf < 1 || k[0] == '#') continue;
        if (!strcmp(k, "section") && nf >= 3) {
            g_d.sec_va = strtoul(a, NULL, 16);
            g_d.sec_size = strtoul(b, NULL, 16);
            if (!g_d.sec_size || g_d.sec_size > 0x10000) return 0;
            g_d.sec = calloc(1, g_d.sec_size);
        } else if (!strcmp(k, "data") && nf >= 3 && g_d.sec) {
            uint32_t off = strtoul(a, NULL, 16);
            uint8_t buf[64];
            int n = hexbytes(b, buf, sizeof buf);
            if (n < 0 || off + (uint32_t)n > g_d.sec_size) return 0;
            memcpy(g_d.sec + off, buf, (size_t)n);
        } else if (!strcmp(k, "patch") && nf >= 4 && g_d.np < MAX_PATCHES) {
            Patch *p = &g_d.p[g_d.np++];
            p->va = strtoul(a, NULL, 16);
            p->n = hexbytes(b, p->old, sizeof p->old);
            if (p->n <= 0 || hexbytes(c, p->neu, sizeof p->neu) != p->n) return 0;
        } else if (!strcmp(k, "reloc") && nf >= 4) {
            if (a[0] == 'S' && g_d.nsr < MAX_RELOCS) {
                g_d.sr[g_d.nsr].off = strtoul(b, NULL, 16);
                g_d.sr[g_d.nsr++].sign = c[0] == '-' ? -1 : 1;
            } else if (a[0] == 'P' && nf >= 5 && g_d.npr < MAX_RELOCS) {
                g_d.pr[g_d.npr].patch = atoi(b);
                g_d.pr[g_d.npr].off = strtoul(c, NULL, 16);
                g_d.pr[g_d.npr++].sign = d[0] == '-' ? -1 : 1;
            }
        } else if (!strcmp(k, "hook") && nf >= 3) {
            g_d.hook_slot = strtoul(a, NULL, 16);
            g_d.hook_ret = strtoul(b, NULL, 16);
        } else if (!strcmp(k, "dll") && nf >= 2) {
            lstrcpynA(g_d.dll, a, sizeof g_d.dll);
        }
    }
    if (!g_d.sec || !g_d.np || !g_d.hook_slot || !g_d.dll[0]) { lg("PR2Nation.patches is incomplete"); return 0; }
    for (int i = 0; i < g_d.npr; i++)
        if (g_d.pr[i].patch < 0 || g_d.pr[i].patch >= g_d.np || g_d.pr[i].off + 4 > (uint32_t)g_d.p[g_d.pr[i].patch].n)
            return 0;
    for (int i = 0; i < g_d.nsr; i++)
        if (g_d.sr[i].off + 4 > g_d.sec_size) return 0;
    return 1;
}

/* ---- patching ------------------------------------------------------------------------- */
static int readable(uint32_t va, int n)
{
    MEMORY_BASIC_INFORMATION mi;
    if (!VirtualQuery((void *)(uintptr_t)va, &mi, sizeof mi) || mi.State != MEM_COMMIT) return 0;
    return va + (uint32_t)n <= (uint32_t)(uintptr_t)mi.BaseAddress + (uint32_t)mi.RegionSize;
}

static void write_mem(uint32_t va, const void *src, size_t n)
{
    DWORD old;
    VirtualProtect((void *)(uintptr_t)va, n, PAGE_EXECUTE_READWRITE, &old);
    memcpy((void *)(uintptr_t)va, src, n);
    VirtualProtect((void *)(uintptr_t)va, n, old, &old);
}

static void fix(uint8_t *at, int sign, uint32_t delta)
{
    uint32_t v;
    memcpy(&v, at, 4);
    v += sign > 0 ? delta : (uint32_t)-delta;
    memcpy(at, &v, 4);
}

static void apply(void)
{
    /* already patched on disk (PR2_nation.exe, the file route): nothing to do */
    for (int i = 0; i < g_d.np; i++)
        if (readable(g_d.p[i].va, g_d.p[i].n) && !memcmp((void *)(uintptr_t)g_d.p[i].va, g_d.p[i].neu, g_d.p[i].n) &&
            readable(g_d.sec_va, 16)) {
            lg("this exe already carries the patches (file route): loader idle");
            return;
        }
    for (int i = 0; i < g_d.np; i++) {
        const Patch *p = &g_d.p[i];
        if (!readable(p->va, p->n) || memcmp((void *)(uintptr_t)p->va, p->old, p->n)) {
            lg("original bytes differ at %08X: not the game build the mod was made for; "
                 "nothing patched, the game starts without the mod", p->va);
            return;
        }
    }
    uint8_t *at = VirtualAlloc((void *)(uintptr_t)g_d.sec_va, g_d.sec_size, MEM_RESERVE | MEM_COMMIT,
                               PAGE_EXECUTE_READWRITE);
    if (!at) at = VirtualAlloc(NULL, g_d.sec_size, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
    if (!at) { lg("no memory for the patch section: the game starts without the mod"); return; }
    uint32_t delta = (uint32_t)(uintptr_t)at - g_d.sec_va;
    memcpy(at, g_d.sec, g_d.sec_size);
    for (int i = 0; i < g_d.nsr; i++) fix(at + g_d.sr[i].off, g_d.sr[i].sign, delta);
    for (int i = 0; i < g_d.npr; i++) fix(g_d.p[g_d.pr[i].patch].neu + g_d.pr[i].off, g_d.pr[i].sign, delta);
    if (delta) {
        char v[16];
        snprintf(v, sizeof v, "%08X", (unsigned)(uintptr_t)at);
        SetEnvironmentVariableA("PR2NATION_SECTION", v);
    }
    for (int i = 0; i < g_d.np; i++) write_mem(g_d.p[i].va, g_d.p[i].neu, (size_t)g_d.p[i].n);
    FlushInstructionCache(GetCurrentProcess(), NULL, 0);
    char dll[MAX_PATH + 80];
    snprintf(dll, sizeof dll, "%s%s", g_dir, g_d.dll);
    HMODULE h = LoadLibraryA(dll);
    lg("%d patches applied in memory, section at %08X; %s %s", g_d.np, (unsigned)(uintptr_t)at, g_d.dll,
         h ? "loaded" : "did NOT load");
}

/* ---- the trigger: MSVCR71!__set_app_type, called by the CRT right after the entry point ---- */
typedef void (__cdecl *SetAppType_t)(int);
static SetAppType_t g_set_app_type;

static void __cdecl on_set_app_type(int type)
{
    uint32_t ret = (uint32_t)(uintptr_t)__builtin_return_address(0);
    SetAppType_t real = g_set_app_type;
    if (ret == g_d.hook_ret) {
        write_mem(g_d.hook_slot, &real, 4);                      /* the import slot as it was */
        apply();
    }
    real(type);
}

static void install(void)
{
    if (GetEnvironmentVariableA("PR2NATION_OFF", NULL, 0)) { lg("PR2NATION_OFF set: the game starts without the mod"); return; }
    if (!load_data()) return;
    if (!readable(g_d.hook_slot, 4)) { lg("the trigger slot %08X is not in this exe", g_d.hook_slot); return; }
    g_set_app_type = *(SetAppType_t *)(uintptr_t)g_d.hook_slot;
    SetAppType_t mine = on_set_app_type;
    write_mem(g_d.hook_slot, &mine, 4);
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID res)
{
    (void)res;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(h);
        DWORD n = GetModuleFileNameA(NULL, g_dir, MAX_PATH);
        while (n && g_dir[n - 1] != '\\') n--;
        g_dir[n] = 0;
        install();
    }
    return TRUE;
}
