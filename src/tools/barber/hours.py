"""Parsing of opening hours and store metadata."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List, Sequence, Tuple

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_INDEX = {name: idx for idx, name in enumerate(DAY_NAMES)}
WDAYS_MAP = {idx: name for idx, name in enumerate(DAY_NAMES)}


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


def expand_day_token(token: str) -> List[str]:
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


def parse_hours_line(line: str) -> Tuple[Dict[str, List[str]], List[str]]:
    hours: Dict[str, List[str]] = {name: [] for name in DAY_NAMES}
    closed_days: List[str] = []
    clean = (line or "").strip().rstrip(".;")
    for part in clean.split(";"):
        part = part.strip()
        if not part:
            continue
        part = part.replace("—", "-")
        part = part.replace("–", "-")

        if ":" not in part:
            continue
        days_raw, times_raw = part.split(":", 1)
        day_tokens = [tok.strip() for tok in days_raw.split(",") if tok.strip()]
        days: List[str] = []
        for token in day_tokens:
            days.extend(expand_day_token(token))

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
    for day, slots in hours.items():
        if not slots and day not in closed_days:
            closed_days.append(day)
    closed_seen: Dict[str, None] = {}
    ordered_closed = []
    for day in closed_days:
        if day not in closed_seen:
            ordered_closed.append(day)
            closed_seen[day] = None
    return hours, ordered_closed


def parse_time(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"bad time value: {value}")
    hour = int(parts[0])
    minute = int(parts[1])
    return time(hour=hour, minute=minute)


def weekday_name_ru(day: str) -> str:
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


def parse_store_info(text: str) -> StoreInfo:
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

    hours, closed_days = parse_hours_line(hours_line)

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
