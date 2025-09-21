"""Helpers for working with time strings and language normalisation."""
from __future__ import annotations


def format_time(value: str) -> str:
    """Return a time string without a leading zero in hours."""
    if len(value) >= 4 and value.startswith("0"):
        return value[1:]
    return value


def normalize_lang_tag(tag: str | None) -> str:
    """Collapse locale variants (es-ES, ru-RU, en-US) to short codes."""
    if not tag:
        return "es"
    lowered = tag.lower()
    if lowered.startswith("es"):
        return "es"
    if lowered.startswith("ru"):
        return "ru"
    if lowered.startswith("en"):
        return "en"
    return "es"
