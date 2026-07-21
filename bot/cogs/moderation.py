from __future__ import annotations

import datetime
import random
import string
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from storage import store

# Farben angelehnt an die Screenshots: rot = Strafe, gruen = Aufhebung,
# gold = Verwarnung.
COLOR_PUNISH = discord.Color.from_str("#ED4245")
COLOR_LIFT = discord.Color.from_str("#57F287")
COLOR_WARN = discord.Color.from_str("#FEE75C")


def _case_id() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=7))


def _responsible_text(moderator) -> str:
    if isinstance(moderator, discord.Member):
        role = moderator.top_role
        if role and role.name != "@everyone":
            return f"{moderator.mention} *({role.name})*"
        return moderator.mention
    return str(moderator)


async def _send_dm_embed(
    member: discord.Member,
    title: str,
    color: discord.Color,
    fields: list[tuple[str, str]],
) -> None:
    """Baut ein Embed im Stil der Screenshots: fette Labels als Liste im
    Description-Feld, farbiger Rahmen links, Footer mit Servername."""
    description = "\n".join(f"**{label}:** {value}" for label, value in fields)
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=f"Gesendet von {member.guild.name}")
    try:
        await member.send(embed=embed)
    except discord.Forbidden:
        pass


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.action_handlers["mod.kick"] = self._handle_kick_action
        bot.action_handlers["mod.ban"] = self._handle_ban_action

    async def _handle_kick_action(self, payload: dict) -> None:
        guild = self.bot.get_guild(payload["guild_id"])
        member = guild.get_member(payload["user_id"]) if guild else None
        if member:
            await self._do_kick(member, payload.get("actor", "Web"), payload.get("reason", ""))

    async def _handle_ban_action(self, payload: dict) -> None:
        guild = self.bot.get_guild(payload["guild_id"])
        member = guild.get_member(payload["user_id"]) if guild else None
        if member:
            await self._do_ban(member, payload.get("actor", "Web"), payload.get("reason", ""))

    def _log(self, guild_id: int, action: str, target: str, moderator: str, reason: str, case_id: str | None = None) -> None:
        def _do(data):
            data["moderation_log"].insert(0, {
                "id": uuid.uuid4().hex[:8],
                "case_id": case_id,
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

    # ---------- Kick / Ban (auch von Web-Aktionen genutzt) ----------

    async def _do_kick(self, member: discord.Member, moderator, reason: str) -> None:
        await _send_dm_embed(member, "Du wurdest gekickt", COLOR_PUNISH, [
            ("Grund", reason or "Kein Grund angegeben"),
            ("Verantwortlich", _responsible_text(moderator)),
        ])
        await member.kick(reason=reason or None)
        self._log(member.guild.id, "Kick", str(member), _responsible_text(moderator), reason)

    async def _do_ban(self, member: discord.Member, moderator, reason: str) -> None:
        await _send_dm_embed(member, "Du wurdest gebannt", COLOR_PUNISH, [
            ("Grund", reason or "Kein Grund angegeben"),
            ("Verantwortlich", _responsible_text(moderator)),
        ])
        await member.ban(reason=reason or None)
        self._log(member.guild.id, "Ban", str(member), _responsible_text(moderator), reason)

    @app_commands.command(name="kick", description="Kickt ein Mitglied")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, mitglied: discord.Member, grund: str = "") -> None:
        await self._do_kick(mitglied, interaction.user, grund)
        await interaction.response.send_message(f"{mitglied} wurde gekickt.", ephemeral=True)

    @app_commands.command(name="ban", description="Bannt ein Mitglied")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, mitglied: discord.Member, grund: str = "") -> None:
        await self._do_ban(mitglied, interaction.user, grund)
        await interaction.response.send_message(f"{mitglied} wurde gebannt.", ephemeral=True)

    # ---------- Timeout / Untimeout ----------

    @app_commands.command(name="timeout", description="Timeout fuer ein Mitglied (in Minuten)")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, mitglied: discord.Member, minuten: int, grund: str = "") -> None:
        await _send_dm_embed(mitglied, "Du wurdest stummgeschaltet", COLOR_PUNISH, [
            ("Grund", grund or "Kein Grund angegeben"),
            ("Dauer", f"{minuten} Minuten"),
            ("Verantwortlich", _responsible_text(interaction.user)),
        ])
        await mitglied.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=minuten), reason=grund or None)
        self._log(interaction.guild_id, f"Timeout ({minuten}m)", str(mitglied), _responsible_text(interaction.user), grund)
        await interaction.response.send_message(f"{mitglied} hat {minuten} Minuten Timeout.", ephemeral=True)

    @app_commands.command(name="untimeout", description="Hebt den Timeout eines Mitglieds auf")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, mitglied: discord.Member, grund: str = "") -> None:
        await mitglied.timeout(None, reason=grund or None)
        await _send_dm_embed(mitglied, "Du wurdest entstummt", COLOR_LIFT, [
            ("Grund", grund or "Kein Grund angegeben"),
            ("Verantwortlich", _responsible_text(interaction.user)),
        ])
        self._log(interaction.guild_id, "Untimeout", str(mitglied), _responsible_text(interaction.user), grund)
        await interaction.response.send_message(f"Timeout von {mitglied} aufgehoben.", ephemeral=True)

    # ---------- Warn / Unwarn ----------

    @app_commands.command(name="warn", description="Verwarnt ein Mitglied")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, mitglied: discord.Member, grund: str) -> None:
        case_id = _case_id()
        await _send_dm_embed(mitglied, f"Du wurdest verwarnt \u2013 Fall `{case_id}`", COLOR_WARN, [
            ("Grund", grund),
            ("Verantwortlich", _responsible_text(interaction.user)),
        ])
        self._log(interaction.guild_id, "Warn", str(mitglied), _responsible_text(interaction.user), grund, case_id=case_id)
        await interaction.response.send_message(f"{mitglied} wurde verwarnt (Fall `{case_id}`).", ephemeral=True)

    @app_commands.command(name="unwarn", description="Hebt eine Verwarnung anhand der Fall-ID auf")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unwarn(self, interaction: discord.Interaction, mitglied: discord.Member, fall_id: str, grund: str = "") -> None:
        await _send_dm_embed(mitglied, f"Verwarnung aufgehoben \u2013 Fall `{fall_id}`", COLOR_LIFT, [
            ("Grund", grund or "Kein Grund angegeben"),
            ("Verantwortlich", _responsible_text(interaction.user)),
        ])
        self._log(interaction.guild_id, "Unwarn", str(mitglied), _responsible_text(interaction.user), grund, case_id=fall_id)
        await interaction.response.send_message(f"Verwarnung `{fall_id}` von {mitglied} aufgehoben.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
