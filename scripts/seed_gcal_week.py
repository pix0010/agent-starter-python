#!/usr/bin/env python3
"""Seed Google Calendar with demo busy events for the next 7 days.

Reads GCAL_CALENDAR_MAP or GCAL_DEFAULT_CALENDAR_ID and creates a few
"Busy (Demo)" events to simulate occupancy.

Usage:
  PYTHONPATH=src GOOGLE_APPLICATION_CREDENTIALS=... GCAL_CALENDAR_MAP='{"ruben":"..."}' \
  python scripts/seed_gcal_week.py
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta

from tools.gcal import _get_service, _calendar_id_for_staff, _to_iso


def _staff_ids() -> list[str]:
    raw = os.getenv("GCAL_CALENDAR_MAP", "").strip()
    if raw:
        try:
            mp = json.loads(raw)
            return list(mp.keys())
        except Exception:
            pass
    # default single calendar
    return ["default"]


def main() -> None:
    svc = _get_service()
    tznow = datetime.now().astimezone()
    start_day = tznow.replace(hour=0, minute=0, second=0, microsecond=0)

    for staff_id in _staff_ids():
        cal_id = _calendar_id_for_staff(None if staff_id == "default" else staff_id)
        print(f"Seeding calendar for {staff_id}: {cal_id}")
        # create 1–2 busy blocks per day, 60–120 min
        for d in range(7):
            base = start_day + timedelta(days=d)
            blocks = random.randint(1, 2)
            for _ in range(blocks):
                start_hour = random.choice([10, 11, 12, 16, 17])
                duration = random.choice([60, 90, 120])
                sdt = base.replace(hour=start_hour, minute=0)
                edt = sdt + timedelta(minutes=duration)
                ev = {
                    "summary": "Busy (Demo)",
                    "start": {"dateTime": _to_iso(sdt)},
                    "end": {"dateTime": _to_iso(edt)},
                    "transparency": "opaque",
                }
                created = svc.events().insert(calendarId=cal_id, body=ev).execute()
                print("  +", created.get("id"), _to_iso(sdt), duration)


if __name__ == "__main__":
    main()

