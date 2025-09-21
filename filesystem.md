# Структура проекта

Репозиторий содержит голосового ассистента Betrán Estilistas (RU/ES/EN) на базе LiveKit Agents. «Горячий» контур (STT → диалог → TTS) выполняется в Python, интеграции (GCal/CRM/уведомления) вынесены в n8n.

## Обзор директорий
```
.
├─ src/
│  ├─ agent.py                  # точка входа воркера; конфиг STT/TTS/LLM, ивенты
│  ├─ speech/                   # пост-обработка речи (humanize, SSML, thinking-bridge)
│  │  ├─ humanize.py            # «слоты одним дыханием», время словами
│  │  ├─ ssml.py                # сборка SSML для Azure TTS
│  │  ├─ events.py              # регистрация THINKING-бриджей и фильтров
│  │  └─ time_utils.py          # форматы времени, нормализация языка
│  ├─ clients/
│  │  └─ n8n.py                 # HTTP-клиент к продовому n8n (book/reschedule/cancel/find)
│  ├─ tools/
│  │  ├─ barber/               # «источник правды» (услуги/мастера/слоты)
│  │  │  ├─ services.py        # модели, каталог услуг, профили мастеров
│  │  │  ├─ hours.py           # парсинг часов и календаря салона
│  │  │  ├─ availability.py    # генерация сетки слотов
│  │  │  ├─ matching.py        # подбор услуги по запросу клиента
│  │  │  └─ toolbox.py         # function_tool для LiveKit (resolve_date, suggest_slots, ...)
│  │  └─ gcal.py               # врапперы тулов бронирования → n8n webhooks
│  └─ utils.py                 # вспомогательные функции (чтение текстов)
├─ db/barber/                  # текстовые файлы: услуги, мастера, факты, плейбук
├─ prompts/                    # системный и приветственный промпты (RU/ES/EN)
├─ scripts/                    # демо/отладка: сидинг календаря, сценарии, конвертер логов
├─ tests/                      # базовые eval-тесты поведения агента (Azure LLM required)
├─ docs/CONTEXT.md             # быстрый гид по запуску/логам/тестам
├─ logs/                       # транскрипты, контакты, сценарии (генерируется)
├─ README.md                   # обзор и быстрый старт
├─ filesystem.md               # текущий документ
├─ pyproject.toml / uv.lock    # зависимости (uv + httpx, livekit, dateparser, ...)
├─ Dockerfile                  # образ воркера (uv sync + prewarm + start)
└─ .env.* / taskfile.yml ...   # конфиги, дев-инструменты
```

## Компоненты

### `src/agent.py`
- Загружает `.env.local`, формирует инструкции (`_build_instructions`).
- Создаёт `AgentSession` с Azure STT/TTS, Azure OpenAI (GPT‑4o), Silero VAD, turn-detector.
- Подписывается на события сессии (partial transcripts, history logging), регистрирует THINKING-bridge из `speech.events`.
- Подключает инструменты из `tools.barber.toolbox` и `tools.gcal`.
- Управляет авто-свитчем языка TTS/LLM и пост-обработкой через `speech.humanize`/`speech.ssml`.

### `src/speech/`
- `humanize.py` — склейка слотов в одну фразу, время словами на RU/ES/EN.
- `ssml.py` — шаблон SSML для Azure TTS (стиль/просодия из `.env`).
- `events.py` — THINKING-фразы («Секунду, сверяюсь…») с задержкой/кулдауном.
- `time_utils.py` — служебные функции (формат времени, нормализация тега языка).

### `src/clients/n8n.py`
- Тонкий HTTP-клиент (Basic Auth, таймаут 3 с) для боевых воркфлоу n8n.
- `create_booking / reschedule_booking / cancel_booking / find_by_phone` вызываются синхронно, используются из `tools/gcal.py` через `asyncio.to_thread`.

### `src/tools/barber/`
- Парсит текстовые данные `db/barber/*.txt`, строит `BarberDB` (услуги/мастера/индексы).
- Генерирует слоты (`availability.py`) и сопоставляет услуги запросу (`matching.py`).
- Экспортирует `function_tool`: `resolve_date`, `get_services`, `get_price`, `list_staff`, `suggest_slots`, `remember_contact` и др. Всё хранится в `toolbox.py`.
- Слоты проверяются только по расписанию салона/мастера; финальная проверка занятости происходит в n8n при бронировании.

