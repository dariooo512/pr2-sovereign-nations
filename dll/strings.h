/* The DLL's own string table ("FNN"), registered with the game's
 * NA2dLib::CStringManager so every text id resolves like a vanilla one:
 * mission popups, buttons and logbook text all look ids up by name.
 * research/ui_entry.md §5. Main thread only.
 */
#ifndef PR2N_STRINGS_H
#define PR2N_STRINGS_H
#include <stdint.h>

#define FNN_STRING_TABLE "FNN"

/* CW32StringManager key: h = (h*0x71 + (signed char)c) % 999999991 (0x3B9AC9F7), 32-bit
   wrap, C truncating % (A2dLib 0x1002BB30). */
int32_t strings_hash(const char *id);

/* Set (or add) the text of `id` and re-register the table (Remove + Add).
   Text is UTF-8; '<n>' is the mission-text line break. Returns 1 if the text
   is stored; the registration itself may be pending until the manager exists. */
int  strings_set(const char *id, const char *utf8_text);
const char *strings_get(const char *id);       /* our UTF-8 copy, NULL if unknown */

/* Register pending changes once A2dLib's string manager exists (per frame).
   Returns 1 when the current table is registered. */
int  strings_flush(void);
int  strings_registered(void);

/* Pure blob builder (also used by tools/check_ui_static.py through a host
   harness): .res layout = u32 count; count x {u32 hash, u32 byte offset of the
   text from byte 4, u32 nargs, u32 byte length}; UTF-16LE text; entries
   sorted by (int32)hash ascending. Returns a malloc'd blob (free()) or NULL. */
uint8_t *strings_build_blob(uint32_t *size_out);

#endif
