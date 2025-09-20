#!/usr/bin/env python3
"""
Convert technical scenario logs (.txt with USER/ASSISTANT/TOOL_* lines)
into human-readable chat transcripts.

Outputs alongside each input file by default:
  - <name>.chat.txt   (clean chat: Client/Assistant only)
  - <name>.chat.html  (pretty HTML bubbles)

Also can emit an index.html with a two-pane viewer (sidebar + inline chat).

Usage examples:
  PYTHONPATH=src python scripts/convert_logs_to_chats.py --glob 'logs/stress_tests/*.txt' --index
  python scripts/convert_logs_to_chats.py --dir logs/stress_tests --labels ru --index

"""
import argparse
import html
import json
import re
from pathlib import Path
from typing import List, Tuple


Speaker = Tuple[str, str]  # (role, text)


CHAT_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f6f7f9;margin:0;padding:20px}
.wrap{max-width:900px;margin:0 auto}
.bubble{max-width:740px;padding:12px 14px;border-radius:14px;margin:8px 0;line-height:1.5;white-space:pre-wrap}
.client{background:#fff;border:1px solid #e5e7eb;align-self:flex-end;margin-left:auto}
.assistant{background:#e8f0ff;border:1px solid #d1d9ff}
.meta{font-size:12px;color:#6b7280;margin:2px 0 0 4px}
.row{display:flex;flex-direction:column}
h1{font-size:18px;margin:0 0 12px 0}
.file{font-size:13px;color:#111827;margin:2px 0 14px 0}
"""


USER_RE = re.compile(r"^USER:\s*(.*)")
ASSISTANT_RE = re.compile(r"^ASSISTANT:\s*(.*)")


def parse_log_txt(path: Path) -> List[Speaker]:
    """Extract only user/assistant messages from a technical .txt log.

    We keep lines starting with:
      USER: ...
      ASSISTANT: ...
    and ignore TOOL_CALL/TOOL_RESULT and anything else.

    If subsequent lines don't start with a known prefix and are not TOOL_*,
    we append them to the last message (to support rare multiline messages).
    """
    messages: List[Speaker] = []
    last_role = None
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")

            # Tool lines are skipped entirely
            if line.startswith("TOOL_CALL") or line.startswith("TOOL_RESULT"):
                continue

            m_user = USER_RE.match(line)
            if m_user:
                text = m_user.group(1).strip()
                messages.append(("user", text))
                last_role = "user"
                continue

            m_asst = ASSISTANT_RE.match(line)
            if m_asst:
                text = m_asst.group(1).strip()
                messages.append(("assistant", text))
                last_role = "assistant"
                continue

            # Possibly a continuation of the last message (rare)
            if last_role and line and not line.strip().startswith("#"):
                if not (line.startswith("USER:") or line.startswith("ASSISTANT:")):
                    role, prev = messages[-1]
                    messages[-1] = (role, prev + "\n" + line)

    return messages


def write_chat_txt(messages: List[Speaker], dst: Path, labels: str = "ru") -> None:
    if labels == "ru":
        user_label, asst_label = "Клиент", "Ассистент"
    elif labels == "es":
        user_label, asst_label = "Cliente", "Asistente"
    else:
        user_label, asst_label = "User", "Assistant"

    lines = []
    for role, text in messages:
        who = user_label if role == "user" else asst_label
        lines.append(f"{who}: {text}")
    dst.write_text("\n\n".join(lines) + "\n", encoding="utf-8")


def write_chat_html(messages: List[Speaker], dst: Path, title: str, labels: str = "ru") -> None:
    if labels == "ru":
        user_label, asst_label = "Клиент", "Ассистент"
    elif labels == "es":
        user_label, asst_label = "Cliente", "Asistente"
    else:
        user_label, asst_label = "User", "Assistant"

    out = ['<!doctype html><meta charset="utf-8"><title>Chat Transcript</title>',
           f"<style>{CHAT_CSS}</style>", '<div class="wrap">', f"<h1>Chat Transcript</h1>", f'<div class="file">{html.escape(title)}</div>']
    for role, text in messages:
        who = user_label if role == "user" else asst_label
        bubble_class = "client" if role == "user" else "assistant"
        out.append(
            f'<div class="row"><div class="bubble {bubble_class}">{html.escape(text)}</div><div class="meta">{who}</div></div>'
        )
    out.append("</div>")
    dst.write_text("\n".join(out), encoding="utf-8")


def find_metrics_for(log_path: Path) -> Path | None:
    # Attempts to find a metrics json with same prefix
    base = log_path.stem  # e.g., 20250919_193253_adaptive_cut_ruben
    cand = log_path.with_name(base + "_metrics.json")
    return cand if cand.exists() else None


def load_metrics_summary(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    steps = len(data) if isinstance(data, list) else 0
    tool_calls = sum(len(d.get("tool_calls", [])) for d in data) if isinstance(data, list) else 0
    turn_secs = [d.get("turn_sec") for d in data if isinstance(d, dict) and isinstance(d.get("turn_sec"), (int, float))] if isinstance(data, list) else []
    avg_turn = (sum(turn_secs) / len(turn_secs)) if turn_secs else None
    return {"steps": steps, "tool_calls": tool_calls, "avg_turn_sec": avg_turn}


def write_index_html(entries: List[dict], dst: Path) -> None:
    rows = []
    for e in entries:
        name = html.escape(e["name"])  # base name
        chat_link = html.escape(e.get("chat_html_rel", ""))
        txt_link = html.escape(e.get("src_rel", ""))
        metrics = e.get("metrics", {})
        steps = metrics.get("steps")
        calls = metrics.get("tool_calls")
        avg = metrics.get("avg_turn_sec")
        stats = []
        if steps is not None:
            stats.append(f"шагов: {steps}")
        if calls is not None:
            stats.append(f"вызовов тулзов: {calls}")
        if avg is not None:
            stats.append(f"средн. turn_sec: {avg:.2f}")
        stats_txt = " · ".join(stats)
        rows.append(f"<li><a href='{chat_link}'>{name}</a> <span style='color:#6b7280'>(<a href='{txt_link}'>raw</a>{' · ' + stats_txt if stats_txt else ''})</span></li>")

    html_out = """
<!doctype html>
<meta charset="utf-8">
<title>Scenario Transcripts</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f6f7f9;margin:0;padding:20px}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:20px;margin:0 0 12px 0}
ul{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 16px}
li{margin:6px 0}
code{background:#eef2ff;padding:1px 4px;border-radius:4px}
</style>
<div class="wrap">
  <h1>Scenario Transcripts</h1>
  <p>Сгенерировано из технических логов: оставлены только реплики клиента и ассистента.</p>
  <ul>
    __ROWS__
  </ul>
</div>
""".replace("__ROWS__", ''.join(rows))
    dst.write_text(html_out, encoding="utf-8")


def write_index_spa_html(entries: List[dict], dst: Path) -> None:
    """Write a two-pane SPA-like index with sidebar + inline chat viewer."""
    payload = []
    for e in entries:
        metrics = e.get("metrics", {})
        payload.append({
            "name": e["name"],
            "file": e.get("chat_html_rel", ""),
            "raw": e.get("src_rel", ""),
            "metrics": metrics,
        })

    # Embed raw JSON into <script> tag. No HTML escaping here; keep valid JS.
    data_json = json.dumps(payload, ensure_ascii=False)

    template = r"""
<!doctype html>
<meta charset="utf-8">
<title>Scenario Transcripts</title>
<style>
:root { --bg:#f6f7f9; --panel:#ffffff; --border:#e5e7eb; --muted:#6b7280; --primary:#1f2937; --accent:#eef2ff; }
* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; background: var(--bg); color: var(--primary); }
.app { display: grid; grid-template-columns: 320px 1fr; height: 100vh; }
.sidebar { background: var(--panel); border-right: 1px solid var(--border); display: flex; flex-direction: column; min-width: 280px; }
.sidebar header { padding: 14px 16px; font-weight: 600; border-bottom: 1px solid var(--border); }
.search { padding: 10px 12px; border-bottom: 1px solid var(--border); }
.search input { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; }
.list { overflow: auto; padding: 6px; }
.item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 8px; color: inherit; text-decoration: none; border: 1px solid transparent; margin: 4px 0; cursor: pointer; font-size: 13.5px; line-height: 1.25; }
.item:hover { background: #fafafa; border-color: var(--border); }
.item.active { background: var(--accent); border-color: #d1d9ff; }
.item .num { min-width: 26px; height: 22px; line-height: 22px; text-align: center; background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 6px; color: #374151; font-size: 12px; }
.item .name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item .stats { color: var(--muted); font-size: 12px; }
.main { display: flex; flex-direction: column; height: 100%; }
.topbar { padding: 12px 16px; border-bottom: 1px solid var(--border); background: var(--panel); display: flex; align-items: center; gap: 10px; }
.topbar .title { font-weight: 600; }
.topbar .meta { color: var(--muted); font-size: 12px; }
.viewer { overflow: auto; height: calc(100% - 49px); padding: 16px; }
.placeholder { color: var(--muted); padding: 24px; }
.badge { display:inline-block; font-size: 12px; background:#eef2ff; border:1px solid #d1d9ff; padding:2px 6px; border-radius: 6px; margin-left: 6px; }
/* file:// fallback via iframe */
#viewer iframe{width:100%;height:100%;border:0;background:#fff}
/* Chat bubble styles for embedded transcripts */
#viewer .wrap{max-width:900px;margin:0 auto}
#viewer .row{display:flex;flex-direction:column}
#viewer .bubble{max-width:740px;padding:12px 14px;border-radius:14px;margin:8px 0;line-height:1.5;white-space:pre-wrap}
#viewer .client{background:#fff;border:1px solid #e5e7eb;align-self:flex-end;margin-left:auto}
#viewer .assistant{background:#e8f0ff;border:1px solid #d1d9ff}
#viewer .meta{font-size:12px;color:#6b7280;margin:2px 0 0 4px}
</style>
<div class="app">
  <aside class="sidebar">
    <header>Сценарии <span id="count" class="count"></span></header>
    <div class="search"><input id="q" placeholder="Поиск по названию..."></div>
    <div id="list" class="list"></div>
  </aside>
  <section class="main">
    <div class="topbar"> 
      <div class="title" id="title">Выберите сценарий слева</div>
      <div class="meta" id="meta"></div>
    </div>
    <div id="viewer" class="viewer">
      <div class="placeholder">Кликните на сценарий слева — диалог откроется здесь без перезагрузки страницы.</div>
    </div>
  </section>
</div>
<script>
const DATA = __DATA_JSON__;
const USE_IFRAME = location.protocol === 'file:'; // fetch() often blocked for file://
const $ = sel => document.querySelector(sel);
const listEl = $('#list');
const titleEl = $('#title');
const metaEl = $('#meta');
const viewerEl = $('#viewer');
const qEl = $('#q');
const countEl = document.querySelector('#count');

function fmtStats(m) {
  if (!m) return '';
  const bits = [];
  if (m.steps != null) bits.push(`шагов: ${m.steps}`);
  if (m.tool_calls != null) bits.push(`вызовов тулзов: ${m.tool_calls}`);
  if (m.avg_turn_sec != null) bits.push(`средн. turn_sec: ${m.avg_turn_sec.toFixed(2)}`);
  return bits.join(' · ');
}

function updateCount(n) {
  const total = DATA.length;
  if (!countEl) return;
  countEl.textContent = (n === total) ? `— ${total}` : `— ${n}/${total}`;
}

function renderList(items) {
  listEl.innerHTML = '';
  items.forEach((it, idx) => {
    const a = document.createElement('a');
    a.className = 'item';
    a.href = `#${encodeURIComponent(it.file)}`;
    a.dataset.file = it.file;
    a.dataset.name = it.name;
    a.dataset.raw = it.raw || '';
    a.dataset.idx = idx;
    const stats = fmtStats(it.metrics);
    const display = (it.name || '').replace(/\.txt$/, '');
    const num = String(idx + 1).padStart(2, '0');
    a.innerHTML = `<span class=\"num\">${num}</span><div class=\"name\">${display}</div>${stats ? `<div class=\"meta stats\">${stats}</div>` : ''}`;
    a.addEventListener('click', (ev) => {
      ev.preventDefault();
      selectItem(a);
    });
    listEl.appendChild(a);
  });
  updateCount(items.length);
}

function clearActive() {
  listEl.querySelectorAll('.item.active').forEach(el => el.classList.remove('active'));
}

async function selectItem(a) {
  clearActive();
  a.classList.add('active');
  const file = a.dataset.file;
  const name = a.dataset.name;
  window.location.hash = encodeURIComponent(file);
  titleEl.textContent = name;
  const idx = Number(a.dataset.idx);
  const m = DATA[idx] && DATA[idx].metrics || null;
  const stats = fmtStats(m);
  const raw = a.dataset.raw;
  metaEl.innerHTML = `${stats ? stats + ' · ' : ''}<a href="${raw}" target="_blank">raw</a>`;
  await loadChat(file);
}

async function loadChat(path) {
  viewerEl.innerHTML = '<div class=\"placeholder\">Загрузка…</div>';
  if (USE_IFRAME) {
    viewerEl.innerHTML = `<iframe src="${path}"></iframe>`;
    return;
  }
  try {
    const res = await fetch(path, { cache: 'no-store' });
    const txt = await res.text();
    // Extract inner content of <div class="wrap">…</div>
    const parser = new DOMParser();
    const doc = parser.parseFromString(txt, 'text/html');
    const wrap = doc.querySelector('div.wrap');
    if (wrap) {
      viewerEl.innerHTML = '';
      viewerEl.appendChild(wrap);
    } else {
      viewerEl.innerHTML = txt;
    }
  } catch (e) {
    viewerEl.innerHTML = `<div class=\"placeholder\">Ошибка загрузки: ${e}</div>`;
  }
}

function applyFilter() {
  const q = (qEl.value || '').toLowerCase();
  const filtered = DATA.filter(it => it.name.toLowerCase().includes(q));
  renderList(filtered);
}

// init
renderList(DATA);
qEl.addEventListener('input', applyFilter);

// open from hash if present
if (location.hash) {
  const file = decodeURIComponent(location.hash.slice(1));
  const a = Array.from(listEl.querySelectorAll('.item')).find(el => el.dataset.file === file);
  if (a) selectItem(a);
}
</script>
"""
    html_out = template.replace("__DATA_JSON__", data_json)
    dst.write_text(html_out, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Convert technical logs to chat transcripts")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--glob", help="Glob pattern for input .txt files (e.g., logs/stress_tests/*.txt)")
    g.add_argument("--dir", help="Directory to scan for .txt logs")
    ap.add_argument("--labels", choices=["ru", "en", "es"], default="ru", help="Speaker labels language")
    ap.add_argument("--no-html", action="store_true", help="Skip HTML output")
    ap.add_argument("--no-text", action="store_true", help="Skip plain text output")
    ap.add_argument("--index", action="store_true", help="Write index.html in the folder (when using --dir or same parent)")
    args = ap.parse_args()

    inputs: List[Path] = []
    if args.glob:
        inputs = [Path(p) for p in sorted(Path().glob(args.glob))]
    elif args.dir:
        d = Path(args.dir)
        inputs = sorted([p for p in d.iterdir() if p.suffix == ".txt"]) if d.exists() else []
    else:
        # Default to stress_tests directory if present
        d = Path("logs/stress_tests")
        if d.exists():
            inputs = sorted([p for p in d.iterdir() if p.suffix == ".txt"]) 
        else:
            ap.error("Provide --glob or --dir; default logs/stress_tests not found")

    # Filter out already-converted chat text files
    inputs = [p for p in inputs if not p.name.endswith('.chat.txt')]

    if not inputs:
        print("No input .txt logs found")
        return

    entries = []
    for src in inputs:
        messages = parse_log_txt(src)
        base = src.stem
        chat_txt = src.with_name(base + ".chat.txt")
        chat_html = src.with_name(base + ".chat.html")
        if not args.no_text:
            write_chat_txt(messages, chat_txt, labels=args.labels)
        if not args.no_html:
            write_chat_html(messages, chat_html, title=src.name, labels=args.labels)

        entry = {
            "name": src.name,
            "src": str(src),
            "src_rel": src.name,
            "chat_html": str(chat_html),
            "chat_html_rel": chat_html.name,
        }
        mpath = find_metrics_for(src)
        if mpath is not None:
            entry["metrics"] = load_metrics_summary(mpath)
        entries.append(entry)

    # Write an index near the common parent if requested
    if args.index:
        parent = inputs[0].parent
        write_index_spa_html(entries, parent / "index.html")
        print(f"Index written: {parent / 'index.html'}")

    print(f"Processed {len(inputs)} log(s)")


if __name__ == "__main__":
    main()
