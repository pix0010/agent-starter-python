from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx

try:
    from livekit.agents.llm import function_tool, RunContext  # новые версии
except Exception:  # pragma: no cover
    from livekit.agents import function_tool, RunContext      # старые версии

WMO_CODE_TEXT = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Rain showers (slight)",
    81: "Rain showers (moderate)",
    82: "Rain showers (violent)",
    85: "Snow showers (slight)",
    86: "Snow showers (heavy)",
    95: "Thunderstorm (slight/moderate)",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

async def _get_json(url: str, params: dict, timeout_s: float = 8.0) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

async def _geocode(name: str, language: str = "en", count: int = 1) -> Optional[dict]:
    data = await _get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": name, "count": count, "language": language, "format": "json"},
    )
    results = data.get("results") or []
    return results[0] if results else None

async def _current_weather(
    lat: float,
    lon: float,
    *,
    unit: str = "c",
    wind_unit: str = "kmh",
    timezone: str = "auto",
) -> dict:
    temp_unit = "celsius" if unit.lower().startswith("c") else "fahrenheit"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,wind_speed_10m,weather_code",
        "temperature_unit": temp_unit,
        "wind_speed_unit": wind_unit,
        "timezone": timezone,
    }
    data = await _get_json("https://api.open-meteo.com/v1/forecast", params)

    if "current" in data:
        cur = data["current"]
        return {
            "temperature": cur.get("temperature_2m"),
            "wind_speed": cur.get("wind_speed_10m"),
            "weather_code": cur.get("weather_code"),
            "time": cur.get("time"),
            "units": {
                "temperature": "°C" if temp_unit == "celsius" else "°F",
                "wind_speed": {"kmh": "km/h", "ms": "m/s", "mph": "mph"}[wind_unit],
            },
        }

    if "current_weather" in data:
        cur = data["current_weather"]
        t = cur.get("temperature")
        ws = cur.get("windspeed")
        code = cur.get("weathercode")
        if temp_unit == "fahrenheit" and t is not None:
            t = (t * 9 / 5) + 32
        return {
            "temperature": t,
            "wind_speed": ws,
            "weather_code": code,
            "time": cur.get("time"),
            "units": {"temperature": "°F" if temp_unit == "fahrenheit" else "°C", "wind_speed": "km/h"},
        }
    return {}

@function_tool(
    name="lookup_weather",
    description=(
        "Get current weather by a human-readable location (city/address). "
        "Args: location (str), unit ('c' or 'f', default 'c'), language (IETF tag like 'ru' or 'es'). "
        "Returns: current temperature, wind speed, condition code/text, and resolved location info."
    ),
)
async def lookup_weather(
    context: RunContext,
    location: str,
    unit: str = "c",
    language: str = "ru",
) -> Dict[str, Any]:
    q = (location or "").strip()
    if not q:
        return {"ok": False, "error": "location_is_empty"}

    try:
        geo = await _geocode(q, language=language or "en", count=1)
        if not geo:
            return {"ok": False, "error": "location_not_found", "query": q}

        lat = float(geo["latitude"])
        lon = float(geo["longitude"])
        resolved = {"name": geo.get("name"), "country": geo.get("country"), "lat": lat, "lon": lon}

        wind_unit = "kmh"
        cw = await _current_weather(lat, lon, unit=unit or "c", wind_unit=wind_unit, timezone="auto")
        if not cw:
            return {"ok": False, "error": "weather_unavailable", "resolved": resolved}

        code = cw.get("weather_code")
        condition_text = WMO_CODE_TEXT.get(int(code)) if code is not None else None

        return {
            "ok": True,
            "resolved": resolved,
            "current": {
                "temperature": cw.get("temperature"),
                "wind_speed": cw.get("wind_speed"),
                "condition_code": code,
                "condition_text": condition_text,
                "time": cw.get("time"),
                "units": cw.get("units"),
            },
            "source": "open-meteo",
        }
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout"}
    except httpx.HTTPError as e:
        return {"ok": False, "error": "http_error", "detail": str(e)}
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return {"ok": False, "error": "unexpected_error", "detail": str(e)}