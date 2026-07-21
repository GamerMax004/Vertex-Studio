"""
Workflow-Engine.

Ersetzt einen vollen visuellen n8n-artigen Canvas-Editor durch eine simple,
aber echte Pipeline: Ein Trigger (Ereignis) löst eine geordnete Liste von
Aktionen aus. Definiert wird das im Dashboard unter /workflows.

Unterstützte Trigger:
  member_join      – Mitglied tritt bei
  member_boost     – Mitglied boostet den Server
  ticket_closed     – Ticket wurde geschlossen (wird von tickets.py ausgelöst)
  message_keyword   – Nachricht enthält ein bestimmtes Wort

Unterstützte Aktionen:
  send_message  {channel_id, content}
  add_role      {role_id}
  remove_role   {role_id}
  send_embed    {channel_id, title, description, color}

In content/description können Platzhalter genutzt werden:
  {user}, {user_id}, {guild}, {ticket_id}
"""

from __future__ import annotations

import discord
from discord.ext import commands

from storage import store


def _fill(text: str, context: dict) -> str:
    if not text:
        return text
    for key, value in context.items():
        text = text.replace(f"{{{key}}}", str(value))
    return text


class WorkflowsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def trigger(self, event_type: str, guild: discord.Guild, member: discord.Member | None = None, extra: dict | None = None) -> None:
        extra = extra or {}
        workflows = store.load()["workflows"]
        context = {
            "user": str(member) if member else "",
            "user_mention": member.mention if member else "",
            "user_id": member.id if member else "",
            "guild": guild.name if guild else "",
            **extra,
        }
        for wf in workflows.values():
            if not wf.get("enabled", True):
                continue
            trig = wf["trigger"]
            if trig["type"] != event_type:
                continue
            if event_type == "message_keyword":
                if trig.get("keyword", "").lower() not in extra.get("message_content", "").lower():
                    continue

            for action in wf.get("actions", []):
                await self._run_action(action, guild, member, context)

            store.append_live_feed(f"Workflow '{wf['name']}' ausgelöst ({event_type})", category="workflow")

    async def _run_action(self, action: dict, guild: discord.Guild, member: discord.Member | None, context: dict) -> None:
        try:
            if action["type"] == "send_message":
                channel = guild.get_channel(int(action["channel_id"]))
                if channel:
                    await channel.send(_fill(action.get("content", ""), context))

            elif action["type"] == "add_role" and member:
                role = guild.get_role(int(action["role_id"]))
                if role:
                    await member.add_roles(role, reason="Workflow")

            elif action["type"] == "remove_role" and member:
                role = guild.get_role(int(action["role_id"]))
                if role:
                    await member.remove_roles(role, reason="Workflow")

            elif action["type"] == "send_embed":
                channel = guild.get_channel(int(action["channel_id"]))
                if channel:
                    color = action.get("color", "")
                    embed = discord.Embed(
                        title=_fill(action.get("title", ""), context) or None,
                        description=_fill(action.get("description", ""), context) or None,
                        color=int(color.lstrip("#"), 16) if color else discord.Color.default(),
                    )
                    await channel.send(embed=embed)
        except Exception as exc:  # noqa: BLE001
            store.append_live_feed(f"Workflow-Aktion fehlgeschlagen ({action.get('type')}): {exc}", category="error")

    # ---------- Trigger-Quellen ----------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self.trigger("member_join", member.guild, member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.premium_since and not before.premium_since:
            await self.trigger("member_boost", after.guild, after)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        await self.trigger(
            "message_keyword",
            message.guild,
            message.author if isinstance(message.author, discord.Member) else None,
            {"message_content": message.content},
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorkflowsCog(bot))
