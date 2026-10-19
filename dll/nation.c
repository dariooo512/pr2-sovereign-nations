#include "nation.h"
#include "adapter.h"
#include "engine.h"
#include "log.h"

#include "lua.h"
#include "war.h"
#include "flag.h"
#include "navy.h"
#include "panel.h"
#include "officials.h"
#include "watchdog.h"
#include "sight.h"
#include "replog.h"
#include "towninfo.h"

void persist_install(void);
void api_frame(void);

void nation_install_hooks(void)
{
    plua_init();
    persist_install();
    war_install();
    towns_install();
    ui_init();
    navy_install();
    panel_install();
    officials_install();
    towninfo_install();
    sight_install();
    flag_install();
    replog_install();
}

void nation_frame(void)
{
    watchdog_start();
    plua_frame_check();
    flag_init();
    api_frame();
    war_frame();
    navy_frame();
    panel_frame();
    towninfo_frame();
    sight_frame();
    adapter_frame();
}
