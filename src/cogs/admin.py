import logging
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from src.db import Database
from src.nadeo.client import NadeoClient

logger = logging.getLogger(__name__)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_player_info(self, account_id: str) -> Optional[dict]:
        try:
            oauth_client = self.bot.oauth_client
            if not oauth_client:
                logger.error("OAuth client not initialized")
                return None

            display_names = await oauth_client.get_display_names([account_id])

            if account_id in display_names:
                return {
                    "account_id": account_id,
                    "display_name": display_names[account_id],
                }
            else:
                logger.warning(f"Player not found in Trackmania: {account_id}")
                return None
        except Exception as e:
            logger.error(f"Failed to fetch player info from OAuth API: {e}")
            return None

    @app_commands.command(name="player", description="Manage tracked Belgian players")
    @app_commands.describe(
        action="Action to perform (add or remove)",
        account_id="Player's Nadeo account UUID",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="add", value="add"),
            app_commands.Choice(name="remove", value="remove"),
        ]
    )
    async def player(
        self,
        interaction: discord.Interaction,
        action: str,
        account_id: str,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        db: Database = self.bot.db
        await interaction.response.defer(ephemeral=True)

        try:
            if action == "add":
                await self._handle_add_player(interaction, db, account_id)
            elif action == "remove":
                await self._handle_remove_player(interaction, db, account_id)
        except Exception as e:
            logger.error(f"Error in player command: {e}")
            await interaction.followup.send(
                f"An error occurred: {str(e)}", ephemeral=True
            )

    async def _handle_add_player(
        self, interaction: discord.Interaction, db: Database, account_id: str
    ):
        if await db.player_exists(account_id):
            existing = await db.get_player(account_id)
            await interaction.followup.send(
                f"Player already tracked: **{existing['player_name']}** ({account_id})",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Fetching player info from Nadeo...", ephemeral=True
        )

        player_info = await self._get_player_info(account_id)
        if not player_info:
            await interaction.followup.send(
                f"Player not found in Nadeo API: {account_id}",
                ephemeral=True,
            )
            return

        player_name = player_info["display_name"]
        success = await db.add_player(account_id, player_name)

        if success:
            total = await db.get_player_count()
            await interaction.followup.send(
                f"Added player: **{player_name}**\n"
                f"Total tracked: {total}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Failed to add player to database",
                ephemeral=True,
            )

    async def _handle_remove_player(
        self, interaction: discord.Interaction, db: Database, account_id: str
    ):
        player = await db.get_player(account_id)
        if not player:
            await interaction.followup.send(
                f"Player not found in tracking list: {account_id}",
                ephemeral=True,
            )
            return

        success = await db.remove_player(account_id)

        if success:
            total = await db.get_player_count()
            await interaction.followup.send(
                f"Removed player: **{player['player_name']}**\n"
                f"Total tracked: {total}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Failed to remove player from database",
                ephemeral=True,
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))