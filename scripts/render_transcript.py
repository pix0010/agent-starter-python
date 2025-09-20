#!/usr/bin/env python3
import sys
import json
import html
from pathlib import Path

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f6f7f9;margin:0;padding:20px}
.wrap{max-width:840px;margin:0 auto}
.bubble{max-width:600px;padding:12px 14px;border-radius:14px;margin:10px 0;line-height:1.4;white-space:pre-wrap}
.user{background:#fff;border:1px solid #e5e7eb;align-self:flex-end;margin-left:auto}
.agent{background:#e8f0ff;border:1px solid #d1d9ff}
.meta{font-size:12px;color:#6b7280;margin:2px 0 0 4px}
.row{display:flex;flex-direction:column}
h1{font-size:18px;margin:0 0 12px 0}
"""

def extract_messages(history: dict):
    """Пытаемся достать плоский чат из session.history.to_dict()."""
    items = history.get("items", [])
    for it in items:
        role = it.get("role") or it.get("participant", {}).get("role")
        text_parts = []
        for content in it.get("content", []) or []:
            text_value = content.get("text") or content.get("value") or content.get("content")
            if isinstance(text_value, str) and text_value.strip():
                text_parts.append(text_value.strip())
        text = " ".join(text_parts).strip()
        if text:
            yield role, text

def render_html(messages):
    out = ['<!doctype html><meta charset="utf-8"><title>Transcript</title>',
           f"<style>{CSS}</style>", '<div class="wrap"><h1>Transcript</h1>']
    for role, text in messages:
        escaped = html.escape(text)
        bubble_class = "user" if role == "user" else "agent"
        out.append(
            f'<div class="row"><div class="bubble {bubble_class}">{escaped}</div><div class="meta">{role}</div></div>'
        )
    out.append("</div>")
    return "\n".join(out)

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/render_transcript.py logs/transcript_*.json")
        sys.exit(1)
    src = Path(sys.argv[1])
    dst = src.with_suffix(".html")
    history = json.loads(src.read_text(encoding="utf-8"))
    html_out = render_html(list(extract_messages(history)))
    dst.write_text(html_out, encoding="utf-8")
    print(f"Written: {dst}")

if __name__ == "__main__":
    main()
