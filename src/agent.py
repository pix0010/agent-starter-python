import logging
import os

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
    RunContext,  # можно удалить, если нигде не используется
    WorkerOptions,
    cli,
    metrics,
)
# from livekit.agents.llm import function_tool  # больше не нужно
from livekit.plugins import azure, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

# 🔽 добавили импорт нашего тулза погоды
from tools.weather import lookup_weather

logger = logging.getLogger("agent")

load_dotenv(".env.local")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=read_text("prompts/system.txt", default=(
                "You are a helpful voice AI assistant. Keep answers concise."
            )),
            tools=[lookup_weather],  # ← подключили внешний инструмент
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


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
    )

    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # Если self-hosted — параметр noise_cancellation убери
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    # Произносим приветствие, если оно задано
    greeting = read_text("prompts/greeting.txt")
    if greeting:
        # Специально используем say(), чтобы произнести ровно этот текст, без LLM-переиначивания
        await session.say(greeting)  # Требует настроенный TTS плагин

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))