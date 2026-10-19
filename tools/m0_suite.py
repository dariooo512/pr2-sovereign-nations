"""M0 acceptance suite: one command, fully in the background.

    python tools/m0_suite.py [--static-only] [--minutes N]

1. Static: the fact checker and every patch test.
2. Build the full patch set (patches/p0*.py, in order) and deploy it to the
   test install as PR2_nation.exe.
3. In-game scenarios (each a fresh game process under gamehost):
   REG-01  a normal game with no nation-5 town survives N minutes at 20x
   TER-01  an ordinary town (Tortuga) and a governor town (Margarita) set to
           nation 5 (display = their old power) survive N minutes at 20x
   SAV-01  QuickSave, cold restart, load: both towns are still nation 5, and
           the reloaded game keeps running
   MIL-01  in the reloaded game, power->player war/peace follows player_rel:
           peace gives 0 for every power, war with Spain gives Spain 1

The game's Save folder is shared with the user's own game, so the suite
backs it up first and always restores it afterwards. Results go to
_build/m0_report.md.
"""
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import env  # noqa: E402
import session  # noqa: E402

PATCHES = sorted((env.HERE / "patches").glob("p0*.py"))
BUILD = env.HERE / "_build" / "m0" / "PR2_nation.exe"
REPORT = env.HERE / "_build" / "m0_report.md"
SPEED_PLUS = (475, 13)
PLAYER_REL = 0x9F7000            # P01 data label (first in the .nation section)
REL_EXIT_POWER_VS_PLAYER = 0x9F7037
results = []


def run(*args, timeout=600):
    p = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True,
                       errors="replace", timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]


def record(test, ok, detail):
    results.append((test, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {test:<8} {detail}", flush=True)


def kill_game():
    for exe in ("PR2_nation.exe", "PR2_target.exe"):
        subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True)
    time.sleep(2)


def game_alive():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq PR2_nation.exe"],
                         capture_output=True, text=True).stdout
    return "PR2_nation.exe" in out


def crashes(log_from=0):
    text = session.latest_log().read_text(errors="replace")[log_from:]
    return re.findall(r"SECOND .*", text)


def speed_up():
    for _ in range(6):
        session.cmd("click", *SPEED_PLUS)


def hold(minutes, test, what):
    """Let the game run; FAIL on any unhandled exception or process exit."""
    end = time.time() + 60 * minutes
    while time.time() < end:
        time.sleep(10)
        if crashes() or not game_alive():
            record(test, False, f"{what}: {(crashes() or ['game exited'])[0]}")
            return False
    record(test, True, f"{what}: {minutes} min at 20x, no unhandled exception")
    return True


def town(name):
    for line in (env.HERE / "_build" / "towns.tsv").read_text().splitlines()[1:]:
        idx, n, lager, nat, disp = line.split("\t")
        if n == name:
            return lager, int(nat)
    raise KeyError(name)


def static():
    if (HERE / "check_facts.py").exists():           # exports before 20 Oct 2026 left it out
        code, tail = run(HERE / "check_facts.py")
        record("FACTS", code == 0, tail[0])
    else:
        print("SKIP  FACTS    tools/check_facts.py is not in this checkout")
    for t in sorted(HERE.glob("test_*.py")):
        code, tail = run(t)
        record(t.stem, code == 0, tail[0])


def build_and_deploy():
    args = [HERE / "pe_patch.py", BUILD]
    for p in PATCHES:
        args += ["--patch-module", p]
    code, tail = run(*args)
    record("BUILD", code == 0, f"{', '.join(p.stem for p in PATCHES)} -> {tail[0]}")
    env.deploy(BUILD)


def scenario_reg(minutes):
    kill_game()
    session.newgame([], "PR2_nation.exe")
    speed_up()
    hold(minutes, "REG-01", "normal game, full patch set")


def scenario_nation5(minutes):
    kill_game()
    session.newgame([], "PR2_nation.exe")
    flips = {"Tortuga": None, "Margarita": None}
    for name in flips:
        lager, nat = town(name)
        flips[name] = nat
        session.cmd("setnation", lager, 5, nat)
    speed_up()
    if not hold(minutes, "TER-01", "Tortuga + Margarita (governor town) at nation 5"):
        return False
    session.cmd("call", "0x57EE90", "0x700500")          # QuickSave
    time.sleep(5)
    kill_game()
    session.load("Quick Save", [], "PR2_nation.exe")
    towns = session.scan_towns()
    n5 = sorted(int(d) for _, n, d in towns if n == "5")
    ok = len(towns) == 60 and n5 == sorted(flips.values())
    record("SAV-01", ok, f"after reload: {len(towns)} towns, nation-5 display powers {n5} "
                         f"(expected {sorted(flips.values())})")
    return ok


def decisions(since):
    text = session.latest_log().read_text(errors="replace")[since:]
    return re.findall(rf"BP {REL_EXIT_POWER_VS_PLAYER:#x} hit#\d+ tid=\d+ eax=(0x[01]) \[ecx\+0x18\]=0(\d)", text)


def scenario_war(minutes):
    """Runs in the reloaded game left by scenario_nation5."""
    speed_up()
    spec = f"{REL_EXIT_POWER_VS_PLAYER:#x}=eax,ecx+0x18:1"
    mark = len(session.latest_log().read_text(errors="replace"))
    session.cmd("bp", spec)
    time.sleep(30 * minutes)
    peace = decisions(mark)
    mark = len(session.latest_log().read_text(errors="replace"))
    session.cmd("write", f"{PLAYER_REL + 3:#x}", "01")     # war with Spain
    session.cmd("bp", spec)
    time.sleep(30 * minutes)
    war = decisions(mark)
    peace_ok = bool(peace) and all(r == "0x0" for r, _ in peace)
    spain_war = [r for r, p in war if p == "3"]
    others = [r for r, p in war if p != "3"]
    war_ok = "0x1" in spain_war and all(r == "0x0" for r in others)
    record("MIL-01", peace_ok and war_ok and not crashes(),
           f"peace: {len(peace)} decisions, all 0 = {peace_ok}; war(Spain): Spain "
           f"{spain_war.count('0x1')}x1/{len(spain_war)}, others all 0 = {all(r == '0x0' for r in others)}")


def main():
    static_only = "--static-only" in sys.argv
    minutes = next((float(sys.argv[i + 1]) for i, a in enumerate(sys.argv) if a == "--minutes"), 3)
    static()
    if not static_only:
        backup = env.backup_saves()
        try:
            env.windowed(True)
            env.fast_boot(True)
            env.dpi_aware(True)
            build_and_deploy()
            scenario_reg(minutes)
            if scenario_nation5(minutes):
                scenario_war(1)
        finally:
            kill_game()
            for f in backup.iterdir():                      # restore the user's saves/settings
                if f.is_file():
                    shutil.copy2(f, env.SAVE_DIR / f.name)
            orig_cfg = env.BACKUPS / "settings.cfg.orig"   # taken before the very first change
            if orig_cfg.exists():
                shutil.copy2(orig_cfg, env.SAVE_DIR / "settings.cfg")
            print(f"restored the Save folder from {backup} (settings.cfg from {orig_cfg.name})")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("# M0 acceptance run " + time.strftime("%Y-%m-%d %H:%M") + "\n\n| Test | Result | Detail |\n|---|---|---|\n"
                      + "".join(f"| {t} | {'PASS' if ok else 'FAIL'} | {d} |\n" for t, ok, d in results))
    failed = [t for t, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed -> {REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
