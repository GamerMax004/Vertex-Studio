"""
Zentrales Storage-Modul.

Bot und Web-Dashboard laufen im selben Prozess (siehe main.py), teilen sich
aber KEINEN gemeinsamen Speicher im RAM, weil das Web in einem eigenen
Thread läuft. Deshalb ist data.json die einzige "Quelle der Wahrheit".

Schreibzugriffe sind über ein Lock + Temp-Datei + os.replace abgesichert
(atomarer Write, kein kaputtes JSON bei parallelem Zugriff).

Kommunikation Web -> Bot läuft über die "actions_queue": Das Web hängt dort
Aktionen an (z.B. Ticket schließen), der Bot pollt die Queue alle paar
Sekunden (siehe bot/client.py) und führt sie auf Discord aus. Danach wird
der Eintrag entfernt und das Ergebnis (z.B. neuer Ticket-Status) direkt in
die jeweilige Sektion geschrieben.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DATA_PATH = Path(os.environ.get("VERTEX_DATA_PATH", Path(__file__).parent / "data.json"))

_lock = threading.RLock()

DEFAULT_DATA: dict[str, Any] = {
    "bot_status": {
        "online": False,
        "latency_ms": None,
        "version": "0.1.0",
        "started_at": None,
        "guild_count": 0,
    },
    "tickets": {},          # ticket_id -> {...}
    "moderation_log": [],   # Liste von Mod-Aktionen
    "live_feed": [],        # letzte Ereignisse, neueste zuerst, max 200
    "actions_queue": [],    # Aktionen von Web -> Bot, die noch ausgeführt werden müssen
    "discord_logs": [],     # Message-Delete/Edit/Ban/Kick-Events, max 500
    "role_panels": {},      # panel_id -> {channel_id, message_id, roles: [{role_id, label}]}
    "announcements": {},    # id -> {channel_id, content, send_at, repeat, sent}
    "tasks": {},            # id -> {content, due_at, channel_id, done}
    "backups": {},          # id -> {created_at, guild_id, path}
    "known_commands": [],   # vom Bot nach dem Sync befüllt, für die Slash-Command-Verwaltung
    "workflows": {},        # id -> {name, trigger: {type, ...}, actions: [...], enabled}
    "automations": {        # einfache Trigger-Aktion-Automatisierung statt Workflow-Editor
        "ticket_closed_message": "",
        "welcome_message": "",
        "welcome_channel_id": None,
        "boost_message": "",
        "boost_role_id": None,
    },
    "settings": {
        "guild_id": None,
        "disabled_commands": [],
        "status_text": None,
        "automod": {
            "enabled": False,
            "banned_words": [],
            "max_mentions": 5,
        },
        "ticket_category_id": None,
        "ticket_log_channel_id": None,
        "transcript_dir": "storage/transcripts",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_raw() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return json.loads(json.dumps(DEFAULT_DATA))  # deep copy
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            # Datei beschädigt -> nicht überschreiben, sondern laut scheitern.
            # Lieber ein sichtbarer Fehler als stiller Datenverlust.
            raise RuntimeError(f"data.json ist beschädigt: {DATA_PATH}")
    # fehlende Top-Level-Keys ergänzen (z.B. nach Update mit neuen Feldern)
    changed = False
    for key, default_value in DEFAULT_DATA.items():
        if key not in data:
            data[key] = json.loads(json.dumps(default_value))
            changed = True
    if changed:
        _write_raw(data)
    return data


def _write_raw(data: dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = DATA_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DATA_PATH)  # atomar auf allen unterstützten Plattformen


def load() -> dict[str, Any]:
    with _lock:
        return _read_raw()


def mutate(fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Lädt die Daten, wendet fn(data) an (in-place) und speichert atomar.
    Gibt die aktualisierten Daten zurück. Alle Schreibzugriffe sollten über
    diese Funktion laufen, damit kein Lost Update zwischen Bot und Web
    entsteht."""
    with _lock:
        data = _read_raw()
        fn(data)
        _write_raw(data)
        return data


def append_live_feed(text: str, category: str = "info") -> None:
    def _do(data: dict[str, Any]) -> None:
        data["live_feed"].insert(0, {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "category": category,
            "timestamp": now_iso(),
        })
        data["live_feed"] = data["live_feed"][:200]

    mutate(_do)


def enqueue_action(action_type: str, payload: dict[str, Any]) -> str:
    """Vom Web aufgerufen. Legt eine Aktion ab, die der Bot als nächstes
    ausführt. Gibt die action_id zurück."""
    action_id = uuid.uuid4().hex
    def _do(data: dict[str, Any]) -> None:
        data["actions_queue"].append({
            "id": action_id,
            "type": action_type,
            "payload": payload,
            "created_at": now_iso(),
            "status": "pending",
        })
    mutate(_do)
    return action_id


def pop_pending_actions() -> list[dict[str, Any]]:
    """Vom Bot aufgerufen. Holt alle offenen Aktionen und leert die Queue
    (die einzelnen Cogs sind dafür zuständig, sie danach korrekt
    abzuarbeiten und ggf. Fehler in live_feed zu protokollieren)."""
    result: list[dict[str, Any]] = []

    def _do(data: dict[str, Any]) -> None:
        result.extend(data["actions_queue"])
        data["actions_queue"] = []

    mutate(_do)
    return result
