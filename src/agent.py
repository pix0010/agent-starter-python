import logging
import os
import sys
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from src.utils import read_text
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    RoomOutputOptions,
    RunContext,
    WorkerOptions,
    cli,
    metrics,
)
# from livekit.agents.llm import function_tool  # больше не нужно
from livekit.plugins import azure, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins.azure.tts import StyleConfig, ProsodyConfig

# 🔽 добавили импорт наших тулзов
from tools.weather import lookup_weather
from tools.barber import (
    load_barber_db,
    get_services,
    get_price,
    get_open_hours,
    list_staff,
    get_staff_day,
    suggest_slots,
)

logger = logging.getLogger("agent")

load_dotenv(".env.local")

_SIMPLE_CONSOLE = os.getenv("AGENT_CONSOLE_SIMPLE", "").lower() in {"1", "true", "yes"}
if _SIMPLE_CONSOLE:
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("livekit").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def _build_instructions() -> str:
    """Формируем динамические инструкции с учётом текущей даты/времени."""
    tz = os.getenv("APP_TZ", "Europe/Madrid")
    now = datetime.now(ZoneInfo(tz))
    now_str = now.strftime("%Y-%m-%d %H:%M")
    base_instructions = read_text("prompts/system.txt")
    dynamic_tail = (
        f"\n\nТекущее локальное время: {now_str} ({tz}). "
        "Интерпретируй слова 'сегодня/завтра' относительно этой временной зоны. "
        "Всегда проверяй факты через доступные инструменты, прежде чем отвечать."
    )
    if base_instructions:
        return base_instructions + dynamic_tail
    return (
        "Ты — голосовой ассистент Betrán Estilistas. "
        "Отвечай на русском, используй инструменты для уточнения фактов."
        + dynamic_tail
    )


class Assistant(Agent):
    def __init__(self, instructions: str) -> None:
        super().__init__(
            instructions=instructions,
            tools=[
                lookup_weather,
                get_services,
                get_price,
                get_open_hours,
                list_staff,
                get_staff_day,
                suggest_slots,
            ],
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()
    proc.userdata["barber_db"] = load_barber_db("db/barber")  # ← добавили


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        # ⚠️ Рекомендуемая привычка под тебя (RU/ES):
        stt=azure.STT(
            speech_key=os.getenv("AZURE_SPEECH_KEY"),
            speech_region=os.getenv("AZURE_SPEECH_REGION", "francecentral"),
            language=["ru-RU"],  # добавь "es-ES" при двуязычии: ["es-ES","ru-RU"]
        ),
        tts=azure.TTS(
            speech_key=os.getenv("AZURE_SPEECH_KEY"),
            speech_region=os.getenv("AZURE_SPEECH_REGION", "francecentral"),
            voice="ru-RU-SvetlanaNeural",
            language="ru-RU",
        ),
        llm=openai.LLM.with_azure(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("OPENAI_API_VERSION", "2024-10-21"),
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            temperature=0.3,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
        # → включаем выравнивание текстов по озвучке (для печатного вывода стабильнее)
        use_tts_aligned_transcript=True,
    )

    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        if not _SIMPLE_CONSOLE:
            logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        if not _SIMPLE_CONSOLE:
            metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    # ======== ЛОГИ ТЕКСТА: компактно ========
    _partial = {"active": False, "len": 0}

    def _clear_partial_line():
        if _partial["active"]:
            sys.stdout.write("\r" + (" " * _partial["len"]) + "\r")
            sys.stdout.flush()
            _partial["active"] = False
            _partial["len"] = 0

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev):
        txt = getattr(ev, "transcript", "") or ""
        if not txt:
            return

        if _SIMPLE_CONSOLE:
            if getattr(ev, "is_final", False):
                print(f"USER: {txt}", flush=True)
        else:
            if getattr(ev, "is_final", False):
                _clear_partial_line()
                logger.info(f"USER: {txt}")
            else:
                s = f"USER(partial): {txt}"
                sys.stdout.write("\r" + s)
                sys.stdout.flush()
                _partial["active"] = True
                _partial["len"] = len(s)

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev):
        item = getattr(ev, "item", None)
        role = getattr(item, "role", None)
        text = getattr(item, "text_content", None)
        if role == "assistant" and text:
            if _SIMPLE_CONSOLE:
                print(f"ASSISTANT: {text}", flush=True)
            else:
                _clear_partial_line()
                logger.info(f"ASSISTANT: {text}")

    async def log_usage():
        summary = usage_collector.get_summary()
        if not _SIMPLE_CONSOLE:
            logger.info(f"Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    # на завершение — сохраняем всю историю беседы в файл
    async def _save_history():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("logs", exist_ok=True)
        path = f"logs/transcript_{ctx.room.name}_{ts}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session.history.to_dict(), f, ensure_ascii=False, indent=2)
        if not _SIMPLE_CONSOLE:
            logger.info(f"Transcript saved to {path}")
    ctx.add_shutdown_callback(_save_history)

    await session.start(
        agent=Assistant(instructions=_build_instructions()),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # Если self-hosted — параметр noise_cancellation убери
            noise_cancellation=noise_cancellation.BVC(),
        ),
        # → текст сразу в консоль, без «привязки» к аудиопотоку (меньше задержка вывода)
        room_output_options=RoomOutputOptions(sync_transcription=False),
    )

    # 1) Стиль речи (подбери один из: "customer-service", "assistant", "friendly", "cheerful")
    session.tts.update_options(
        style=StyleConfig(
            style="cheerful",  # 👈 обратите внимание: без дефиса чаще всего
            # role можно не задавать, если не нужно: role="YoungAdultFemale" и т.п. зависят от голоса
            # degree — «насколько выражен» стиль (если поддерживается конкретным voice)
            degree=1.0,                # 0.01–2.0 (пример диапазона; см. поддерживаемость голосом)
        )
    )

    # 2) Просодия: скорость/тон/громкость (SSML-совместимые значения)
    session.tts.update_options(
        prosody=ProsodyConfig(
            rate="fast",    # чуть быстрее (например, +5%..+10%), Prosody rate must be one of 'x-slow', 'slow', 'medium', 'fast', 'x-fast'
            pitch="medium",   # Prosody pitch must be one of 'x-low', 'low', 'medium', 'high', 'x-high
            volume="medium", # Prosody volume must be one of 'silent', 'x-soft', 'soft', 'medium', 'loud', 'x-loud'
        )
    )

    # Произносим приветствие, если оно задано
    greeting = read_text("prompts/greeting.txt")
    if greeting:
        # Специально используем say(), чтобы произнести ровно этот текст, без LLM-переиначивания
        await session.say(greeting)  # Требует настроенный TTS плагин

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
