#!/usr/bin/env python3
"""
שכבת אחסון פשוטה מבוססת קבצי JSON - אותו עיקרון כמו tenders/*.json בכלי
המקורי: בלי מסד נתונים, קל לבדוק ולערוך ידנית, מספיק לאימות ביקוש עם
כמה לקוחות ראשונים לפני שמשקיעים בתשתית כבדה יותר.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
CLIENTS_FILE = DATA_DIR / "clients.json"
JOBS_FILE = DATA_DIR / "jobs.json"

JOB_STATUSES = [
    "טיוטת הצעה",
    "הצעה נשלחה",
    "מתוזמן",
    "בביצוע",
    "הושלם",
    "שולם",
]


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, records: list[dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_clients() -> list[dict]:
    return _load(CLIENTS_FILE)


def get_client(client_id: str) -> dict | None:
    return next((c for c in list_clients() if c["id"] == client_id), None)


def add_client(name: str, phone: str, address: str = "") -> dict:
    clients = list_clients()
    client = {
        "id": str(uuid.uuid4()),
        "name": name,
        "phone": phone,
        "address": address,
        "created_at": _now(),
    }
    clients.append(client)
    _save(CLIENTS_FILE, clients)
    return client


def list_jobs() -> list[dict]:
    return _load(JOBS_FILE)


def add_job(client_id: str, description: str, trade: str, quote: dict) -> dict:
    jobs = list_jobs()
    job = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "description": description,
        "trade": trade,
        "quote": quote,
        "status": JOB_STATUSES[0],
        "scheduled_date": None,
        "created_at": _now(),
    }
    jobs.append(job)
    _save(JOBS_FILE, jobs)
    return job


def update_job(job_id: str, **fields) -> dict | None:
    jobs = list_jobs()
    for job in jobs:
        if job["id"] == job_id:
            job.update(fields)
            _save(JOBS_FILE, jobs)
            return job
    return None
