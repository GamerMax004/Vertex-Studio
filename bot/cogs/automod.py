from __future__ import annotations

import discord
from discord.ext import commands

from storage import store


class AutomodCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        settings = store.load()["settings"].get("automod", {})
        if not settings.get("enabled"):
            return
        if message.author.guild_permissions.manage_messages:
            return

        reason = None
        content_lower = message.content.lower()
        banned_words = settings.get("banned_words", [])
        if any(word.lower() in content_lower for word in banned_words if word):
            reason = "verbotenes Wort"

        max_mentions = settings.get("max_mentions", 5)
        if len(message.mentions) > max_mentions:
            reason = "Mass Mention"

        if reason:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            store.append_live_feed(f"Automod: Nachricht von {message.author} entfernt ({reason})", category="automod")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutomodCog(bot))
