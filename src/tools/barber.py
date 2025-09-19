from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

# Совместимость импортов в разных версиях livekit-agents
try:
    from livekit.agents.llm import function_tool, RunContext
except Exception:
    from livekit.agents import function_tool, RunContext

from livekit.agents import get_job_context  # чтобы достать proc.userdata в тулзе


# ---------- Загрузка БД (из JSON в память) ----------

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_INDEX = {name: idx for idx, name in enumerate(DAY_NAMES)}


@dataclass
class StoreInfo:
    name: str
    address: str
    phone: str
    email: str
    timezone: str
    hours: Dict[str, List[str]]
    closed_days: List[str]
    socials: Dict[str, str] = field(default_factory=dict)
    notes: Dict[str, str] = field(default_factory=dict)
    holidays: List[str] = field(default_factory=list)


@dataclass
class Service:
    code: str
    name: str
    category: str
    price_text: str
    duration_min: Optional[int]
    price_eur: Optional[float] = None


@dataclass
class StaffMember:
    id: str
    name: str
    summary: str
    specialties: List[str]
    schedule: Dict[str, List[str]]
    weekly_days_off: List[str]
    time_off_dates: List[str] = field(default_factory=list)
    service_codes: List[str] = field(default_factory=list)


@dataclass
class BarberDB:
    store: StoreInfo
    services: List[Service]
    staff: List[StaffMember]
    knowledge: Dict[str, str]
    conversation_playbook: str
    service_index: Dict[str, Service]
    service_keywords: Dict[str, List[str]]
    service_tags: Dict[str, List[str]]
    currency: str = "EUR"


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _slug(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9]+", "_", norm)
    norm = norm.strip("_")
    return norm or "item"


def _normalize(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text or "")
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9]+", " ", norm)
    return norm.strip()


def _expand_day_token(token: str) -> List[str]:
    token = token.strip().replace("–", "-")
    token = token.title()
    if "-" not in token:
        return [token]
    start, end = token.split("-", 1)
    start = start.strip()
    end = end.strip()
    if start not in DAY_INDEX or end not in DAY_INDEX:
        return [token]
    start_idx = DAY_INDEX[start]
    end_idx = DAY_INDEX[end]
    if end_idx < start_idx:
        end_idx += 7
    days: List[str] = []
    for offset in range(start_idx, end_idx + 1):
        days.append(DAY_NAMES[offset % 7])
    return days


def _parse_hours_line(line: str) -> tuple[Dict[str, List[str]], List[str]]:
    hours: Dict[str, List[str]] = {name: [] for name in DAY_NAMES}
    closed_days: List[str] = []
    clean = (line or "").strip().rstrip(".;")
    for part in clean.split(";"):
        part = part.strip()
        if not part:
            continue
        part = part.replace("—", "-")
        part = part.replace("–", "-")
        if " " not in part:
            continue
        days_token, times_raw = part.split(" ", 1)
        days = _expand_day_token(days_token)
        value = times_raw.strip().strip(".")
        value_lower = value.lower()
        is_closed = any(key in value_lower for key in ["closed", "cerrado", "выход", "festivo"])
        if is_closed:
            for day in days:
                closed_days.append(day)
            continue
        segments = []
        for chunk in value.split("/"):
            chunk = chunk.strip()
            if not chunk:
                continue
            chunk = chunk.replace(" ", "")
            chunk = chunk.replace("–", "-")
            chunk = chunk.replace("—", "-")
            if "-" not in chunk:
                continue
            segments.append(chunk)
        if not segments:
            for day in days:
                closed_days.append(day)
            continue
        for day in days:
            hours.setdefault(day, []).extend(segments)
    # mark days without segments as closed
    for day, slots in hours.items():
        if not slots and day not in closed_days:
            closed_days.append(day)
    # ensure unique order preserving
    closed_seen: Dict[str, None] = {}
    ordered_closed = []
    for day in closed_days:
        if day not in closed_seen:
            ordered_closed.append(day)
            closed_seen[day] = None
    return hours, ordered_closed


def _parse_time(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"bad time value: {value}")
    hour = int(parts[0])
    minute = int(parts[1])
    return time(hour=hour, minute=minute)


def _weekday_name_rus(day: str) -> str:
    mapping = {
        "Mon": "понедельник",
        "Tue": "вторник",
        "Wed": "среда",
        "Thu": "четверг",
        "Fri": "пятница",
        "Sat": "суббота",
        "Sun": "воскресенье",
    }
    return mapping.get(day, day)


