"""Durable local notifications for supervising agents."""
from datetime import datetime, timezone
import uuid

from .database import get_db_manager


def emit(kind, payload):
    event = {"type": kind, "time": datetime.now(timezone.utc).isoformat(), "data": payload}
    return get_db_manager().put("event", str(uuid.uuid4()), event)
