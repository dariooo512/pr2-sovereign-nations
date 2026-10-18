/* Silence in the test install: while PR2Nation.dev sits next to the exe (tools/env.py puts it
 * there; the player package never has it), the game's own audio session is muted through the
 * Windows Core Audio per-application volume (the volume mixer's mute for this process), so
 * test runs make no sound. The game's own volume settings (options.dat) stay untouched.
 * [Dev] Sound=1 in PR2Nation.ini keeps the sound on.
 *
 * MMDeviceEnumerator -> default render endpoint -> IAudioSessionManager -> the process's
 * default session (GUID_NULL, the one Miles/DirectSound/waveOut streams join) ->
 * ISimpleAudioVolume::SetMute(TRUE). Re-applied every few seconds: the session can be
 * recreated (device change), and the first call may come before the game opens its audio.
 * The COM interfaces are called through their vtables (slot numbers from the Windows SDK). */
#include <windows.h>
#include <objbase.h>
#include "log.h"

static const GUID k_clsid_enum = {0xBCDE0395, 0xE52F, 0x467C, {0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E}};
static const GUID k_iid_enum   = {0xA95664D2, 0x9614, 0x4F35, {0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6}};
static const GUID k_iid_asm    = {0xBFA971F1, 0x4D5E, 0x40BB, {0x93, 0x5E, 0x96, 0x70, 0x39, 0xBF, 0xBE, 0xE4}};

typedef HRESULT (__stdcall *Release_t)(void *self);
typedef HRESULT (__stdcall *DefaultEndpoint_t)(void *self, int flow, int role, void **device);   /* slot 4 */
typedef HRESULT (__stdcall *Activate_t)(void *self, const GUID *iid, DWORD ctx, void *params, void **out); /* 3 */
typedef HRESULT (__stdcall *SimpleVolume_t)(void *self, const GUID *session, BOOL cross, void **out);  /* 4 */
typedef HRESULT (__stdcall *SetMute_t)(void *self, BOOL mute, const GUID *ctx);                        /* 5 */

#define VT(obj, slot) ((*(void ***)(obj))[slot])

static int g_state = -1;            /* -1 not decided, 0 sound on, 1 mute */
static unsigned g_ticks;

static void exe_file(char *path, const char *name)
{
    DWORD n = GetModuleFileNameA(NULL, path, MAX_PATH);
    while (n && path[n - 1] != '\\') n--;
    lstrcpynA(path + n, name, MAX_PATH - (int)n);
}

static int decide(void)
{
    char path[MAX_PATH];
    exe_file(path, "PR2Nation.dev");
    if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return 0;
    exe_file(path, "PR2Nation.ini");
    if (GetPrivateProfileIntA("Dev", "Sound", 0, path)) return 0;
    return 1;
}

static int mute_now(void)
{
    void *en = NULL, *dev = NULL, *mgr = NULL, *vol = NULL;
    HRESULT co = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);    /* the game's thread may have COM already */
    int ok = 0;
    if (SUCCEEDED(CoCreateInstance(&k_clsid_enum, NULL, CLSCTX_ALL, &k_iid_enum, &en)) && en &&
        SUCCEEDED(((DefaultEndpoint_t)VT(en, 4))(en, 0 /* eRender */, 1 /* eMultimedia */, &dev)) && dev &&
        SUCCEEDED(((Activate_t)VT(dev, 3))(dev, &k_iid_asm, CLSCTX_ALL, NULL, &mgr)) && mgr &&
        SUCCEEDED(((SimpleVolume_t)VT(mgr, 4))(mgr, NULL, FALSE, &vol)) && vol)
        ok = SUCCEEDED(((SetMute_t)VT(vol, 5))(vol, TRUE, NULL));
    if (vol) ((Release_t)VT(vol, 2))(vol);
    if (mgr) ((Release_t)VT(mgr, 2))(mgr);
    if (dev) ((Release_t)VT(dev, 2))(dev);
    if (en) ((Release_t)VT(en, 2))(en);
    if (SUCCEEDED(co)) CoUninitialize();
    return ok;
}

void mute_frame(void)
{
    if (g_state < 0) {
        g_state = decide();
        if (g_state) log_line("SOUND: test install (PR2Nation.dev): the game is muted ([Dev] Sound=1 keeps it on)");
    }
    if (!g_state || g_ticks++ % 150) return;                      /* every 150 frames (a few seconds) */
    static int last = -1;
    int ok = mute_now();
    if (ok != last) log_line("SOUND: mute %s", ok ? "applied" : "failed (no audio device?)");   /* changes only */
    last = ok;
}
