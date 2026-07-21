"""
Ticket-Modul.

Ablauf:
  1. Ein Admin postet mit /ticket-panel ein Panel mit "Ticket erstellen"-Button.
  2. Klick erstellt einen privaten Kanal, legt einen Eintrag in data.json an
     und postet dort eine Nachricht mit "Ticket schließen"-Button.
  3. Schließen (per Discord-Button ODER per Web-Dashboard-Aktion aus der
     actions_queue) erzeugt ein Transcript, archiviert den Kanal-Inhalt und
     löscht den Kanal.

Alle Buttons nutzen DynamicItem mit custom_id-Regex, damit sie auch nach
einem Bot-Neustart noch funktionieren (kein In-Memory-View-Cache nötig).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from storage import store


async def _summarize_transcript(transcript_text: str) -> str | None:
    """Fasst ein Ticket-Transcript zusammen, aber NUR wenn GROQ_API_KEY
    gesetzt ist. Der Key wird bewusst nicht in data.json gespeichert
    (Secret), sondern nur als Umgebungsvariable gelesen. Ohne Key macht
    dieses Modul einfach nichts – kein Fehler, keine Kosten."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or not transcript_text.strip():
        return None
    try:
        from groq import AsyncGroq
    except ImportError:
        return None
    try:
        client = AsyncGroq(api_key=api_key)
        response = await client.chat.completions.create(
            # Aktuelles Groq-Flaggschiff-Modell; ggf. anpassen, falls Groq
            # das Modell-Lineup ändert (siehe console.groq.com/docs/models).
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Fasse dieses Support-Ticket in 2-3 Sätzen auf Deutsch zusammen."},
                {"role": "user", "content": transcript_text[:6000]},
            ],
            max_tokens=200,
        )
        return response.choices[0].message.content
    except Exception:
        return None


