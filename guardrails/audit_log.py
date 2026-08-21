"""Append-only JSONL audit trail for every AI interaction — RFP requires
"logging, traceability and auditability of AI-generated outputs" as a scored
deliverable, and it's also just the right debugging tool: when an answer
looks wrong later, this is how you reconstruct exactly what was retrieved
and what the model was told."""
import json
from datetime import datetime, timezone
from pathlib import Path

from config import AUDIT_LOG_PATH


def log_interaction(record: dict):
    path = Path(AUDIT_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **record}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
