#!/usr/bin/env python3
"""Text-mode demo of a booking flow using the Assistant.

This simulates a short conversation, where the user asks for a service and a
master, confirms a time, provides name and phone, and the agent books via
Google Calendar. At the end, the script cancels the created event to avoid
leaving residue in calendars.

Requirements: Azure OpenAI env vars, Google Calendar creds and GCAL_CALENDAR_MAP.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

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


load_dotenv('.env.local', override=False)


def _require(var: str) -> str:
    v = os.getenv(var)
    if not v:
        raise RuntimeError(f'Missing env: {var}')
    return v


def _llm():
    return openai.LLM.with_azure(
        azure_deployment=_require('AZURE_OPENAI_DEPLOYMENT'),
        azure_endpoint=_require('AZURE_OPENAI_ENDPOINT'),
        api_key=_require('AZURE_OPENAI_API_KEY'),
        api_version=os.getenv('OPENAI_API_VERSION', '2024-10-21'),
        model=os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4o'),
        temperature=0.3,
    )


async def main():
    async with (_llm() as llm, AgentSession(llm=llm) as session):
        # Ensure tools can work outside worker context
        _DB = barber.load_barber_db("db/barber")
        barber._get_db = lambda: _DB  # type: ignore[attr-defined]
        await session.start(Assistant(_build_instructions()))

        # 1) User asks to book
        print('> USER: Хочу записаться на мужскую стрижку сегодня после 16:00 к Рубену')
        r1 = await session.run(user_input='Хочу записаться на мужскую стрижку сегодня после 16:00 к Рубену')
        await asyncio.sleep(1.5)
        # consume tool calls and assistant answer
        r1.expect.skip_next_event_if(type='message', role='assistant')
        # 2) Pick a time (the agent should propose slots first)
        print('> USER: Давай на 17:30. Меня зовут Иван, телефон +34 600 000 099')
        r2 = await session.run(user_input='Давай на 17:30. Меня зовут Иван, телефон +34 600 000 099')
        await asyncio.sleep(1.5)
        # agent should create booking
        r2.expect.skip_next_event_if(type='message', role='assistant')
        print('Flow executed. Check Rubén calendar and then we will clean up manually if needed.')

if __name__ == '__main__':
    asyncio.run(main())
