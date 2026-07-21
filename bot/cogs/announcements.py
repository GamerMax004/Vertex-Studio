from __future__ import annotations

from datetime import datetime, timedelta, timezone

from discord.ext import commands, tasks

from storage import store


class AnnouncementsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.check_announcements.start()

    def cog_unload(self) -> None:
        self.check_announcements.cancel()

    @tasks.loop(seconds=30)
    async def check_announcements(self) -> None:
        data = store.load()
        now = datetime.now(timezone.utc)
        for ann_id, ann in list(data["announcements"].items()):
            if ann.get("sent") and ann.get("repeat", "once") == "once":
                continue
            send_at = datetime.fromisoformat(ann["send_at"])
            if send_at > now:
                continue

            channel = self.bot.get_channel(ann["channel_id"])
            if channel:
                await channel.send(ann["content"])
                store.append_live_feed(f"Ankündigung gesendet in #{getattr(channel, 'name', ann['channel_id'])}", category="announcement")

            repeat = ann.get("repeat", "once")
            next_send = None
            if repeat == "daily":
                next_send = send_at + timedelta(days=1)
            elif repeat == "weekly":
                next_send = send_at + timedelta(weeks=1)

            def _do(d, ann_id=ann_id, next_send=next_send):
                if next_send:
                    d["announcements"][ann_id]["send_at"] = next_send.isoformat()
                else:
                    d["announcements"][ann_id]["sent"] = True
            store.mutate(_do)

    @check_announcements.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnnouncementsCog(bot))
