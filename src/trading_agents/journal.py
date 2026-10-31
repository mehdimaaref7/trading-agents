"""Journal append-only de chaque décision (JSON lines), pour l'audit et le validateur."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _path() -> Path:
    return Path(os.environ.get("TRADING_JOURNAL", "logs/journal.jsonl"))


def log_event(kind: str, **data) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **data}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
