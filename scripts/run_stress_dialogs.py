#!/usr/bin/env python
"""Run scripted stress-test conversations with the Betrán Estilistas agent.

Each scenario spins up a fresh `AgentSession`, drives it with a list of user
messages, and saves the resulting transcript (including tool calls) into
`logs/stress_tests/` for manual review.

Requires Azure OpenAI credentials in `.env.local`, identical to the runtime.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
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
    {
        "id": "early_fade_switch",
        "title": "Быстрая запись на стрижку+бороду с изменением пожеланий",
        "messages": [
            "Привет! Хочу записаться на стрижку и бороду как можно раньше.",
            "А если сегодня уже занято, то есть что-то завтра после 18:00?",
            "Давай тогда того, кто делает чёткий fade.",
            "Запиши меня, пожалуйста, оставлю номер позже."
        ],
    },
    {
        "id": "color_master_preference",
        "title": "Окрашивание с приоритетом мастера и переносом даты",
        "messages": [
            "Салют! Нужен блонд с тонировкой, лучше утром.",
            "Хочу к Саре, она свободна в ближайшие дни?",
            "Если утром занята, то можно вечер, но только не понедельник.",
            "Пришли пару идей, как ухаживать после окрашивания."
        ],
    },
    {
        "id": "parent_child_combo",
        "title": "Папа и ребёнок в одном визите",
        "messages": [
            "Hola! Можно ли записать сразу папу и сына подряд?",
            "Ребёнку 8 лет, ему нужно быстро и аккуратно.",
            "Есть окно на субботу к полудню?",
            "Сколько по времени займёт оба визита подряд?"
        ],
    },
    {
        "id": "tuesday_closed_confusion",
        "title": "Попытка записи на закрытый день и поиск альтернатив",
        "messages": [
            "Мне удобно только во вторник вечером, возьмёте?",
            "А если совсем нужно, есть ли исключения?",
            "Хорошо, тогда предложи альтернативу как можно позднее в другой день.",
            "Скажи, кто из мастеров будет свободен."
        ],
    },
    {
        "id": "cancel_booking_flow",
        "title": "Отмена гипотетической брони без данных",
        "messages": [
            "Привет, хочу отменить запись на пятницу.",
            "Номер брони не помню, но оставлял телефон на +34600111222.",
            "Если нельзя, можно перенести на следующую среду утром?"
        ],
    },
    {
        "id": "service_not_offered",
        "title": "Запрос услуги вне меню (маникюр)",
        "messages": [
            "Делаете ли вы маникюр или ногти?",
            "А если нет, что посоветуешь вместо, чтобы руки выглядели ухоженно?",
            "Ладно, тогда только бороду подправить — когда можно?"
        ],
    },
    {
        "id": "donation_program",
        "title": "Уточнение про донорство волос",
        "messages": [
            "Я слышала, что вы принимаете волосы на донорство. Это правда?",
            "Какие требования к длине и подготовке?",
            "Можно ли совместить это с окрашиванием в один визит?",
            "Когда лучше записаться, чтобы мастер успел?"
        ],
    },
    # weather_smalltalk scenario removed as weather tooling was dropped
    {
        "id": "spanish_switch",
        "title": "Переключение на испанский и обратно",
        "messages": [
            "Hola, ¿puedo reservar algo para mañana?",
            "Prefiero hablar en español, pero si hay detalles técnicos puedes usar ruso.",
            "Necesito un alisado natural, ¿quién lo hace mejor?",
            "Vale, dime horarios y lo confirmo en ruso."
        ],
    },
    {
        "id": "price_pushback",
        "title": "Попытка выбить точную цену",
        "messages": [
            "Сколько точно стоит балаяж на длинные волосы?",
            'Нет, мне нужна конкретная цифра, не "ориентировочно".',
            "Хорошо, что если я пришлю фото, сможете точнее сказать?",
            "Тогда запиши меня на диагностику."
        ],
    },
    {
        "id": "late_evening_request",
        "title": "Просьба о записи после закрытия",
        "messages": [
            "Хочу прийти сегодня после 20:30, это реально?",
            "А есть шанс задержаться минут на 15?",
            "Если нет, предложи ближайшее утро и напомни, что сделать с бородой пока жду."
        ],
    },
    {
        "id": "enzimo_details",
        "title": "Глубокие вопросы про Enzimo Therapy",
        "messages": [
            "Что за Enzimo Therapy у вас?",
            "Сколько держится эффект и можно ли после неё краситься?",
            "Есть ли противопоказания?",
            "Запиши на консультацию, но сначала хочу короткую стрижку."
        ],
    },
    {
        "id": "walkin_group",
        "title": "Группа друзей без записи",
        "messages": [
            "Мы сейчас втроём рядом с салоном, возьмёте без записи?",
            "Если нет, насколько быстро можно записаться?",
            "Нам нужны два fade и одна укладка под вечеринку.",
            "Сможете всех троих поставить подряд?"
        ],
    },
    {
        "id": "reschedule_conflict",
        "title": "Перенос существующей записи и уточнение графика",
        "messages": [
            "Я уже записан на пятницу 11:00, можно ли перенести на более раннее утро?",
            "Если нет, давай на субботу, но только если есть Alex.",
            "Что я могу сделать дома, чтобы держался стиль до визита?"
        ],
    },
    {
        "id": "wedding_styling",
        "title": "Подготовка к свадьбе с советами",
        "messages": [
            "У меня свадьба через неделю, хочу свежий образ.",
            "Думаю про лёгкие волны и макияж, вы делаете макияж?",
            "Тогда предложи что-то из ухода, чтобы волосы блестели.",
            "Запиши меня на середину недели, днём, но чтобы был мастер с опытом свадеб.",
            "И напомни, что мне сделать накануне дома."
        ],
    },
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


async def run_scenario(base_dir: Path, timestamp: str, scenario: Dict) -> Dict:
    log_path = base_dir / f"{timestamp}_{scenario['id']}.txt"
    summary: Dict[str, str] = {"id": scenario["id"], "title": scenario["title"], "log": str(log_path)}

    async with _create_llm() as azure_llm:
        async with AgentSession(llm=azure_llm) as session:
            await session.start(Assistant(_build_instructions()))
            for msg in scenario["messages"]:
                run = await session.run(user_input=msg)
                events = getattr(run, "events", [])
                assistant_events = [e for e in events if getattr(e, "type", "") == "message" and getattr(e.item, "role", "") == "assistant"]
                if not assistant_events:
                    summary.setdefault("warnings", []).append(f"no-assistant-reply-after: {msg}")
                await asyncio.sleep(2.5)

            history = session.history.to_dict()
            transcript = _format_history(history)
            header = [
                f"Scenario: {scenario['title']}",
                f"ID: {scenario['id']}",
                f"Messages: {len(scenario['messages'])}",
                "=" * 60,
                transcript,
            ]
            log_path.write_text("\n".join(header), encoding="utf-8")
            summary["items"] = str(len(history.get("items", [])))
    return summary


async def main() -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("logs/stress_tests")
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    for scenario in SCENARIOS:
        print(f"Running scenario {scenario['id']}...")
        summary = await run_scenario(out_dir, timestamp, scenario)
        summaries.append(summary)
        print(f"  -> log saved to {summary['log']}")
        await asyncio.sleep(3)

    summary_path = out_dir / f"{timestamp}_summary.json"
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
