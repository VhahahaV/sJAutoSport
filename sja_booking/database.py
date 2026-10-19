"""SQLite snapshots and booking history shared by CLI and workers."""
import json
import sqlite3
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path


def encode(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


class DatabaseManager:
    def __init__(self, db_path=None):
        from .config import DATA_DIR
        self.db_path = Path(db_path or DATA_DIR / "state.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,id))")
        self.db_path.chmod(0o600)

    def put(self, kind, key, payload):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload",
                         (kind, key, json.dumps(payload, ensure_ascii=False, default=encode)))
        return True

    def get(self, kind, key):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT payload FROM records WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, kind, key):
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, key)).rowcount
        return bool(count)

    async def save_monitor(self, info):
        return self.put("monitor", info["id"], info)

    async def load_monitor(self, key):
        return self.get("monitor", key)

    async def load_all_monitors(self):
        return self.all("monitor")

    async def delete_monitor(self, key):
        return self.delete("monitor", key)

    async def save_booking_record(self, order_id, preset, venue_name, field_type_name,
                                  date, start_time, end_time, status, message):
        info = dict(order_id=order_id, preset=preset, venue_name=venue_name,
                    field_type_name=field_type_name, date=date, start_time=start_time,
                    end_time=end_time, status=status, message=message,
                    created_at=datetime.now().isoformat())
        return self.put("booking", str(uuid.uuid4()), info)

    async def save_reservation(self, scope, date, order_id, message):
        return self.put("reservation", json.dumps([scope, date]), {"scope": scope, "date": date, "order_id": order_id, "message": message})

    async def get_reservation(self, scope, date):
        return self.get("reservation", json.dumps([scope, date]))

    async def delete_reservation_by_order_id(self, order_id):
        removed = False
        for record in self.all("reservation"):
            if record.get("order_id") == order_id:
                removed |= self.delete("reservation", json.dumps([record["scope"], record["date"]]))
        return removed


_db_manager = None


def get_db_manager():
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
