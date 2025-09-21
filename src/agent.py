import logging
import os
import sys
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from src.utils import read_text
from livekit.agents import (
    NOT_GIVEN,
    Agent,
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
from livekit.agents import BackgroundAudioPlayer, AudioConfig, BuiltinAudioClip
# from livekit.agents.llm import function_tool  # больше не нужно
from livekit.plugins import azure, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins.azure.tts import StyleConfig, ProsodyConfig

# 🔽 добавили импорт наших тулзов
from speech import (
    build_ssml,
    humanize_slots,
    normalize_lang_tag,
    register_thinking_bridge,
    replace_time_with_words,
    summarize_hours,
)
from tools.barber import (
    load_barber_db,
    get_services,
    get_price,
    get_open_hours,
    resolve_date,
    list_staff,
    get_staff_day,
    get_staff_week,
    suggest_slots,
    remember_contact,
)
from tools.gcal import create_booking, cancel_booking, find_booking_by_phone, reschedule_booking

logger = logging.getLogger("agent")

load_dotenv(".env.local")

_SIMPLE_CONSOLE = os.getenv("AGENT_CONSOLE_SIMPLE", "").lower() in {"1", "true", "yes"}
if _SIMPLE_CONSOLE:
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("livekit").setLevel(logging.WARNING)
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
class Assistant(Agent):
    def __init__(self, instructions: str) -> None:
        super().__init__(
            instructions=instructions,
            tools=[
                get_services,
                get_price,
                get_open_hours,
                resolve_date,
                list_staff,
                get_staff_day,
                get_staff_week,
                suggest_slots,
                remember_contact,
                create_booking,
                cancel_booking,
                find_booking_by_phone,
                reschedule_booking,
            ],
        )
        # Текущий язык TTS для humanize/SSML; обновляется при переключении
        self.tts_lang = "es-ES"

    # Лёгкая пост-обработка текста перед синтезом: humanize слотов и, опционально, SSML
    def tts_node(self, text, model_settings):  # type: ignore[override]
        from livekit.agents.voice.agent import Agent as _BaseAgent
        from livekit.agents.voice.transcription.filters import filter_markdown, filter_emoji

        humanize_enabled = os.getenv("TTS_HUMANIZE_SLOTS", "1").lower() in {"1", "true", "yes"}
        summarize_enabled = os.getenv("TTS_SUMMARIZE_HOURS", "1").lower() in {"1", "true", "yes"}
        use_ssml = os.getenv("TTS_SLOTS_SSML", "0").lower() in {"1", "true", "yes"}

        # Map to short code
        lang_long = getattr(self, "tts_lang", "es-ES") or "es-ES"
        lang_short = "es"
        if lang_long.startswith("ru"):
            lang_short = "ru"
        elif lang_long.startswith("en"):
            lang_short = "en"

        async def _gen():
            async for chunk in text:
                s = str(chunk)
                changed = False
                if humanize_enabled:
                    s, changed = humanize_slots(s, lang_short)
                    replaced = replace_time_with_words(s, lang_short)
                    if replaced != s:
                        s = replaced
                        changed = True
                if summarize_enabled:
                    s2, changed2 = summarize_hours(s, lang_short)
                    if changed2:
                        s = s2
                        changed = True
                if use_ssml and changed:
                    yield build_ssml(s, lang_long)
                else:
                    yield s

        # Пропускаем через штатные фильтры (markdown/emoji), чтобы TTS не озвучивал эмодзи словами
        filtered = filter_emoji(filter_markdown(_gen()))
        return _BaseAgent.default.tts_node(self, filtered, model_settings)


def prewarm(proc: JobProcess):
    # Чуть агрессивнее VAD, чтобы быстрее завершать реплики
    proc.userdata["vad"] = silero.VAD.load(
        min_silence_duration=0.45,
        prefix_padding_duration=0.4,
    )
    proc.userdata["barber_db"] = load_barber_db("db/barber")  # ← добавили


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    # --- Языковые голоса (Azure TTS) ---
    VOICE_BY_LANG = {
        # Более естественные дефолтные голоса; можно переопределить в .env.local
        "es": os.getenv("AZURE_TTS_VOICE_ES", "es-ES-AlvaroNeural"),
        "ru": os.getenv("AZURE_TTS_VOICE_RU", "ru-RU-DmitryNeural"),
        "en": os.getenv("AZURE_TTS_VOICE_EN", "en-US-JennyNeural"),
    }

    # --- Параметры TTS (стиль/просодия) из .env ---
    def _env_choice(var: str, allowed: set[str], default: str) -> str:
        v = (os.getenv(var) or default).strip().lower()
        return v if v in allowed else default

    def _env_float(var: str, default: float) -> float:
        raw = os.getenv(var)
        if not raw:
            return default
        try:
            return float(raw)
        except Exception:
            return default

    # Допустимые значения, соответствующие ProsodyConfig
    _ALLOWED_RATE = {"x-slow", "slow", "medium", "fast", "x-fast"}
    _ALLOWED_PITCH = {"x-low", "low", "medium", "high", "x-high"}
    _ALLOWED_VOLUME = {"silent", "x-soft", "soft", "medium", "loud", "x-loud"}

    TTS_STYLE = os.getenv("TTS_STYLE", "chat")
    TTS_STYLE_DEGREE = _env_float("TTS_STYLE_DEGREE", 1.0)
    TTS_RATE = _env_choice("TTS_PROSODY_RATE", _ALLOWED_RATE, "fast")
    TTS_PITCH = _env_choice("TTS_PROSODY_PITCH", _ALLOWED_PITCH, "medium")
    TTS_VOLUME = _env_choice("TTS_PROSODY_VOLUME", _ALLOWED_VOLUME, "medium")

    def _read_spanish_greeting() -> str:
        g = read_text("prompts/greeting.txt") or ""
        if g:
            parts = g.strip().splitlines()
            buf = []
            for line in parts:
                if line.strip() == "":
                    break
                buf.append(line)
            if buf:
                return "\n".join(buf).strip()
        return "¡Hola! Soy tu asistente virtual. ¿En qué puedo ayudarte?"

    # --- Сессия с авто-детектом языка (RU/ES/EN) и стартовым испанским TTS ---
    session = AgentSession(
        stt=azure.STT(
            speech_key=os.getenv("AZURE_SPEECH_KEY"),
            speech_region=os.getenv("AZURE_SPEECH_REGION", "francecentral"),
            language=["es-ES", "ru-RU", "en-US"],
            explicit_punctuation=True,
            phrase_list=[
                "Betrán",
                "Betrán Estilistas",
                "Puerto de Sagunto",
                "Sagunto",
                "Valencia",
                "cita",
                "corte",
                "barba",
                # RU доменные слова (улучшают качество распознавания + детект языка)
                "Бетран",
                "Бетран Эстилистас",
                "Пуэрто де Сагунто",
                "записаться",
                "стрижка",
                "борода",
                "окрашивание",
                "укладка",
                # EN fallback
                "appointment",
                "booking",
                "haircut",
            ],
        ),
        tts=azure.TTS(
            speech_key=os.getenv("AZURE_SPEECH_KEY"),
            speech_region=os.getenv("AZURE_SPEECH_REGION", "francecentral"),
            language="es-ES",
            voice=VOICE_BY_LANG["es"],
        ),
        llm=openai.LLM.with_azure(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("OPENAI_API_VERSION", "2024-10-21"),
            temperature=0.3,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        # Быстрее реакция и без ожидания TTS‑alignment
        preemptive_generation=True,
        use_tts_aligned_transcript=False,
        # Прерывания и авто‑возврат после ложных
        allow_interruptions=True,
        min_interruption_duration=0.25,
        false_interruption_timeout=1.0,
        resume_false_interruption=True,
        # Endpointing: шустрее закрываем реплики
        min_endpointing_delay=0.35,
        max_endpointing_delay=3.5,
        # Иногда требуется до 4 шагов тулзов (дата→часы→цена→слоты)
        max_tool_steps=4,
    )

    # Опционально: задержать preemptive_generation на первый ход, чтобы избежать гонок
    _delay_preemptive_first = (os.getenv("AGENT_PREEMPTIVE_DELAY_FIRST_TURN", "0").lower() in {"1", "true", "yes"})
    _preemptive_gate = {"armed": _delay_preemptive_first}
    if _preemptive_gate["armed"]:
        # временно выключаем — включим после первой финальной реплики пользователя
        try:
            session.options.preemptive_generation = False  # type: ignore[attr-defined]
        except Exception:
            pass

    # В новых версиях LiveKit авторезюм ложных прерываний встроен — ручной resume убран

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        if not _SIMPLE_CONSOLE:
            metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    # ======== ЛОГИ ТЕКСТА: компактно ========
    _partial = {"active": False, "len": 0}
    interaction = {"awaiting_user": False}
    _last_user_final = {"t": 0.0}

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
                try:
                    _last_user_final["t"] = _time.monotonic()
                except Exception:
                    pass
                interaction["awaiting_user"] = False
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
            # Если ассистент задал вопрос — ждём пользователя, не бриджим
            try:
                t = (text or "").strip()
                if "?" in t or "¿" in t:
                    interaction["awaiting_user"] = True
            except Exception:
                pass

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

    # Базовые инструкции + агент (будем обновлять инструкции при смене языка)
    base_instructions = _build_instructions()
    assistant = Assistant(instructions=base_instructions)

    await session.start(
        agent=assistant,
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # Если self-hosted — параметр noise_cancellation убери
            noise_cancellation=noise_cancellation.BVC(),
        ),
        # → текст сразу в консоль, без «привязки» к аудиопотоку (меньше задержка вывода)
        room_output_options=RoomOutputOptions(sync_transcription=False),
    )

    # Фоновое «думание»: мягкое клавиатурное шуршание (в консоли не играет)
    if (os.getenv("THINKING_BG_AUDIO", "0").lower() in {"1", "true", "yes"}) and not _SIMPLE_CONSOLE:
        try:
            _bg = BackgroundAudioPlayer(
                thinking_sound=[
                    AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.12),
                    AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.10),
                ]
            )
            await _bg.start(room=ctx.room, agent_session=session)
            ctx.add_shutdown_callback(_bg.aclose)
        except Exception:
            pass

    # 1) Стиль речи (из .env)
    session.tts.update_options(style=StyleConfig(style=TTS_STYLE, degree=TTS_STYLE_DEGREE))

    # 2) Просодия из .env
    session.tts.update_options(prosody=ProsodyConfig(rate=TTS_RATE, pitch=TTS_PITCH, volume=TTS_VOLUME))

    # Автосмена языка после первой фразы пользователя — синхронный колбэк + async задача
    lang_state = {"current": "es", "switched_once": False}

    register_thinking_bridge(
        session,
        lang_state=lang_state,
        interaction_state=interaction,
        last_user_final_at=_last_user_final,
    )

    async def _apply_lang_switch(detected: str):
        """Асинхронная часть переключения языка/голоса и обновления инструкций."""
        # 1) TTS: язык и голос
        session.tts.update_options(
            language={"es": "es-ES", "ru": "ru-RU", "en": "en-US"}[detected],
            voice=VOICE_BY_LANG.get(detected, VOICE_BY_LANG["es"]),
        )
        # keep assistant language for TTS post-processing
        try:
            assistant.tts_lang = {"es": "es-ES", "ru": "ru-RU", "en": "en-US"}[detected]
        except Exception:
            assistant.tts_lang = "es-ES"
        # 2) LLM: целевой язык ответа
        lang_clause = {
            "es": "Responde en español de forma natural y concisa.",
            "ru": "Отвечай по-русски, кратко и естественно.",
            "en": "Respond in natural, concise English.",
        }[detected]
        await assistant.update_instructions(f"{base_instructions}\n\n{lang_clause}")
        # 3) Ненавязчивое подтверждение — только один раз
        if not lang_state["switched_once"]:
            ack = {
                "es": "Perfecto, hablamos en español.",
                "ru": "Хорошо, переключаюсь на русский.",
                "en": "Great, switching to English.",
            }[detected]
        
            await session.say(ack)
            lang_state["switched_once"] = True
        lang_state["current"] = detected
        # Если мы задерживали preemptive для первого хода — включим его после подтверждения
        if _preemptive_gate["armed"]:
            try:
                session.options.preemptive_generation = True  # type: ignore[attr-defined]
            except Exception:
                pass
            _preemptive_gate["armed"] = False

    @session.on("user_input_transcribed")
    def _on_lang_autoswitch(ev):
        """Синхронный колбэк: проверяем язык и запускаем async‑задачу при необходимости."""
        if not getattr(ev, "is_final", False):
            return
        detected_tag = getattr(ev, "language", None)
        if not detected_tag:
            return
        detected = normalize_lang_tag(detected_tag)
        if detected == lang_state["current"]:
            # Язык не сменился — если preemptive был задержан на первый ход, включим его теперь
            if _preemptive_gate["armed"]:
                try:
                    session.options.preemptive_generation = True  # type: ignore[attr-defined]
                except Exception:
                    pass
                _preemptive_gate["armed"] = False
            return
        asyncio.create_task(_apply_lang_switch(detected))

    # Одно приветствие на испанском (берём первый абзац из greeting.txt)
    greeting_es = _read_spanish_greeting()
    if greeting_es:
        await session.say(greeting_es, allow_interruptions=True)

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