def _fmt_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class TicketPanelView(discord.ui.LayoutView):
    """Statisches Panel, das in einem Kanal gepostet wird."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        container = discord.ui.Container(
            discord.ui.TextDisplay("# Support"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                "Erstelle ein Ticket, wenn du Unterstützung vom Team brauchst. "
                "Ein privater Kanal wird für dich angelegt."
            ),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
            discord.ui.ActionRow(CreateTicketButton()),
        )
        self.add_item(container)


class CreateTicketButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"vertex:ticket:create",
):
    def __init__(self) -> None:
        super().__init__(
            discord.ui.Button(
                label="Ticket erstellen",
                style=discord.ButtonStyle.secondary,
                custom_id="vertex:ticket:create",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: TicketsCog = interaction.client.get_cog("TicketsCog")  # type: ignore
        await cog.create_ticket(interaction)


class CloseTicketButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"vertex:ticket:close:(?P<ticket_id>[a-zA-Z0-9]+)",
):
    def __init__(self, ticket_id: str) -> None:
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Ticket schließen",
                style=discord.ButtonStyle.secondary,
                custom_id=f"vertex:ticket:close:{ticket_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["ticket_id"])

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: TicketsCog = interaction.client.get_cog("TicketsCog")  # type: ignore
        await cog.close_ticket(self.ticket_id, closed_by=str(interaction.user), interaction=interaction)


class TicketChannelView(discord.ui.LayoutView):
    def __init__(self, ticket_id: str) -> None:
        super().__init__(timeout=None)
        container = discord.ui.Container(
            discord.ui.TextDisplay("# Ticket"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                "Ein Teammitglied meldet sich in Kürze. Schließe das Ticket, "
                "sobald dein Anliegen erledigt ist."
            ),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
            discord.ui.ActionRow(CloseTicketButton(ticket_id)),
        )
        self.add_item(container)


class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.action_handlers["ticket.close"] = self._handle_close_action

    async def _handle_close_action(self, payload: dict) -> None:
        await self.close_ticket(payload["ticket_id"], closed_by=f"Web ({payload.get('actor', 'unbekannt')})")

    # ---------- Slash Commands ----------

    @app_commands.command(name="ticket-panel", description="Postet das Ticket-Panel in diesem Kanal")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_panel(self, interaction: discord.Interaction) -> None:
        await interaction.channel.send(view=TicketPanelView())
        await interaction.response.send_message("Panel gepostet.", ephemeral=True)

    @app_commands.command(name="ticket-setup", description="Legt Kategorie und Log-Kanal für Tickets fest")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        kategorie: discord.CategoryChannel,
        log_kanal: discord.TextChannel,
    ) -> None:
        def _do(data):
            data["settings"]["guild_id"] = interaction.guild_id
            data["settings"]["ticket_category_id"] = kategorie.id
            data["settings"]["ticket_log_channel_id"] = log_kanal.id

        store.mutate(_do)
        await interaction.response.send_message("Ticket-Einstellungen gespeichert.", ephemeral=True)

    # ---------- Kernlogik (wird von Discord-Button UND Web-Aktion genutzt) ----------

    async def create_ticket(self, interaction: discord.Interaction) -> None:
        data = store.load()
        settings = data["settings"]
        category = None
        if settings.get("ticket_category_id"):
            category = interaction.guild.get_channel(settings["ticket_category_id"])

        ticket_id = uuid.uuid4().hex[:8]
        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{ticket_id}",
            category=category,
            overwrites={
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            },
        )

        def _do(d):
            d["tickets"][ticket_id] = {
                "id": ticket_id,
                "guild_id": interaction.guild_id,
                "channel_id": channel.id,
                "opened_by": str(interaction.user),
                "opened_by_id": interaction.user.id,
                "status": "offen",
                "created_at": store.now_iso(),
                "closed_at": None,
                "closed_by": None,
            }

        store.mutate(_do)
        store.append_live_feed(f"Ticket erstellt von {interaction.user}", category="ticket")

        await channel.send(
            content=interaction.user.mention,
            view=TicketChannelView(ticket_id),
        )
        await interaction.response.send_message(f"Ticket erstellt: {channel.mention}", ephemeral=True)

    async def close_ticket(
        self,
        ticket_id: str,
        closed_by: str,
        interaction: discord.Interaction | None = None,
    ) -> None:
        data = store.load()
        ticket = data["tickets"].get(ticket_id)
        if ticket is None or ticket["status"] != "offen":
            if interaction:
                await interaction.response.send_message("Ticket nicht gefunden oder bereits geschlossen.", ephemeral=True)
            return

        guild = self.bot.get_guild(ticket["guild_id"])
        channel = guild.get_channel(ticket["channel_id"]) if guild else None

        transcript_text = f"Transcript – Ticket {ticket_id}\nErstellt: {ticket['created_at']}\nGeschlossen: {store.now_iso()} von {closed_by}\n\n"
        if channel is not None:
            messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
            for msg in messages:
                transcript_text += f"[{msg.created_at:%Y-%m-%d %H:%M}] {msg.author}: {msg.content}\n"

        transcript_dir = Path(data["settings"].get("transcript_dir", "storage/transcripts"))
        transcript_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = transcript_dir / f"{ticket_id}.txt"
        transcript_path.write_text(transcript_text, encoding="utf-8")
        summary = await _summarize_transcript(transcript_text)

        def _do(d):
            d["tickets"][ticket_id]["status"] = "archiviert"
            d["tickets"][ticket_id]["closed_at"] = store.now_iso()
            d["tickets"][ticket_id]["closed_by"] = closed_by
            d["tickets"][ticket_id]["transcript_path"] = str(transcript_path)
            d["tickets"][ticket_id]["summary"] = summary

        store.mutate(_do)
        store.append_live_feed(f"Ticket {ticket_id} geschlossen von {closed_by}", category="ticket")

        workflows_cog = self.bot.get_cog("WorkflowsCog")
        if workflows_cog and guild:
            opener = guild.get_member(ticket.get("opened_by_id"))
            await workflows_cog.trigger("ticket_closed", guild, opener, {"ticket_id": ticket_id})

        log_channel_id = data["settings"].get("ticket_log_channel_id")
        if guild and log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                text = f"Ticket `{ticket_id}` von {ticket['opened_by']} geschlossen von {closed_by}."
                if summary:
                    text += f"\nZusammenfassung: {summary}"
                await log_channel.send(text)

        if interaction:
            await interaction.response.send_message("Ticket wird geschlossen.", ephemeral=True)
        if channel is not None:
            await channel.delete(reason=f"Ticket geschlossen von {closed_by}")

async def setup(bot: commands.Bot) -> None:
    bot.add_dynamic_items(CreateTicketButton, CloseTicketButton)
    await bot.add_cog(TicketsCog(bot))
