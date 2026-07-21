from __future__ import annotations

import discord
from discord.ext import commands

from storage import store


class LogsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _log(self, event: str, detail: str) -> None:
        def _do(data):
            data["discord_logs"].insert(0, {
                "event": event,
                "detail": detail,
                "timestamp": store.now_iso(),
            })
            data["discord_logs"] = data["discord_logs"][:500]
        store.mutate(_do)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        self._log("message_delete", f"{message.author} in #{getattr(message.channel, 'name', message.channel.id)}: {message.content[:200]}")

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or before.content == after.content:
            return
        self._log("message_edit", f"{before.author} in #{getattr(before.channel, 'name', before.channel.id)}: '{before.content[:100]}' -> '{after.content[:100]}'")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        self._log("member_join", f"{member} ist beigetreten")
        store.append_live_feed(f"{member} ist beigetreten", category="member")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        self._log("member_remove", f"{member} hat den Server verlassen")
        store.append_live_feed(f"{member} hat den Server verlassen", category="member")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        self._log("member_ban", f"{user} wurde gebannt")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LogsCog(bot))
