#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple

from dotenv import load_dotenv
import argparse

# reuse helpers from our gcal/tooling
from tools.gcal import _get_service, _calendar_id_for_staff, _busy_intervals, _to_iso
from tools import barber


load_dotenv('.env.local', override=True)


@dataclass
class StaffProfile:
    id: str
    durations: List[int]
    weights: List[float]


def _staff_profiles() -> Dict[str, StaffProfile]:
    return {
        'sara': StaffProfile('sara', durations=[75, 120, 180], weights=[0.5, 0.3, 0.2]),
        'ruben': StaffProfile('ruben', durations=[20, 30, 40, 45, 60], weights=[0.3, 0.3, 0.2, 0.1, 0.1]),
        'alex': StaffProfile('alex', durations=[20, 30], weights=[0.6, 0.4]),
        'pau': StaffProfile('pau', durations=[20, 30, 40, 45], weights=[0.35, 0.35, 0.2, 0.1]),
        'betran': StaffProfile('betran', durations=[20, 50, 60, 75], weights=[0.4, 0.2, 0.2, 0.2]),
    }


WDAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']


def _parse_time(value: str) -> time:
    hh, mm = value.split(':', 1)
    return time(hour=int(hh), minute=int(mm))


def _day_open_intervals(store, dt: datetime) -> List[Tuple[datetime, datetime]]:
    tz = dt.tzinfo
    wday = WDAYS[dt.weekday()]
    slots = store.hours.get(wday, [])
    out = []
    for interval in slots:
        if '-' not in interval:
            continue
        s, e = interval.split('-', 1)
        sdt = datetime.combine(dt.date(), _parse_time(s), tzinfo=tz)
        edt = datetime.combine(dt.date(), _parse_time(e), tzinfo=tz)
        if edt > sdt:
            out.append((sdt, edt))
    return out


def _rand_start_in_interval(start: datetime, end: datetime) -> datetime:
    # align to 30-min grid
    span_min = int((end - start).total_seconds() // 60)
    # choose a grid index
    grid_count = max(1, span_min // 30)
    idx = random.randint(0, grid_count - 1)
    start_dt = start + timedelta(minutes=30 * idx)
    return start_dt.replace(second=0, microsecond=0)


def _intersects(a: Tuple[datetime, datetime], b: Tuple[datetime, datetime]) -> bool:
    (as_, ae) = a
    (bs, be) = b
    return not (ae <= bs or as_ >= be)


def _services_for_staff(db, staff_id: str):
    member = next((m for m in db.staff if m.id == staff_id), None)
    services = db.services
    if not member:
        # fallback: all services
        return [s for s in services if (s.duration_min or 0) > 0]
    svc_map = {s.code: s for s in services}
    out = []
    for code in member.service_codes:
        s = svc_map.get(code)
        if s and (s.duration_min or 0) > 0:
            out.append(s)
    # fallback if mapping empty
    if not out:
        out = [s for s in services if (s.duration_min or 0) > 0]
    return out


_FIRST_NAMES = [
    'Carlos', 'María', 'Lucía', 'Javier', 'Sofía', 'Alejandro', 'Ana', 'Pablo', 'Elena', 'Miguel',
    'Иван', 'Мария', 'Алексей', 'Виктория', 'Дмитрий', 'Ольга',
]

def _fake_client() -> tuple[str, str]:
    name = random.choice(_FIRST_NAMES)
    phone = f"+34 600 {random.randint(100,999)} {random.randint(100,999)}"
    return name, phone


def seed(days_total: int = 10, heavy_days: int = 2) -> None:
    svc = _get_service()

    # Load DB to respect store hours and timezone
    db = barber.load_barber_db('db/barber')
    tznow = datetime.now().astimezone()
    start_day = tznow.replace(hour=0, minute=0, second=0, microsecond=0)

    # Staff from GCAL_CALENDAR_MAP (or default calendar)
    mp_raw = os.getenv('GCAL_CALENDAR_MAP', '').strip()
    if mp_raw:
        staff_ids = list((json.loads(mp_raw) or {}).keys())
    else:
        staff_ids = ['default']

    for staff_id in staff_ids:
        cal_id = _calendar_id_for_staff(None if staff_id == 'default' else staff_id)
        print(f'== {staff_id}: {cal_id}')

        for d in range(days_total):
            base = start_day + timedelta(days=d)
            # Intervals when the shop is open
            intervals = _day_open_intervals(db.store, base.astimezone(tznow.tzinfo))
            if not intervals:
                continue

            # Existing busy intervals from GCal to avoid overlaps
            busy = _busy_intervals(cal_id, _to_iso(base), _to_iso(base + timedelta(days=1)))
            placed: List[Tuple[datetime, datetime]] = []

            # Heavy early days: 4-6 per day; later: 0-2 with gaps
            if d < heavy_days:
                blocks_target = random.randint(4, 6)
            else:
                # 40% days with 0, 40% with 1, 20% с 2
                blocks_target = random.choices([0, 1, 2], weights=[0.4, 0.4, 0.2], k=1)[0]

            attempts = 0
            svcs = _services_for_staff(db, staff_id)
            while blocks_target > 0 and attempts < 120:
                attempts += 1
                interval = random.choice(intervals)
                sdt = _rand_start_in_interval(*interval)
                svc_choice = random.choice(svcs)
                dur = int(svc_choice.duration_min or 30)
                edt = sdt + timedelta(minutes=dur)
                # must fit into interval
                if edt > interval[1]:
                    continue
                cand = (sdt, edt)
                # must not intersect existing busy
                if any(_intersects(cand, b) for b in busy):
                    continue
                if any(_intersects(cand, p) for p in placed):
                    continue
                # create event
                client_name, client_phone = _fake_client()
                ev = {
                    'summary': f"Betrán — {svc_choice.name} — {client_name}",
                    'description': f"Client: {client_name}\nPhone: {client_phone}\nService: {svc_choice.code} — {svc_choice.name}\nPrice: {svc_choice.price_text}",
                    'start': {'dateTime': _to_iso(sdt)},
                    'end': {'dateTime': _to_iso(edt)},
                    'extendedProperties': {
                        'private': {
                            'phone': client_phone,
                            'name': client_name,
                            'service_id': svc_choice.code,
                        }
                    },
                    'transparency': 'opaque',
                }
                created = svc.events().insert(calendarId=cal_id, body=ev).execute()
                print('  +', _to_iso(sdt), dur, svc_choice.code, '→', created.get('id'))
                placed.append(cand)
                blocks_target -= 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Seed realistic salon occupancy into Google Calendars')
    parser.add_argument('--days', type=int, default=10, help='Total days to seed')
    parser.add_argument('--heavy-days', type=int, default=2, help='Number of early heavily-booked days')
    parser.add_argument('--reset', action='store_true', help='Cleanup demo entries before seeding (removes Busy (Demo) and code-prefixed early seeds)')
    args = parser.parse_args()

    random.seed()
    if args.reset:
        from scripts.cleanup_gcal_demo import cleanup  # type: ignore
        cleanup(remove_realistic_code_prefix=True)
    seed(days_total=args.days, heavy_days=args.heavy_days)
