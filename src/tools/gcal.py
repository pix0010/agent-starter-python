"""Booking helpers that proxy LiveKit tool calls to n8n."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import os

try:  # pragma: no cover
    from livekit.agents.llm import function_tool, RunContext
except Exception:  # pragma: no cover
    from livekit.agents import function_tool, RunContext  # type: ignore

# --- совместимость импорта «каталога» в новом/старом разрезе пакетов
try:  # pragma: no cover
    from tools.barber.matching import match_service as _match_service  # type: ignore
    from tools.barber.toolbox import _get_db  # type: ignore
except Exception:  # pragma: no cover
    from tools import barber as _barber_mod  # type: ignore

    _match_fn = getattr(_barber_mod, "_match_service", getattr(_barber_mod, "match_service", None))
    _get_db_fn = getattr(_barber_mod, "_get_db", None)

    if _match_fn is None or _get_db_fn is None:  # pragma: no cover
        raise ImportError("Legacy barber module does not expose required helpers")

    def _match_service(db, query):  # type: ignore[override]
        return _match_fn(db, query)

    def _get_db():  # type: ignore[override]
        return _get_db_fn()

# клиент n8n
from clients import n8n as n8n_client


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(os.getenv("APP_TZ", "Europe/Madrid")))
    return dt


def _to_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _build_services_meta(
    service_id: Optional[str], services: Optional[List[str]]
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Собирает [{id,name,price_text,duration_min}, ...] и суммарную длительность (мин)."""
    db = _get_db()
    meta: List[Dict[str, Any]] = []
    total = 0

    def add(query: str | None) -> None:
        if not query:
            return
        svc = _match_service(db, query)
        if not svc:
            return
        duration = getattr(svc, "duration_min", None)
        meta.append(
            {
                "id": getattr(svc, "code", ""),
                "name": getattr(svc, "name", "") or "",
                "price_text": getattr(svc, "price_text", "") or "",
                "duration_min": duration if duration is not None else None,
            }
        )
        nonlocal total
        if duration:
            total += int(duration)

    if services:
        for item in services:
            add(item)
    elif service_id:
        add(service_id)

    return meta, (total or None)


@function_tool(
    name="create_booking",
    description=(
        "Create a booking via n8n. Args: name (str), phone (str), start_iso (ISO), "
        "staff_id (str), service_id (optional), services (optional list), duration_min (optional)."
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
    """Бьём в n8n /api/booking/book с services_meta, получаем нормальный ответ для агента."""
    try:
        services_meta, total = _build_services_meta(service_id, services)
        duration = int(duration_min) if duration_min else (int(total) if total else 30)
        start_dt = _parse_iso(start_iso)
        end_dt = start_dt + timedelta(minutes=duration)
        payload = {
            "name": name,
            "phone": phone,
            "start_iso": _to_iso(start_dt),
            "end_iso": _to_iso(end_dt),
            "staff_id": staff_id,
            "service_id": service_id or "",
            "services": services or ([service_id] if service_id else []),
            "services_meta": services_meta,
            "duration_min": duration,
            "timeZone": os.getenv("APP_TZ", "Europe/Madrid"),
        }
        resp = await n8n_client.create_booking(payload)
        if resp.get("ok"):
            return resp
        return {"ok": False, "error": resp.get("error") or {"code": "n8n_error"}}
    except Exception as exc:  # pragma: no cover - сеть/некорректные данные
        return {"ok": False, "error": "n8n_error", "detail": str(exc)}


@function_tool(
    name="cancel_booking",
    description="Cancel a booking via n8n. Args: booking_id (str), staff_id (str).",
)
async def cancel_booking(context: RunContext, booking_id: str, staff_id: str) -> Dict[str, Any]:
    try:
        resp = await n8n_client.cancel_booking({"booking_id": booking_id, "staff_id": staff_id})
        if resp.get("ok"):
            return resp
        return {"ok": False, "error": resp.get("error") or {"code": "n8n_error"}}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "n8n_error", "detail": str(exc)}


@function_tool(
    name="find_booking_by_phone",
    description="Find bookings by phone via n8n. Args: phone (str), staff_id (str), days (optional).",
)
async def find_booking_by_phone(
    context: RunContext,
    phone: str,
    staff_id: str,
    days: int = 30,
) -> Dict[str, Any]:
    try:
        payload = {"phone": phone, "staff_id": staff_id, "days": days}
        resp = await n8n_client.find_by_phone(payload)
        if resp.get("ok"):
            return resp
        return {"ok": False, "error": resp.get("error") or {"code": "n8n_error"}}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "n8n_error", "detail": str(exc)}


@function_tool(
    name="reschedule_booking",
    description="Reschedule an existing booking via n8n. Args: booking_id, staff_id, new_start_iso (ISO), duration_min (optional).",
)
async def reschedule_booking(
    context: RunContext,
    booking_id: str,
    staff_id: str,
    new_start_iso: str,
    duration_min: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        payload: Dict[str, Any] = {
            "booking_id": booking_id,
            "staff_id": staff_id,
            "new_start_iso": new_start_iso,
        }
        if duration_min is not None:
            payload["duration_min"] = int(duration_min)
        resp = await n8n_client.reschedule_booking(payload)
        if resp.get("ok"):
            return resp
        return {"ok": False, "error": resp.get("error") or {"code": "n8n_error"}}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "n8n_error", "detail": str(exc)}
