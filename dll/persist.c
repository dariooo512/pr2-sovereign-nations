/* Persistence + lifecycle + clock: the NationState lives inside the .pr2.
 *
 * Save: World::Save calls the serializer twice (a sizing pass with cap == 0,
 * then a fill pass). After the four vanilla CNation blobs we append
 *   'PNAT' u32 len  <core_serialize bytes>
 * only when a nation has been founded, so a save without a nation stays
 * byte-identical to vanilla. Load: peek the next byte; '{' = no blob.
 * (research/save_hooks.md §1-§2)
 */
#include <string.h>
#include "game.h"
#include "hook.h"
#include "log.h"
#include "adapter.h"
#include "navy.h"
#include "sight.h"

#define FLEET_MAGIC 0x544C4650u   /* 'PFLT': per-fleet orders after the nation block */
#define NATC_MAGIC  0x56434E50u   /* 'PNCV': the national convoys' handles, after PFLT */

static uint8_t g_blob[sizeof(NationState) + 64];

static void stream_write(MemStream *s, const void *src, uint32_t n)
{
    if (s->cap) {
        if (s->cur + n > s->base + s->cap) {          /* fill pass larger than sized: never overrun */
            log_line("SAVE: stream full, %u bytes dropped", n);
            return;
        }
        memcpy(s->cur, src, n);
    }
    s->cur += n;
}

static void on_save(Regs *r)
{
    MemStream *s = (MemStream *)(uintptr_t)r->esi;
    NationState *st = adapter_state();
    if (!st->founded)
        return;
    int n = core_serialize(st, g_blob, sizeof g_blob);
    if (n <= 0) {
        log_line("SAVE: serialize failed; nation not written");
        return;
    }
    uint32_t hdr[2] = {NATION_MAGIC, (uint32_t)n};
    stream_write(s, hdr, sizeof hdr);
    stream_write(s, g_blob, (uint32_t)n);
    uint8_t orders[16 * 6];                                 /* per-fleet orders (navy.c) */
    int on = navy_save_orders(orders, sizeof orders);
    if (on > 0) {
        uint32_t oh[2] = {FLEET_MAGIC, (uint32_t)on};
        stream_write(s, oh, sizeof oh);
        stream_write(s, orders, (uint32_t)on);
    }
    uint8_t natc[16 * 8];                                   /* national convoys (sight.c) */
    int cn = natc_save(natc, sizeof natc);
    if (cn > 0) {
        uint32_t ch[2] = {NATC_MAGIC, (uint32_t)cn};
        stream_write(s, ch, sizeof ch);
        stream_write(s, natc, (uint32_t)cn);
    }
    if (s->cap)
        log_line("SAVE: nation '%s' written (%d bytes)", st->name, n);
}

static void on_load(Regs *r)
{
    MemStream *s = (MemStream *)(uintptr_t)r->esi;
    NationState *st = adapter_state();
    navy_after_load_nations();                     /* g_nations was just rebuilt */
    core_init(st);
    uint32_t left = s->cap - (uint32_t)(s->cur - s->base);
    if (left >= 1 && s->cur[0] == '{') {
        log_line("LOAD: no nation in this save");
        adapter_on_loaded_state();
        return;
    }
    uint32_t hdr[2];
    if (left < sizeof hdr) {
        log_line("LOAD: truncated stream at nation block; leaving to vanilla checks");
        return;
    }
    memcpy(hdr, s->cur, sizeof hdr);
    if (hdr[0] != NATION_MAGIC || left < sizeof hdr + hdr[1]) {
        log_line("LOAD: unknown block (magic %08X len %u); leaving to vanilla checks", hdr[0], hdr[1]);
        return;
    }
    /* a nation block from a newer mod version may be larger: reject it but
       still skip it, so the rest of the save loads */
    if (hdr[1] > sizeof g_blob || !core_deserialize(st, s->cur + sizeof hdr, (int)hdr[1])) {
        /* §13: never silently load mismatched nation data. The block is
           skipped so the rest of the save still loads; the player is told. */
        core_init(st);
        adapter_message("Your nation's data in this save is damaged or from an incompatible "
                        "mod version. The game continues without the nation.");
        log_line("LOAD: nation block rejected (version/checksum)");
    } else {
        log_line("LOAD: nation '%s' restored (%u bytes)", st->name, hdr[1]);
    }
    s->cur += sizeof hdr + hdr[1];
    navy_load_orders(NULL, 0);
    natc_load(NULL, 0);
    for (int blk = 0; blk < 2; blk++) {                       /* PFLT, then PNCV; each optional */
        left = s->cap - (uint32_t)(s->cur - s->base);
        if (left < 8) break;
        uint32_t oh[2];
        memcpy(oh, s->cur, sizeof oh);
        if (oh[0] == FLEET_MAGIC && oh[1] <= 16 * 6 && left >= 8 + oh[1]) {
            navy_load_orders(s->cur + 8, (int)oh[1]);
            s->cur += 8 + oh[1];
        } else if (oh[0] == NATC_MAGIC && oh[1] <= 16 * 8 && left >= 8 + oh[1]) {
            natc_load(s->cur + 8, (int)oh[1]);
            s->cur += 8 + oh[1];
        } else {
            break;
        }
    }
    adapter_on_loaded_state();
}

static void on_world_reset(Regs *r) { (void)r; core_init(adapter_state()); adapter_on_reset(); }
static void on_newgame_done(Regs *r) { (void)r; log_line("new game ready"); adapter_on_world_ready(); navy_world_ready(); sight_world_ready(); }
static void on_load_done(Regs *r) { (void)r; log_line("load complete"); adapter_on_world_ready(); navy_world_ready(); sight_world_ready(); }

static void on_daily(Regs *r)
{
    (void)r;
    adapter_daily();
}

void persist_install(void)
{
    static const uint8_t save_b[]  = {0x8B, 0x46, 0x08, 0x85, 0xC0};
    static const uint8_t load_b[]  = {0x8B, 0x46, 0x04, 0x8B, 0x1E};
    static const uint8_t reset_b[] = {0xB9, 0xEC, 0x3A, 0x70, 0x00};
    static const uint8_t newg_b[]  = {0xB8, 0x0B, 0x00, 0x00, 0x00};
    static const uint8_t loadd_b[] = {0x81, 0xC4, 0x8C, 0x00, 0x00, 0x00};
    static const uint8_t daily_b[] = {0x33, 0xF6, 0x8D, 0x9F, 0xD4, 0x09, 0x00, 0x00};
    hook_install("World::Save+nation", GH_SAVE_AFTER_NATIONS, save_b, sizeof save_b, on_save);
    hook_install("World::Load+nation", GH_LOAD_AFTER_NATIONS, load_b, sizeof load_b, on_load);
    hook_install("World::Reset", GH_WORLD_RESET, reset_b, sizeof reset_b, on_world_reset);
    hook_install("NewGame done", GH_NEWGAME_DONE, newg_b, sizeof newg_b, on_newgame_done);
    hook_install("Load done", GH_LOAD_DONE, loadd_b, sizeof loadd_b, on_load_done);
    hook_install("World::Tick new day", GH_DAILY, daily_b, sizeof daily_b, on_daily);
}
