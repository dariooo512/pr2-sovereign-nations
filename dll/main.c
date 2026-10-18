/* PR2Nation.dll -- the player-nation feature for Port Royale 2 (1.1.2.3).
 *
 * Loaded by patch P06 at process start. Installs runtime hooks and runs the
 * nation logic on the game's main thread (per-frame hook on A2dLib's
 * CWalhallaClient::InputProcessor).
 */
#include <windows.h>
#include <stdint.h>
#include <stdlib.h>
#include "hook.h"
#include "log.h"
#include "nation.h"
#include "clock.h"
#include "game.h"

void mute_frame(void);                     /* mute.c */

#define A2D_INPUTPROCESSOR_RVA 0x2F2C0   /* CWalhallaClient::InputProcessor */

static unsigned long g_frames;

uint32_t g_section_delta;                  /* game.h: the loader moved the .nation section */

static void find_section(void)
{
    char v[16];
    DWORD n = GetEnvironmentVariableA("PR2NATION_SECTION", v, sizeof v);
    if (!n || n >= sizeof v) return;
    uint32_t at = (uint32_t)strtoul(v, NULL, 16);
    MEMORY_BASIC_INFORMATION mi;
    if (!at || !VirtualQuery((void *)(uintptr_t)at, &mi, sizeof mi) || mi.State != MEM_COMMIT) {
        log_line("PR2NATION_SECTION=%s is not mapped; using 0x%08X", v, GA_SECTION);
        return;
    }
    g_section_delta = at - GA_SECTION;
    log_line("patches applied in memory by the loader, section at 0x%08X", at);
}

static void on_frame(Regs *r)
{
    (void)r;
    g_frames++;
    nation_frame();
    mute_frame();                         /* test install: no sound (mute.c) */
}

static void install_hooks(void)
{
    HMODULE a2d = GetModuleHandleA("A2dLib-2.20A.dll");
    if (!a2d) {
        log_line("A2dLib not loaded; frame hook unavailable");
        return;
    }
    /* push ebx; push ebp; push esi; push edi; mov ebp, ecx */
    static const uint8_t ip[] = {0x53, 0x55, 0x56, 0x57, 0x8B, 0xE9};
    hook_install("A2d.InputProcessor", (uint32_t)(uintptr_t)a2d + A2D_INPUTPROCESSOR_RVA,
                 ip, sizeof ip, on_frame);
    nation_install_hooks();
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID res)
{
    (void)h; (void)res;
    if (reason == DLL_PROCESS_ATTACH) {
        log_open();
        log_line("PR2Nation.dll loaded (build " __DATE__ " " __TIME__ ")");
        find_section();
        clock_install();                  /* before the game reads a clock */
        install_hooks();
    }
    return TRUE;
}

unsigned long pr2n_frames(void) { return g_frames; }
