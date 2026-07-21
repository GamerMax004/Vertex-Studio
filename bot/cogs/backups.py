from __future__ import annotations

import json
import uuid
from pathlib import Path

from discord.ext import commands

from storage import store

BACKUP_DIR = Path(__file__).parent.parent.parent / "storage" / "backups"


class BackupsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.action_handlers["backup.create"] = self._handle_create

    async def _handle_create(self, payload: dict) -> None:
        guild = self.bot.get_guild(payload["guild_id"])
        if guild is None:
            store.append_live_feed("Backup fehlgeschlagen: Server nicht gefunden", category="error")
            return

        snapshot = {
            "guild_id": guild.id,
            "guild_name": guild.name,
            "roles": [
                {"id": r.id, "name": r.name, "color": str(r.color), "permissions": r.permissions.value}
                for r in guild.roles
            ],
            "channels": [
                {"id": c.id, "name": c.name, "type": str(c.type), "category": c.category.name if c.category else None}
                for c in guild.channels
            ],
        }

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_id = uuid.uuid4().hex[:8]
        path = BACKUP_DIR / f"{backup_id}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        def _do(data):
            data["backups"][backup_id] = {
                "id": backup_id,
                "guild_id": guild.id,
                "guild_name": guild.name,
                "created_at": store.now_iso(),
                "path": str(path),
            }
        store.mutate(_do)
        store.append_live_feed(f"Backup erstellt für {guild.name}", category="backup")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BackupsCog(bot))
