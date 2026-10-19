"""JSON-only CLI; discover every operation with `sja schema`."""
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import config, service
from .daemon import SOCKET, request
from .operations import CONTRACTS


def output(value):
    print(json.dumps(value, ensure_ascii=False))


def parser():
    root = argparse.ArgumentParser(description="Headless SJTU sports operations. All results are JSON.")
    commands = root.add_subparsers(dest="group")
    schema = commands.add_parser("schema", help="Show operations and their JSON input contracts")
    schema.add_argument("operation", nargs="?", choices=sorted(CONTRACTS))
    daemon = commands.add_parser("daemon", help="Manage private local worker process")
    daemon.add_argument("action", choices=["start", "run", "status", "stop", "logs"])
    groups = {}
    for operation, (model, description) in CONTRACTS.items():
        group, action = operation.split(".")
        if group not in groups:
            groups[group] = commands.add_parser(group).add_subparsers(dest="action", required=True)
        command = groups[group].add_parser(action, help=description, description=description)
        command.set_defaults(operation=operation)
        command.add_argument("--json", default="{}", help="JSON object, @FILE, or - for stdin; use schema to inspect fields")
        if operation == "auth.start":
            command.add_argument("--username")
            command.add_argument("--nickname")
            command.add_argument("--password-stdin", action="store_true", help="Read password from stdin; never put it in process arguments")
        elif operation == "auth.verify":
            command.add_argument("--session-id")
            command.add_argument("--code")
    return root


def load_payload(raw):
    if raw == "-":
        raw = sys.stdin.read()
    elif raw.startswith("@"):
        path = Path(raw[1:])
        try:
            raw = path.read_text()
        except OSError as exc:
            raise ValueError(f"Cannot read JSON input file {path}: {exc.strerror}") from exc
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--json must contain an object")
    return value


def daemon_action(action):
    if action == "run":
        from .daemon import run
        run()
        return {"ok": True, "result": {"stopped": True}}
    if action == "logs":
        path = config.DATA_DIR / "daemon.log"
        lines = path.read_text().splitlines()[-100:] if path.exists() else []
        return {"ok": True, "result": {"path": str(path), "lines": lines}}
    if action != "start":
        response = asyncio.run(request(f"daemon.{action}"))
        if action == "stop":
            for _ in range(100):
                if not SOCKET.exists():
                    break
                time.sleep(.05)
        return response
    try:
        return asyncio.run(request("daemon.status", timeout=5))
    except (OSError, asyncio.TimeoutError):
        pass
    log_path = config.DATA_DIR / "daemon.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    env = os.environ.copy()
    env["SJA_DATA_DIR"] = str(config.DATA_DIR)
    with os.fdopen(fd, "a") as handle:
        process = subprocess.Popen([sys.executable, "-m", "sja_booking.daemon"],
                                   stdin=subprocess.DEVNULL, stdout=handle, stderr=handle,
                                   start_new_session=True, env=env, cwd=Path(__file__).resolve().parent.parent)
    for _ in range(100):
        try:
            return asyncio.run(request("daemon.status", timeout=2))
        except (OSError, asyncio.TimeoutError):
            if process.poll() is not None:
                raise RuntimeError(f"Daemon failed to start; inspect {log_path}")
            time.sleep(0.1)
    raise RuntimeError(f"Daemon startup timed out; inspect {log_path}")


def main():
    args = parser().parse_args()
    try:
        if args.group is None:
            initialized = service.initialize_database()
            response = {"ok": True, "result": {**initialized, "stage": "login", "next": "sja auth start --username USER_NAME --password-stdin"}}
        elif args.group == "schema":
            names = [args.operation] if args.operation else sorted(CONTRACTS)
            response = {"ok": True, "result": {name: {"description": CONTRACTS[name][1],
                       "input": CONTRACTS[name][0].model_json_schema()} for name in names}}
        elif args.group == "daemon":
            response = daemon_action(args.action)
        else:
            payload = load_payload(args.json)
            if args.operation in {"auth.start", "auth.qr-start"}:
                daemon_action("start")
            if args.operation == "auth.start":
                for key in ("username", "nickname"):
                    if getattr(args, key) is not None:
                        payload[key] = getattr(args, key)
                if args.password_stdin:
                    if args.json == "-":
                        raise ValueError("Use either --json - or --password-stdin")
                    payload["password"] = sys.stdin.readline().rstrip("\r\n")
                elif "password" not in payload and sys.stdin.isatty():
                    payload["password"] = getpass.getpass("Password: ")
            elif args.operation == "auth.verify":
                if args.session_id:
                    payload["session_id"] = args.session_id
                if args.code:
                    payload["code"] = args.code
            response = asyncio.run(request(args.operation, payload))
        output(response)
        return 0 if response.get("ok") else 1
    except (OSError, asyncio.TimeoutError, ConnectionError) as exc:
        output({"ok": False, "error": {"code": "daemon_unavailable", "message": "Run sja daemon start; inspect sja daemon logs", "detail": str(exc)}})
        return 2
    except (ValueError, RuntimeError) as exc:
        output({"ok": False, "error": {"code": "cli_error", "message": str(exc)}})
        return 2
    except KeyboardInterrupt:
        output({"ok": False, "error": {"code": "interrupted"}})
        return 130


if __name__ == "__main__":
    sys.exit(main())
