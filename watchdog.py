"""
watchdog.py — Global Process Watchdog
Scans registrations/ for process definitions, checks each one, restarts if needed.
Runs via Windows Task Scheduler every 5 minutes.

Usage:
    python C:\\watchdog\\watchdog.py
"""

import json
import logging
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    print("psutil not installed. Run: pip install psutil")
    sys.exit(1)

ROOT = Path(__file__).parent
REGISTRATIONS_DIR = ROOT / "registrations"
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOGS_DIR / "watchdog.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("watchdog")


# ── Helpers ───────────────────────────────────────────────────────────────────

def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def find_processes(match: str) -> list:
    """Find all processes whose cmdline contains the match string."""
    results = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
            if match in cmdline:
                results.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return results


def kill_process(proc):
    try:
        proc.kill()
        logger.info(f"  Killed PID {proc.pid}")
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        logger.warning(f"  Could not kill PID {proc.pid}: {e}")


def kill_port_holder(port: int):
    """Kill any process listening on the given port."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                pid = line.split()[-1]
                if pid.isdigit():
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True, timeout=5
                    )
                    logger.info(f"  Killed port {port} holder PID {pid}")
    except Exception as e:
        logger.warning(f"  kill_port_holder({port}) failed: {e}")


def start_process(reg: dict):
    """Launch the restart command for a registration."""
    cmd = reg["restart_cmd"]
    cwd = reg.get("cwd") or str(ROOT)

    # wscript.exe needs argv split, not shell
    if cmd.lower().lstrip().startswith("wscript"):
        parts = cmd.split(None, 1)
        subprocess.Popen(
            parts,
            cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    logger.info(f"  Started: {cmd}")


# ── Check handlers ────────────────────────────────────────────────────────────

def _is_running(proc) -> bool:
    try:
        return proc.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def check_process(reg: dict):
    match = reg["match"]
    max_inst = reg.get("max_instances", 1)
    max_mem_mb = reg.get("max_memory_mb")
    procs = find_processes(match)

    # Kill processes exceeding memory threshold
    if max_mem_mb and procs:
        for proc in list(procs):
            try:
                mem_mb = proc.memory_info().rss / (1024 * 1024)
                if mem_mb > max_mem_mb:
                    logger.info(f"[{reg['name']}] PID {proc.pid} using {mem_mb:.0f}MB > {max_mem_mb}MB — killing")
                    kill_process(proc)
                    procs.remove(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                procs.remove(proc)
        if not procs:
            time.sleep(1)

    # Kill oldest extras when over max_instances
    if len(procs) > max_inst:
        try:
            procs_sorted = sorted(procs, key=lambda p: p.create_time())
        except Exception:
            procs_sorted = procs
        extras = procs_sorted[:len(procs_sorted) - max_inst]
        logger.info(f"[{reg['name']}] {len(procs)} instances (max {max_inst}) — killing {len(extras)} oldest")
        for proc in extras:
            kill_process(proc)
        procs = procs_sorted[len(procs_sorted) - max_inst:]
        time.sleep(1)

    # Restart if none left (only if restart_cmd provided)
    live = [p for p in procs if _is_running(p)]
    if not live:
        if reg.get("restart_cmd"):
            logger.info(f"[{reg['name']}] Not running — restarting")
            start_process(reg)
        else:
            logger.debug(f"[{reg['name']}] Not running (no restart_cmd — managed externally)")
    else:
        logger.debug(f"[{reg['name']}] OK ({len(live)} instance(s))")


def check_port(reg: dict):
    port = reg["port"]
    if not port_open(port):
        logger.info(f"[{reg['name']}] Port {port} not open — restarting")
        kill_port_holder(port)
        time.sleep(1)
        start_process(reg)
    else:
        logger.debug(f"[{reg['name']}] OK (port {port} open)")


def check_file_age(reg: dict):
    filepath = Path(reg["file"])
    max_age = reg.get("max_age_seconds", 3600)

    if not filepath.exists():
        logger.info(f"[{reg['name']}] File missing: {filepath} — restarting")
        _kill_match_before_restart(reg)
        start_process(reg)
        return

    age = time.time() - filepath.stat().st_mtime
    if age > max_age:
        logger.info(f"[{reg['name']}] File age {int(age)}s > {max_age}s — restarting")
        _kill_match_before_restart(reg)
        start_process(reg)
    else:
        logger.debug(f"[{reg['name']}] OK (file age {int(age)}s)")


def check_schedule(reg: dict):
    """Restart once per day at a specified time (HH:MM, 24h)."""
    daily_at = reg.get("daily_at", "02:00")
    name = reg["name"]

    state_dir = ROOT / "state"
    state_dir.mkdir(exist_ok=True)
    state_file = state_dir / f"{name.lower().replace(' ', '_').replace('-', '_')}.json"

    last_date = None
    if state_file.exists():
        try:
            last_date = json.loads(state_file.read_text(encoding="utf-8")).get("last_restart_date")
        except Exception:
            pass

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    scheduled = datetime.strptime(f"{today} {daily_at}", "%Y-%m-%d %H:%M")

    if now >= scheduled and last_date != today:
        logger.info(f"[{name}] Daily restart at {daily_at} — restarting")
        _kill_match_before_restart(reg)
        start_process(reg)
        state_file.write_text(json.dumps({"last_restart_date": today}), encoding="utf-8")
    else:
        logger.debug(f"[{name}] OK (last restart: {last_date or 'never'}, scheduled: {daily_at})")


def _kill_match_before_restart(reg: dict):
    """If registration has kill_match, kill all matching processes before restarting."""
    kill_match = reg.get("kill_match")
    if not kill_match:
        return
    procs = find_processes(kill_match)
    if procs:
        logger.info(f"[{reg['name']}] Killing {len(procs)} old instance(s) matching '{kill_match}'")
        for proc in procs:
            kill_process(proc)
        time.sleep(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info(f"=== Watchdog run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    if not REGISTRATIONS_DIR.exists():
        logger.warning(f"No registrations/ directory at {REGISTRATIONS_DIR}")
        return

    reg_files = sorted(REGISTRATIONS_DIR.glob("*.json"))
    if not reg_files:
        logger.info("No registrations found.")
        return

    for reg_file in reg_files:
        try:
            reg = json.loads(reg_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to read {reg_file.name}: {e}")
            continue

        if not reg.get("enabled", True):
            logger.debug(f"[{reg.get('name', reg_file.stem)}] Disabled, skipping")
            continue

        check_type = reg.get("check")
        try:
            if check_type == "process":
                check_process(reg)
            elif check_type == "port":
                check_port(reg)
            elif check_type == "file_age":
                check_file_age(reg)
            elif check_type == "schedule":
                check_schedule(reg)
            else:
                logger.warning(f"[{reg.get('name')}] Unknown check type: {check_type}")
        except Exception as e:
            logger.error(f"[{reg.get('name')}] Check failed: {e}")

    logger.info("=== Done ===")


if __name__ == "__main__":
    main()
