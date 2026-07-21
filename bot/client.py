from __future__ import annotations

import discord
from discord.ext import commands, tasks

from storage import store

INITIAL_COGS = (
    "bot.cogs.tickets",
    "bot.cogs.moderation",
    "bot.cogs.automod",
    "bot.cogs.roles",
    "bot.cogs.embeds",
    "bot.cogs.announcements",
    "bot.cogs.logs",
    "bot.cogs.tasks_reminders",
    "bot.cogs.backups",
    "bot.cogs.automations",
    "bot.cogs.workflows",
    "bot.cogs.core",
)


class VertexBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        # type -> async handler(payload: dict). Cogs registrieren sich in cog_load
        # per bot.action_handlers["mod.kick"] = self.handle_kick, statt selbst
        # die ganze Queue zu leeren.
        self.action_handlers: dict[str, "callable"] = {}
        self.tree.interaction_check = self._check_command_enabled

    async def _check_command_enabled(self, interaction: discord.Interaction) -> bool:
        if interaction.command is None:
            return True
        disabled = store.load()["settings"].get("disabled_commands", [])
        if interaction.command.qualified_name in disabled:
            await interaction.response.send_message(
                "Dieser Befehl ist über das Dashboard deaktiviert.", ephemeral=True
            )
            return False
        return True

    async def setup_hook(self) -> None:
        for cog in INITIAL_COGS:
            await self.load_extension(cog)
        await self.tree.sync()

        commands_list = sorted(cmd.name for cmd in self.tree.get_commands())
        store.mutate(lambda data: data.update(known_commands=commands_list))

        self.update_status.start()
        self.dispatch_actions.start()

    @tasks.loop(seconds=5)
    async def dispatch_actions(self) -> None:
        for action in store.pop_pending_actions():
            handler = self.action_handlers.get(action["type"])
            if handler is None:
                store.append_live_feed(f"Keine Aktion registriert für {action['type']}", category="error")
                continue
            try:
                await handler(action["payload"])
            except Exception as exc:  # noqa: BLE001
                store.append_live_feed(f"Fehler bei {action['type']}: {exc}", category="error")

    @dispatch_actions.before_loop
    async def _before_dispatch(self) -> None:
        await self.wait_until_ready()

    async def on_ready(self) -> None:
        def _do(data):
            data["bot_status"]["online"] = True
            data["bot_status"]["started_at"] = store.now_iso()
            data["bot_status"]["guild_count"] = len(self.guilds)

        store.mutate(_do)
        store.append_live_feed(f"Bot online als {self.user}", category="system")
        print(f"Eingeloggt als {self.user} ({len(self.guilds)} Server)")

        status_text = store.load()["settings"].get("status_text")
        if status_text:
            await self.change_presence(activity=discord.CustomActivity(name=status_text))

    @tasks.loop(seconds=15)
    async def update_status(self) -> None:
        def _do(data):
            data["bot_status"]["latency_ms"] = round(self.latency * 1000) if self.latency else None
            data["bot_status"]["guild_count"] = len(self.guilds)

        store.mutate(_do)

    @update_status.before_loop
    async def _before_update_status(self) -> None:
        await self.wait_until_ready()

    async def close(self) -> None:
        def _do(data):
            data["bot_status"]["online"] = False

        store.mutate(_do)
        await super().close()
