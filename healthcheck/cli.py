"""Command line: run | watch | report | page | postman-import | postman-export | newman | gui."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import webbrowser
from pathlib import Path

from .config import ConfigError, load_config


def _fmt_ms(v):
    return "-" if v is None else f"{v:.0f}"


def _print_results(results) -> None:
    w = max(len(r.name) for r in results)
    print(f"{'Endpoint'.ljust(w)}  Stat  HTTP    ms  Tries  Errors")
    for r in results:
        print(f"{r.name.ljust(w)}  {'OK  ' if r.ok else 'FAIL'}  {str(r.status or '-'):>4} {_fmt_ms(r.elapsed_ms):>5}"
              f"   {r.attempts:>3}   {'; '.join(r.errors)}")


def cmd_run(args) -> int:
    from .runner import Runner, write_junit
    cfg = load_config(args.config)
    results = Runner(cfg, alerts=not args.no_alerts).run_once()
    _print_results(results)
    if args.junit:
        Path(args.junit).parent.mkdir(parents=True, exist_ok=True)
        write_junit(results, args.junit)
        print(f"JUnit report: {args.junit}")
    print(f"Status page: {cfg.settings.status_page}")
    failed = [r for r in results if not r.ok]
    if failed:
        print(f"\n{len(failed)}/{len(results)} endpoints failing.")
    return 1 if failed and args.fail_on_error else 0


def cmd_watch(args) -> int:
    from .runner import Runner
    cfg = load_config(args.config)
    interval = args.interval or cfg.settings.interval_seconds
    runner = Runner(cfg)
    print(f"Checking every {interval} s – press Ctrl+C to stop")
    try:
        while True:
            started = time.monotonic()
            print(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
            _print_results(runner.run_once())
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def cmd_report(args) -> int:
    from .history import History, sla_report
    cfg = load_config(args.config)
    rows = sla_report(cfg, History(cfg.settings.history_file))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    pct = lambda v: "-" if v is None else f"{v:6.2f}%"
    w = max(len(r["name"]) for r in rows)
    print(f"{'Endpoint'.ljust(w)}     24h      7d     30d    Target     Met    Avg ms  p95 ms")
    for r in rows:
        print(f"{r['name'].ljust(w)}  {pct(r['24h']):>7} {pct(r['7d']):>7} {pct(r['30d']):>7}  {r['target']:6.2f}%"
              f"   {'yes' if r['met'] else 'NO':>6}   {_fmt_ms(r['avg']):>7} {_fmt_ms(r['p95']):>7}")
    return 0 if all(r["met"] for r in rows) or not args.fail_on_breach else 2


def cmd_page(args) -> int:
    from .history import History
    from .statuspage import write_status_page
    cfg = load_config(args.config)
    path = write_status_page(cfg, History(cfg.settings.history_file))
    print(f"Status page: {path}")
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0


def cmd_postman_import(args) -> int:
    from .postman import import_to_yaml
    n = import_to_yaml(Path(args.collection), Path(args.output), Path(args.environment) if args.environment else None)
    print(f"Imported {n} endpoint(s) -> {args.output}")
    return 0


def cmd_postman_export(args) -> int:
    from .postman import export_collection
    cfg = load_config(args.config)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(export_collection(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Postman collection: {out}  ({len(cfg.endpoints)} requests with tests)")
    return 0


def cmd_newman(args) -> int:
    from .postman import run_newman
    env = dict(kv.split("=", 1) for kv in args.env_var or [])
    return run_newman(Path(args.collection), Path(args.junit) if args.junit else None, env)


def cmd_heartbeat(args) -> int:
    """Exit 0 if the last scheduled run is recent – used as the Docker HEALTHCHECK."""
    from .history import History
    cfg = load_config(args.config)
    runs = History(cfg.settings.history_file).runs()
    max_age = args.max_age or cfg.settings.interval_seconds * 3
    if not runs:
        print("unhealthy: no runs recorded yet")
        return 1
    age = time.time() - runs[-1]["ts"]
    if age > max_age:
        print(f"unhealthy: last run {age:.0f}s ago (limit {max_age}s)")
        return 1
    print(f"ok: last run {age:.0f}s ago, {runs[-1]['ok']}/{runs[-1]['total']} endpoints passed")
    return 0


def cmd_gui(args) -> int:
    try:
        from .ui.app import main as gui_main
    except ImportError as exc:
        raise RuntimeError("the desktop app is not available in this install (headless / Docker image). "
                           f"Install the full requirements.txt on a machine with a display. ({exc})") from exc
    gui_main(args.config, demo=args.demo)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="healthcheck", description="Automated API Health-Checker")
    p.add_argument("-c", "--config", default="endpoints.yaml", help="YAML config (default: endpoints.yaml)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("run", help="run all checks once (for CI pipelines)")
    s.add_argument("--junit", help="write a JUnit XML report to this path")
    s.add_argument("--fail-on-error", action="store_true", help="exit with code 1 if any endpoint fails")
    s.add_argument("--no-alerts", action="store_true", help="do not send alerts")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("watch", help="check continuously on a schedule")
    s.add_argument("--interval", type=int, help="seconds (overrides the YAML)")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("report", help="SLA / availability report")
    s.add_argument("--json", action="store_true")
    s.add_argument("--fail-on-breach", action="store_true", help="exit with code 2 if an SLA is breached")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("page", help="regenerate the status page")
    s.add_argument("--open", action="store_true", help="open it in the browser")
    s.set_defaults(func=cmd_page)

    s = sub.add_parser("postman-import", help="Postman collection -> YAML")
    s.add_argument("collection")
    s.add_argument("-e", "--environment", help="Postman environment JSON")
    s.add_argument("-o", "--output", default="endpoints.imported.yaml")
    s.set_defaults(func=cmd_postman_import)

    s = sub.add_parser("postman-export", help="YAML -> Postman collection (runnable with Newman)")
    s.add_argument("-o", "--output", default="postman/health-check.postman_collection.json")
    s.set_defaults(func=cmd_postman_export)

    s = sub.add_parser("newman", help="run a Postman collection with Newman")
    s.add_argument("collection", nargs="?", default="postman/health-check.postman_collection.json")
    s.add_argument("--junit")
    s.add_argument("--env-var", action="append", help="KEY=VALUE (repeatable)")
    s.set_defaults(func=cmd_newman)

    s = sub.add_parser("heartbeat", help="exit 0 if the last run is recent (container health check)")
    s.add_argument("--max-age", type=int, help="seconds (default: 3 x interval_seconds)")
    s.set_defaults(func=cmd_heartbeat)

    s = sub.add_parser("gui", help="desktop app")
    s.add_argument("--demo", action="store_true", help="also start the built-in demo API on port 8000")
    s.set_defaults(func=cmd_gui)
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 3
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 4
