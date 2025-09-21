"""Service matching utilities."""
from __future__ import annotations

import re
from typing import Optional

from .services import BarberDB, Service, normalize_text


def match_service(db: BarberDB, query: str) -> Optional[Service]:
    if not query:
        return None
    key = (query or "").strip().lower()

    generic_tokens = {"стрижка", "corte", "haircut", "подстричь", "подстричься"}
    beard_signals = any(tok in key for tok in ["бород", "barba", "beard"])
    female_signals = any(tok in key for tok in ["жен", "дев", "chica", "girl", "woman", "mujer"])
    kids_signals = any(tok in key for tok in ["дет", "реб", "niñ", "kid", "peque"])

    if any(tok in key for tok in generic_tokens):
        if beard_signals:
            cand = db.service_index.get("svc002") or db.service_index.get("SVC002")
            if cand:
                return cand
        if female_signals:
            cand = db.service_index.get("svc016") or db.service_index.get("SVC016")
            if cand:
                return cand
        if kids_signals:
            cand = db.service_index.get("svc003") or db.service_index.get("SVC003")
            if cand:
                return cand
        cand = db.service_index.get("svc001") or db.service_index.get("SVC001")
        if cand:
            return cand

    svc = db.service_index.get(key)
    if svc:
        return svc

    normalized = normalize_text(query)
    for code in db.service_keywords.get(normalized, []):
        found = db.service_index.get(code.lower())
        if found:
            return found

    q2 = re.sub(r"\s*\[[^\]]*\]\s*", " ", query)
    q2 = re.sub(r"\s*\([^\)]*\)\s*", " ", q2)
    normalized2 = normalize_text(q2)
    for code in db.service_keywords.get(normalized2, []):
        found = db.service_index.get(code.lower())
        if found:
            return found
    return None
