# Структура файлов проекта

Этот репозиторий — стартовый шаблон голосового ассистента (RU/ES/EN) для салона красоты Betrán Estilistas на базе LiveKit Agents (Python) с Azure Speech (STT/TTS), Azure OpenAI (LLM) и интеграцией с Google Calendar.

## Дерево (укороченный обзор)
```
.
├─ src/                         # исходный код пакета
│  ├─ __init__.py
│  ├─ agent.py                  # вход воркера/консоли, настройка STT/TTS/LLM, события
│  ├─ utils.py                  # утилиты
│  └─ tools/
│     ├─ __init__.py
│     ├─ barber.py              # услуги/цены/слоты, мастера, индексация, контакты
│     └─ gcal.py                # инструменты для Google Calendar (create/cancel/find/reschedule)
├─ prompts/                     # системные подсказки/приветствия
│  ├─ system.txt
│  └─ greeting.txt
├─ db/
│  └─ barber/                   # «источник правды»: текстовые данные салона
│     ├─ bertran_services_catalog.txt
│     ├─ bertran_master_profiles.txt
│     ├─ bertran_kb_facts.txt
│     ├─ bertran_conversation_playbook.txt
│     └─ betran_estilistas_plain.txt
├─ scripts/                     # служебные и демо‑скрипты
│  ├─ README.md
│  ├─ cleanup_gcal_demo.py
│  ├─ convert_logs_to_chats.py
│  ├─ render_transcript.py
│  ├─ run_adaptive_scenarios.py
│  ├─ run_demo_booking.py
│  ├─ run_scenarios_v2.py
│  └─ seed_gcal_realistic.py
├─ tests/
│  └─ test_agent.py             # базовые eval‑тесты поведения ассистента
├─ docs/
│  └─ CONTEXT.md                # краткий гид по запуску/данным/логам/тестам
├─ logs/                        # результаты прогонов, транскрипты, метрики (генерируется)
│  ├─ adaptive_run.out
│  ├─ contacts.csv
│  └─ stress_tests/ ...         # диалоги и метрики сценариев
├─ .github/                     # CI (ruff/tests) и ассеты
│  ├─ assets/livekit-mark.png
│  └─ workflows/{ruff,tests,template-check}.yml
├─ .env.example                 # шаблон переменных окружения
├─ .env.local                   # локальные секреты (не коммитить публично)
├─ Dockerfile                   # контейнеризация воркера
├─ pyproject.toml               # зависимости, конфиги ruff/pytest
├─ taskfile.yaml                # удобные локальные задачи (если используете task)
├─ uv.lock                      # lock‑файл менеджера пакетов uv
├─ README.md                    # обзор проекта и быстрый старт
└─ .dockerignore / .gitignore   # игнор‑правила
```

## Ключевые директории и файлы
- `src/agent.py` — точка входа воркера LiveKit Agents; инициализация Azure STT/TTS, Azure OpenAI, Silero VAD, детектор очередности реплик, обработчики событий, динамические инструкции, переключение языка TTS по речи пользователя.
- `src/tools/barber.py` — работа с данными салона: парсинг часов работы, каталог услуг (цены/длительности/теги), профили мастеров, генерация слотов, фильтрация по GCal, вспомогательные `function_tool` для LLM.
- `src/tools/gcal.py` — интеграция с Google Calendar (создание/отмена/поиск/перенос записей), чтение занятости, сопоставление `staff_id → calendar id` через `GCAL_CALENDAR_MAP`.
- `prompts/` — системный промпт и приветствия (используются агентом при запуске).
- `db/barber/` — текстовая база знаний: услуги, мастера, факты, плейбук, расширенный контент. Эти файлы редактируются вручную и подхватываются кодом.
- `scripts/` — утилиты для посева расписаний в GCal, запуска сценариев (линейных и адаптивных), рендера транскриптов, конвертации логов в чистые чаты и т.д.
- `tests/test_agent.py` — проверка дружественности и отказов (grounding/безопасность) с использованием LLM‑оценок.
- `docs/CONTEXT.md` — пошаговый гид: env, запуск, тесты, логи, сиды календаря.
- `logs/` — артефакты прогонов: транскрипты `transcript_*.json`, диалоги/метрики сценариев в `logs/stress_tests/`, контакты.
- `pyproject.toml` — зависимости: `livekit-agents`, плагины (azure/openai/silero/turn-detector), Google API, `dateparser`; dev‑зависимости `pytest`, `ruff`.
- `Dockerfile` — сборка контейнера с `uv`, предзагрузка моделей (`download-files`) и запуск воркера.

## Окружение и секреты
- Шаблон: `.env.example` → копируйте в `.env.local` и заполните минимумом:
  - LiveKit: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
  - Azure Speech: `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`
  - Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `OPENAI_API_VERSION`
  - Google Calendar: `GOOGLE_APPLICATION_CREDENTIALS` или `GOOGLE_SERVICE_ACCOUNT_JSON`, `GCAL_CALENDAR_MAP`
- Дополнительно: `APP_TZ`, `AGENT_CONSOLE_SIMPLE`, `GCAL_DEFAULT_CALENDAR_ID` (fallback).

