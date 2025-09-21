"""Utilities to humanise schedule phrases for TTS output."""
from __future__ import annotations

import re
from typing import Iterable, Tuple

from .time_utils import format_time


_TIME_PATTERN = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")


def _extract_times(text: str) -> list[str]:
    return _TIME_PATTERN.findall(text or "")


# --- Russian helpers -----------------------------------------------------

def _ru_number_word(n: int) -> str:
    mapping = {
        0: "ноль",
        1: "один",
        2: "два",
        3: "три",
        4: "четыре",
        5: "пять",
        6: "шесть",
        7: "семь",
        8: "восемь",
        9: "девять",
        10: "десять",
        11: "одиннадцать",
        12: "двенадцать",
    }
    x = n % 12
    if x == 0:
        x = 12
    return mapping.get(x, str(x))


def _ru_minute_simple(mm: int) -> str:
    simple = {
        0: "",
        5: "пять",
        10: "десять",
        15: "пятнадцать",
        20: "двадцать",
        25: "двадцать пять",
        30: "тридцать",
        35: "тридцать пять",
        40: "сорок",
        45: "сорок пять",
        50: "пятьдесят",
        55: "пятьдесят пять",
    }
    return simple.get(mm, f"{mm}")


def _ru_time_words(h: int, m: int) -> str:
    if m == 0:
        return _ru_number_word(h)
    return f"{_ru_number_word(h)} {_ru_minute_simple(m)}"


def _ru_hour_genitive(h: int) -> str:
    mapping = {
        1: "часа",
        2: "двух",
        3: "трёх",
        4: "четырёх",
        5: "пяти",
        6: "шести",
        7: "семи",
        8: "восьми",
        9: "девяти",
        10: "десяти",
        11: "одиннадцати",
        12: "двенадцати",
    }
    x = h % 12
    if x == 0:
        x = 12
    return mapping.get(x, "")


def _ru_minute_phrase(mm: int) -> str:
    mapping = {0: "", 15: "пятнадцати", 30: "тридцати", 45: "сорока пяти"}
    return mapping.get(mm, "")


