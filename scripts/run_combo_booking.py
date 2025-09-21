#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
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


async def _say(session: AgentSession, text: str) -> None:
    # retry on transient Azure errors
    tries = 0
    while True:
        try:
            await session.run(user_input=text)
            break
        except Exception as e:
            emsg = str(e).lower()
            tries += 1
            if tries <= 4 and ("429" in emsg or "rate limit" in emsg or "timeout" in emsg or "connection" in emsg):
                await asyncio.sleep(6 * tries)
                continue
            raise


async def main() -> None:
    # Make tools work outside worker context
    _DB = barber.load_barber_db("db/barber")
    barber._get_db = lambda: _DB  # type: ignore[attr-defined]

    async with (_llm() as llm, AgentSession(llm=llm) as session):
        await session.start(Assistant(_build_instructions()))

        # Complex service: color + cut with Sara tomorrow between 17:00-18:00
        await _say(session, "Хочу завтра окрашивание и стрижку у Сары после 17:00.")
        await asyncio.sleep(1.5)
        await _say(session, "Подойдёт ближайшее время между 17:00 и 18:00.")
        await asyncio.sleep(1.2)
        await _say(session, "Да, подтверждаю. Я Антон, телефон +34600111222.")
        await asyncio.sleep(1.2)

        # Dump last events to stdout for quick check
        hist = session.history.to_dict()
        items = hist.get("items", [])[-20:]
        for it in items:
            t = it.get("type")
            if t == "message":
                role = it.get("role")
                for c in it.get("content", []) or []:
                    if isinstance(c, str):
                        txt = c
                    else:
                        txt = c.get("text") or c.get("value") or c.get("content") or ""
                    if txt:
                        print(f"{role.upper()}: {txt.strip()}")
            elif t == "function_call":
                print(f"TOOL_CALL {it.get('name')}: {it.get('arguments')}")
            elif t == "function_call_output":
                print(f"TOOL_RESULT {it.get('name')}: {it.get('output')}")


if __name__ == "__main__":
    asyncio.run(main())

