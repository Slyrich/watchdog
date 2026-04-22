"""
register.py — Register/manage processes with the global watchdog.

Usage:
    python C:\\watchdog\\register.py add --name "MyApp" --check port --port 8080 --restart "python app.py" --cwd "C:\\myproject" --project "myproject"
    python C:\\watchdog\\register.py remove --name "MyApp"
    python C:\\watchdog\\register.py list
    python C:\\watchdog\\register.py enable --name "MyApp"
    python C:\\watchdog\\register.py disable --name "MyApp"

Check types:
    process   — checks if a process with matching cmdline is running
                --match "bot.py" --max-instances 1
    port      — checks if a port is listening
                --port 5000
    file_age  — checks if a file was updated within max_age_seconds
                --file "C:\\path\\tunnel_url.txt" --max-age-seconds 7200
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
REGISTRATIONS_DIR = ROOT / "registrations"
REGISTRATIONS_DIR.mkdir(exist_ok=True)


def name_to_filename(name: str) -> str:
    return name.lower().replace(" ", "-").replace("_", "-") + ".json"


def get_reg_path(name: str) -> Path:
    return REGISTRATIONS_DIR / name_to_filename(name)


def cmd_add(args):
    reg = {
        "name": args.name,
        "project": args.project or "",
        "check": args.check,
        "enabled": True,
        "restart_cmd": args.restart,
        "cwd": args.cwd or "",
    }

    if args.check == "process":
        if not args.match:
            print("ERROR: --match is required for check=process")
            sys.exit(1)
        reg["match"] = args.match
        reg["max_instances"] = args.max_instances

    elif args.check == "port":
        if args.port is None:
            print("ERROR: --port is required for check=port")
            sys.exit(1)
        reg["port"] = args.port

    elif args.check == "file_age":
        if not args.file:
            print("ERROR: --file is required for check=file_age")
            sys.exit(1)
        reg["file"] = args.file
        reg["max_age_seconds"] = args.max_age_seconds

    path = get_reg_path(args.name)
    path.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Registered: {args.name}  ->  {path}")
    print(f"Watchdog will pick this up on its next run.")


def cmd_remove(args):
    path = get_reg_path(args.name)
    if path.exists():
        path.unlink()
        print(f"Removed: {args.name}")
    else:
        print(f"Not found: {args.name}")


def cmd_list(args):
    files = sorted(REGISTRATIONS_DIR.glob("*.json"))
    if not files:
        print("No registrations.")
        return
    print(f"{'STATUS':<6} {'PROJECT':<16} {'NAME':<30} {'CHECK':<10} {'DETAIL'}")
    print("-" * 80)
    for f in files:
        try:
            reg = json.loads(f.read_text(encoding="utf-8"))
            status = "ON " if reg.get("enabled", True) else "OFF"
            check = reg.get("check", "?")
            detail = str(reg.get("port") or reg.get("match") or reg.get("file") or "")
            print(f"{status:<6} {reg.get('project',''):<16} {reg['name']:<30} {check:<10} {detail}")
        except Exception as e:
            print(f"  {f.name}: ERROR {e}")


def _toggle(name: str, enabled: bool):
    path = get_reg_path(name)
    if not path.exists():
        print(f"Not found: {name}")
        return
    reg = json.loads(path.read_text(encoding="utf-8"))
    reg["enabled"] = enabled
    path.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{'Enabled' if enabled else 'Disabled'}: {name}")


def main():
    parser = argparse.ArgumentParser(
        description="Watchdog process registration tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── add ──────────────────────────────────────────────────────────────────
    add_p = sub.add_parser("add", help="Register a process for monitoring")
    add_p.add_argument("--name",    required=True, help="Unique name for this registration")
    add_p.add_argument("--project", default="",   help="Project this belongs to")
    add_p.add_argument("--check",   required=True, choices=["process", "port", "file_age"])
    add_p.add_argument("--restart", required=True, help="Command to restart the process")
    add_p.add_argument("--cwd",     default="",   help="Working directory for restart command")
    # process options
    add_p.add_argument("--match",        help="Cmdline substring to match (check=process)")
    add_p.add_argument("--max-instances", type=int, default=1, dest="max_instances",
                       help="Max allowed instances before killing extras (default: 1)")
    # port options
    add_p.add_argument("--port", type=int, help="Port to check (check=port)")
    # file_age options
    add_p.add_argument("--file", help="File path to check freshness of (check=file_age)")
    add_p.add_argument("--max-age-seconds", type=int, default=7200, dest="max_age_seconds",
                       help="Max file age in seconds before restarting (default: 7200)")

    # ── remove ───────────────────────────────────────────────────────────────
    rm_p = sub.add_parser("remove", help="Unregister a process")
    rm_p.add_argument("--name", required=True)

    # ── list ─────────────────────────────────────────────────────────────────
    sub.add_parser("list", help="List all registrations")

    # ── enable / disable ─────────────────────────────────────────────────────
    en_p = sub.add_parser("enable", help="Enable a disabled registration")
    en_p.add_argument("--name", required=True)
    dis_p = sub.add_parser("disable", help="Temporarily disable a registration")
    dis_p.add_argument("--name", required=True)

    args = parser.parse_args()
    {
        "add":     cmd_add,
        "remove":  cmd_remove,
        "list":    cmd_list,
        "enable":  lambda a: _toggle(a.name, True),
        "disable": lambda a: _toggle(a.name, False),
    }[args.cmd](args)


if __name__ == "__main__":
    main()