def _summarize_hours_ru(text: str) -> tuple[str, bool]:
    pattern = re.compile(
        r"с\s*(\d{1,2}):(\d{2})\s*до\s*(\d{1,2}):(\d{2})\s*(?:и|,)\s*с\s*(\d{1,2}):(\d{2})\s*до\s*(\d{1,2}):(\d{2})",
        flags=re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return text, False
    h1, m1, h2, m2, h3, m3, h4, m4 = map(int, m.groups())
    if m1 not in (0, 15, 30, 45) or m4 not in (0, 15, 30, 45):
        return text, False
    start = _ru_hour_genitive(h1)
    end = _ru_hour_genitive(h4)
    start_min = _ru_minute_phrase(m1)
    parts = ["с", start]
    if start_min:
        parts.append(start_min)
    parts.extend(["до", end])
    phrase = " ".join(p for p in parts if p)
    phrase += ", с перерывом на обед"
    return pattern.sub(phrase, text, count=1), True


# --- Spanish helpers -----------------------------------------------------

def _es_hour_word(h: int) -> str:
    mapping = {
        1: "una",
        2: "dos",
        3: "tres",
        4: "cuatro",
        5: "cinco",
        6: "seis",
        7: "siete",
        8: "ocho",
        9: "nueve",
        10: "diez",
        11: "once",
        12: "doce",
    }
    x = h % 12
    if x == 0:
        x = 12
    return mapping.get(x, str(x))


def _es_time_phrase(h: int, m: int, *, article: bool = True) -> str:
    if m == 0:
        return f"las {_es_hour_word(h)}" if article else _es_hour_word(h)
    if m == 30:
        return f"las {_es_hour_word(h)} y media" if article else f"{_es_hour_word(h)} y media"
    if m == 15:
        return f"las {_es_hour_word(h)} y cuarto" if article else f"{_es_hour_word(h)} y cuarto"
    if m == 45:
        nxt = _es_hour_word(h + 1)
        return f"las {nxt} menos cuarto" if article else f"{nxt} menos cuarto"
    return f"las {_es_hour_word(h)}:{m:02d}" if article else f"{_es_hour_word(h)}:{m:02d}"


def _summarize_hours_es(text: str) -> tuple[str, bool]:
    pattern = re.compile(
        r"de\s*(\d{1,2}):(\d{2})\s*a\s*(\d{1,2}):(\d{2})\s*(?:y|,)\s*de\s*(\d{1,2}):(\d{2})\s*a\s*(\d{1,2}):(\d{2})",
        flags=re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return text, False
    h1, m1, h2, m2, h3, m3, h4, m4 = map(int, m.groups())
    if m1 not in (0, 15, 30, 45) or m4 not in (0, 15, 30, 45):
        return text, False
    start = _es_time_phrase(h1, m1)
    end = _es_time_phrase(h4, m4)
    phrase = f"de {start} a {end}, con pausa para comer"
    return pattern.sub(phrase, text, count=1), True


# --- English helpers -----------------------------------------------------

def _en_hour_word(h: int) -> str:
    mapping = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
        11: "eleven",
        12: "twelve",
    }
    x = h % 12
    if x == 0:
        x = 12
    return mapping.get(x, str(x))


def _en_time_phrase(h: int, m: int) -> str:
    if m == 0:
        return _en_hour_word(h)
    if m == 30:
        return f"half past {_en_hour_word(h)}"
    if m == 15:
        return f"quarter past {_en_hour_word(h)}"
    if m == 45:
        return f"quarter to {_en_hour_word(h + 1)}"
    minutes = {
        5: "five",
        10: "ten",
        20: "twenty",
        25: "twenty-five",
        35: "thirty-five",
        40: "forty",
    }.get(m, f"{m:02d}")
    return f"{_en_hour_word(h)} {minutes}"


def _summarize_hours_en(text: str) -> tuple[str, bool]:
    pattern = re.compile(
        r"from\s*(\d{1,2}):(\d{2})\s*to\s*(\d{1,2}):(\d{2})\s*(?:and|,)\s*from\s*(\d{1,2}):(\d{2})\s*to\s*(\d{1,2}):(\d{2})",
        flags=re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return text, False
    h1, m1, h2, m2, h3, m3, h4, m4 = map(int, m.groups())
    if m1 not in (0, 15, 30, 45) or m4 not in (0, 15, 30, 45):
        return text, False
    start = _en_time_phrase(h1, m1)
    end = _en_time_phrase(h4, m4)
    phrase = f"from {start} to {end}, with a lunch break"
    return pattern.sub(phrase, text, count=1), True


# --- Public API ----------------------------------------------------------

def _join_times(times: Iterable[str], lang: str) -> str:
    if not times:
        return ""
    lang = lang or "es"
    if lang == "ru":
        parts = []
        for value in times:
            try:
                hh, mm = value.split(":")
                parts.append(_ru_time_words(int(hh), int(mm)))
            except Exception:
                parts.append(format_time(value))
    elif lang == "es":
        parts = []
        for value in times:
            try:
                hh, mm = value.split(":")
                parts.append(_es_time_phrase(int(hh), int(mm), article=False))
            except Exception:
                parts.append(format_time(value))
    elif lang == "en":
        parts = []
        for value in times:
            try:
                hh, mm = value.split(":")
                parts.append(_en_time_phrase(int(hh), int(mm)))
            except Exception:
                parts.append(format_time(value))
    else:
        parts = [format_time(value) for value in times]

    parts = list(parts)
    if len(parts) == 1:
        return parts[0]
    conj = {"ru": " и ", "es": " y ", "en": " and "}.get(lang, " y ")
    return ", ".join(parts[:-1]) + conj + parts[-1]


def humanize_slots(text: str, lang: str) -> tuple[str, bool]:
    times = _extract_times(text)
    if len(times) < 2:
        return text, False
    joined = _join_times(times[:3], lang)
    if text.strip() == "\n".join(times) or "\n" in text:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if all(ln in times for ln in lines):
            return joined, True
    pattern = re.compile(r"(?:\b(?:[01]?\d|2[0-3]):[0-5]\d\b(?:\s*[,/\n]\s*)?){2,}")
    new_text, n = pattern.subn(joined, text, count=1)
    if n > 0:
        return new_text, True
    return f"{text.rstrip()} — {joined}", True


def replace_time_with_words(text: str, lang: str) -> str:
    def repl(match: re.Match[str]) -> str:
        hh = int(match.group(1))
        mm = int(match.group(2))
        if lang == "ru":
            return _ru_time_words(hh, mm)
        if lang == "es":
            return _es_time_phrase(hh, mm, article=False)
        if lang == "en":
            return _en_time_phrase(hh, mm)
        return match.group(0)

    return re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", repl, text)


def summarize_hours(text: str, lang: str) -> tuple[str, bool]:
    if lang == "ru":
        return _summarize_hours_ru(text)
    if lang == "es":
        return _summarize_hours_es(text)
    if lang == "en":
        return _summarize_hours_en(text)
    return text, False
