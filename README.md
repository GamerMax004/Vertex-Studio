# Vertex Studio Bot Panel

Discord-Bot + Web-Dashboard in einem Service. Kein separates API-/DB-System –
alle Daten liegen in `storage/data.json`, geschützt durch atomare Writes.

## Architektur

```
main.py            Startet Web (Thread) + Bot (Hauptthread)
bot/client.py       Bot-Grundgerüst, lädt Cogs, pflegt bot_status
bot/cogs/tickets.py Ticket-Modul (vollständig, als Referenz für weitere Module)
web/app.py          Flask-Dashboard (Routen, Health-Endpoint)
web/templates/       Server-gerenderte Seiten
storage/store.py    Gemeinsamer JSON-Speicher + Actions-Queue
storage/data.json    Wird beim ersten Start automatisch angelegt
```

**Bot ↔ Web ohne API/Websocket:** Der Bot schreibt seinen Status und Ereignisse
direkt in `data.json`. Das Web liest bei jedem Request daraus (Dashboard) bzw.
pollt alle 5s (`/api/live-feed`, siehe `dashboard.js`). Aktionen, die der Bot
auf Discord ausführen muss (z.B. "Ticket schließen" aus dem Dashboard), landet
das Web in `actions_queue`; der Bot pollt die Queue alle 5s ab
(`TicketsCog.poll_actions`).

## Lokal starten

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # DISCORD_TOKEN eintragen
python main.py
```

Dashboard läuft dann auf http://localhost:8081

## Deployment auf Render

1. Neuer **Web Service**, Build Command `pip install -r requirements.txt`,
   Start Command `python main.py` (steht auch im `Procfile`).
2. Environment Variable `DISCORD_TOKEN` setzen.
3. `storage/data.json` liegt standardmäßig im Repo-Verzeichnis. Für dauerhafte
   Daten über Deploys hinweg einen **Persistent Disk** an `storage/` mounten
   (sonst geht der Inhalt bei jedem Deploy verloren, weil Render das
   Dateisystem neu aufsetzt).
4. `/health` ist der Keep-Alive-Endpoint (gleiches Muster wie dein bisheriges
   `SafetyGuard`-Setup) – dort einen Uptime-Monitor draufsetzen.

## Discord-Setup

- `/ticket-panel` in einem Kanal ausführen, um das Panel zu posten.
- `/ticket-setup` einmalig ausführen, um Ticket-Kategorie und Log-Kanal
  festzulegen.
- `/rolepanel` erstellt ein Button-Role-Panel mit bis zu 5 Rollen.
- `/kick`, `/ban`, `/timeout`, `/warn` für Moderation.

## KI-Assistent (Groq)

Ticket-Zusammenfassungen beim Schließen sind optional und nur aktiv, wenn
die Umgebungsvariable `GROQ_API_KEY` gesetzt ist (kostenloser Key unter
console.groq.com). Ohne Key passiert einfach nichts – kein Fehler.
Zusätzlich `pip install groq` nicht vergessen (steht in `requirements.txt`).

## Workflows

Unter `/workflows` im Dashboard lassen sich Trigger→Aktionen-Ketten visuell
zusammenklicken (Ersatz für einen vollen n8n-artigen Canvas-Editor):

- Trigger: Mitglied tritt bei, Mitglied boostet, Ticket geschlossen,
  Nachricht enthält Schlüsselwort
- Aktionen: Nachricht senden, Rolle geben/entfernen, Embed senden
- Platzhalter in Texten: `{user}`, `{user_mention}`, `{ticket_id}`

Die einfachen Schnell-Einstellungen (Willkommensnachricht, Boost-Rolle)
unter `/settings` laufen weiterhin separat über `bot/cogs/automations.py` –
für simple Fälle reicht das oft, ohne extra einen Workflow zu bauen.

## Weitere Module ergänzen

Jedes neue Modul (Moderation, Automod, Rollen, Embed Builder, Logs,
Analytics, ...) folgt demselben Muster wie `tickets.py`:

1. Neue Datei `bot/cogs/<modul>.py`, in `bot/client.py` unter `INITIAL_COGS`
   eintragen.
2. Eigene Sektion in `storage/store.py::DEFAULT_DATA` ergänzen.
3. Aktionen vom Web über `store.enqueue_action(...)` einreihen, im Cog per
   `@tasks.loop` abholen (wie `TicketsCog.poll_actions`).
4. Neue Route in `web/app.py` + Template + Eintrag in `NAV_MODULES`
   (`ready: True` setzen, sobald fertig).

Sag mir einfach, welches Modul als nächstes drankommt.
