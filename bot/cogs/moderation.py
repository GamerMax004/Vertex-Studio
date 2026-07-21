from __future__ import annotations

import uuid

import discord
from discord import app_commands
from discord.ext import commands

from storage import store


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.action_handlers["mod.kick"] = self._handle_kick_action
        bot.action_handlers["mod.ban"] = self._handle_ban_action

    async def _handle_kick_action(self, payload: dict) -> None:
        guild = self.bot.get_guild(payload["guild_id"])
        member = guild.get_member(payload["user_id"]) if guild else None
        if member:
            await member.kick(reason=payload.get("reason"))
            self._log(guild.id, "Kick", str(member), payload.get("actor", "Web"), payload.get("reason", ""))

    async def _handle_ban_action(self, payload: dict) -> None:
        guild = self.bot.get_guild(payload["guild_id"])
        member = guild.get_member(payload["user_id"]) if guild else None
        if member:
            await member.ban(reason=payload.get("reason"))
            self._log(guild.id, "Ban", str(member), payload.get("actor", "Web"), payload.get("reason", ""))

    def _log(self, guild_id: int, action: str, target: str, moderator: str, reason: str) -> None:
        def _do(data):
            data["moderation_log"].insert(0, {
                "id": uuid.uuid4().hex[:8],
                "guild_id": guild_id,
                "action": action,
                "target": target,
                "moderator": moderator,
                "reason": reason or "Kein Grund angegeben",
                "timestamp": store.now_iso(),
            })
            data["moderation_log"] = data["moderation_log"][:500]
        store.mutate(_do)
        store.append_live_feed(f"{action}: {target} von {moderator} ({reason or 'kein Grund'})", category="moderation")

    @app_commands.command(name="kick", description="Kickt ein Mitglied")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, mitglied: discord.Member, grund: str = "") -> None:
        await mitglied.kick(reason=grund or None)
        self._log(interaction.guild_id, "Kick", str(mitglied), str(interaction.user), grund)
        await interaction.response.send_message(f"{mitglied} wurde gekickt.", ephemeral=True)

    @app_commands.command(name="ban", description="Bannt ein Mitglied")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, mitglied: discord.Member, grund: str = "") -> None:
        await mitglied.ban(reason=grund or None)
        self._log(interaction.guild_id, "Ban", str(mitglied), str(interaction.user), grund)
        await interaction.response.send_message(f"{mitglied} wurde gebannt.", ephemeral=True)

    @app_commands.command(name="timeout", description="Timeout für ein Mitglied (in Minuten)")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, mitglied: discord.Member, minuten: int, grund: str = "") -> None:
        import datetime
        await mitglied.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=minuten), reason=grund or None)
        self._log(interaction.guild_id, f"Timeout ({minuten}m)", str(mitglied), str(interaction.user), grund)
        await interaction.response.send_message(f"{mitglied} hat {minuten} Minuten Timeout.", ephemeral=True)

    @app_commands.command(name="warn", description="Verwarnt ein Mitglied")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, mitglied: discord.Member, grund: str) -> None:
        self._log(interaction.guild_id, "Warn", str(mitglied), str(interaction.user), grund)
        await interaction.response.send_message(f"{mitglied} wurde verwarnt.", ephemeral=True)
        try:
            await mitglied.send(f"Du wurdest verwarnt: {grund}")
        except discord.Forbidden:
            pass

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
