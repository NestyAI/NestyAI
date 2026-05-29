from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def get_current_datetime(timezone: str = "Asia/Ho_Chi_Minh") -> dict[str, str]:
    now = datetime.now(ZoneInfo(timezone))
    return {
        "iso": now.isoformat(),
        "date": now.date().isoformat(),
        "time": now.time().strftime("%H:%M:%S"),
        "timezone": timezone,
    }

