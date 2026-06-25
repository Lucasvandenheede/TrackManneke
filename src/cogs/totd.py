import asyncio
import logging
from datetime import datetime, date
from typing import Optional, List
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
from discord.ext import commands, tasks
from src.nadeo.totd import TOTDClient
from src.embeds.totd import TOTDEmbed
import src.config as config

PARIS_TZ = ZoneInfo("Europe/Paris")

logger = logging.getLogger(__name__)

class Totd(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.retry_count = 0
        self.max_retries = 5
        self.last_error: Optional[str] = None
        self._last_post_date: Optional[date] = None
        self.post_totd_leaderboard.start()

    def cog_unload(self):
        self.post_totd_leaderboard.cancel()
        logger.info("TOTD cog unloaded and background task cancelled")

    @tasks.loop(minutes=1.0)
    async def post_totd_leaderboard(self):
        now_paris = datetime.now(PARIS_TZ)
        if now_paris.hour != 18 or now_paris.minute != 59:
            return
        if self._last_post_date == now_paris.date():
            return
        self._last_post_date = now_paris.date()

        logger.info("TOTD background task triggered at 18:59 Paris time")
        await self._fetch_and_post_leaderboard()

    @post_totd_leaderboard.before_loop
    async def before_post_totd_leaderboard(self):
        await self.bot.wait_until_ready()

    async def _get_totd_channel(self) -> Optional[discord.TextChannel]:
        db = self.bot.db
        channel_id_str = (await db.get_config("totd_channel_id")) or config.TOTD_CHANNEL_ID
        if not channel_id_str:
            logger.error("TOTD channel ID not configured")
            return None
        try:
            channel_id = int(channel_id_str)
            channel = self.bot.get_channel(channel_id)
            if not channel:
                logger.error(f"TOTD channel not found: {channel_id}")
            return channel
        except ValueError:
            logger.error(f"Invalid TOTD channel ID: {channel_id_str}")
            return None

    async def _fetch_and_post_leaderboard(self):
        nadeo_client = self.bot.nadeo_client
        db = self.bot.db

        channel = await self._get_totd_channel()
        if not channel:
            return

        self.retry_count = 0
        while self.retry_count < self.max_retries:
            try:
                await self._post_to_channel(channel, nadeo_client, db)
                self.retry_count = 0
                self.last_error = None
                return
            except Exception as e:
                self.retry_count += 1
                self.last_error = str(e)
                if self.retry_count < self.max_retries:
                    wait_time = self.retry_count * 2 * 60
                    logger.warning(
                        f"TOTD fetch failed (attempt {self.retry_count}/{self.max_retries}): {e}. "
                        f"Retrying in {wait_time // 60} minutes..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.critical(
                        f"TOTD fetch failed after {self.max_retries} attempts. Last error: {e}"
                    )

    async def _resolve_and_add_players(self, account_ids: List[str], db, nadeo_client=None):
        oauth = self.bot.oauth_client
        if not oauth:
            logger.warning("OAuth client unavailable, cannot resolve new player names")
            return

        new_count = 0
        for i in range(0, len(account_ids), 50):
            batch = account_ids[i : i + 50]
            try:
                names = await oauth.get_display_names(batch)
                for aid, name in names.items():
                    if await db.save_discovered_player(aid, name):
                        new_count += 1
            except Exception as e:
                logger.error(f"Failed to resolve players for batch: {e}")

        if new_count:
            logger.info(f"Auto-tracked {new_count} new Belgian players")

    async def _post_to_channel(
        self, channel: discord.TextChannel, nadeo_client, db
    ):
        totd_client = TOTDClient(nadeo_client)

        logger.info("Fetching current TOTD...")
        totd_data = await totd_client.get_current_totd(
            oauth_client=self.bot.oauth_client
        )
        map_uid = totd_data.get("map_uid")
        if not map_uid:
            raise Exception("Could not extract map_uid from TOTD data")

        logger.info(f"TOTD map_uid: {map_uid}")

        belgian_players = await db.get_all_players()
        result = await totd_client.get_belgian_leaderboard(
            map_uid, belgian_players
        )

        if result["new_player_ids"]:
            logger.info(f"Discovered {len(result['new_player_ids'])} new Belgian players, resolving names...")
            await self._resolve_and_add_players(result["new_player_ids"], db)
            belgian_players = await db.get_all_players()
            result = await totd_client.get_belgian_leaderboard(
                map_uid, belgian_players
            )

        entries = result["entries"]

        logger.info(f"Found {len(entries)} Belgian players on this map")
        embed = TOTDEmbed.build(totd_data, entries)

        await channel.send(embed=embed)
        logger.info("TOTD leaderboard posted successfully")

    @app_commands.command(name="set-totd-channel", description="Set the channel for TOTD leaderboard posts")
    @app_commands.describe(channel="The channel to post TOTD leaderboards in")
    async def set_totd_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        try:
            db = self.bot.db
            await db.set_config("totd_channel_id", str(channel.id))
            await interaction.response.send_message(
                f"TOTD leaderboard channel set to {channel.mention}",
                ephemeral=True,
            )
            logger.info(f"TOTD channel updated to {channel.id} by {interaction.user}")
        except Exception as e:
            logger.error(f"Error setting TOTD channel: {e}")
            await interaction.response.send_message(
                f"An error occurred: {str(e)}",
                ephemeral=True,
            )

    @app_commands.command(name="totd-leaderboard", description="Show the current TOTD leaderboard for Belgian players")
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.user.id)
    async def totd_leaderboard(self, interaction: discord.Interaction):
        nadeo_client = self.bot.nadeo_client
        db = self.bot.db

        if not nadeo_client:
            await interaction.response.send_message(
                "Nadeo client is not initialized. Check server configuration.",
                ephemeral=True,
            )
            return

        channel = await self._get_totd_channel()
        if not channel:
            await interaction.response.send_message(
                "TOTD channel not configured.", ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            totd_client = TOTDClient(nadeo_client)
            totd_data = await totd_client.get_current_totd(
                oauth_client=self.bot.oauth_client
            )
            map_uid = totd_data.get("map_uid")
            if not map_uid:
                await interaction.followup.send(
                    "Could not fetch current TOTD data.", ephemeral=True
                )
                return

            belgian_players = await db.get_all_players()

            result = await totd_client.get_belgian_leaderboard(
                map_uid, belgian_players
            )

            if result["new_player_ids"]:
                logger.info(f"Discovered {len(result['new_player_ids'])} new Belgian players")
                await self._resolve_and_add_players(result["new_player_ids"], db)
                belgian_players = await db.get_all_players()
                result = await totd_client.get_belgian_leaderboard(
                    map_uid, belgian_players
                )

            entries = result["entries"]

            embed = TOTDEmbed.build(totd_data, entries)

            await channel.send(embed=embed)
            await interaction.followup.send(
                f"Leaderboard posted to {channel.mention}.", ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in /totd-leaderboard: {e}")
            await interaction.followup.send(
                f"An error occurred while fetching the leaderboard: {str(e)}",
                ephemeral=True,
            )

    @totd_leaderboard.error
    async def totd_leaderboard_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            retry_after = int(error.retry_after)
            await interaction.response.send_message(
                f"Command on cooldown. Try again in **{retry_after} seconds**.",
                ephemeral=True,
            )
        else:
            logger.error(f"Unexpected error in /totd-leaderboard: {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An unexpected error occurred.", ephemeral=True
                )

async def setup(bot: commands.Bot):
    await bot.add_cog(Totd(bot))
