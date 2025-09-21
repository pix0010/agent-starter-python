<a href="https://livekit.io/">
  <img src="./.github/assets/livekit-mark.png" alt="LiveKit logo" width="100" height="100">
</a>

# LiveKit Agents — Betrán Estilistas (Python)

Голосовой ассистент салона Betrán Estilistas. Работает на LiveKit Agents, поддерживает RU/ES/EN, использует Azure Speech (STT/TTS) и Azure OpenAI (GPT‑4o). «Горячий» контур — распознавание речи, планирование, ответ — выполняется в Python рядом с WebRTC. Все «холодные» действия (бронирование, CRM, уведомления) передаются во внешний n8n‑воркфлоу.

## Архитектура одним взглядом
- **LiveKit AgentSession**: Azure STT (es‑ES/ru‑RU/en‑US), Silero VAD, Multilingual turn detector, Azure TTS. Включены interruptions и preemptive generation для живой речи.
- **Пост‑обработка речи**: пакет `src/speech/` превращает списки слотов в короткие фразы, строит SSML и вставляет “thinking”‑мостики.
- **Данные салона**: `src/tools/barber/` читает текстовые файлы `db/barber/*.txt`, генерирует слоты и экспортирует `function_tool` (resolve_date, suggest_slots, list_staff, ...).
- **Бронирования**: `src/tools/gcal.py` вызывает `clients/n8n.py`, который обращается к продовому n8n (`/webhook/api/booking/*`). n8n уже работает с Google Calendar и возвращает `ok/ error`.
- **Логи и диагностика**: сценарные скрипты пишут диалоги и метрики в `logs/`, есть утилиты для конвертации в “чистые” чаты.

## Требования и установка
1. Python 3.11+, [uv](https://docs.astral.sh/uv/), аккаунты LiveKit, Azure OpenAI/Speech, доступ к n8n (Basic Auth) и Google Calendar (для n8n).
2. Клон → `uv sync`.
3. Скопируйте `.env.example` → `.env.local` и заполните минимум:
   - `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
   - `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`
   - `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `OPENAI_API_VERSION`
   - `N8N_BASE`, `N8N_USER`, `N8N_PASS`, `N8N_TIMEOUT`
   - (опц.) `GOOGLE_APPLICATION_CREDENTIALS` или `GOOGLE_SERVICE_ACCOUNT_JSON`, `GCAL_CALENDAR_MAP` — нужны воркфлоу n8n и сидерам календаря.
   - `APP_TZ=Europe/Madrid`

> **Совет:** n8n использует idempotency_key, передавайте его из агента (например, `room:start_iso:phone`).

## Запуск
- Предзагрузка моделей: `uv run python src/agent.py download-files`
- Режимы:
  - Консоль: `AGENT_CONSOLE_SIMPLE=1 uv run python -m src.agent console`
  - Dev (LiveKit rooms): `uv run python -m src.agent dev`
  - Prod worker: `uv run python -m src.agent start`
- Smoke n8n (curl): см. `tests_smoke.sh` — создаёт/переносит/ищет/отменяет запись.

## Данные и промпты
- Источник правды — `db/barber/*.txt`: услуги, длительности, профили мастеров, факты и правила диалога.
- Промпты — `prompts/system.txt` (правила диалога RU/ES/EN) и `prompts/greeting.txt` (приветствия).

## Скрипты
| Скрипт | Назначение |
| --- | --- |
| `scripts/run_quick_checks.py` | Два smoke‑сценария (бронь на любого мастера, поиск+отмена). Логи в `logs/quick_checks/`. |
| `scripts/run_scenarios_v2.py` | ~15 линейных сценариев (RU/ES/EN) с логами и метриками. |
| `scripts/run_adaptive_scenarios.py` | Адаптивные сценарии: выбирают слоты, задают уточнения, пробуют альтернативы. |
| `scripts/run_demo_booking.py` | Короткая текстовая демо-сессия (подбор → бронирование → опц. отмена). |
| `scripts/seed_gcal_realistic.py`, `scripts/cleanup_gcal_demo.py` | Реалистичный сидинг/очистка календарей (исп. прямой Google API). |
| `scripts/render_transcript.py`, `scripts/convert_logs_to_chats.py` | Конвертация логов LiveKit в читаемые HTML/тексты. |

Все LLM‑скрипты запускайте через `uv run ...`, чтобы подтянуть плагины LiveKit.

## Тестирование
- `tests/test_agent.py` проверяет тон/grounding/безопасность. Требует реальный доступ к Azure GPT‑4o и сети. При отсутствии интернета тесты падают с `httpx.ConnectError` — это ожидаемо.
- Для регрессий по бронированию используйте `tests_smoke.sh` (curl → n8n) или сценарии из `scripts/`.

## Логи
- `logs/transcript_*.json` — полная история сессий (сохраняется при завершении).
- `logs/quick_checks/`, `logs/stress_tests/` — выходы сценариев (`.txt`, `.json`, `.comment.txt`).
- `logs/contacts.csv` — результаты инструмента `remember_contact` (простая CSV база).

## Карта репозитория
Подробное дерево с комментариями см. в [filesystem.md](filesystem.md).

## Лицензия
MIT — см. `LICENSE`.
