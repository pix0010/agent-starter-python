from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# Defer heavy imports to runtime to avoid ImportError during static checks

try:
    from livekit.agents.llm import function_tool, RunContext  # new versions
except Exception:  # pragma: no cover
    from livekit.agents import function_tool, RunContext  # old versions

# Import barber module lazily to allow monkeypatch of _get_db in non-worker runs
from . import barber as barber_mod  # reuse service durations and DB


_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_SERVICE_CACHE: Dict[str, Any] = {}


def _load_credentials():
    from google.oauth2 import service_account  # type: ignore

    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    if path and os.path.isfile(path):
        return service_account.Credentials.from_service_account_file(path, scopes=_SCOPES)
    raise RuntimeError("Google service account credentials not provided. Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS.")


def _get_service():
    if "svc" in _SERVICE_CACHE:
        return _SERVICE_CACHE["svc"]
    # dynamic import to avoid hard dependency at import-time
    from googleapiclient.discovery import build  # type: ignore

    creds = _load_credentials()
    svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
    _SERVICE_CACHE["svc"] = svc
    return svc


def _calendar_id_for_staff(staff_id: Optional[str]) -> str:
    mapping_raw = os.getenv("GCAL_CALENDAR_MAP", "")
    default_cal = os.getenv("GCAL_DEFAULT_CALENDAR_ID")
    cal_id: Optional[str] = None
    if mapping_raw.strip():
        try:
            mapping = json.loads(mapping_raw)
            if staff_id and staff_id in mapping:
                cal_id = mapping[staff_id]
        except Exception:
            pass
    if cal_id is None:
        cal_id = default_cal
    if not cal_id:
        raise RuntimeError("GCAL calendar id is not configured. Provide GCAL_CALENDAR_MAP or GCAL_DEFAULT_CALENDAR_ID")
    return str(cal_id)


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _to_iso(dt: datetime) -> str:
    # RFC3339 with seconds, keep timezone
    return dt.isoformat(timespec="seconds")


def _busy_intervals(cal_id: str, start_iso: str, end_iso: str) -> List[Tuple[datetime, datetime]]:
    svc = _get_service()
    body = {
        "timeMin": start_iso,
        "timeMax": end_iso,
        "timeZone": os.getenv("APP_TZ", "Europe/Madrid"),
        "items": [{"id": cal_id}],
    }
    resp = svc.freebusy().query(body=body).execute()
    rngs = []
    cal = (resp.get("calendars") or {}).get(cal_id, {})
    for b in cal.get("busy", []) or []:
        s = _parse_iso(b["start"]) if "T" in b["start"] else datetime.fromisoformat(b["start"] + "T00:00:00+00:00")
        e = _parse_iso(b["end"]) if "T" in b["end"] else datetime.fromisoformat(b["end"] + "T00:00:00+00:00")
        rngs.append((s, e))
    return rngs


def _event_get(cal_id: str, event_id: str) -> Dict[str, Any]:
    svc = _get_service()
    return svc.events().get(calendarId=cal_id, eventId=event_id).execute()


