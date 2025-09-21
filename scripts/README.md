# Scripts Cheat Sheet

| Скрипт | Что делает | Примечания |
| --- | --- | --- |
| `run_quick_checks.py` | Два smoke‑сценария (бронь “на любого мастера”, поиск + отмена). Пишет `.txt`, `.json`, `.comment.txt` в `logs/quick_checks/`. | Использует реальные инструменты (Azure + n8n), между шагами есть паузы. |
| `run_scenarios_v2.py` | ~15 линейных сценариев RU/ES/EN: цены, подбор мастера, create/cancel/reschedule. | Логи и метрики в `logs/stress_tests/`. Тюнинг пауз — внутри файла. |
| `run_adaptive_scenarios.py` | Адаптивный набор: анализирует TOOL_RESULT, сам выбирает слоты, пробует альтернативы. | Флаги: `--sleep-between`, `--step-sleep`, `--skip-existing`, `--max-retries`, `--retry-sleep`. |
| `run_demo_booking.py` | Небольшой демонстрационный диалог (подбор → create → опц. cancel). | Полезно для видео/консольных демо. |
| `run_stress_dialogs.py` | Пакетный запуск сценариев из JSON (расширенные тесты). | Пишет диалоги + метрики в `logs/stress_tests/`. |
| `seed_gcal_realistic.py` | Реалистичный сидинг календарей (через Google API). | Требует сервисный аккаунт и `GCAL_CALENDAR_MAP`. Первый день плотнее, затем реже. |
| `cleanup_gcal_demo.py` | Очистка демо‑событий в Google Calendar. | Флаги: `--days-back`, `--days-forward`, `--also-realistic`. |
| `seed_gcal_week.py` | Упрощённый сидинг «Busy» на неделю. | Используйте только для быстрых заглушек. |
| `render_transcript.py` | Конвертирует `logs/transcript_*.json` в HTML. | `python scripts/render_transcript.py <path>` |
| `convert_logs_to_chats.py` | Удаляет tool‑шум из сценарных логов и строит “чистые” чаты/HTML. | `python scripts/convert_logs_to_chats.py --dir logs/stress_tests --index` |

## Общие правила
- Для скриптов, использующих LLM/инструменты, запускайте через `uv run ...`, чтобы подхватить плагины LiveKit и виртуальное окружение.
- Все сценарии ожидают, что `.env.local` заполнен (Azure, LiveKit, n8n; при необходимости Google). Без доступа к Azure OpenAI или n8n они завершатся ошибкой.
- Для чистки/сидинга Google Calendar убедитесь, что сервисный аккаунт имеет права «Make changes to events» на нужных календарях.

Полный обзор структуры и окружения см. в `README.md` и `docs/CONTEXT.md`.
