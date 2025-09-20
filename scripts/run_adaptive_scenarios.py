#!/usr/bin/env python3
"""Adaptive scenario orchestrator for Betrán Estilistas agent.

Goals:
- Drive multi-turn conversations that adapt to the agent's responses.
- Parse tool call outputs (e.g., suggest_slots) and make decisions (choose a slot, change master, add/remove services).
- Inject non-linear clarifications (price, care tips) and occasionally change intent.
- Collect per-turn latency metrics and per-turn tool usage (approx).

Run with uv (so livekit plugins are available):
  uv run python scripts/run_adaptive_scenarios.py

Outputs:
  logs/stress_tests/<ts>_<id>.txt         — linearized transcript with TOOL_CALL/TOOL_RESULT
  logs/stress_tests/<ts>_<id>_metrics.json — per-turn latency + tool usage summary
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


# Ensure tools can access the DB outside worker context
_STRESS_DB = barber.load_barber_db("db/barber")
barber._get_db = lambda: _STRESS_DB  # type: ignore[attr-defined]

load_dotenv(".env.local", override=False)


def _require(var: str) -> str:
    v = os.getenv(var)
    if not v:
        raise RuntimeError(f"Env var required: {var}")
    return v


def _create_llm() -> openai.LLM:
    return openai.LLM.with_azure(
        azure_deployment=_require("AZURE_OPENAI_DEPLOYMENT"),
        azure_endpoint=_require("AZURE_OPENAI_ENDPOINT"),
        api_key=_require("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("OPENAI_API_VERSION", "2024-10-21"),
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        temperature=0.3,
    )


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


def _new_events_since(history: Dict, start_idx: int) -> List[Dict[str, Any]]:
    items = history.get("items", [])
    return items[start_idx:]


def _parse_output_payload(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return raw
    s = raw.strip()
    try:
        return json.loads(s)
    except Exception:
        try:
            return ast.literal_eval(s)
        except Exception:
            return s


def _extract_tool_results(items: List[Dict]) -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    for it in items:
        if it.get("type") == "function_call_output":
            out.append((it.get("name", ""), _parse_output_payload(it.get("output"))))
    return out


def _extract_tool_calls(items: List[Dict]) -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    for it in items:
        if it.get("type") == "function_call":
            out.append((it.get("name", ""), _parse_output_payload(it.get("arguments"))))
    return out


def _pick_slot(suggest_out: Dict) -> Optional[str]:
    try:
        slots = suggest_out.get("slots") or []
        if not slots:
            return None
        # Pick earliest or random among first 3
        k = min(3, len(slots))
        choice = random.choice(slots[:k])
        return choice.get("iso")
    except Exception:
        return None


@dataclass
class AdaptiveScenario:
    id: str
    goal: str
    # knobs for behavior
    prefer_master: Optional[str] = None
    prefer_services: List[str] = field(default_factory=list)
    language_hint: Optional[str] = None  # 'ru' | 'es' | 'en'
    change_mind_prob: float = 0.2
    ask_price_prob: float = 0.4
    ask_care_prob: float = 0.3


ADAPTIVE_SCENARIOS: List[AdaptiveScenario] = [
    AdaptiveScenario(id="adaptive_cut_ruben", goal="Хочу мужскую стрижку сегодня после 16:00", prefer_master="ruben", change_mind_prob=0.3, ask_price_prob=0.2, ask_care_prob=0.3),
    AdaptiveScenario(id="adaptive_color_cut_sara", goal="Quiero color y corte esta semana", prefer_master="sara", prefer_services=["Окрашивание (Color)", "Женская стрижка"], language_hint="es", change_mind_prob=0.25),
    AdaptiveScenario(id="adaptive_parent_child_alex", goal="Папа и ребёнок подряд утром в субботу", prefer_master="alex", change_mind_prob=0.2),
    AdaptiveScenario(id="adaptive_permanente_pau", goal="Нужна химическая завивка ближе к обеду", prefer_master="pau", ask_care_prob=0.5),
    AdaptiveScenario(id="adaptive_any_master", goal="Нужно ближайшее окно на стрижку", prefer_master=None, change_mind_prob=0.2),
    # 6: пакет без явного мастера, агент должен предложить и уточнить
    AdaptiveScenario(id="adaptive_combo_no_master", goal="Нужно окрашивание и стрижка на следующей неделе", prefer_services=["Окрашивание (Color)", "Женская стрижка"], change_mind_prob=0.3, ask_price_prob=0.5),
    # 7: английский поток
    AdaptiveScenario(id="adaptive_cut_english", goal="I'd like a men's haircut tomorrow morning", language_hint="en", prefer_master="ruben", change_mind_prob=0.2),
    # 8: испанский + смена желания
    AdaptiveScenario(id="adaptive_mechas_es", goal="Quiero mechas por la mañana", language_hint="es", prefer_master="sara", prefer_services=["Мелирование (Mechas)"], change_mind_prob=0.4),
    # 9: высокая нагрузка + просьба об уходе
    AdaptiveScenario(id="adaptive_heavy_care_ru", goal="Хочу сложную работу с блондом ближе к вечеру", prefer_master="sara", prefer_services=["Осветление (Iluminación)"], ask_care_prob=0.6),
    # 10: party-like с изменением мнения (в конце попросит на час позже)
    AdaptiveScenario(id="adaptive_party_switch_alex", goal="Поставьте папу и сына подряд утром", prefer_master="alex", change_mind_prob=0.5),
    # 11: запрос не из меню, потом альтернатива
    AdaptiveScenario(id="adaptive_not_offered_then_alt", goal="Делаете ли маникюр вечером?", prefer_master=None, ask_care_prob=0.4),
    # 12: только диагностика цены
    AdaptiveScenario(id="adaptive_diagnostics_only", goal="Хочу консультацию по цене перед окрашиванием", prefer_master="sara", ask_price_prob=0.8),
    # 13: pau + длинные процедуры с поправкой времени
    AdaptiveScenario(id="adaptive_pau_long_combo", goal="Мне нужна химическая завивка и потом сушка", prefer_master="pau", prefer_services=["Химическая завивка (Permanente)", "Сушка феном"], change_mind_prob=0.35),
    # 14: betran универсальный, предложить время и поменять
    AdaptiveScenario(id="adaptive_betran_general", goal="Нужна быстрая стрижка в обед", prefer_master="betran", change_mind_prob=0.25),
    # 15: без мастера, вечер, пакет
    AdaptiveScenario(id="adaptive_evening_combo", goal="Нужно окрашивание и сушка вечером", prefer_master=None, prefer_services=["Окрашивание (Color)", "Сушка феном"], ask_price_prob=0.5, change_mind_prob=0.3),
]


async def run_adaptive(llm: openai.LLM, sc: AdaptiveScenario, out_dir: Path, step_sleep: float = 0.5) -> None:
    async with AgentSession(llm=llm) as session:
        await session.start(Assistant(_build_instructions()))
        metrics: List[Dict[str, Any]] = []
        last_idx = 0
        picked_slot: Optional[str] = None
        name, phone = None, None
        # seed
        seed_msg = sc.goal
        if sc.prefer_master:
            seed_msg += f" к {sc.prefer_master.capitalize()}"
        if sc.language_hint == "es":
            seed_msg = "Hola. " + seed_msg
        elif sc.language_hint == "en":
            seed_msg = "Hi. " + seed_msg

        for step in range(1, 8):  # 7-turn cap per scenario
            t0 = time.monotonic()
            res = await session.run(user_input=seed_msg if step == 1 else next_msg)
            t1 = time.monotonic()
            turn_items = _new_events_since(session.history.to_dict(), last_idx)
            last_idx += len(turn_items)
            calls = _extract_tool_calls(turn_items)
            results = _extract_tool_results(turn_items)
            # Approximate per-tool latency: split turn time across tool results (best-effort without per-event timestamps)
            approx_latencies = []
            if results:
                per = round((t1 - t0) * 1000 / max(1, len(results)))
                approx_latencies = [{"name": r[0], "approx_ms": per} for r in results]

            metrics.append({
                "step": step,
                "user": seed_msg if step == 1 else next_msg,
                "turn_sec": round(t1 - t0, 3),
                "tool_calls": [c[0] for c in calls],
                "tool_results": [r[0] for r in results],
                "tool_latencies_approx": approx_latencies,
            })

            # react adaptively based on tool results
            next_msg = None
            # pick slot if offered
            for name_r, payload in results:
                if name_r == "suggest_slots" and isinstance(payload, dict):
                    candidate = _pick_slot(payload)
                    if candidate:
                        picked_slot = candidate
                        break

            if picked_slot and random.random() < sc.change_mind_prob:
                # change mind: ask for different time or add a service
                if sc.prefer_services:
                    # add/remove one service randomly
                    if random.random() < 0.5:
                        next_msg = "Давайте добавим ещё укладку после стрижки, это возможно?"
                    else:
                        next_msg = "Можно без сушки, оставим только стрижку. Какие тогда варианты по времени?"
                else:
                    next_msg = "А можно на полчаса позже?"
                picked_slot = None
                continue

            if not picked_slot:
                # ask clarifications or request slots again
                if random.random() < sc.ask_price_prob and sc.prefer_services:
                    next_msg = "И по цене подскажите, сколько ориентировочно за пакет выйдет?"
                elif random.random() < sc.ask_care_prob:
                    next_msg = "А что посоветуете по уходу перед процедурой?"
                else:
                    next_msg = "Предложите, пожалуйста, ближайшие слоты ещё раз."
                continue

            # confirm with name and phone after slot chosen
            if not name:
                # invent on the fly
                fake_names = ["Иван", "Мария", "Пабло", "Елена", "John", "Laura"]
                name = random.choice(fake_names)
                phone = f"+34 600 {random.randint(100,999)} {random.randint(100,999)}"
            next_msg = f"Бронируем на {picked_slot}. Меня зовут {name}, телефон {phone}."
            picked_slot = None

            # stop after booking likely created (agent will call create_booking)
            if step >= 6:
                break

            # small pacing to avoid hitting rate limits
            await asyncio.sleep(step_sleep)

        # dump artifacts
        history = session.history.to_dict()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (out_dir / f"{ts}_{sc.id}.txt").write_text(_format_history(history), encoding="utf-8")
        (out_dir / f"{ts}_{sc.id}_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    out_dir = Path("logs/stress_tests")
    out_dir.mkdir(parents=True, exist_ok=True)
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--sleep-between', type=float, default=2.0)
    p.add_argument('--step-sleep', type=float, default=0.5)
    p.add_argument('--skip-existing', action='store_true')
    p.add_argument('--max-retries', type=int, default=2)
    p.add_argument('--retry-sleep', type=float, default=5.0)
    args = p.parse_args()

    # Determine finished scenarios by presence of txt logs
    done_ids = set()
    for f in out_dir.glob('*_*.txt'):
        try:
            sid = f.name.split('_', 2)[-1].rsplit('.', 1)[0]
            # If filename ends with scenario id, include; otherwise skip
            for sc in ADAPTIVE_SCENARIOS:
                if f.name.endswith(f"_{sc.id}.txt"):
                    done_ids.add(sc.id)
        except Exception:
            pass

    async with _create_llm() as llm:
        for sc in ADAPTIVE_SCENARIOS:
            if args.skip_existing and sc.id in done_ids:
                print(f"Skipping (exists): {sc.id}")
                continue
            print(f"Running adaptive: {sc.id} — {sc.goal}")
            tries = 0
            while True:
                try:
                    await run_adaptive(llm, sc, out_dir, step_sleep=args.step_sleep)
                    break
                except Exception as e:
                    emsg = str(e).lower()
                    tries += 1
                    if ('429' in emsg or 'rate limit' in emsg) and tries <= args.max_retries:
                        print(f"Scenario {sc.id} hit rate limit, retry {tries}/{args.max_retries} after {args.retry_sleep}s…")
                        await asyncio.sleep(args.retry_sleep)
                        continue
                    print(f"Scenario {sc.id} failed: {e}")
                    break
            await asyncio.sleep(args.sleep_between)


if __name__ == "__main__":
    asyncio.run(main())