def _event_patch(cal_id: str, event_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    svc = _get_service()
    return svc.events().patch(calendarId=cal_id, eventId=event_id, body=body).execute()


def _intersects(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return not (a_end <= b_start or a_start >= b_end)


def _service_duration_minutes(service_id: Optional[str], fallback: int = 30) -> int:
    if not service_id:
        return fallback
    db = barber_mod._get_db()
    svc = barber_mod._match_service(db, service_id)
    if svc and svc.duration_min:
        return max(30, int(svc.duration_min))
    return fallback


@function_tool(
    name="create_booking",
    description=(
        "Create a Google Calendar booking for the selected time. "
        "Args: name (str), phone (str), start_iso (ISO datetime), service_id (optional), services (optional list), duration_min (optional), staff_id (str). "
        "If services are provided, the total duration will be the sum of their durations. Returns booking id, link, and times."
    ),
)
async def create_booking(
    context: RunContext,
    name: str,
    phone: str,
    start_iso: str,
    staff_id: str,
    service_id: Optional[str] = None,
    services: Optional[List[str]] = None,
    duration_min: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        cal_id = _calendar_id_for_staff(staff_id)
        # Derive duration: explicit parameter > sum(services) > single service
        total = 0
        svc_list = []
        if services:
            for q in services:
                m = barber_mod._match_service(barber_mod._get_db(), q)
                if m and (m.duration_min or 0) > 0:
                    total += int(m.duration_min or 0)
                    svc_list.append(m)
        dur = int(duration_min) if duration_min else (total if total > 0 else _service_duration_minutes(service_id))
        start_dt = _parse_iso(start_iso)
        end_dt = start_dt + timedelta(minutes=dur)

        # Check conflicts
        for b_start, b_end in _busy_intervals(cal_id, _to_iso(start_dt - timedelta(hours=1)), _to_iso(end_dt + timedelta(hours=1))):
            if _intersects(start_dt, end_dt, b_start, b_end):
                return {"ok": False, "error": "time_conflict"}

        # Build event
        svc = _get_service()

        # Resolve service metadata for nicer summary/description
        svc_obj = None
        svc_name = None
        svc_code = None
        price_text = ""
        if svc_list:
            # Compose readable pack name
            names = [s.name for s in svc_list]
            svc_name = " + ".join(names[:2]) + (" …" if len(names) > 2 else "")
            svc_code = ",".join(s.code for s in svc_list)
            price_text = ", ".join(s.price_text for s in svc_list if s.price_text)
        else:
            try:
                if service_id:
                    svc_obj = barber_mod._match_service(barber_mod._get_db(), service_id)
            except Exception:
                svc_obj = None
            svc_name = (svc_obj.name if svc_obj else (service_id or "Appointment")).strip()
            svc_code = (svc_obj.code if svc_obj else (service_id or "")).strip()
            price_text = (svc_obj.price_text if svc_obj else "").strip()

        summary = f"Betrán — {svc_name} — {name}"
        lines = [f"Client: {name}", f"Phone: {phone}"]
        if svc_list:
            lines.append("Services:")
            for s in svc_list:
                lines.append(f"- {s.code} — {s.name} ({s.price_text}; {s.duration_min} min)")
        else:
            lines.append(f"Service: {svc_code} — {svc_name}")
            if price_text:
                lines.append(f"Price: {price_text}")
        description = "\n".join(lines)
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": _to_iso(start_dt)},
            "end": {"dateTime": _to_iso(end_dt)},
            "extendedProperties": {
                "private": {
                    "phone": phone,
                    "name": name,
                    "service_id": svc_code or (service_id or ""),
                    "services": json.dumps([s.code for s in svc_list]) if svc_list else "",
                }
            },
            "transparency": "opaque",
        }
        created = svc.events().insert(calendarId=cal_id, body=event).execute()
        return {
            "ok": True,
            "booking_id": created.get("id"),
            "html_link": created.get("htmlLink"),
            "start": created.get("start", {}).get("dateTime"),
            "end": created.get("end", {}).get("dateTime"),
            "calendar_id": cal_id,
        }
    except Exception as e:
        return {"ok": False, "error": "gcal_error", "detail": str(e)}


@function_tool(
    name="cancel_booking",
    description=(
        "Cancel a Google Calendar booking. Args: booking_id (str), staff_id (str)."
    ),
)
async def cancel_booking(context: RunContext, booking_id: str, staff_id: str) -> Dict[str, Any]:
    try:
        cal_id = _calendar_id_for_staff(staff_id)
        svc = _get_service()
        svc.events().delete(calendarId=cal_id, eventId=booking_id).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": "gcal_error", "detail": str(e)}


@function_tool(
    name="find_booking_by_phone",
    description=(
        "Find calendar bookings by phone number in extended properties. "
        "Args: phone (str), staff_id (str), days (int, default 30), from_iso (optional)."
    ),
)
async def find_booking_by_phone(
    context: RunContext,
    phone: str,
    staff_id: str,
    days: int = 30,
    from_iso: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        cal_id = _calendar_id_for_staff(staff_id)
        svc = _get_service()
        now = datetime.now().astimezone()
        t_min = _to_iso(datetime.fromisoformat(from_iso)) if from_iso else _to_iso(now - timedelta(days=1))
        t_max = _to_iso(now + timedelta(days=max(1, min(int(days or 30), 180))))
        events = (
            svc.events()
            .list(
                calendarId=cal_id,
                privateExtendedProperty=f"phone={phone}",
                timeMin=t_min,
                timeMax=t_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            )
            .execute()
        )
        items = []
        for ev in events.get("items", []) or []:
            items.append(
                {
                    "id": ev.get("id"),
                    "summary": ev.get("summary"),
                    "start": (ev.get("start", {}) or {}).get("dateTime"),
                    "end": (ev.get("end", {}) or {}).get("dateTime"),
                    "html_link": ev.get("htmlLink"),
                }
            )
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": "gcal_error", "detail": str(e)}


@function_tool(
    name="reschedule_booking",
    description=(
        "Reschedule an existing booking to a new start time. "
        "Args: booking_id (str), staff_id (str), new_start_iso (ISO), service_id (optional), duration_min (optional)."
    ),
)
async def reschedule_booking(
    context: RunContext,
    booking_id: str,
    staff_id: str,
    new_start_iso: str,
    service_id: Optional[str] = None,
    duration_min: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        cal_id = _calendar_id_for_staff(staff_id)
        # Fetch current event to compute duration if not provided
        current = _event_get(cal_id, booking_id)
        cur_start_raw = (current.get("start", {}) or {}).get("dateTime")
        cur_end_raw = (current.get("end", {}) or {}).get("dateTime")
        if not cur_start_raw or not cur_end_raw:
            return {"ok": False, "error": "event_missing_times"}
        cur_start = _parse_iso(cur_start_raw)
        cur_end = _parse_iso(cur_end_raw)
        cur_dur = int((cur_end - cur_start).total_seconds() // 60)

        dur = int(duration_min) if duration_min else (int(_service_duration_minutes(service_id)) if service_id else cur_dur)

        new_start = _parse_iso(new_start_iso)
        new_end = new_start + timedelta(minutes=dur)

        # Free/busy check, excluding current event timeframe
        busy = _busy_intervals(cal_id, _to_iso(new_start - timedelta(hours=1)), _to_iso(new_end + timedelta(hours=1)))
        for b_start, b_end in busy:
            # allow overlap only if it exactly matches current event time window
            if _intersects(new_start, new_end, b_start, b_end) and not (
                b_start == cur_start and b_end == cur_end
            ):
                return {"ok": False, "error": "time_conflict"}

        body = {
            "start": {"dateTime": _to_iso(new_start)},
            "end": {"dateTime": _to_iso(new_end)},
        }
        updated = _event_patch(cal_id, booking_id, body)
        return {
            "ok": True,
            "booking_id": booking_id,
            "start": updated.get("start", {}).get("dateTime"),
            "end": updated.get("end", {}).get("dateTime"),
        }
    except Exception as e:
        return {"ok": False, "error": "gcal_error", "detail": str(e)}


def filter_slots_with_gcal(staff_id: str, slot_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter pre-computed slot items against Google Calendar busy intervals.

    slot_items: list of dicts with keys: iso (start), date, time, end_time, weekday, ...
    Returns items that do not intersect busy intervals.
    """
    try:
        cal_id = _calendar_id_for_staff(staff_id)
        if not slot_items:
            return slot_items
        first = slot_items[0]
        # Determine query window: from first slot start to last slot end
        start_dt = _parse_iso(first["iso"]) if "iso" in first else None
        end_dt = None
        for it in slot_items:
            # compute end per item
            if "iso" in it and it.get("end_time"):
                dt = _parse_iso(it["iso"]).replace()
                # end from date + end_time
                end_candidate = datetime.fromisoformat(it["iso"])  # start with tz
                # derive end by replacing hour/minute
                hh, mm = map(int, (it["end_time"] or "00:00").split(":"))
                end_candidate = end_candidate.replace(hour=hh, minute=mm)
                end_dt = end_candidate if end_dt is None or end_candidate > end_dt else end_dt
        if start_dt is None or end_dt is None:
            return slot_items
        busy = _busy_intervals(cal_id, _to_iso(start_dt), _to_iso(end_dt))

        def is_free(item: Dict[str, Any]) -> bool:
            if "iso" not in item:
                return True
            s = _parse_iso(item["iso"])
            hh, mm = map(int, (item.get("end_time") or "00:00").split(":"))
            e = s.replace(hour=hh, minute=mm)
            for b_start, b_end in busy:
                if _intersects(s, e, b_start, b_end):
                    return False
            return True

        return [x for x in slot_items if is_free(x)]
    except Exception:
        # On any error, return original list to avoid blocking flow
        return slot_items
