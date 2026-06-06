import asyncio
import logging
from datetime import datetime, date
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
from discord.ext import commands, tasks
from src.nadeo.cotd import COTDClient
from src.nadeo.totd import TOTDClient
from src.embeds.cotd import COTDEmbed
import src.config as config

logger = logging.getLogger(__name__)


class Cotd(commands.Cog):
    CUP_SCHEDULE: List[Dict] = [
        {"type": "cotn", "phase": "qualifier", "hour": 3, "minute": 15},
        {"type": "cotn", "phase": "rounds", "hour": 3, "minute": 45},
        {"type": "cotm", "phase": "qualifier", "hour": 11, "minute": 15},
        {"type": "cotm", "phase": "rounds", "hour": 11, "minute": 45},
        {"type": "cotd", "phase": "qualifier", "hour": 19, "minute": 15},
        {"type": "cotd", "phase": "rounds", "hour": 19, "minute": 45},
    ]

    MAX_RETRIES = 5
    RETRY_BACKOFF_SECONDS = 120
    PHASE_LABEL = {
        "qualifier": "Qualifier Results",
        "rounds": "Rounds Results",
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tz = ZoneInfo(config.TIMEZONE)
        self._last_post: Dict[str, date] = {}
        self.post_cup_results.start()
        schedule_repr = [
            f"{s['type']}/{s['phase']}@{s['hour']:02d}:{s['minute']:02d}"
            for s in self.CUP_SCHEDULE
        ]
        logger.info(f"Cotd cog loaded - schedule: {schedule_repr}")

    def cog_unload(self):
        self.post_cup_results.cancel()
        logger.info("Cotd cog unloaded and background task cancelled")

    @tasks.loop(minutes=1.0)
    async def post_cup_results(self):
        now = datetime.now(self.tz)
        for slot in self.CUP_SCHEDULE:
            if now.hour == slot["hour"] and now.minute == slot["minute"]:
                cup_type = slot["type"]
                phase = slot["phase"]
                key = f"{cup_type}_{phase}"
                if self._last_post.get(key) == now.date():
                    return
                self._last_post[key] = now.date()
                logger.info(
                    f"Triggering {cup_type} {phase} post at "
                    f"{now.strftime('%H:%M')} {config.TIMEZONE}"
                )
                if phase == "qualifier":
                    await self._fetch_and_post_qualifier(cup_type)
                else:
                    await self._fetch_and_post_rounds(cup_type)
                return

    @post_cup_results.before_loop
    async def before_post_cup_results(self):
        await self.bot.wait_until_ready()

    async def _get_channel(self) -> Optional[discord.TextChannel]:
        db = self.bot.db
        channel_id_str = (
            db.get_config("cotd_channel_id")
            or config.COTD_CHANNEL_ID
            or config.TOTD_CHANNEL_ID
        )
        if not channel_id_str:
            logger.error("COTD channel ID not configured")
            return None
        try:
            channel_id = int(channel_id_str)
        except ValueError:
            logger.error(f"Invalid COTD channel ID: {channel_id_str}")
            return None
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.error(f"COTD channel not found: {channel_id}")
            return None
        return channel

    async def _get_map_info(self) -> Dict:
        totd_client = TOTDClient(self.bot.nadeo_client)
        try:
            totd = await totd_client.get_current_totd(
                oauth_client=self.bot.oauth_client
            )
        except Exception as e:
            logger.warning(f"Failed to fetch TOTD for map info: {e}")
            return {
                "name": "Unknown Map",
                "author_name": "Unknown",
                "author_account_id": "",
                "author_time": 0,
                "thumbnail_url": "",
                "map_uid": "",
                "season_uid": "",
            }

        thumbnail = totd.get("image_url", "") or ""
        if thumbnail and not thumbnail.startswith("http"):
            thumbnail = ""

        return {
            "name": totd.get("name", "Unknown Map"),
            "author_name": totd.get("author_name", "Unknown"),
            "author_account_id": totd.get("author_account_id", ""),
            "author_time": totd.get("medal_time", 0) or 0,
            "thumbnail_url": thumbnail,
            "map_uid": totd.get("map_uid", ""),
            "season_uid": totd.get("season_uid", ""),
        }

    async def _fetch_and_post_qualifier(self, cup_type: str):
        channel = await self._get_channel()
        if not channel:
            return

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                await self._post_qualifier_to_channel(channel, cup_type)
                return
            except Exception as e:
                logger.warning(
                    f"{cup_type.upper()} qualifier post failed (attempt "
                    f"{attempt}/{self.MAX_RETRIES}): {e}"
                )
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_BACKOFF_SECONDS)
                else:
                    logger.critical(
                        f"{cup_type.upper()} qualifier post failed after "
                        f"{self.MAX_RETRIES} attempts: {e}"
                    )

    async def _fetch_and_post_rounds(self, cup_type: str):
        channel = await self._get_channel()
        if not channel:
            return

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                await self._post_rounds_to_channel(channel, cup_type)
                return
            except Exception as e:
                logger.warning(
                    f"{cup_type.upper()} rounds post failed (attempt "
                    f"{attempt}/{self.MAX_RETRIES}): {e}"
                )
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_BACKOFF_SECONDS)
                else:
                    logger.critical(
                        f"{cup_type.upper()} rounds post failed after "
                        f"{self.MAX_RETRIES} attempts: {e}"
                    )

    async def _resolve_new_players(
        self,
        account_ids: List[str],
        db,
    ) -> Dict[str, str]:
        oauth = self.bot.oauth_client
        if not oauth or not account_ids:
            return {}

        name_map: Dict[str, str] = {}
        for i in range(0, len(account_ids), 50):
            batch = account_ids[i : i + 50]
            try:
                names = await oauth.get_display_names(batch)
                for aid, name in names.items():
                    if not db.player_exists(aid):
                        db.add_player(aid, name)
                        logger.info(
                            f"Auto-tracked new Belgian player: {name} ({aid})"
                        )
                    name_map[aid] = name
            except Exception as e:
                logger.error(f"Failed to resolve names batch: {e}")
        return name_map

    async def _post_qualifier_to_channel(
        self, channel: discord.TextChannel, cup_type: str
    ):
        nadeo_client = self.bot.nadeo_client
        db = self.bot.db
        if not nadeo_client:
            raise Exception("Nadeo client not initialized")

        cotd_client = COTDClient(nadeo_client)
        belgian_players = db.get_all_players()
        belgian_ids = {p["account_id"] for p in belgian_players}
        name_map = {p["account_id"]: p["player_name"] for p in belgian_players}

        map_info = await self._get_map_info()

        logger.info(f"Fetching {cup_type.upper()} qualifier data from Meet API...")
        data = await cotd_client.fetch_qualifier_data(cup_type, belgian_ids)

        new_ids = [
            e["account_id"] for e in data["qualifier"] if e["account_id"] not in name_map
        ]
        if new_ids:
            logger.info(
                f"Resolving {len(new_ids)} new player names for {cup_type.upper()}"
            )
            resolved = await self._resolve_new_players(new_ids, db)
            name_map.update(resolved)

        embed = COTDEmbed.build_qualifier(
            data["cup_label"], map_info, data["qualifier"], name_map
        )
        await channel.send(embed=embed)
        logger.info(
            f"{data['cup_label']} qualifier posted: "
            f"{len(data['qualifier'])} Belgian players"
        )

    async def _post_rounds_to_channel(
        self, channel: discord.TextChannel, cup_type: str
    ):
        nadeo_client = self.bot.nadeo_client
        db = self.bot.db
        if not nadeo_client:
            raise Exception("Nadeo client not initialized")

        cotd_client = COTDClient(nadeo_client)
        belgian_players = db.get_all_players()
        belgian_ids = {p["account_id"] for p in belgian_players}
        name_map = {p["account_id"]: p["player_name"] for p in belgian_players}

        map_info = await self._get_map_info()

        logger.info(f"Fetching {cup_type.upper()} rounds data from Meet API...")
        data = await cotd_client.fetch_rounds_data(cup_type, belgian_ids)

        if not data["rounds"]:
            raise Exception(
                f"No rounds results yet for {cup_type} (expected divisions "
                f"with Belgian players: "
                f"{sorted(set(q['division'] for q in data['qualifier']))})"
            )

        new_ids = list(
            {e["account_id"] for e in data["rounds"]} - set(name_map.keys())
        )
        if new_ids:
            logger.info(
                f"Resolving {len(new_ids)} new player names for {cup_type.upper()}"
            )
            resolved = await self._resolve_new_players(new_ids, db)
            name_map.update(resolved)

        embed = COTDEmbed.build_rounds(
            data["cup_label"], map_info, data["rounds"], name_map
        )
        await channel.send(embed=embed)
        logger.info(
            f"{data['cup_label']} rounds posted: "
            f"{len(data['rounds'])} Belgian players"
        )

    @app_commands.command(
        name="set-cotd-channel",
        description="Set the channel for COTD/COTN/COTM results posts",
    )
    @app_commands.describe(channel="The channel to post COTD results in")
    async def set_cotd_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        try:
            db = self.bot.db
            db.set_config("cotd_channel_id", str(channel.id))
            await interaction.response.send_message(
                f"COTD/COTN/COTM results channel set to {channel.mention}",
                ephemeral=True,
            )
            logger.info(
                f"COTD channel updated to {channel.id} by {interaction.user}"
            )
        except Exception as e:
            logger.error(f"Error setting COTD channel: {e}")
            await interaction.response.send_message(
                f"An error occurred: {str(e)}", ephemeral=True
            )

    @app_commands.command(
        name="cotd-qualifier",
        description="Manually fetch and post the qualifier results for a cup",
    )
    @app_commands.describe(cup_type="Which cup to fetch (cotd, cotn, cotm)")
    @app_commands.choices(
        cup_type=[
            app_commands.Choice(name="Cup of the Day", value="cotd"),
            app_commands.Choice(name="Cup of the Night", value="cotn"),
            app_commands.Choice(name="Cup of the Morning", value="cotm"),
        ]
    )
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.user.id)
    async def cotd_qualifier(
        self, interaction: discord.Interaction, cup_type: str
    ):
        if not self.bot.nadeo_client:
            await interaction.response.send_message(
                "Nadeo client is not initialized.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)
        try:
            channel = await self._get_channel()
            if not channel:
                await interaction.followup.send(
                    "COTD results channel is not configured.", ephemeral=True
                )
                return
            await self._post_qualifier_to_channel(channel, cup_type)
            await interaction.followup.send(
                f"{cup_type.upper()} qualifier posted.", ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in /cotd-qualifier: {e}")
            await interaction.followup.send(
                f"An error occurred: {str(e)}", ephemeral=True
            )

    @app_commands.command(
        name="cotd-rounds",
        description="Manually fetch and post the rounds results for a cup",
    )
    @app_commands.describe(cup_type="Which cup to fetch (cotd, cotn, cotm)")
    @app_commands.choices(
        cup_type=[
            app_commands.Choice(name="Cup of the Day", value="cotd"),
            app_commands.Choice(name="Cup of the Night", value="cotn"),
            app_commands.Choice(name="Cup of the Morning", value="cotm"),
        ]
    )
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.user.id)
    async def cotd_rounds(
        self, interaction: discord.Interaction, cup_type: str
    ):
        if not self.bot.nadeo_client:
            await interaction.response.send_message(
                "Nadeo client is not initialized.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)
        try:
            channel = await self._get_channel()
            if not channel:
                await interaction.followup.send(
                    "COTD results channel is not configured.", ephemeral=True
                )
                return
            await self._post_rounds_to_channel(channel, cup_type)
            await interaction.followup.send(
                f"{cup_type.upper()} rounds posted.", ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in /cotd-rounds: {e}")
            await interaction.followup.send(
                f"An error occurred: {str(e)}", ephemeral=True
            )

    @cotd_qualifier.error
    async def cotd_qualifier_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        await self._handle_cmd_error(interaction, error, "/cotd-qualifier")

    @cotd_rounds.error
    async def cotd_rounds_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        await self._handle_cmd_error(interaction, error, "/cotd-rounds")

    async def _handle_cmd_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
        name: str,
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            retry_after = int(error.retry_after)
            await interaction.response.send_message(
                f"Command on cooldown. Try again in **{retry_after} seconds**.",
                ephemeral=True,
            )
        else:
            logger.error(f"Unexpected error in {name}: {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An unexpected error occurred.", ephemeral=True
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(Cotd(bot))
