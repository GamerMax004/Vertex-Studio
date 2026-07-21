from __future__ import annotations

import discord
from discord.ext import commands

from storage import store


class AutomationsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        automations = store.load()["automations"]
        channel_id = automations.get("welcome_channel_id")
        message = automations.get("welcome_message")
        if channel_id and message:
            channel = member.guild.get_channel(channel_id)
            if channel:
                await channel.send(message.replace("{user}", member.mention))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        automations = store.load()["automations"]
        was_boosting = before.premium_since is not None
        is_boosting = after.premium_since is not None
        if is_boosting and not was_boosting:
            role_id = automations.get("boost_role_id")
            message = automations.get("boost_message")
            if role_id:
                role = after.guild.get_role(role_id)
                if role:
                    await after.add_roles(role, reason="Server Boost")
            if message:
                try:
                    await after.send(message)
                except discord.Forbidden:
                    pass
            store.append_live_feed(f"{after} boostet den Server", category="boost")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutomationsCog(bot))
