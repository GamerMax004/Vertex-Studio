from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for

from storage import store

BACKUP_DIR = Path(__file__).parent.parent / "storage" / "backups"
TRANSCRIPT_DIR = Path(__file__).parent.parent / "storage" / "transcripts"

# Module, die es schon gibt bzw. die als "bald verfügbar" im Nav auftauchen.
# Reihenfolge = Reihenfolge im Sidebar-Menü.
NAV_MODULES = [
    {"key": "dashboard", "label": "Dashboard", "ready": True},
    {"key": "tickets", "label": "Tickets", "ready": True},
    {"key": "moderation", "label": "Moderation", "ready": True},
    {"key": "automod", "label": "Automod", "ready": True},
    {"key": "roles", "label": "Rollenverwaltung", "ready": True},
    {"key": "embeds", "label": "Embed Builder", "ready": True},
    {"key": "announcements", "label": "Announcements", "ready": True},
    {"key": "commands", "label": "Slash-Commands", "ready": True, "endpoint": "commands_page"},
    {"key": "logs", "label": "Discord-Logs", "ready": True},
    {"key": "analytics", "label": "Analytics", "ready": True},
    {"key": "tasks", "label": "Aufgaben", "ready": True, "endpoint": "tasks_page"},
    {"key": "backups", "label": "Backup-Center", "ready": True},
    {"key": "files", "label": "Dateimanager", "ready": True},
    {"key": "console", "label": "Live-Konsole", "ready": True},
    {"key": "workflows", "label": "Workflows", "ready": True},
    {"key": "settings", "label": "Server-Einstellungen", "ready": True, "endpoint": "settings_page"},
]