def _parse_store_info(text: str) -> StoreInfo:
    name = "Betrán Estilistas"
    address = ""
    phone = ""
    email = ""
    timezone = "Europe/Madrid"
    socials: Dict[str, str] = {}
    notes: Dict[str, str] = {}
    hours_line = ""

    address_match = re.search(r"Address:\s*([^\n]+)", text)
    if address_match:
        address = address_match.group(1).strip().rstrip(".")

    phone_match = re.search(r"Phone:\s*([^,\n]+)", text)
    if phone_match:
        phone = phone_match.group(1).strip()

    email_match = re.search(r"email:\s*([^\s;]+)", text, flags=re.IGNORECASE)
    if email_match:
        email = email_match.group(1).strip()

    hours_match = re.search(r"Hours:\s*([^\n]+)", text)
    if hours_match:
        hours_line = hours_match.group(1).strip()

    # Fallbacks if EN block missing
    if not address:
        address_match_ru = re.search(r"Адрес:\s*([^\n]+)", text)
        if address_match_ru:
            address = address_match_ru.group(1).strip().rstrip(".")
    if not phone:
        phone_match_ru = re.search(r"Телефон:\s*([^,\n]+)", text)
        if phone_match_ru:
            phone = phone_match_ru.group(1).strip()
    if not email:
        email_match_ru = re.search(r"email:\s*([^\s;]+)", text, flags=re.IGNORECASE)
        if email_match_ru:
            email = email_match_ru.group(1).strip()
    if not hours_line:
        hours_match_ru = re.search(r"Часы:\s*([^\n]+)", text)
        if hours_match_ru:
            hours_line = hours_match_ru.group(1).strip()

    hours, closed_days = _parse_hours_line(hours_line)

    socials_match = re.search(r"Instagram\s*\(@([^\)]+)\)", text)
    if socials_match:
        socials["instagram"] = f"@{socials_match.group(1).strip()}"
    if "Facebook" in text:
        socials.setdefault("facebook", "Betrán Estilistas")
    if "Twitter" in text:
        socials.setdefault("twitter", "@betran")

    philosophy_match = re.search(r"Философия:([^\[]+)", text)
    if philosophy_match:
        notes["philosophy"] = philosophy_match.group(1).strip()

    community_match = re.search(r"Комьюнити:([^\[]+)", text)
    if community_match:
        notes["community"] = community_match.group(1).strip()

    return StoreInfo(
        name=name,
        address=address,
        phone=phone,
        email=email,
        timezone=timezone,
        hours=hours,
        closed_days=closed_days,
        socials=socials,
        notes=notes,
        holidays=[],
    )


def _parse_services_catalog(text: str) -> List[Service]:
    services: List[Service] = []
    category = "General"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Каталог") or line.startswith("Примечание"):
            continue
        if line.startswith("—") and line.endswith(":"):
            category = line.strip("—:").strip()
            continue
        if "—" not in line:
            continue
        parts = [part.strip() for part in line.split("—")]
        if len(parts) < 4:
            continue
        code = parts[0].replace(" ", "")
        name = parts[1]
        price_text = parts[2]
        duration_text = parts[3]

        price_eur: Optional[float] = None
        price_clean = price_text.replace("€", "").replace("eur", "").replace(" ", "").replace(",", ".").lower()
        if price_clean.replace(".", "", 1).isdigit():
            try:
                price_eur = float(price_clean)
            except ValueError:
                price_eur = None

        duration_min: Optional[int] = None
        duration_match = re.search(r"(\d+)", duration_text)
        if duration_match:
            try:
                duration_min = int(duration_match.group(1))
            except ValueError:
                duration_min = None

        services.append(
            Service(
                code=code,
                name=name,
                category=category,
                price_text=price_text,
                duration_min=duration_min,
                price_eur=price_eur,
            )
        )
    return services


def _infer_specialties(text: str) -> List[str]:
    text_lower = text.lower()
    mapping = {
        "мужские": "men_cuts",
        "женские": "women_cuts",
        "уклад": "styling",
        "цвет": "color",
        "мелир": "highlights",
        "блон": "blond",
        "бров": "brows",
        "fade": "fade",
        "дет": "kids",
        "бород": "barber_beard",
        "barb": "barber",
        "alz": "smoothing",
        "универс": "generalist",
        "enzimo": "treatments",
        "терап": "treatments",
        "tanino": "smoothing",
        "trenz": "braids",
        "perman": "perms",
    }
    specialties = []
    for key, value in mapping.items():
        if key in text_lower:
            specialties.append(value)
    if not specialties:
        specialties.append("generalist")
    return specialties


