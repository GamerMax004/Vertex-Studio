from __future__ import annotations

import discord
from discord.ext import commands

from storage import store


class EmbedsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.action_handlers["embed.send"] = self._handle_send

    async def _handle_send(self, payload: dict) -> None:
        channel = self.bot.get_channel(payload["channel_id"])
        if channel is None:
            store.append_live_feed("Embed-Versand fehlgeschlagen: Kanal nicht gefunden", category="error")
            return

        embed = discord.Embed(
            title=payload.get("title") or None,
            description=payload.get("description") or None,
            color=int(payload["color"].lstrip("#"), 16) if payload.get("color") else discord.Color.default(),
        )
        if payload.get("footer"):
            embed.set_footer(text=payload["footer"])
        if payload.get("image_url"):
            embed.set_image(url=payload["image_url"])
        if payload.get("thumbnail_url"):
            embed.set_thumbnail(url=payload["thumbnail_url"])

        await channel.send(embed=embed)
        store.append_live_feed(f"Embed gesendet in #{getattr(channel, 'name', channel.id)}", category="embed")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmbedsCog(bot))