## Генерируемые и локальные каталоги
- `logs/` — создаётся автоматически при сохранении транскриптов, конвертации логов, сидировании календаря и прогоне сценариев.
- `.venv/`, `.pytest_cache/`, `.uv_cache/`, `.DS_Store` — локальные/временные артефакты среды разработки (могут отсутствовать у других разработчиков).

## Быстрые команды (локально)
- Установка: `uv sync`
- Предзагрузка моделей: `uv run python src/agent.py download-files`
- Консольный режим: `uv run python -m src.agent console` (упростить вывод: `AGENT_CONSOLE_SIMPLE=1 ...`)
- Демонстрационный посев расписаний: `PYTHONPATH=src python scripts/seed_gcal_realistic.py --reset --days 10`
- Сценарии (линейные/адаптивные): `uv run python scripts/run_scenarios_v2.py` / `uv run python scripts/run_adaptive_scenarios.py`

```
Подсказка: структура и роли файлов также кратко описаны в README.md и docs/CONTEXT.md.
```

## Диаграмма модулей и поток данных

```
┌───────────┐   речь   ┌───────────┐   текст   ┌───────────────┐   запрос   ┌──────────────┐
│  Клиент   │ ───────▶ │  LiveKit  │ ───────▶ │  Azure STT    │ ─────────▶ │ AgentSession │
└───────────┘          │  Room     │          └───────────────┘            │  (src/agent) │
                       └───────────┘                                        └──────┬───────┘
                                                                                   │
                                                                                   │prompt+history
                                                                                   ▼
                                                                            ┌──────────────┐
                                                                            │ Azure OpenAI │ ← системный промпт из
                                                                            │   (LLM)      │   `prompts/system.txt`
                                                                            └──────┬───────┘
                                                                                   │ функции (tools)
                                                                                   ▼
         ┌───────────────────────────────┐                 ┌────────────────────────────────────────┐
         │ tools/barber.py               │                 │ tools/gcal.py                          │
         │ - каталог услуг/мастеров      │                 │ - create/cancel/find/reschedule        │
         │ - часы/слоты/фильтрация GCal  │                 │ - busy/свободные интервалы             │
         └──────┬────────────────────────┘                 └───────────────────────┬────────────────┘
                │ чтение данных из `db/barber/*.txt`                                │ Google Calendar API
                ▼                                                                    ▼
          «Источник правды»                                                     Календарь мастера

                                                       │
                                                       ▼
                                             ┌──────────────────┐  текст  ┌───────────────┐  речь  ┌───────────┐
                                             │ Ответ ассистента │ ──────▶ │  Azure TTS    │ ─────▶ │  Клиент   │
                                             └──────────────────┘         └───────────────┘        └───────────┘
```

## Пример `.env.local`

Скопируйте `.env.example` в `.env.local` и заполните минимум переменных:

```
# LiveKit
LIVEKIT_URL=wss://<your-livekit-host>
LIVEKIT_API_KEY=lk_...
LIVEKIT_API_SECRET=...

# Azure Speech
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=francecentral

# Azure OpenAI (GPT-4o через Azure)
AZURE_OPENAI_ENDPOINT=https://<your-azure-openai>.openai.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4o
OPENAI_API_VERSION=2024-10-21

# Часовой пояс приложения
APP_TZ=Europe/Madrid

# Google Calendar
# либо путь к файлу сервисного аккаунта:
GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/service_account.json
# либо сам JSON в переменной (одна строка):
# GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'

# Соответствие мастеров календарям (staff_id → calendarId)
GCAL_CALENDAR_MAP='{"ruben":"<cal_id>","sara":"<cal_id>","alex":"<cal_id>","betran":"<cal_id>","pau":"<cal_id>"}'

# Опционально: запасной календарь (на всякий случай)
# GCAL_DEFAULT_CALENDAR_ID=<cal_id>

# Упрощённый консольный вывод (меньше логов)
AGENT_CONSOLE_SIMPLE=1
```

Советы:
- Дайте сервисному аккаунту права «Make changes to events» в календарях мастеров (Share → Add people → email сервис‑аккаунта).
- Значение `GCAL_CALENDAR_MAP` — валидный JSON (одна строка). Имена (`ruben`, `sara`, …) должны совпадать с `staff.id` из `db/barber` (см. `tools/barber.py`).
- Не коммитьте `.env.local` в публичные репозитории.

## Примеры запуска

- Первичная установка: `uv sync`
- Предзагрузка аудио/моделей: `uv run python src/agent.py download-files`
- Консоль (быстрый диалог без WebRTC‑клиента):
  - `AGENT_CONSOLE_SIMPLE=1 uv run python -m src.agent console`
- Воркеры (для LiveKit Rooms):
  - Dev: `uv run python -m src.agent dev`
  - Prod: `uv run python -m src.agent start`

## Проверка интеграции с календарями

- Посеять реалистичные записи: `PYTHONPATH=src python scripts/seed_gcal_realistic.py --reset --days 10`
- Проверить слоты/перенос/поиск (сценарии):
  - `uv run python scripts/run_scenarios_v2.py`
  - `uv run python scripts/run_adaptive_scenarios.py`
- Конвертировать логи сценариев в «чистые чаты»: `python scripts/convert_logs_to_chats.py --dir logs/stress_tests --index`
