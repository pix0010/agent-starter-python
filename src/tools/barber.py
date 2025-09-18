from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Совместимость импортов в разных версиях livekit-agents
try:
    from livekit.agents.llm import function_tool, RunContext
except Exception:
    from livekit.agents import function_tool, RunContext

from livekit.agents import get_job_context  # чтобы достать proc.userdata в тулзе


# ---------- Загрузка БД (из JSON в память) ----------

@dataclass
class BarberDB:
    currency: str
    services: List[Dict[str, Any]]
    staff: List[Dict[str, Any]]
    store: Dict[str, Any]

def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def load_barber_db(base_dir: str | Path) -> BarberDB:
    base = Path(base_dir)
    services = _read_json(base / "services.json")
    staff = _read_json(base / "staff.json")
    store = _read_json(base / "store.json")

    currency = services.get("currency") or "EUR"
    return BarberDB(
        currency=currency,
        services=services.get("services", []),
        staff=staff.get("staff", []),
        store=store,
    )

# ---------- Утилиты ----------

WDAYS_MAP = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"
}

def _get_db() -> BarberDB:
    # Достаём объект БД, загруженный в prewarm
    ctx = get_job_context()
    return ctx.proc.userdata["barber_db"]

def _localize_name(name_dict: Dict[str, str], locale: str) -> str:
    if not isinstance(name_dict, dict):
        return str(name_dict)
    return name_dict.get(locale) or name_dict.get("ru") or name_dict.get("es") or name_dict.get("en") or next(iter(name_dict.values()), "")

def _weekday_hours(store: Dict[str, Any], dt: Optional[datetime]) -> Dict[str, Any]:
    hours = store.get("hours", {})
    if dt is None:
        return {"hours": hours}
    wday = WDAYS_MAP[dt.weekday()]
    val = hours.get(wday, "closed")
    return {"weekday": wday, "value": val}

def _is_holiday(store: Dict[str, Any], date_iso: str) -> bool:
    holidays = store.get("holidays", [])
    return date_iso[:10] in set(holidays)

def _match_service(services: List[Dict[str, Any]], query: str, locale: str) -> Optional[Dict[str, Any]]:
    q = query.strip().lower()
    # 1) точное совпадение по id
    for s in services:
        if str(s.get("id", "")).lower() == q:
            return s
    # 2) вхождение по именам (во всех локалях)
    for s in services:
        name = s.get("name")
        if isinstance(name, dict):
            # сначала локаль
            if q in (name.get(locale, "")).lower():
                return s
            # потом любые прочие
            for v in name.values():
                if q in str(v).lower():
                    return s
        else:
            if q in str(name).lower():
                return s
    return None

# ---------- Тулзы ----------

@function_tool(
    name="get_services",
    description="List all services with duration and price. Args: locale (str, e.g. 'ru' or 'es').",
)
async def get_services(context: RunContext, locale: str = "ru") -> Dict[str, Any]:
    db = _get_db()
    out = []
    for s in db.services:
        out.append({
            "id": s.get("id"),
            "name": _localize_name(s.get("name", {}), locale),
            "duration_min": s.get("duration_min"),
            "price": s.get("price"),
        })
    return {"currency": db.currency, "services": out}

@function_tool(
    name="get_price",
    description="Get price & duration for a given service by id or human name. Args: service (str), locale (str).",
)
async def get_price(context: RunContext, service: str, locale: str = "ru") -> Dict[str, Any]:
    db = _get_db()
    s = _match_service(db.services, service, locale)
    if not s:
        return {"ok": False, "error": "service_not_found", "query": service}
    return {
        "ok": True,
        "service": {
            "id": s.get("id"),
            "name": _localize_name(s.get("name", {}), locale),
            "duration_min": s.get("duration_min"),
            "price": s.get("price"),
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
    store = db.store or {}
    if not date_iso:
        return {"store": {"name": store.get("name"), "timezone": store.get("timezone"), "hours": store.get("hours")}}

    try:
        dt = datetime.fromisoformat(date_iso)
    except Exception:
        return {"ok": False, "error": "bad_date_iso"}

    day = _weekday_hours(store, dt)
    closed = (day.get("value", "closed") == "closed") or _is_holiday(store, date_iso)
    return {
        "ok": True,
        "date": date_iso,
        "weekday": day.get("weekday"),
        "closed": closed,
        "hours": None if closed else day.get("value"),
        "holiday": _is_holiday(store, date_iso),
    }

@function_tool(
    name="list_staff",
    description="List staff and skills. Optionally filter by service_id.",
)
async def list_staff(context: RunContext, service_id: Optional[str] = None) -> Dict[str, Any]:
    db = _get_db()
    out = []
    for st in db.staff:
        skills = st.get("skills", [])
        if service_id and service_id not in skills:
            continue
        out.append({"id": st.get("id"), "name": st.get("name"), "skills": skills})
    return {"staff": out}

@function_tool(
    name="get_staff_day",
    description="Get staff working status and shifts for a given date. Args: staff_id (str), date_iso (ISO 8601).",
)
async def get_staff_day(context: RunContext, staff_id: str, date_iso: str) -> Dict[str, Any]:
    db = _get_db()
    try:
        dt = datetime.fromisoformat(date_iso)
    except Exception:
        return {"ok": False, "error": "bad_date_iso"}

    # найти сотрудника
    staff = next((s for s in db.staff if s.get("id") == staff_id), None)
    if not staff:
        return {"ok": False, "error": "staff_not_found"}

    # выходные конкретного сотрудника
    days_off = set(staff.get("days_off", []))
    is_day_off = (date_iso[:10] in days_off)

    # смены по дню недели
    wday = WDAYS_MAP[dt.weekday()]
    shifts_by_wday = (staff.get("shifts") or {}).get(wday, [])
    working = (len(shifts_by_wday) > 0) and (not is_day_off)

    return {
        "ok": True,
        "staff_id": staff_id,
        "date": date_iso,
        "weekday": wday,
        "working": working,
        "shifts": shifts_by_wday if working else [],
        "day_off": is_day_off,
    }
