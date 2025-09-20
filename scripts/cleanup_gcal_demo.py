#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

import argparse
from tools.gcal import _get_service, _calendar_id_for_staff, _to_iso


load_dotenv('.env.local', override=True)


def cleanup(days_back: int = 30, days_forward: int = 60, remove_realistic_code_prefix: bool = False) -> None:
    svc = _get_service()
    mp_raw = os.getenv('GCAL_CALENDAR_MAP', '').strip()
    if mp_raw:
        staff_ids = list((json.loads(mp_raw) or {}).keys())
    else:
        staff_ids = ['default']

    now = datetime.now().astimezone()
    t_min = _to_iso(now - timedelta(days=days_back))
    t_max = _to_iso(now + timedelta(days=days_forward))

    for staff_id in staff_ids:
        cal_id = _calendar_id_for_staff(None if staff_id == 'default' else staff_id)
        print(f'== scanning {staff_id}: {cal_id}')
        page_token = None
        removed = 0
        while True:
            events = (
                svc.events()
                .list(
                    calendarId=cal_id,
                    timeMin=t_min,
                    timeMax=t_max,
                    singleEvents=True,
                    orderBy='startTime',
                    pageToken=page_token,
                    maxResults=2500,
                )
                .execute()
            )
            for ev in events.get('items', []) or []:
                summary = (ev.get('summary') or '').strip()
                desc = (ev.get('description') or '').strip()
                # Remove classic demo seeds
                is_demo = 'Busy (Demo)' in summary or 'Busy (Demo)' in desc
                # Optionally, remove old realistic seeds with code prefix in summary (not recommended by default)
                is_old_codey = summary.startswith('Betrán — SVC') if remove_realistic_code_prefix else False
                if is_demo or is_old_codey:
                    svc.events().delete(calendarId=cal_id, eventId=ev['id']).execute()
                    removed += 1
            page_token = events.get('nextPageToken')
            if not page_token:
                break
        print(f'  removed: {removed}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Cleanup demo events from Google Calendars')
    parser.add_argument('--days-back', type=int, default=30, help='Look back range in days')
    parser.add_argument('--days-forward', type=int, default=60, help='Look forward range in days')
    parser.add_argument('--also-realistic', action='store_true', help='Also remove early realistic seeds with code prefix in summary (Betrán — SVC...)')
    args = parser.parse_args()

    cleanup(days_back=args.days_back, days_forward=args.days_forward, remove_realistic_code_prefix=args.also_realistic)
