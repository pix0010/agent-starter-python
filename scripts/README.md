Scripts overview

- seed_gcal_realistic.py
  - Fills Google Calendars for all mapped masters with realistic appointments for N days. Heavier load in the first days, then sparser. Each event uses a real service name + correct duration, client name/phone in description.
  - Flags: `--days N`, `--heavy-days M`, `--reset` (cleanup demo entries before seeding).
  - Requires: `GOOGLE_APPLICATION_CREDENTIALS` or `GOOGLE_SERVICE_ACCOUNT_JSON`, and `GCAL_CALENDAR_MAP`.

- cleanup_gcal_demo.py
  - Removes demo entries from Google Calendars across a date range. By default removes “Busy (Demo)” events; with `--also-realistic` also erases early code‑prefixed seeds.
  - Flags: `--days-back`, `--days-forward`, `--also-realistic`.

- run_scenarios_v2.py
  - Runs ~15 linear scripted scenarios (RU/ES/EN), exercising tools for slots/prices/booking/cancel/reschedule. Saves dialogs to `logs/stress_tests/*.txt` and per‑turn metrics to `*_metrics.json` (turn_sec + tool activity).
  - Run: `uv run python scripts/run_scenarios_v2.py`

- run_adaptive_scenarios.py
  - Adaptive orchestrator: reads TOOL_RESULT (e.g., suggest_slots), automatically picks a slot, injects clarifications (price/care), occasionally changes intent (time/master/services). Writes dialogs and metrics (including approximate per‑tool latency per turn).
  - Flags: `--sleep-between`, `--step-sleep`, `--skip-existing`, `--max-retries`, `--retry-sleep`.
  - Run: `uv run python scripts/run_adaptive_scenarios.py`

- run_demo_booking.py
  - Simple text‑mode demo: user asks to book, agent proposes slots, confirms a time, and creates a booking (optionally cancel afterwards).

- render_transcript.py
  - Converts `logs/transcript_*.json` to HTML for quick reading.

- convert_logs_to_chats.py
  - Converts technical scenario logs (`logs/stress_tests/*.txt`) into clean chat transcripts by stripping tool calls and leaving only client/assistant messages.
  - Produces `<name>.chat.txt` and `<name>.chat.html` next to each input file.
  - With `--index` also generates a two‑pane viewer `logs/stress_tests/index.html` (sidebar list of scenarios + inline chat preview without page reload).
  - Usage: `python scripts/convert_logs_to_chats.py --dir logs/stress_tests --index` (labels: `--labels ru|en|es`).

- seed_gcal_week.py (optional)
  - Legacy simple seeder (adds “Busy” slots on a week). Prefer `seed_gcal_realistic.py`.

Notes
- All scripts expect environment variables from `.env.local` (Azure OpenAI, Google Calendar, etc.).
- For LLM‑driven scripts use `uv run` so LiveKit plugins are available in the venv.
