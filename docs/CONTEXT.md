Context Guide — Betrán Estilistas Agent

Purpose
- Orient quickly: how to run the agent, seed Google Calendars, execute tests (linear/adaptive), read logs/metrics, and where data lives.

Prerequisites
- Python 3.11+
- uv package manager installed
- Azure OpenAI + Azure Speech credentials
- Google Cloud service account credentials for Calendar API
- LiveKit account (URL, API key/secret)

Environment Setup
- Copy env template and fill values:
  `cp .env.example .env.local`
- Minimal variables in `.env.local`:
  - LiveKit: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
  - Azure Speech: `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`
  - Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `OPENAI_API_VERSION`
  - Google Calendar:
    - `GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/service_account.json`
      (or `GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'`)
    - `GCAL_CALENDAR_MAP='{"ruben":"<cal_id>","sara":"<cal_id>","alex":"<cal_id>","betran":"<cal_id>","pau":"<cal_id>"}'`
    - Optional fallback: `GCAL_DEFAULT_CALENDAR_ID=<cal_id>` (not recommended in prod)

Install deps
- `uv sync`

Run the Agent
- First-time model prewarm: `uv run python src/agent.py download-files`
- Modes:
  - Console: `uv run python -m src.agent console`
    - Plain prints: `AGENT_CONSOLE_SIMPLE=1 uv run python -m src.agent console`
  - Dev (WebRTC clients): `uv run python -m src.agent dev`
  - Prod worker: `uv run python -m src.agent start`

Data (source of truth)
- `db/barber/*.txt`
  - `bertran_services_catalog.txt` — services, durations (min), indicative prices
  - `bertran_master_profiles.txt` — masters and summaries/skills
  - `bertran_kb_facts.txt` — address, hours, contacts
  - `bertran_conversation_playbook.txt` — concise conversational patterns
  - `betran_estilistas_plain.txt` — extended content

Google Calendar Integration
- Create per‑master calendars; share each with the service account email (“Make changes to events”).
- Map staff_id → calendar id in `GCAL_CALENDAR_MAP`.
- Tools:
  - `suggest_slots(service_id?, services?, start_iso?, party?, staff_id?)` — allocates contiguous 30‑min blocks for a single service or sum of services; filters by GCal occupancy; supports groups via `party`.
  - `create_booking(name, phone, start_iso, service_id?, services?, staff_id?, duration_min?)` — creates one event; summary is human‑readable; codes/prices live in description and private extended properties.
  - `cancel_booking(booking_id, staff_id)` / `find_booking_by_phone(phone, staff_id, days?)` / `reschedule_booking(booking_id, staff_id, new_start_iso, ...)`.

Seeding and Cleanup
- Realistic seeding (first days heavier):
  `PYTHONPATH=src python3 scripts/seed_gcal_realistic.py --reset --days 10 --heavy-days 2`
  - `--reset` cleans demo entries first.
- Cleanup only:
  `PYTHONPATH=src python3 scripts/cleanup_gcal_demo.py --days-back 60 --days-forward 60 --also-realistic`

Tests and Logs
- Quick checks (2 scenarios, human‑paced):
  `uv run python scripts/run_quick_checks.py`
  - Output: `logs/quick_checks/*.txt` and `.json` + a `.comment.txt` per run.

- Linear scripted scenarios (~15), human‑paced with backoff:
  `uv run python scripts/run_scenarios_v2.py`
  - Per scenario outputs:
    - Dialog: `logs/stress_tests/<ts>_<id>.txt`
    - Metrics: `logs/stress_tests/<ts>_<id>_metrics.json`

- Adaptive scenarios (dynamic), human‑paced:
  `uv run python scripts/run_adaptive_scenarios.py --sleep-between 6 --step-sleep 1.5 --max-retries 6 --retry-sleep 15`
  - Behavior: parses tool results, auto‑picks slots, injects clarifications; built‑in backoff (429/content filter).
  - Output: dialog + metrics in `logs/stress_tests/`.

Reading Outputs
- Live tail: `tail -f logs/adaptive_run.out`
- Latest files: `ls -lt logs/stress_tests/`
- Open dialog: `sed -n '1,160p' logs/stress_tests/<ts>_<id>.txt`
- Metrics JSON: `cat logs/stress_tests/<ts>_<id>_metrics.json`

Performance Notes
- `turn_sec` includes LLM + tools for the step. Approx per‑tool latency is included; for precise per‑tool timing, add event timestamps in tools (optional enhancement).
- Scripts insert human‑like pauses and exponential backoff to avoid Azure 429; tune with flags or environment as needed.

Prompts and Behavior
- System prompt `prompts/system.txt` (RU/ES/EN) encodes:
  - Short answers, next‑step prompts, tool usage rules
  - Booking flow: confirm service → suggest_slots → create_booking → remember_contact
  - Packages: use `services=[...]` with suggest/create
  - Party (groups): consecutive slots via `party`

FAQ
- “Where are services/masters defined?” → `db/barber/*.txt`
- “How to seed demo schedule?” → `scripts/seed_gcal_realistic.py`
- “How to run tests?” → linear `run_scenarios_v2.py`, adaptive `run_adaptive_scenarios.py`
- “How to view logs?” → `logs/stress_tests/` dialogs + metrics; live tail in `logs/adaptive_run.out`
