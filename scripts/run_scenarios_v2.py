#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
import sys
from pathlib import Path as _Path
# Ensure repo root on sys.path for `src/...` imports inside agent module
_repo_root = str(_Path(__file__).resolve().parents[1])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from livekit.agents import AgentSession
from livekit.plugins import openai

from agent import Assistant, _build_instructions
from tools import barber


# Ensure tools can access the database outside of a worker context.
_STRESS_DB = barber.load_barber_db("db/barber")
barber._get_db = lambda: _STRESS_DB  # type: ignore[attr-defined]

load_dotenv(".env.local", override=False)


def _require(var: str) -> str:
    value = os.getenv(var)
    if not value:
        raise RuntimeError(f"Environment variable {var} is required for Azure LLM")
    return value


def _create_llm() -> openai.LLM:
    return openai.LLM.with_azure(
        azure_deployment=_require("AZURE_OPENAI_DEPLOYMENT"),
        azure_endpoint=_require("AZURE_OPENAI_ENDPOINT"),
        api_key=_require("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("OPENAI_API_VERSION", "2024-10-21"),
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        temperature=0.3,
    )


SCENARIOS: List[Dict] = [
    {"id": "ru_mens_cut_ruben", "title": "RU: Мужская стрижка к Рубену сегодня, с контактом", "messages": [
        "Хочу записаться на мужскую стрижку сегодня после 16:00 к Рубену.",
        "Давай на 17:30. Меня зовут Иван, телефон +34 600 100 001."
    ]},
    {"id": "es_color_sara_combo", "title": "ES: Color + Corte con Sara (paquete)", "messages": [
        "Hola, quiero color y corte con Sara esta semana.",
        "Perfecto, anótame el miércoles por la tarde. Me llamo Laura, mi teléfono es +34 600 100 002."
    ]},
    {"id": "find_and_reschedule", "title": "Поиск по телефону и перенос", "messages": [
        "Я записывался у Сары на окрашивание, не помню время. Телефон +34 600 100 002.",
        "Можно перенести на 30 минут позже?"
    ]},
    {"id": "cancel_by_phone", "title": "Отмена по телефону", "messages": [
        "Нужно отменить запись. Телефон +34 600 100 001."
    ]},
    {"id": "parent_child_alex_party", "title": "Папа и ребёнок подряд у Алекса (party=2)", "messages": [
        "Можно записать папу и сына подряд к Алексу утром в субботу?",
        "Имя Пётр, телефон +34 600 100 003."
    ]},
    {"id": "pau_long_permanente", "title": "Длинная процедура: Permanente у Пау", "messages": [
        "Нужна химическая завивка у Пау. Лучше ближе к обеду.",
        "Запиши на ближайшее подходящее, имя Карлос, телефон +34 600 100 004."
    ]},
    {"id": "tuesday_closed_alt", "title": "Вторник закрыты — предложить альтернативу", "messages": [
        "Могу только во вторник вечером. Есть ли окна?",
        "Тогда предложи ближайшую альтернативу вечером.",
        "Запиши меня, имя Анна, телефон +34 600 100 005."
    ]},
    {"id": "service_not_offered_brows_alt", "title": "Невходящая услуга → альтернатива", "messages": [
        "Делаете ли вы маникюр?",
        "Ок, тогда ухоженные брови — когда можно?",
        "Имя Ольга, телефон +34 600 100 006."
    ]},
    {"id": "price_pushback_diagnostics", "title": "Ценовой прессинг → диагностика", "messages": [
        "Сколько точно стоит балаяж на длинные волосы?",
        "Нужна конкретная цифра.",
        "Хорошо, тогда запишите меня на диагностику. Меня зовут Мария, +34 600 100 007."
    ]},
    {"id": "spanish_flow", "title": "Полный поток на испанском", "messages": [
        "Hola, ¿puedo reservar mechas con Sara para mañana por la tarde?",
        "Vale a las 18:00. Mi nombre es Elena, teléfono +34 600 100 008."
    ]},
    {"id": "english_flow", "title": "Flow in English", "messages": [
        "Hi, I'd like a men's haircut tomorrow morning with Ruben.",
        "Let's do 10:30. My name is John, phone +34 600 100 009."
    ]},
    {"id": "combo_ru_color_cut", "title": "RU: Окрашивание + стрижка (пакет)", "messages": [
        "Нужно окрашивание и стрижка у Сары на следующей неделе.",
        "Давай на любое утро. Имя Светлана, телефон +34 600 100 010."
    ]},
    {"id": "walkin_group_three", "title": "Трое без записи → ближайшее подряд", "messages": [
        "Нас трое рядом с салоном. Возьмёте без записи?",
        "Если нет, поставьте подряд как можно быстрее.",
        "Телефон для связи +34 600 100 011."
    ]},
    {"id": "rubens_fade_recommend", "title": "Рекомендация мастера по fade", "messages": [
        "Хочу чёткий fade. Кто лучше сделает?",
        "Тогда запишите к нему завтра во второй половине дня. Иван, +34 600 100 012."
    ]},
    {"id": "reschedule_after_create", "title": "Создать, перенести, подтвердить", "messages": [
        "Запишите меня на окрашивание сегодня к вечеру.",
        "Перенесём на 30 минут позже, пожалуйста. Телефон +34 600 100 013."
    ]},
]


def _format_history(history: Dict) -> str:
    lines: List[str] = []
    for item in history.get("items", []):
        typ = item.get("type")
        if typ == "message":
            role = item.get("role", "")
            chunks = item.get("content", []) or []
            for chunk in chunks:
                if isinstance(chunk, str):
                    text = chunk
                elif isinstance(chunk, dict):
                    text = chunk.get("text") or chunk.get("value") or chunk.get("content") or ""
                else:
                    text = ""
                text = (text or "").strip()
                if text:
                    lines.append(f"{role.upper()}: {text}")
        elif typ == "function_call":
            name = item.get("name", "")
            args = item.get("arguments")
            lines.append(f"TOOL_CALL {name}: {args}")
        elif typ == "function_call_output":
            name = item.get("name", "")
            output = item.get("output")
            lines.append(f"TOOL_RESULT {name}: {output}")
    return "\n".join(lines)


async def run_one(llm: openai.LLM, scenario: Dict, out_dir: Path) -> None:
    async with AgentSession(llm=llm) as session:
        await session.start(Assistant(_build_instructions()))
        import time
        metrics: List[Dict] = []
        for msg in scenario["messages"]:
            t0 = time.monotonic()
            res = await session.run(user_input=msg)
            t1 = time.monotonic()
            # extract tool activity from last turn
            items = session.history.to_dict().get("items", [])
            # Rough extraction: just list names seen in last N items (heuristic)
            tool_calls = []
            tool_results = []
            for it in items[-12:]:
                if it.get("type") == "function_call":
                    tool_calls.append(it.get("name"))
                elif it.get("type") == "function_call_output":
                    tool_results.append(it.get("name"))
            approx_lat = []
            if tool_results:
                per = round((t1 - t0) * 1000 / max(1, len(tool_results)))
                approx_lat = [{"name": n, "approx_ms": per} for n in tool_results]
            metrics.append({
                "user": msg,
                "turn_sec": round(t1 - t0, 3),
                "tool_calls": tool_calls,
                "tool_results": tool_results,
                "tool_latencies_approx": approx_lat,
            })
        history = session.history.to_dict()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        txt = _format_history(history)
        (out_dir / f"{ts}_{scenario['id']}.txt").write_text(txt, encoding="utf-8")
        (out_dir / f"{ts}_{scenario['id']}_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    out_dir = Path("logs/stress_tests")
    out_dir.mkdir(parents=True, exist_ok=True)
    async with _create_llm() as llm:
        for sc in SCENARIOS:
            print(f"Running: {sc['id']} — {sc['title']}")
            try:
                await run_one(llm, sc, out_dir)
            except Exception as e:
                print(f"Scenario {sc['id']} failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
