"""A private Unix socket keeps captcha sessions and async workers alive across CLI calls."""
import asyncio
import fcntl
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone

from pydantic import ValidationError

from . import config, service
from .models import BookingTarget
from .notification import emit
from .operations import Operations, public

SOCKET = config.DATA_DIR / "agent.sock"
MAX_MESSAGE = 4 * 1024 * 1024


async def request(operation, payload=None, timeout=600):
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(SOCKET), limit=MAX_MESSAGE), 5)
    try:
        writer.write(json.dumps({"operation": operation, "payload": payload or {}}).encode() + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout)
        if not line:
            raise ConnectionError("Daemon closed connection; inspect daemon.log")
        return json.loads(line)
    finally:
        writer.close()
        await writer.wait_closed()


class Daemon:
    def __init__(self):
        self.ops = Operations()
        self.stop = asyncio.Event()
        self.lock = asyncio.Lock()
        self.restored = False

    async def handle(self, reader, writer):
        try:
            raw = await asyncio.wait_for(reader.readline(), 10)
            envelope = json.loads(raw)
            operation = envelope["operation"]
            async with self.lock:
                if operation == "daemon.status":
                    result = {"pid": os.getpid(), "data_dir": str(config.DATA_DIR), "restored": self.restored}
                elif operation == "daemon.stop":
                    self.stop.set()
                    result = {"stopping": True}
                else:
                    result = await self.ops.dispatch(operation, envelope.get("payload", {}))
            result = public(result)
            success = not (isinstance(result, dict) and result.get("success") is False)
            response = {"ok": success, "result": result}
        except PermissionError as exc:
            response = {"ok": False, "error": {"code": "login_required", "message": str(exc)}}
        except ValidationError as exc:
            response = {"ok": False, "error": {"code": "invalid_input", "details": exc.errors(include_input=False, include_context=False, include_url=False)}}
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            response = {"ok": False, "error": {"code": "invalid_request", "message": str(exc)}}
        except Exception as exc:
            logging.getLogger(__name__).exception("Command failed")
            response = {"ok": False, "error": {"code": "operation_failed", "message": str(exc)}}
        try:
            writer.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def restore(self):
        await service.restore_state()
        self.restored = True

    async def expire_logins(self):
        while True:
            for sid, session in list(service._login_sessions.items()):
                if datetime.now(timezone.utc) - session.created_at > service._LOGIN_SESSION_TIMEOUT:
                    result = await service.cancel_login_session(sid)
                    self.ops.login_result(result, sid)
            for sid, session in list(service._qr_sessions.items()):
                if datetime.now(timezone.utc) - session["created_at"] > service._LOGIN_SESSION_TIMEOUT:
                    await service.cancel_qr_login(sid)
                    self.ops.login_result({}, sid)
            await asyncio.sleep(30)

    async def shutdown(self):
        await service.shutdown()
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for path in self.ops.captchas.values():
            path.unlink(missing_ok=True)

    async def run(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop.set)
        await self.restore()
        asyncio.create_task(self.expire_logins(), name="expire-logins")
        server = await asyncio.start_unix_server(self.handle, path=str(SOCKET), limit=MAX_MESSAGE)
        SOCKET.chmod(0o600)
        emit("daemon_started", {"pid": os.getpid()})
        try:
            await self.stop.wait()
            # Finish active commands before cancellation or a shutdown could leave
            # a reservation in an unknown state.
            async with self.lock:
                pass
        finally:
            server.close()
            await server.wait_closed()
            await self.shutdown()


def run():
    os.umask(0o077)
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with (config.DATA_DIR / "daemon.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another daemon already owns this data directory")
        SOCKET.unlink(missing_ok=True)
        try:
            asyncio.run(Daemon().run())
        finally:
            SOCKET.unlink(missing_ok=True)


if __name__ == "__main__":
    run()
