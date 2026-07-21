from __future__ import annotations

import discord
from discord.ext import commands

from storage import store


class CoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.action_handlers["bot.set_status"] = self._handle_set_status

    async def _handle_set_status(self, payload: dict) -> None:
        text = payload.get("text", "")

        def _do(data):
            data["settings"]["status_text"] = text or None
        store.mutate(_do)

        if text:
            await self.bot.change_presence(activity=discord.CustomActivity(name=text))
        else:
            await self.bot.change_presence(activity=None)
        store.append_live_feed(f"Bot-Status geändert: {text or '(entfernt)'}", category="system")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CoreCog(bot))
