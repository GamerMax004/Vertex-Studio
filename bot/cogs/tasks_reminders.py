from __future__ import annotations

from datetime import datetime, timezone

from discord.ext import commands, tasks

from storage import store


class TasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.check_tasks.start()

    def cog_unload(self) -> None:
        self.check_tasks.cancel()

    @tasks.loop(seconds=30)
    async def check_tasks(self) -> None:
        data = store.load()
        now = datetime.now(timezone.utc)
        for task_id, task in list(data["tasks"].items()):
            if task.get("done"):
                continue
            due_at = datetime.fromisoformat(task["due_at"])
            if due_at > now:
                continue
            channel = self.bot.get_channel(task["channel_id"]) if task.get("channel_id") else None
            if channel:
                await channel.send(f"Erinnerung: {task['content']}")
            store.append_live_feed(f"Aufgabe fällig: {task['content']}", category="task")

            def _do(d, task_id=task_id):
                d["tasks"][task_id]["done"] = True
            store.mutate(_do)

    @check_tasks.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TasksCog(bot))