### `src/tools/gcal.py`
- Оборачивает LiveKit `function_tool` для бронирования, переноса, отмены и поиска.
- Отправляет запросы в n8n (`/webhook/api/booking/*`), возвращая структуру `ok/error` в стиле прежнего API.

### Скрипты (`scripts/`)
- `run_scenarios_v2.py`, `run_adaptive_scenarios.py`, `run_quick_checks.py` — автоматические сценарии.
- `seed_gcal_realistic.py`, `cleanup_gcal_demo.py` — сидинг/очистка календаря (используют Google API напрямую, если нужен).
- `convert_logs_to_chats.py` — превращает логи LiveKit в читабельные диалоги.

## Окружение и переменные
Минимально требуется заполнить `.env.local`:
```
LIVEKIT_URL=...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=francecentral
AZURE_OPENAI_ENDPOINT=https://<endpoint>.openai.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4o
OPENAI_API_VERSION=2024-10-21
APP_TZ=Europe/Madrid

# n8n прод-воркфлоу
N8N_BASE=https://pix0010.app.n8n.cloud
N8N_USER=voicebot
N8N_PASS=45812438
N8N_TIMEOUT=3.0

# (опц.) если нативные gcal-скрипты/воркфлоу используют собственные календари
GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/service_account.json
GCAL_CALENDAR_MAP='{...}'
```
Советы:
- n8n должен иметь доступ к тем же сервисным аккаунтам GCal (права «Make changes to events»).
- `idempotency_key` поддерживается воркфлоу — формируйте на стороне агента (например, `room:start_iso:phone`).
- Не коммитьте `.env.local` и ключи в репозиторий.

## Поток данных (упрощённо)
```
Пользователь ──WebRTC──▶ LiveKit Room
    │                        │
    │                        ▼
    │            Azure STT / turn-detector (es/ru/en)
    │                        │
    │                        ▼
    │                LiveKit AgentSession (Python)
    │                    ├─ speech.humanize → ответ «живым» голосом
    │                    ├─ tools.barber.toolbox → resolve_date/suggest_slots/…
    │                    └─ tools.gcal → clients.n8n (book/reschedule/...)
    │                                              │
    │                                              ▼
    │                                      n8n workflow (HTTP)
    │                                              │
    │                                              ▼
    │                                       Google Calendar
    ▼
Azure TTS ──▶ ассистент проговаривает ответ пользователю
```

## Типичные команды
- Зависимости: `uv sync`
- Предзагрузка моделей: `uv run python src/agent.py download-files`
- Консольный режим: `AGENT_CONSOLE_SIMPLE=1 uv run python -m src.agent console`
- Прод-врокер: `uv run python -m src.agent start`
- Smoke для n8n (curl): см. `tests_smoke.sh`
- Сценарии: `uv run python scripts/run_quick_checks.py`, `uv run python scripts/run_adaptive_scenarios.py`

## Тестирование
- `tests/test_agent.py` — использует Azure GPT‑4o; требует валидных `AZURE_*` и сетевого доступа.
- При запрете сети (CI, локальная песочница) тесты падают с `httpx.ConnectError` — документируйте факт и используйте мок или запуск с разрешённым интернетом.

## Логи и артефакты
- `logs/transcript_*.json` — история диалогов из LiveKit.
- `logs/quick_checks/` и `logs/stress_tests/` — диалоги/метрики автосценариев; `scripts/convert_logs_to_chats.py` формирует HTML/тексты без тулов.
- `logs/contacts.csv` — результаты инструмента `remember_contact`.

## Дополнительно
- `Dockerfile` собирает образ на базе uv, прогревает модели (`download-files`) и запускает воркер (`uv run src/agent.py start`).
- `taskfile.yaml` (если используете `task`) содержит удобные алиасы.
- `docs/CONTEXT.md` дублирует основные шаги (env, запуск, сценарии) и подходит как onboarding.
