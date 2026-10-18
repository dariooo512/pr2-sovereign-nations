# found-new-nation: game data files

These are loose files that override files inside the game's `.cpr` archives.
The game uses a loose file in place of the archived one when the loose file sits
at the same relative path under the install folder (`MODDING_GUIDE.md` §0).

| File | Deploys to | What it does |
|---|---|---|
| `lua/config/default/include.ini` | `<game dir>\lua\config\default\include.ini` | The vanilla file (line 1, unchanged byte for byte) plus the `fnn_nation` mission script: the nation menu popups, the founding flow, diplomacy, taxes, the treasury (donate / withdraw), tariff presets and annexation after a conquest |

## How the pieces fit

1. **The script is loaded on New Game and on Load.** `CMission::LoadScriptPath`
   (`0x435DF0`) runs `missions.bin` and then this `include.ini` in the Missions
   Lua state. The script does two things:
   - It appends the group `"fnn"` to `USE_GROUPS`.
   - It registers `fnn_nation = Script_Register("fnn_nation", "fnn", MTYPE_GLOBAL)`.
     `Script_Register` returns `SCRIPT_TABLE.fnn_nation`. The engine looks up
     every mission callback in that table.
2. **`PR2Nation.dll` creates one instance of the mission once per game** with
   `Global_CreateMission("fnn_nation", -1)`, and sets `GLOBALS.FNN_MISSION = 1`.
   - `GLOBALS` is saved with the game, so the DLL does not create the mission
     again after a Load.
   - The DLL creates the mission itself because `mstart.ini` only runs on New
     Game. This way, saves made before the mod was installed also get the
     mission.
3. **`OnCreate` installs the event filter** for `MEVENT_GAME_MENU` and
   `MEVENT_TOWNBATTLE_END`.
4. **Ctrl+N opens the menu.**
   - The DLL polls the key while the game window is in front and the game is
     running (not paused or loading).
   - It then posts a synthetic `OnGameMenu(0x4E41)` event.
   - The script answers with mission popups (`Global_CreatePopup`,
     `OnPopupText`, `OnPopupClose`). Each popup has at most 3 buttons.
5. **Popup text uses string ids from the DLL's own table `"FNN"`.**
   - The DLL registers this table with the game's `CStringManager`
     (`dll/strings.c`).
   - Changing text, such as the nation name or numbers, is set with
     `Nation_SetText(id, text)`. The table is then registered again.
6. **Messages go to the game's message ticker.** They come from the nation core,
   such as declarations or monthly accounts. The script can also send one with
   `Nation_Message(text)`.

Every callback in the script is a few trivial lines. All logic runs through
`FNN_Guard`, which swaps in a harmless Lua error handler. This matters because
the engine's own handler throws, and the throw would crash the game. Without
the DLL, the callbacks do nothing and the mission is never created.

## Deploy / undeploy

- **Deploy:** copy `lua/config/default/include.ini` into the test install at the
  same relative path, next to `PR2Nation.dll` and the patched exe. Nothing
  else is needed. No archive is repacked.
- **Undeploy:** delete the loose `include.ini`.
  - **Do not do this while you still want to load saves that contain the
    nation mission.** The mission is restored from the save. That needs
    `SCRIPT_TABLE.fnn_nation`, so loading such a save without this file is
    expected to fail. This is unverified.
  - Saves from games where the DLL never created the mission are unaffected.
- **Scenario games** read `lua/config/scenario/00x/include.ini` instead. They
  have no nation menu: the DLL logs "nation mission script not loaded" and
  stays inert.

## Checking

```
python tools/check_ui_static.py
```

The check runs this script in the game's real `lua.dll` (Lua 4.1 ASCARON)
against engine stubs and drives every popup flow. It also confirms that
line 1 still equals the vanilla file and that every string id used here has a
default text.