def create_app() -> Flask:
    app = Flask(__name__)

    @app.context_processor
    def inject_nav():
        return {"nav_modules": NAV_MODULES}

    @app.get("/")
    def dashboard():
        data = store.load()
        tickets = data["tickets"].values()
        summary = {
            "offen": sum(1 for t in tickets if t["status"] == "offen"),
            "archiviert": sum(1 for t in tickets if t["status"] == "archiviert"),
        }
        return render_template(
            "dashboard.html",
            active="dashboard",
            bot_status=data["bot_status"],
            live_feed=data["live_feed"][:20],
            ticket_summary=summary,
        )

    @app.get("/tickets")
    def tickets():
        data = store.load()
        alle_tickets = sorted(
            data["tickets"].values(), key=lambda t: t["created_at"], reverse=True
        )
        return render_template("tickets.html", active="tickets", tickets=alle_tickets)

    @app.post("/tickets/<ticket_id>/close")
    def close_ticket(ticket_id: str):
        actor = request.form.get("actor", "Dashboard")
        store.enqueue_action("ticket.close", {"ticket_id": ticket_id, "actor": actor})
        return redirect(url_for("tickets"))

    @app.get("/api/live-feed")
    def api_live_feed():
        data = store.load()
        return jsonify(data["live_feed"][:20])

    # ---------- Moderation ----------

    @app.get("/moderation")
    def moderation():
        data = store.load()
        return render_template("moderation.html", active="moderation", log=data["moderation_log"][:100])

    @app.post("/moderation/action")
    def moderation_action():
        action_type = request.form["type"]  # "mod.kick" oder "mod.ban"
        store.enqueue_action(action_type, {
            "guild_id": int(request.form["guild_id"]),
            "user_id": int(request.form["user_id"]),
            "reason": request.form.get("reason", ""),
            "actor": "Dashboard",
        })
        return redirect(url_for("moderation"))

    # ---------- Automod ----------

    @app.get("/automod")
    def automod():
        data = store.load()
        return render_template("automod.html", active="automod", automod=data["settings"]["automod"])

    @app.post("/automod")
    def automod_save():
        enabled = request.form.get("enabled") == "on"
        words = [w.strip() for w in request.form.get("banned_words", "").split(",") if w.strip()]
        max_mentions = int(request.form.get("max_mentions", 5) or 5)

        def _do(data):
            data["settings"]["automod"] = {
                "enabled": enabled, "banned_words": words, "max_mentions": max_mentions,
            }
        store.mutate(_do)
        return redirect(url_for("automod"))

    # ---------- Rollenverwaltung ----------

    @app.get("/roles")
    def roles():
        data = store.load()
        return render_template("roles.html", active="roles", panels=data["role_panels"])

    # Panels selbst werden per /rolepanel-Slash-Command im Discord erstellt
    # (Kanal- und Rollenauswahl ist dort nativ und braucht keine eigene UI).

    # ---------- Embed Builder ----------

    @app.get("/embeds")
    def embeds():
        return render_template("embeds.html", active="embeds")

    @app.post("/embeds")
    def embeds_send():
        store.enqueue_action("embed.send", {
            "channel_id": int(request.form["channel_id"]),
            "title": request.form.get("title", ""),
            "description": request.form.get("description", ""),
            "color": request.form.get("color", ""),
            "footer": request.form.get("footer", ""),
            "image_url": request.form.get("image_url", ""),
            "thumbnail_url": request.form.get("thumbnail_url", ""),
        })
        return redirect(url_for("embeds"))

    # ---------- Announcements ----------

    @app.get("/announcements")
    def announcements():
        data = store.load()
        items = sorted(data["announcements"].values(), key=lambda a: a["send_at"])
        return render_template("announcements.html", active="announcements", announcements=items)

    @app.post("/announcements")
    def announcements_create():
        ann_id = uuid.uuid4().hex[:8]

        def _do(data):
            data["announcements"][ann_id] = {
                "id": ann_id,
                "channel_id": int(request.form["channel_id"]),
                "content": request.form["content"],
                "send_at": request.form["send_at"],  # ISO-Format vom <input type=datetime-local>
                "repeat": request.form.get("repeat", "once"),
                "sent": False,
            }
        store.mutate(_do)
        return redirect(url_for("announcements"))

    # ---------- Slash-Command-Verwaltung ----------

    @app.get("/commands")
    def commands_page():
        data = store.load()
        disabled = set(data["settings"].get("disabled_commands", []))
        cmds = [{"name": c, "enabled": c not in disabled} for c in data.get("known_commands", [])]
        return render_template("commands.html", active="commands", commands=cmds)

    @app.post("/commands/<name>/toggle")
    def commands_toggle(name: str):
        def _do(data):
            disabled = set(data["settings"].get("disabled_commands", []))
            if name in disabled:
                disabled.discard(name)
            else:
                disabled.add(name)
            data["settings"]["disabled_commands"] = sorted(disabled)
        store.mutate(_do)
        return redirect(url_for("commands_page"))

    # ---------- Discord-Logs ----------

    @app.get("/logs")
    def logs():
        data = store.load()
        return render_template("logs.html", active="logs", logs=data["discord_logs"][:200])

    # ---------- Analytics ----------

    @app.get("/analytics")
    def analytics():
        data = store.load()
        tickets = list(data["tickets"].values())
        mod_log = data["moderation_log"]
        stats = {
            "tickets_total": len(tickets),
            "tickets_offen": sum(1 for t in tickets if t["status"] == "offen"),
            "mod_aktionen": len(mod_log),
            "mod_kicks": sum(1 for m in mod_log if m["action"] == "Kick"),
            "mod_bans": sum(1 for m in mod_log if m["action"] == "Ban"),
            "mod_warns": sum(1 for m in mod_log if m["action"] == "Warn"),
            "discord_logs": len(data["discord_logs"]),
        }
        return render_template("analytics.html", active="analytics", stats=stats)

    # ---------- Aufgaben ----------

    @app.get("/tasks")
    def tasks_page():
        data = store.load()
        items = sorted(data["tasks"].values(), key=lambda t: t["due_at"])
        return render_template("tasks.html", active="tasks", tasks=items)

    @app.post("/tasks")
    def tasks_create():
        task_id = uuid.uuid4().hex[:8]

        def _do(data):
            data["tasks"][task_id] = {
                "id": task_id,
                "content": request.form["content"],
                "due_at": request.form["due_at"],
                "channel_id": int(request.form["channel_id"]) if request.form.get("channel_id") else None,
                "done": False,
            }
        store.mutate(_do)
        return redirect(url_for("tasks_page"))

    # ---------- Backup-Center ----------

    @app.get("/backups")
    def backups():
        data = store.load()
        items = sorted(data["backups"].values(), key=lambda b: b["created_at"], reverse=True)
        return render_template("backups.html", active="backups", backups=items)

    @app.post("/backups/create")
    def backups_create():
        store.enqueue_action("backup.create", {"guild_id": int(request.form["guild_id"])})
        return redirect(url_for("backups"))

    @app.get("/backups/<backup_id>/download")
    def backups_download(backup_id: str):
        data = store.load()
        backup = data["backups"].get(backup_id)
        if not backup:
            abort(404)
        return send_file(backup["path"], as_attachment=True, download_name=f"backup-{backup_id}.json")

    # ---------- Dateimanager ----------

    @app.get("/files")
    def files():
        transcripts = sorted(TRANSCRIPT_DIR.glob("*.txt")) if TRANSCRIPT_DIR.exists() else []
        return render_template("files.html", active="files", transcripts=[f.name for f in transcripts])

    @app.get("/files/transcripts/<name>")
    def files_download_transcript(name: str):
        path = TRANSCRIPT_DIR / name
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=True)

    # ---------- Live-Konsole ----------

    @app.get("/console")
    def console():
        data = store.load()
        return render_template("console.html", active="console", live_feed=data["live_feed"][:100])

    # ---------- Server-Einstellungen ----------

    # ---------- Workflows ----------

    @app.get("/workflows")
    def workflows():
        data = store.load()
        items = sorted(data["workflows"].values(), key=lambda w: w["name"])
        return render_template("workflows.html", active="workflows", workflows=items)

    @app.post("/workflows")
    def workflows_create():
        import json as _json
        wf_id = uuid.uuid4().hex[:8]
        trigger = {"type": request.form["trigger_type"]}
        if request.form["trigger_type"] == "message_keyword":
            trigger["keyword"] = request.form.get("trigger_keyword", "")
        actions = _json.loads(request.form.get("actions_json", "[]"))

        def _do(data):
            data["workflows"][wf_id] = {
                "id": wf_id,
                "name": request.form["name"],
                "trigger": trigger,
                "actions": actions,
                "enabled": True,
            }
        store.mutate(_do)
        return redirect(url_for("workflows"))

    @app.post("/workflows/<wf_id>/toggle")
    def workflows_toggle(wf_id: str):
        def _do(data):
            if wf_id in data["workflows"]:
                data["workflows"][wf_id]["enabled"] = not data["workflows"][wf_id]["enabled"]
        store.mutate(_do)
        return redirect(url_for("workflows"))

    @app.post("/workflows/<wf_id>/delete")
    def workflows_delete(wf_id: str):
        def _do(data):
            data["workflows"].pop(wf_id, None)
        store.mutate(_do)
        return redirect(url_for("workflows"))

    @app.get("/settings")
    def settings_page():
        data = store.load()
        return render_template("settings.html", active="settings", settings=data["settings"], automations=data["automations"])

    @app.post("/settings")
    def settings_save():
        status_text = request.form.get("status_text", "").strip()

        def _do(data):
            data["settings"]["status_text"] = status_text or None
            data["automations"]["welcome_channel_id"] = int(request.form["welcome_channel_id"]) if request.form.get("welcome_channel_id") else None
            data["automations"]["welcome_message"] = request.form.get("welcome_message", "")
            data["automations"]["boost_role_id"] = int(request.form["boost_role_id"]) if request.form.get("boost_role_id") else None
            data["automations"]["boost_message"] = request.form.get("boost_message", "")
        store.mutate(_do)

        if status_text:
            store.enqueue_action("bot.set_status", {"text": status_text})
        return redirect(url_for("settings_page"))

    @app.get("/health")
    def health():
        data = store.load()
        tickets = data["tickets"].values()
        return jsonify({
            "status": "healthy",
            "bot_online": data["bot_status"]["online"],
            "version": data["bot_status"]["version"],
            "latency_ms": data["bot_status"]["latency_ms"],
            "guild_count": data["bot_status"]["guild_count"],
            "offene_tickets": sum(1 for t in tickets if t["status"] == "offen"),
            "timestamp": store.now_iso(),
        })

    return app
