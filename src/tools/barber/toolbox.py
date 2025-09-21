"""Function tools exposed to the agent for salon knowledge."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

try:  # pragma: no cover
    from livekit.agents.llm import function_tool, RunContext
except Exception:  # pragma: no cover
    from livekit.agents import function_tool, RunContext  # type: ignore

from livekit.agents import get_job_context

from .availability import generate_slots
from .hours import StoreInfo, WDAYS_MAP, parse_store_info
from .matching import match_service
from .services import (
    BarberDB,
    Service,
    StaffMember,
    build_service_index,
    build_service_tags,
    parse_master_profiles,
    parse_services_catalog,
    read_text,
)


# Compatibility shim: lazily import new booking helpers once module is loaded
_EXTERNAL_DB: Optional[BarberDB] = None


def set_external_db(db: BarberDB) -> None:
    global _EXTERNAL_DB
    _EXTERNAL_DB = db


def load_barber_db(base_dir: str | Path) -> BarberDB:
    base = Path(base_dir)

    services_text = read_text(base / "bertran_services_catalog.txt")
    facts_text = read_text(base / "bertran_kb_facts.txt")
    masters_text = read_text(base / "bertran_master_profiles.txt")
    knowledge_plain = read_text(base / "betran_estilistas_plain.txt")
    playbook_text = read_text(base / "bertran_conversation_playbook.txt")

    store = parse_store_info(facts_text)
    services = parse_services_catalog(services_text)
    staff = parse_master_profiles(masters_text, store.hours, store.closed_days)
    service_index, service_keywords = build_service_index(services)
    service_tags = build_service_tags(services)

    for member in staff:
        member_tags = set(member.specialties)
        matched_codes: List[str] = []
        for svc in services:
            tags = service_tags.get(svc.code.lower(), [])
            if "generalist" in member_tags or member_tags.intersection(tags):
                matched_codes.append(svc.code)
        member.service_codes = sorted(matched_codes)

    knowledge = {
        "facts": facts_text.strip(),
        "services_catalog": services_text.strip(),
        "masters": masters_text.strip(),
        "salon_story": knowledge_plain.strip(),
    }

    return BarberDB(
        store=store,
        services=services,
        staff=staff,
        knowledge=knowledge,
        conversation_playbook=playbook_text.strip(),
        service_index=service_index,
        service_keywords=service_keywords,
        service_tags=service_tags,
    )


def _get_db() -> BarberDB:
    if _EXTERNAL_DB is not None:
        return _EXTERNAL_DB
    try:
        ctx = get_job_context()
        return ctx.proc.userdata["barber_db"]
    except Exception:
        # Fallback for non-worker runs: load once from disk
        base = Path("db/barber")
        # cache in EXTERNAL_DB to avoid reloading
        db = load_barber_db(base)
        set_external_db(db)
        return db


def _is_holiday(store: StoreInfo, date_iso: str) -> bool:
    date_key = (date_iso or "")[:10]
    return date_key in set(store.holidays)


def _staff_by_id(db: BarberDB, staff_id: str) -> Optional[StaffMember]:
    return next((member for member in db.staff if member.id == staff_id), None)


@function_tool(
    name="resolve_date",
    description=(
        "Parse a natural-language date in RU/ES/EN into a concrete date in salon timezone. "
        "Args: query (str), prefer_morning (bool=false) to bias start-of-day."
    ),
)
async def resolve_date(context: RunContext, query: str, prefer_morning: bool = False) -> Dict[str, Any]:
    db = _get_db()
    tz = ZoneInfo(db.store.timezone or "Europe/Madrid")
    now = datetime.now(tz)
    text = (query or "").strip()
    try:
        import dateparser  # type: ignore
    except Exception:
        weekdays = {
            "понедель": 0,
            "вторник": 1,
            "сред": 2,
            "четверг": 3,
            "пятниц": 4,
            "суббот": 5,
            "воскрес": 6,
            "lunes": 0,
            "martes": 1,
            "miércoles": 2,
            "miercoles": 2,
            "jueves": 3,
            "viernes": 4,
            "sábado": 5,
            "sabado": 5,
            "domingo": 6,
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        w = None
        low = text.lower()
        for k, idx in weekdays.items():
            if k in low:
                w = idx
                break
        if w is None:
            target = now
        else:
            days_ahead = (w - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target = now + timedelta(days=days_ahead)
    else:
        settings = {
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": now,
            "TIMEZONE": db.store.timezone or "Europe/Madrid",
            "RETURN_AS_TIMEZONE_AWARE": True,
        }
        dt = dateparser.parse(text, settings=settings, languages=["ru", "es", "en"])  # type: ignore
        if not dt:
            return {"ok": False, "error": "could_not_parse"}
        target = dt.astimezone(tz)

    date_str = target.date().isoformat()
    weekday = WDAYS_MAP[target.weekday()]
    hour = 9 if prefer_morning else 8
    start_iso = datetime(target.year, target.month, target.day, hour, 0, tzinfo=tz).isoformat(timespec="minutes")
    return {"ok": True, "date": date_str, "weekday": weekday, "start_iso": start_iso}


@function_tool(
    name="get_services",
    description="List all services with duration and price. Args: locale (str, e.g. 'ru' or 'es').",
)
async def get_services(context: RunContext, locale: str = "ru") -> Dict[str, Any]:
    db = _get_db()
    out = []
    for svc in db.services:
        out.append(
            {
                "id": svc.code,
                "name": svc.name,
                "category": svc.category,
                "duration_min": svc.duration_min,
                "price_text": svc.price_text,
                "price_eur": svc.price_eur,
                "tags": db.service_tags.get(svc.code.lower(), []),
            }
        )
    return {"currency": db.currency, "services": out}


@function_tool(
    name="get_price",
    description="Get price & duration for a given service by id or human name. Args: service (str), locale (str).",
)
async def get_price(context: RunContext, service: str, locale: str = "ru") -> Dict[str, Any]:
    db = _get_db()
    svc = match_service(db, service)
    if not svc:
        return {"ok": False, "error": "service_not_found", "query": service}
    return {
        "ok": True,
        "service": {
            "id": svc.code,
            "name": svc.name,
            "category": svc.category,
            "duration_min": svc.duration_min,
            "price_text": svc.price_text,
            "price_eur": svc.price_eur,
            "tags": db.service_tags.get(svc.code.lower(), []),
        },
        "currency": db.currency,
    }


@function_tool(
    name="get_open_hours",
    description=(
        "Get shop open hours. If date_iso (ISO 8601) is provided, returns the day's status (open/closed) "
        "and working interval, considering holidays. Args: date_iso (str|None)."
    ),
)
async def get_open_hours(context: RunContext, date_iso: Optional[str] = None) -> Dict[str, Any]:
    db = _get_db()
    store = db.store
    if not date_iso:
        return {
            "store": {
                "name": store.name,
                "address": store.address,
                "phone": store.phone,
                "email": store.email,
                "timezone": store.timezone,
                "hours": store.hours,
                "closed_days": store.closed_days,
            }
        }

    try:
        dt = datetime.fromisoformat(date_iso)
    except Exception:
        return {"ok": False, "error": "bad_date"}

    tz = ZoneInfo(store.timezone or "Europe/Madrid")
    dt = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
    weekday = WDAYS_MAP[dt.weekday()]

    if weekday in store.closed_days or _is_holiday(store, date_iso):
        return {
            "ok": True,
            "date": dt.date().isoformat(),
            "weekday": weekday,
            "open": False,
            "hours": [],
            "reason": "holiday" if _is_holiday(store, date_iso) else "closed",
        }

    return {
        "ok": True,
        "date": dt.date().isoformat(),
        "weekday": weekday,
        "open": True,
        "hours": store.hours.get(weekday, []),
    }


def _list_staff_payload(member: StaffMember, db: BarberDB) -> Dict[str, Any]:
    return {
        "id": member.id,
        "name": member.name,
        "summary": member.summary,
        "specialties": member.specialties,
        "service_codes": member.service_codes,
    }


def _bookable_staff_ids() -> Sequence[str]:
    raw = os.getenv("GCAL_CALENDAR_MAP", "") or os.getenv("BOOKING_STAFF_IDS", "")
    if not raw:
        return []
    try:
        mapping = json.loads(raw)
        if isinstance(mapping, dict):
            return list(mapping.keys())
        if isinstance(mapping, list):
            return [str(item) for item in mapping]
    except Exception:
        return []
    return []


@function_tool(
    name="list_staff",
    description=(
        "List staff members. Args: locale (str='ru'), bookable_only (bool)."
    ),
)
async def list_staff(context: RunContext, locale: str = "ru", bookable_only: bool = False) -> Dict[str, Any]:
    db = _get_db()
    staff = db.staff
    if bookable_only:
        allowed = set(_bookable_staff_ids())
        if allowed:
            staff = [member for member in staff if member.id in allowed]
    return {"ok": True, "staff": [_list_staff_payload(member, db) for member in staff]}


@function_tool(
    name="get_staff_day",
    description="Return staff availability for a given day. Args: staff_id (str), date_iso (str).",
)
async def get_staff_day(context: RunContext, staff_id: str, date_iso: str) -> Dict[str, Any]:
    db = _get_db()
    staff = _staff_by_id(db, staff_id)
    if not staff:
        return {"ok": False, "error": "staff_not_found"}

    tz = ZoneInfo(db.store.timezone or "Europe/Madrid")
    try:
        dt = datetime.fromisoformat(date_iso)
    except Exception:
        return {"ok": False, "error": "bad_date"}
    dt = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
    weekday = WDAYS_MAP[dt.weekday()]

    weekly_off = set(staff.weekly_days_off)
    date_key = dt.date().isoformat()
    time_off_dates = set(staff.time_off_dates)
    holiday = _is_holiday(db.store, date_iso)
    store_closed = weekday in db.store.closed_days

    shifts_by_wday = staff.schedule.get(weekday, [])
    working = bool(shifts_by_wday) and not (
        store_closed or holiday or weekday in weekly_off or date_key in time_off_dates
    )
    reason: Optional[str] = None
    if not working:
        if store_closed:
            reason = "store_closed"
        elif holiday:
            reason = "holiday"
        elif weekday in weekly_off:
            reason = "weekly_day_off"
        elif date_key in time_off_dates:
            reason = "time_off"

    return {
        "ok": True,
        "staff_id": staff_id,
        "date": dt.date().isoformat(),
        "weekday": weekday,
        "working": working,
        "shifts": shifts_by_wday if working else [],
        "day_off_reason": reason,
        "holiday": holiday,
        "store_closed": store_closed,
    }


@function_tool(
    name="get_staff_week",
    description=(
        "Return staff availability for the next N days. Args: staff_id (str), start_iso (str|None), days (int)."
    ),
)
async def get_staff_week(
    context: RunContext,
    staff_id: str,
    start_iso: Optional[str] = None,
    days: int = 7,
) -> Dict[str, Any]:
    db = _get_db()
    staff = _staff_by_id(db, staff_id)
    if not staff:
        return {"ok": False, "error": "staff_not_found"}

    store = db.store
    tz = ZoneInfo(store.timezone or "Europe/Madrid")

    if start_iso:
        try:
            base_dt = datetime.fromisoformat(start_iso)
            if base_dt.tzinfo is None:
                base_dt = base_dt.replace(tzinfo=tz)
            else:
                base_dt = base_dt.astimezone(tz)
        except Exception:
            return {"ok": False, "error": "bad_start_iso"}
    else:
        base_dt = datetime.now(tz)

    days = max(1, min(int(days or 7), 14))

    items: List[Dict[str, Any]] = []
    for offset in range(days):
        dt = base_dt + timedelta(days=offset)
        weekday = WDAYS_MAP[dt.weekday()]
        weekly_off = set(staff.weekly_days_off)
        date_iso = dt.isoformat(timespec="minutes")
        date_key = date_iso[:10]
        time_off_dates = set(staff.time_off_dates)
        holiday = _is_holiday(store, date_iso)
        store_closed = weekday in store.closed_days

        shifts_by_wday = staff.schedule.get(weekday, [])
        working = bool(shifts_by_wday) and not (
            store_closed or holiday or weekday in weekly_off or date_key in time_off_dates
        )
        reason: Optional[str] = None
        if not working:
            if store_closed:
                reason = "store_closed"
            elif holiday:
                reason = "holiday"
            elif weekday in weekly_off:
                reason = "weekly_day_off"
            elif date_key in time_off_dates:
                reason = "time_off"

        items.append(
            {
                "date": dt.date().isoformat(),
                "weekday": weekday,
                "working": working,
                "shifts": shifts_by_wday if working else [],
                "day_off_reason": reason,
                "holiday": holiday,
                "store_closed": store_closed,
            }
        )

    return {"ok": True, "staff_id": staff_id, "start": base_dt.isoformat(timespec="minutes"), "days": items}


def _duration_from_services(
    db: BarberDB, service_id: Optional[str], services: Optional[List[str]]
) -> tuple[int, List[Service], Optional[Service]]:
    services_list: List[Service] = []
    total_minutes = 0
    primary: Optional[Service] = None
    if services:
        for q in services:
            m = match_service(db, q)
            if m and (m.duration_min or 0) > 0:
                services_list.append(m)
                total_minutes += int(m.duration_min or 0)
        if not services_list and service_id:
            primary = match_service(db, service_id)
    else:
        if service_id:
            primary = match_service(db, service_id)
            if primary and (primary.duration_min or 0) > 0:
                total_minutes = int(primary.duration_min or 0)
                services_list.append(primary)
    return total_minutes, services_list, primary


def _filter_slots_by_staff(raw: List[Dict[str, Any]], staff: StaffMember) -> List[Dict[str, Any]]:
    filtered = []
    time_off_dates = set(staff.time_off_dates)
    weekly_off = set(staff.weekly_days_off)
    for slot in raw:
        date_iso = slot["iso"]
        weekday = slot.get("weekday")
        if weekday in weekly_off:
            continue
        date_key = date_iso[:10]
        if date_key in time_off_dates:
            continue
        filtered.append(slot)
    return filtered


@function_tool(
    name="suggest_slots",
    description=(
        "Suggest appointment slots based on store hours and Google Calendar occupancy. "
        "Args: count (int, default 3), start_iso (optional ISO datetime), service_id (optional), services (optional list of service ids/names), party (int, default 1), staff_id (optional). "
        "If a single service_id or a list of services is provided, allocates contiguous 30-min blocks covering total duration. For party>1, returns sequential group slots."
    ),
)
async def suggest_slots(
    context: RunContext,
    count: int = 3,
    start_iso: Optional[str] = None,
    service_id: Optional[str] = None,
    services: Optional[List[str]] = None,
    party: int = 1,
    staff_id: Optional[str] = None,
) -> Dict[str, Any]:
    db = _get_db()
    store = db.store
    tz = ZoneInfo(store.timezone or "Europe/Madrid")

    if start_iso:
        try:
            base_dt = datetime.fromisoformat(start_iso)
            if base_dt.tzinfo is None:
                base_dt = base_dt.replace(tzinfo=tz)
            else:
                base_dt = base_dt.astimezone(tz)
        except Exception:
            return {"ok": False, "error": "bad_start_iso"}
    else:
        base_dt = datetime.now(tz)

    if count <= 0:
        count = 3
    party = max(1, min(int(party or 1), 4))

    total_minutes, services_list, svc = _duration_from_services(db, service_id, services)
    block_count = 1
    if total_minutes > 0:
        dur = max(30, total_minutes)
        block_count = max(1, (dur + 29) // 30)

    staff = _staff_by_id(db, staff_id) if staff_id else None

    raw = generate_slots(store, base_dt, count=max(count * max(block_count, party) * 3, count))

    if staff is not None:
        raw = _filter_slots_by_staff(raw, staff)

    def contiguous(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        return a["end_time"] == b["time"] and a["date"] == b["date"]

    grouped: List[Dict[str, Any]] = []
    grouped_limit = count if staff is not None else max(count * 4, count)
    i = 0
    while i < len(raw):
        start = raw[i]
        ok = True
        block = [start]
        j = i
        for _ in range(1, block_count):
            if j + 1 >= len(raw) or not contiguous(raw[j], raw[j + 1]):
                ok = False
                break
            block.append(raw[j + 1])
            j += 1

        if ok:
            if party == 1:
                end_slot = block[-1]
                grouped.append(
                    {
                        "iso": start["iso"],
                        "date": start["date"],
                        "time": start["time"],
                        "end_time": end_slot["end_time"],
                        "weekday": start["weekday"],
                        "weekday_ru": start.get("weekday_ru"),
                        "label": start["label"],
                        "blocks": block_count,
                        "service_id": (svc.code if svc else None),
                        "services": [s.code for s in services_list] if services_list else ([(svc.code)] if svc else []),
                    }
                )
            else:
                grp_ok = True
                grp = [start]
                jj = j
                for _ in range(1, party):
                    if jj + 1 >= len(raw) or not contiguous(raw[jj], raw[jj + 1]):
                        grp_ok = False
                        break
                    grp.append(raw[jj + 1])
                    jj += 1
                if grp_ok:
                    grouped.append(
                        {
                            "group": [
                                {
                                    "iso": x["iso"],
                                    "time": x["time"],
                                    "end_time": x["end_time"],
                                }
                                for x in grp
                            ],
                            "date": start["date"],
                            "weekday": start["weekday"],
                            "weekday_ru": start.get("weekday_ru"),
                            "label": start["label"],
                            "party": party,
                            "blocks": block_count,
                            "service_id": (svc.code if svc else None),
                            "services": [s.code for s in services_list] if services_list else ([(svc.code)] if svc else []),
                        }
                    )

        i += 1 if block_count == 1 else block_count
        if len(grouped) >= grouped_limit:
            break

    if staff is not None:
        for item in grouped:
            item.setdefault("staff", [])
            if staff.id not in item["staff"]:
                item["staff"].append(staff.id)

    return {
        "ok": bool(grouped),
        "timezone": store.timezone,
        "start": base_dt.isoformat(timespec="minutes"),
        "slots": grouped[:count],
    }


@function_tool(
    name="remember_contact",
    description=(
        "Store user's contact for booking follow-up. "
        "Args: name (str), phone (str). Returns ok and a reference id."
    ),
)
async def remember_contact(context: RunContext, name: str, phone: str) -> Dict[str, Any]:
    name = (name or "").strip()
    phone = (phone or "").strip()
    if not name or not phone:
        return {"ok": False, "error": "missing_name_or_phone"}

    Path("logs").mkdir(exist_ok=True)
    path = Path("logs/contacts.csv")
    ref = hashlib.sha1(f"{name}|{phone}".encode("utf-8")).hexdigest()[:10]
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["ref", "name", "phone"])
        writer.writerow([ref, name, phone])
    return {"ok": True, "ref": ref}
