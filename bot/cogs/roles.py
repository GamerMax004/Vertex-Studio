from __future__ import annotations

import uuid

import discord
from discord import app_commands
from discord.ext import commands

from storage import store


class RoleButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"vertex:role:(?P<panel_id>[a-zA-Z0-9]+):(?P<role_id>[0-9]+)",
):
    def __init__(self, panel_id: str, role_id: int, label: str) -> None:
        self.panel_id = panel_id
        self.role_id = role_id
        super().__init__(
            discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"vertex:role:{panel_id}:{role_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        panel = store.load()["role_panels"].get(match["panel_id"], {})
        role_id = int(match["role_id"])
        label = next((r["label"] for r in panel.get("roles", []) if r["role_id"] == role_id), "Rolle")
        return cls(match["panel_id"], role_id, label)

    async def callback(self, interaction: discord.Interaction) -> None:
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message("Rolle existiert nicht mehr.", ephemeral=True)
            return
        member: discord.Member = interaction.user  # type: ignore
        if role in member.roles:
            await member.remove_roles(role, reason="Button Role")
            await interaction.response.send_message(f"Rolle {role.name} entfernt.", ephemeral=True)
        else:
            await member.add_roles(role, reason="Button Role")
            await interaction.response.send_message(f"Rolle {role.name} hinzugefügt.", ephemeral=True)


class RolePanelView(discord.ui.LayoutView):
    def __init__(self, panel_id: str, title: str, roles: list[dict]) -> None:
        super().__init__(timeout=None)
        buttons = [RoleButton(panel_id, r["role_id"], r["label"]) for r in roles]
        rows = [discord.ui.ActionRow(*buttons[i:i + 5]) for i in range(0, len(buttons), 5)]
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"# {title}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay("Klicke einen Button, um die Rolle zu erhalten oder zu entfernen."),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
            *rows,
        )
        self.add_item(container)


class RolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="rolepanel", description="Erstellt ein Button-Role-Panel mit bis zu 5 Rollen")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rolepanel(
        self,
        interaction: discord.Interaction,
        titel: str,
        rolle1: discord.Role,
        rolle2: discord.Role | None = None,
        rolle3: discord.Role | None = None,
        rolle4: discord.Role | None = None,
        rolle5: discord.Role | None = None,
    ) -> None:
        rollen = [r for r in (rolle1, rolle2, rolle3, rolle4, rolle5) if r is not None]
        panel_id = uuid.uuid4().hex[:8]
        roles_data = [{"role_id": r.id, "label": r.name} for r in rollen]

        def _do(data):
            data["role_panels"][panel_id] = {
                "channel_id": interaction.channel_id,
                "title": titel,
                "roles": roles_data,
            }
        store.mutate(_do)

        await interaction.channel.send(view=RolePanelView(panel_id, titel, roles_data))
        await interaction.response.send_message("Rollen-Panel gepostet.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    bot.add_dynamic_items(RoleButton)
    await bot.add_cog(RolesCog(bot))
