from pathlib import Path

def read_text(path: str, default: str = "") -> str:
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return default
