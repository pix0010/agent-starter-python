<a href="https://livekit.io/">
  <img src="./.github/assets/livekit-mark.png" alt="LiveKit logo" width="100" height="100">
</a>

# LiveKit Agents — Betrán Estilistas (Python)

Ассистент салона красоты Betrán Estilistas. Поддерживает RU/ES/EN, Azure Speech (STT/TTS), Azure OpenAI (GPT‑4o), управление диалогом, подбор мастера и бронирование через Google Calendar. Каталог услуг, длительности и профили мастеров хранятся в текстовых файлах `db/barber/*.txt` и используются напрямую.

## Что внутри
- LiveKit Agents воркер с Silero VAD и мультиязычным turn‑detector’ом
- Azure Speech STT/TTS (ru‑RU, es‑ES, en‑US; голос en‑US‑JennyMultilingualNeural) и Azure OpenAI (GPT‑4o)
- Тулзы: услуги/цены/длительности, расписание/слоты, мастера, бронирование GCal (create/cancel/find/reschedule)
- Логи, метрики, eval‑тесты, скрипты для демо‑занятости и отладки

## Быстрый старт
- Требования: Python 3.11+, [uv](https://docs.astral.sh/uv/), учётки LiveKit/Azure/Google Cloud
- Установка:
  - `uv sync`
  - `cp .env.example .env.local` и заполнить переменные (см. ниже)

Переменные окружения (минимум):
- LiveKit: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- Azure Speech: `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`
- Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `OPENAI_API_VERSION`
- Google Calendar:
  - `GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/service_account.json` (или `GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'`)
  - `GCAL_CALENDAR_MAP='{"ruben":"<cal_id>","sara":"<cal_id>","alex":"<cal_id>","betran":"<cal_id>","pau":"<cal_id>"}'`
  - (опц.) `GCAL_DEFAULT_CALENDAR_ID=<cal_id>` — fallback‑календарь (не рекомендуем в проде)

Запуск:
- Первый запуск (предзагрузка моделей): `uv run python src/agent.py download-files`
- Режимы: `uv run python -m src.agent console | dev | start`
- Чистый чат: `AGENT_CONSOLE_SIMPLE=1 uv run python -m src.agent console`

## Структура
```
src/agent.py                вход агента; STT/TTS/LLM, ассистент и события
src/tools/barber.py         услуги/цены/слоты; мастера и смены; контакты; индексация поиском RU/ES
src/tools/gcal.py           бронирование Google Calendar: create/cancel/find/reschedule
src/utils.py                утилиты (чтение текстов)
prompts/system.txt          системный промпт (RU/ES/EN, правила флоу и тулзов)
prompts/greeting.txt        приветствия на RU/ES/EN
db/barber/*.txt             база знаний: услуги, мастера, факты, плейбук
scripts/*.py                импорты/демо/рендер/QA (см. scripts/README.md)
```

## Интеграция с Google Calendar
1) Создайте сервисный аккаунт, скачайте JSON ключ; в каждом календаре мастера дайте права “Make changes to events” (Share → Add people → email сервис‑аккаунта).
2) Заполните `GCAL_CALENDAR_MAP` (staff_id → Calendar ID из Settings → Integrate calendar).
3) Инструменты агента:
- `create_booking(name, phone, start_iso, service_id?, staff_id?, duration_min?)`
- `cancel_booking(booking_id, staff_id)`
- `find_booking_by_phone(phone, staff_id, days?)`
- `reschedule_booking(booking_id, staff_id, new_start_iso, service_id?, duration_min?)`
- `suggest_slots(service_id?, start_iso?, party?, staff_id?)` — учитывает длительность (блоки по 30 мин) и занятость GCal при staff_id

Демо‑занятость: `PYTHONPATH=src python scripts/seed_gcal_week.py`

## Данные (источник правды)
- Вся актуальная информация об услугах, ценах, длительностях, мастерах и принципах диалога хранится в `db/barber/*.txt`:
  - `bertran_services_catalog.txt` — названия услуг, ориентировочные цены и длительности (мин)
  - `bertran_master_profiles.txt` — мастера и краткие описания/навыки
  - `bertran_kb_facts.txt` — факты: адрес, часы работы, контакты
  - `bertran_conversation_playbook.txt` — мини‑шаблоны и принципы коротких ответов
  - `betran_estilistas_plain.txt` — расширенная история/контент
  Эти файлы редактируются вручную и подхватываются агентом при запуске.

## Скрипты
- `scripts/seed_gcal_realistic.py` — реалистичное наполнение календарей на N дней (первые дни плотнее, дальше реже). Флаги: `--days`, `--heavy-days`, `--reset` (очистить демо перед посевом).
- `scripts/cleanup_gcal_demo.py` — очистка демо‑событий в Google Calendar; флаг `--also-realistic` убирает ранние «кодовые» записи.
- `scripts/run_scenarios_v2.py` — 15 линейных сценариев (RU/ES/EN), замеряет `turn_sec` по шагам и записывает логи.
- `scripts/run_adaptive_scenarios.py` — адаптивные сценарии: парсит TOOL_RESULT, сам выбирает слоты, задаёт нестандартные вопросы, иногда меняет намерение; записывает логи и метрики (в т.ч. приблизительную латентность инструментов на шаге).
- `scripts/run_demo_booking.py` — короткий демонстрационный флоу: выбрать время → создать запись (и при необходимости отменить).
- `scripts/render_transcript.py` — конвертирует `logs/transcript_*.json` в HTML.
- (Опц.) `scripts/seed_gcal_week.py` — упрощённый посев «Busy» на неделю (для быстрых демо).

## Уборка и актуальность
- Удалены устаревшие файлы: `db/barber/services.json`, `db/barber/staff.json`, `db/barber/store.json`, `db/barber/promt.txt`, `db/barber/greetings.txt`, `.DS_Store`, а также `info.docx` (больше не нужен).
- Источник правды — текстовые файлы в `db/barber/`.

## Контейнеризация
- Dockerfile использует uv, предзагружает модели (`download-files`) и запускает воркер (`uv run src/agent.py start`).

## Лицензия
MIT — см. `LICENSE`.
