"""Registration helpers for LiveKit agent events (thinking bridges, etc.)."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict

try:  # pragma: no cover - typing help only
    from livekit.agents import AgentStateChangedEvent, AgentSession
except Exception:  # pragma: no cover
    AgentStateChangedEvent = Any  # type: ignore
    AgentSession = Any  # type: ignore


def register_thinking_bridge(
    session: "AgentSession",
    *,
    lang_state: Dict[str, Any],
    interaction_state: Dict[str, Any],
    last_user_final_at: Dict[str, float],
) -> None:
    """Register a handler that injects a short filler while the agent is thinking."""

    bridge_delay_ms = max(0, int(os.getenv("BRIDGE_THINKING_DELAY_MS", "600") or 600))
    bridge_cooldown_ms = max(0, int(os.getenv("BRIDGE_THINKING_COOLDOWN_MS", "2000") or 2000))
    last_bridge = {"t": 0.0}

    def _pick(ru: str, es: str, en: str) -> str:
        try:
            cur = lang_state.get("current", "es")
        except Exception:
            cur = "es"
        return {"ru": ru, "es": es, "en": en}.get(cur, es)

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: "AgentStateChangedEvent"):
        if getattr(ev, "new_state", "") != "thinking":
            return
        started = time.monotonic()

        async def _say_if_still_thinking() -> None:
            try:
                await asyncio.sleep(bridge_delay_ms / 1000.0)
                if session.current_speech is not None:
                    return
                if getattr(session, "agent_state", "") != "thinking":
                    return
                if interaction_state.get("awaiting_user"):
                    return
                now = time.monotonic()
                if (now - last_bridge["t"]) * 1000.0 < bridge_cooldown_ms:
                    return
                last_final = last_user_final_at.get("t", 0.0)
                if last_final and now - last_final < (bridge_delay_ms / 1000.0):
                    await asyncio.sleep(0.2)
                    if getattr(session, "agent_state", "") != "thinking":
                        return
                bridge = _pick(
                    ru="Секунду, сверяюсь с расписанием…",
                    es="Un momento, reviso la agenda…",
                    en="One sec, checking the schedule…",
                )
                last_bridge["t"] = now
                await session.say(bridge, allow_interruptions=True, add_to_chat_ctx=False)
            except Exception:
                return

        asyncio.create_task(_say_if_still_thinking())

    # store timestamps for external observation (optional)
    lang_state.setdefault("_bridge_registered", True)
