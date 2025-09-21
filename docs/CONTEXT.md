# Context Guide — Betrán Estilistas Agent

Цель: быстрый чек‑лист для запуска, отладки и проверки бронирований.

## 1. Установка и окружение
1. `uv sync`
2. `cp .env.example .env.local`
3. Заполнить минимум: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `OPENAI_API_VERSION`, `N8N_BASE`, `N8N_USER`, `N8N_PASS`, `N8N_TIMEOUT`, `APP_TZ=Europe/Madrid`.
4. (Опц.) `GOOGLE_APPLICATION_CREDENTIALS`/`GOOGLE_SERVICE_ACCOUNT_JSON`, `GCAL_CALENDAR_MAP` — нужны n8n и сидерам календарей.

## 2. Быстрый запуск
- Предзагрузка моделей: `uv run python src/agent.py download-files`
- Консольный режим: `AGENT_CONSOLE_SIMPLE=1 uv run python -m src.agent console`
- Продовый воркер: `uv run python -m src.agent start`
- Перезапуск LiveKit worker через `--watch`: `uv run python -m src.agent dev`

## 3. Бронирование через n8n
- Инструменты `create_booking`, `cancel_booking`, `reschedule_booking`, `find_booking_by_phone` обращаются к n8n (`${N8N_BASE}/webhook/api/booking/*`, Basic Auth).
- Агент генерирует слоты локально (`suggest_slots`). Итоговые проверки на занятость выполняет n8n, возвращая `200 {"ok":true,...}` или `409 {"ok":false,"error":{"code":"time_conflict"}}`.
- Smoke (curl):
  ```bash
  N8N_BASE=... N8N_USER=... N8N_PASS=... ./tests_smoke.sh
  ```
  Скрипт делает create → reschedule → find → cancel.

## 4. Сценарии и тесты
- Быстрые smoke-сценарии: `uv run python scripts/run_quick_checks.py`
- Линейные сценарии: `uv run python scripts/run_scenarios_v2.py`
- Адаптивные сценарии: `uv run python scripts/run_adaptive_scenarios.py --sleep-between 6 --step-sleep 1.5`
- Ручной smoke для бронирований: `tests_smoke.sh` (curl → n8n)
- Автотесты: `pytest` (нужен доступ к Azure GPT‑4o и внешней сети)

## 5. Данные и промпты
- `db/barber/*.txt` — услуги, мастера, факты, плейбук.
- `prompts/system.txt` — правила диалога (RU/ES/EN), `prompts/greeting.txt` — приветствия.

## 6. Логи и артефакты
- `logs/transcript_<room>_<ts>.json` — полная история сессии (сохраняется при shutdown).
- `logs/quick_checks/` и `logs/stress_tests/` — сценарные диалоги и метрики.
- `logs/contacts.csv` — данные из `remember_contact`.
- Конвертация логов → чаты: `python scripts/convert_logs_to_chats.py --dir logs/stress_tests --index`.

## 7. Полезные команды
```bash
uv run python src/agent.py download-files      # prewarm моделей
AGENT_CONSOLE_SIMPLE=1 uv run -m src.agent console
uv run python scripts/run_quick_checks.py
uv run python scripts/run_adaptive_scenarios.py --sleep-between 6 --step-sleep 1.5
python scripts/render_transcript.py logs/transcript_<...>.json
```

## 8. Траблшутинг
- **Azure 429 / content filter** — увеличьте `--sleep-between`, `--retry-sleep` в сценариях или попросите расширить квоты.
- **pytest падает с `httpx.ConnectError`** — нет выхода в интернет к Azure GPT‑4o. Запускайте в среде с сетью или мокайте LLM.
- **Бронирование возвращает 409** — слот занят в календаре (n8n). Предложите другой через `suggest_slots`.
- **n8n не отвечает** — перепроверьте `N8N_BASE/N8N_USER/N8N_PASS`, статус воркфлоу и права сервисного аккаунта в GCal.

Для детального описания структуры см. [filesystem.md](../filesystem.md), для обзора скриптов — [scripts/README.md](../scripts/README.md).