def _parse_master_profiles(text: str, store_hours: Dict[str, List[str]], store_closed: Sequence[str]) -> List[StaffMember]:
    staff: List[StaffMember] = []
    default_days_off = list(store_closed)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Профили") or line.startswith("Совет"):
            continue
        if not line.startswith("—"):
            continue
        body = line[1:].strip()
        if "—" not in body:
            continue
        name_part, summary_part = body.split("—", 1)
        name = name_part.strip()
        summary = summary_part.strip()
        specialties = _infer_specialties(summary)
        schedule = {day: list(slots) for day, slots in store_hours.items()}
        staff.append(
            StaffMember(
                id=_slug(name),
                name=name,
                summary=summary,
                specialties=specialties,
                schedule=schedule,
                weekly_days_off=list(default_days_off),
            )
        )
    return staff


def _index_services(services: Iterable[Service]) -> tuple[Dict[str, Service], Dict[str, List[str]]]:
    by_id: Dict[str, Service] = {}
    keywords: Dict[str, List[str]] = {}

    def add_keyword(key: str, code: str) -> None:
        normalized = _normalize(key)
        if not normalized:
            return
        keywords.setdefault(normalized, [])
        if code not in keywords[normalized]:
            keywords[normalized].append(code)

    for svc in services:
        by_id[svc.code.lower()] = svc
        by_id.setdefault(svc.code, svc)
        add_keyword(svc.code, svc.code)
        add_keyword(svc.name, svc.code)
        for part in re.split(r"[+/,&]", svc.name):
            add_keyword(part, svc.code)
    return by_id, keywords


def _service_tags(service: Service) -> List[str]:
    tokens = f"{service.category} {service.name}".lower()
    tags: List[str] = []
    if any(word in tokens for word in ["hombre", "caballer", "men", "caballero"]):
        tags.append("men_cuts")
    if any(word in tokens for word in ["barba", "barber", "afeitado"]):
        tags.append("barber_beard")
    if any(word in tokens for word in ["niñ", "kid", "peques"]):
        tags.append("kids")
    if any(word in tokens for word in ["color", "mech", "balay", "ilumin", "baño"]):
        tags.append("color")
    if any(word in tokens for word in ["mech", "balay", "ilumin"]):
        tags.append("highlights")
    if any(word in tokens for word in ["secado", "peinad", "waves", "plancha", "iron"]):
        tags.append("styling")
    if any(word in tokens for word in ["enzimo", "tanino", "tratamiento", "therapy", "keratin", "nutric"]):
        tags.append("treatments")
    if any(word in tokens for word in ["alis", "tanino", "enzimo"]):
        tags.append("smoothing")
    if "trenza" in tokens:
        tags.append("braids")
    if "perman" in tokens:
        tags.append("perms")
    if not tags:
        tags.append("generalist")
    return sorted(set(tags))


def load_barber_db(base_dir: str | Path) -> BarberDB:
    base = Path(base_dir)

    services_text = _read_text(base / "bertran_services_catalog.txt")
    facts_text = _read_text(base / "bertran_kb_facts.txt")
    masters_text = _read_text(base / "bertran_master_profiles.txt")
    knowledge_plain = _read_text(base / "betran_estilistas_plain.txt")
    playbook_text = _read_text(base / "bertran_conversation_playbook.txt")

    store = _parse_store_info(facts_text)
    services = _parse_services_catalog(services_text)
    staff = _parse_master_profiles(masters_text, store.hours, store.closed_days)
    service_index, service_keywords = _index_services(services)
    service_tags = {svc.code.lower(): _service_tags(svc) for svc in services}

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


def _generate_slots(
    store: StoreInfo,
    base_dt: datetime,
    *,
    step_minutes: int = 30,
    count: int = 3,
) -> List[dict]:
    tz = ZoneInfo(store.timezone or "Europe/Madrid")
    aware_dt = base_dt.astimezone(tz) if base_dt.tzinfo else base_dt.replace(tzinfo=tz)
    slots: List[dict] = []

    for offset in range(7):
        current = aware_dt + timedelta(days=offset)
        weekday = WDAYS_MAP[current.weekday()]
        intervals = store.hours.get(weekday, [])
        if not intervals:
            continue

        for interval in intervals:
            try:
                raw_start, raw_end = interval.split("-", 1)
                start_t = _parse_time(raw_start)
                end_t = _parse_time(raw_end)
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
                        "weekday_ru": _weekday_name_rus(weekday),
                        "label": f"{_weekday_name_rus(weekday).capitalize()} {slot_time.strftime('%d.%m')} в {slot_time.strftime('%H:%M')}",
                    }
                )
                if len(slots) >= count:
                    return slots
                slot_time += step

    return slots

