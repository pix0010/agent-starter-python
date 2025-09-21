#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

import sys
from pathlib import Path as _Path
_repo_root = str(_Path(__file__).resolve().parents[1])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from tools.gcal import create_booking  # type: ignore


async def main() -> None:
    load_dotenv('.env.local', override=False)
    tz = ZoneInfo(os.getenv('APP_TZ', 'Europe/Madrid'))
    # Pick next non-closed day at 17:30 (skip Tue/Sun)
    base = (datetime.now(tz) + timedelta(days=1)).replace(hour=17, minute=30, second=0, microsecond=0)
    dt = base
    for _ in range(8):
        if dt.weekday() not in (1, 6):  # 0=Mon ... 6=Sun; skip Tue(1) and Sun(6)
            break
        dt = dt + timedelta(days=1)
    start_iso_sel = dt.isoformat(timespec='minutes')
    print('Selected start time:', start_iso_sel)

    # 2) create booking through n8n with services list
    resp = await create_booking(None, name='Антон', phone='+34600111222', start_iso=start_iso_sel, staff_id='sara', services=['окрашивание', 'стрижка'])
    print('CREATE_BOOKING RESPONSE:', resp)


if __name__ == '__main__':
    asyncio.run(main())
