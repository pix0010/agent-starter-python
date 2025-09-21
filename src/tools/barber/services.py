"""Data models and parsing helpers for the salon knowledge base."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from livekit.agents import get_job_context

from .hours import StoreInfo


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


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def slugify(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9]+", "_", norm)
    norm = norm.strip("_")
    return norm or "item"


def normalize_text(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text or "")
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    norm = norm.lower()
    norm = re.sub(r"[^0-9a-zA-Zа-яА-ЯёЁ]+", " ", norm)
    return norm.strip()


def parse_services_catalog(text: str) -> List[Service]:
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
        price_clean = (
            price_text.replace("€", "")
            .replace("eur", "")
            .replace(" ", "")
            .replace(",", ".")
            .lower()
        )
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


def infer_specialties(text: str) -> List[str]:
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
    specialties = [value for key, value in mapping.items() if key in text_lower]
    if not specialties:
        specialties.append("generalist")
    return specialties


def parse_master_profiles(text: str, store_hours: Dict[str, List[str]], store_closed: Iterable[str]) -> List[StaffMember]:
    staff: List[StaffMember] = []
    in_tips = False
    default_days_off = list(store_closed)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Профили"):
            continue
        if line.startswith("Совет"):
            in_tips = True
            continue
        if in_tips:
            continue
        if not line.startswith("—"):
            continue
        body = line[1:].strip()
        if "—" not in body:
            continue
        name_part, summary_part = body.split("—", 1)
        name = name_part.strip()
        summary = summary_part.strip()
        specialties = infer_specialties(summary)
        schedule = {day: list(slots) for day, slots in store_hours.items()}
        staff.append(
            StaffMember(
                id=slugify(name),
                name=name,
                summary=summary,
                specialties=specialties,
                schedule=schedule,
                weekly_days_off=list(default_days_off),
            )
        )
    return staff


def build_service_index(services: Iterable[Service]) -> Tuple[Dict[str, Service], Dict[str, List[str]]]:
    by_id: Dict[str, Service] = {}
    keywords: Dict[str, List[str]] = {}

    def add_keyword(key: str, code: str) -> None:
        normalized = normalize_text(key)
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
        base_name = re.sub(r"\s*\[[^\]]*\]\s*", " ", svc.name)
        base_name = re.sub(r"\s*\([^\)]*\)\s*", " ", base_name)
        base_name = re.sub(r"\s+", " ", base_name).strip()
        if base_name and base_name.lower() != svc.name.lower():
            add_keyword(base_name, svc.code)
        for part in re.split(r"[+/,&]", svc.name):
            add_keyword(part, svc.code)
    return by_id, keywords


def classify_service(service: Service) -> List[str]:
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


def build_service_tags(services: Iterable[Service]) -> Dict[str, List[str]]:
    return {svc.code.lower(): classify_service(svc) for svc in services}


def get_db() -> BarberDB:
    ctx = get_job_context()
    return ctx.proc.userdata["barber_db"]
