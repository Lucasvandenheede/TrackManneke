import logging
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class Posting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _is_allowed(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You don't have permission to use this command.",
                ephemeral=True,
            )
            return False
        return True

    async def _frozen_status(self) -> str:
        return "frozen" if await self.bot.is_posting_frozen() else "active"

    @app_commands.command(name="freeze", description="Pause automatic result posting (dev only)")
    async def freeze(self, interaction: discord.Interaction):
        if not await self._is_allowed(interaction):
            return
        await self.bot.set_posting_frozen(True)
        await interaction.response.send_message(
            "Automatic result posting is now **frozen**. "
            "Manual commands (e.g. `/totd-leaderboard`, `/cotd-results`) still work.",
            ephemeral=True,
        )
        logger.info(f"Auto-posting frozen by {interaction.user}")

    @app_commands.command(name="unfreeze", description="Resume automatic result posting (dev only)")
    async def unfreeze(self, interaction: discord.Interaction):
        if not await self._is_allowed(interaction):
            return
        await self.bot.set_posting_frozen(False)
        await interaction.response.send_message(
            "Automatic result posting is now **active**.",
            ephemeral=True,
        )
        logger.info(f"Auto-posting unfrozen by {interaction.user}")

    @app_commands.command(name="posting-status", description="Show whether automatic result posting is frozen (dev only)")
    async def posting_status(self, interaction: discord.Interaction):
        if not await self._is_allowed(interaction):
            return
        status = await self._frozen_status()
        await interaction.response.send_message(
            f"Automatic result posting is currently **{status}**.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Posting(bot))
