"""Availability helpers for slot generation."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List
from zoneinfo import ZoneInfo

from .hours import WDAYS_MAP, parse_time, weekday_name_ru, StoreInfo


def generate_slots(
    store: StoreInfo,
    base_dt: datetime,
    *,
    step_minutes: int = 30,
    count: int = 3,
) -> List[Dict[str, str]]:
    tz = ZoneInfo(store.timezone or "Europe/Madrid")
    aware_dt = base_dt.astimezone(tz) if base_dt.tzinfo else base_dt.replace(tzinfo=tz)
    slots: List[Dict[str, str]] = []

    for offset in range(7):
        current = aware_dt + timedelta(days=offset)
        weekday = WDAYS_MAP[current.weekday()]
        intervals = store.hours.get(weekday, [])
        if not intervals:
            continue

        for interval in intervals:
            try:
                raw_start, raw_end = interval.split("-", 1)
                start_t = parse_time(raw_start)
                end_t = parse_time(raw_end)
            except Exception:
                continue

            interval_start = datetime.combine(current.date(), start_t, tzinfo=tz)
            interval_end = datetime.combine(current.date(), end_t, tzinfo=tz)
            if interval_end <= aware_dt and offset == 0:
                continue

            first_slot = max(interval_start, aware_dt if offset == 0 else interval_start)
            first_slot = first_slot.replace(second=0, microsecond=0)
            remainder = first_slot.minute % step_minutes
            if remainder != 0:
                first_slot += timedelta(minutes=step_minutes - remainder)

            step = timedelta(minutes=step_minutes)
            slot_time = first_slot

            while slot_time < interval_end:
                slot_end = slot_time + step
                if slot_end > interval_end:
                    break
                slots.append(
                    {
                        "iso": slot_time.isoformat(timespec="minutes"),
                        "date": slot_time.date().isoformat(),
                        "time": slot_time.strftime("%H:%M"),
                        "end_time": slot_end.strftime("%H:%M"),
                        "weekday": weekday,
                        "weekday_ru": weekday_name_ru(weekday),
                        "label": f"{weekday_name_ru(weekday).capitalize()} {slot_time.strftime('%d.%m')} в {slot_time.strftime('%H:%M')}",
                    }
                )
                if len(slots) >= count:
                    return slots
                slot_time += step

    return slots
