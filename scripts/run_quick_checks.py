#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import AgentSession
from livekit.plugins import openai

import sys
from pathlib import Path as _Path
_repo_root = str(_Path(__file__).resolve().parents[1])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from agent import Assistant, _build_instructions
from tools import barber


load_dotenv(".env.local", override=False)


def _require(var: str) -> str:
    v = os.getenv(var)
    if not v:
        raise RuntimeError(f"Missing env: {var}")
    return v


def _llm():
    return openai.LLM.with_azure(
        azure_deployment=_require("AZURE_OPENAI_DEPLOYMENT"),
        azure_endpoint=_require("AZURE_OPENAI_ENDPOINT"),
        api_key=_require("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("OPENAI_API_VERSION", "2024-10-21"),
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        temperature=0.3,
    )


async def _run_dialog(session: AgentSession, messages: list[str]) -> dict:
    hist_before = len(session.history.to_dict().get("items", []))
    for m in messages:
        # human-like pause before speaking next phrase
        await asyncio.sleep(1.5)
        # retry on Azure 429 or transient errors
        tries = 0
        while True:
            try:
                await session.run(user_input=m)
                break
            except Exception as e:
                emsg = str(e).lower()
                tries += 1
                if tries <= 4 and ("429" in emsg or "rate limit" in emsg or "timeout" in emsg):
                    await asyncio.sleep(6 * tries)
                    continue
                raise
    hist = session.history.to_dict()
    # trim to new items only
    hist["items"] = hist.get("items", [])[hist_before:]
    return hist


def _save(out_dir: Path, tag: str, history: dict, comment: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # plain chat
    lines = []
    for it in history.get("items", []):
        t = it.get("type")
        if t == "message":
            role = it.get("role")
            for c in it.get("content", []) or []:
                if isinstance(c, str):
                    txt = c
                else:
                    txt = c.get("text") or c.get("value") or c.get("content") or ""
                if txt:
                    lines.append(f"{role.upper()}: {txt.strip()}")
        elif t == "function_call":
            lines.append(f"TOOL_CALL {it.get('name')}: {it.get('arguments')}")
        elif t == "function_call_output":
            lines.append(f"TOOL_RESULT {it.get('name')}: {it.get('output')}")
    (out_dir / f"{ts}_{tag}.txt").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / f"{ts}_{tag}.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{ts}_{tag}.comment.txt").write_text(comment.strip() + "\n", encoding="utf-8")


async def main() -> None:
    out_dir = Path("logs/quick_checks")
    # Ensure tools see a DB outside worker context
    _DB = barber.load_barber_db("db/barber")
    barber._get_db = lambda: _DB  # type: ignore[attr-defined]
    async with (_llm() as llm, AgentSession(llm=llm) as session):
        await session.start(Assistant(_build_instructions()))

        # Scenario 1: RU booking any master on Monday
        sc1 = [
            "Хочу записаться на стрижку в понедельник после обеда.",
            "Давайте на 10:30. Запишите на любого мастера.",
            "Имя Антон, телефон +34 615 333 605.",
        ]
        h1 = await _run_dialog(session, sc1)
        _save(out_dir, "booking_any_master", h1, comment="Проверка: слоты → выбор времени → contacts → create_booking. Должен быть TOOL_CALL create_booking и подтверждение.")

        await asyncio.sleep(2.5)

        # Scenario 2: Find by phone and cancel
        sc2 = [
            "Найдите, пожалуйста, мою запись по телефону +34 615 333 605 у любого мастера.",
            "Отмените ближайшую запись, пожалуйста.",
        ]
        h2 = await _run_dialog(session, sc2)
        _save(out_dir, "find_and_cancel", h2, comment="Проверка: find_booking_by_phone → cancel_booking. Должна быть отмена существующего события.")


if __name__ == "__main__":
    asyncio.run(main())