# ---------- Утилиты ----------

WDAYS_MAP = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"
}

def _get_db() -> BarberDB:
    # Достаём объект БД, загруженный в prewarm
    ctx = get_job_context()
    return ctx.proc.userdata["barber_db"]

def _weekday_hours(store: StoreInfo, dt: Optional[datetime]) -> Dict[str, Any]:
    if dt is None:
        return {"hours": store.hours}
    wday_idx = dt.weekday()
    wday = WDAYS_MAP[wday_idx]
    return {"weekday": wday, "value": store.hours.get(wday, [])}


def _is_holiday(store: StoreInfo, date_iso: str) -> bool:
    date_key = (date_iso or "")[:10]
    return date_key in set(store.holidays)


def _match_service(db: BarberDB, query: str) -> Optional[Service]:
    if not query:
        return None
    key = query.strip().lower()
    svc = db.service_index.get(key)
    if svc:
        return svc
    normalized = _normalize(query)
    for code in db.service_keywords.get(normalized, []):
        found = db.service_index.get(code.lower())
        if found:
            return found
    return None

# ---------- Тулзы ----------

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
    svc = _match_service(db, service)
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
        return {"ok": False, "error": "bad_date_iso"}

    day = _weekday_hours(store, dt)
    weekday = day.get("weekday")
    todays_hours: List[str] = day.get("value", [])
    store_closed = weekday in store.closed_days or not todays_hours
    holiday = _is_holiday(store, date_iso)
    closed = store_closed or holiday
    return {
        "ok": True,
        "date": date_iso,
        "weekday": weekday,
        "closed": closed,
        "hours": [] if closed else todays_hours,
        "holiday": holiday,
        "store_closed": store_closed,
    }

@function_tool(
    name="list_staff",
    description="List staff and skills. Optionally filter by service_id.",
)
async def list_staff(context: RunContext, service_id: Optional[str] = None) -> Dict[str, Any]:
    db = _get_db()
    tags_filter: List[str] = []
    if service_id:
        svc = _match_service(db, service_id)
        if svc:
            tags_filter = db.service_tags.get(svc.code.lower(), [])

    out = []
    for member in db.staff:
        if tags_filter:
            member_tags = set(member.specialties)
            if "generalist" not in member_tags and not member_tags.intersection(tags_filter):
                continue
        out.append(
            {
                "id": member.id,
                "name": member.name,
                "summary": member.summary,
                "specialties": member.specialties,
                "supports": member.service_codes,
                "weekly_days_off": member.weekly_days_off,
            }
        )
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
    staff = next((s for s in db.staff if s.id == staff_id), None)
    if not staff:
        return {"ok": False, "error": "staff_not_found"}

    weekday = WDAYS_MAP[dt.weekday()]
    weekly_off = set(staff.weekly_days_off)
    date_key = date_iso[:10]
    time_off_dates = set(staff.time_off_dates)
    holiday = _is_holiday(db.store, date_iso)
    store_closed = weekday in db.store.closed_days

    # смены по дню недели
    wday = WDAYS_MAP[dt.weekday()]
    shifts_by_wday = staff.schedule.get(wday, [])

    working = bool(shifts_by_wday)
    day_off_reason: Optional[str] = None

    if store_closed:
        working = False
        day_off_reason = "store_closed"
    elif holiday:
        working = False
        day_off_reason = "holiday"
    elif wday in weekly_off:
        working = False
        day_off_reason = "weekly_day_off"
    elif date_key in time_off_dates:
        working = False
        day_off_reason = "time_off"

    return {
        "ok": True,
        "staff_id": staff_id,
        "date": date_iso,
        "weekday": wday,
        "working": working,
        "shifts": shifts_by_wday if working else [],
        "day_off": not working,
        "day_off_reason": day_off_reason,
        "holiday": holiday,
        "store_closed": store_closed,
    }


@function_tool(
    name="suggest_slots",
    description=(
        "Suggest upcoming 30-minute appointment slots based on store hours. "
        "Args: count (int, default 3), start_iso (optional ISO datetime)."
    ),
)
async def suggest_slots(context: RunContext, count: int = 3, start_iso: Optional[str] = None) -> Dict[str, Any]:
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

    slots = _generate_slots(store, base_dt, count=count)
    return {
        "ok": bool(slots),
        "timezone": store.timezone,
        "start": base_dt.isoformat(timespec="minutes"),
        "slots": slots,
    }
