import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Set
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
    STATE_IDLE = "IDLE"
    STATE_QUALIFIER = "QUALIFIER"
    STATE_BRACKET_PLAY = "BRACKET_PLAY"

    RD_CUP_RETRIES = 3
    RD_CUP_DELAY = 10
    RD_ROUNDS_DELAY = 30

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tz = ZoneInfo(config.TIMEZONE)
        self.last_challenge_id: Optional[int] = None
        self._state = self.STATE_IDLE
        self._current_cup: Optional[Dict[str, Any]] = None
        self._seen_completed_match_ids: Set[Any] = set()
        self._rounds_entries_buffer: List[Dict[str, Any]] = []
        self._bg_tasks: set = set()
        self.monitor_cotd_lifecycle.start()
        logger.info("Cotd cog loaded - state machine started (IDLE)")

    @staticmethod
    def _format_cup_label(start_date: int, edition: int) -> str:
        date_str = datetime.fromtimestamp(start_date, tz=ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
        return f"COTD {date_str} #{edition}"

    def cog_unload(self):
        self.monitor_cotd_lifecycle.cancel()
        logger.info("Cotd cog unloaded and lifecycle cancelled")

    @tasks.loop(seconds=30)
    async def monitor_cotd_lifecycle(self):
        await self._tick_state_machine()

    @monitor_cotd_lifecycle.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()
        await self._discover_belgian_players()
        cup = await self._acknowledge_current_challenge()
        if cup and cup.get("challenge", {}).get("id"):
            await self._transition_to_qualifier(cup)

    async def _tick_state_machine(self):
        nadeo = self.bot.nadeo_client
        if not nadeo:
            return
        cotd = COTDClient(nadeo)

        try:
            if self._state == self.STATE_IDLE:
                await self._tick_idle(cotd)
            elif self._state == self.STATE_QUALIFIER:
                await self._tick_qualifier(cotd)
            elif self._state == self.STATE_BRACKET_PLAY:
                await self._tick_bracket(cotd)
        except Exception as e:
            logger.error(f"State machine tick failed: {e}", exc_info=True)

    async def _tick_idle(self, cotd: COTDClient):
        cup = await cotd.get_current_cup()
        if not cup or not isinstance(cup, dict):
            return
        challenge = cup.get("challenge", {})
        challenge_id = challenge.get("id")
        if not challenge_id:
            return
        if challenge_id == self.last_challenge_id:
            return
        logger.info(f"New COTD detected (challenge {challenge_id}), entering QUALIFIER")
        await self._transition_to_qualifier(cup)

    async def _transition_to_qualifier(self, cup: Dict[str, Any]):
        self._state = self.STATE_QUALIFIER
        self._current_cup = cup
        logger.info(f"State → QUALIFIER (edition {cup.get('edition', 1)})")

    async def _tick_qualifier(self, cotd: COTDClient):
        cup = self._current_cup
        if not cup:
            self._reset_state()
            return
        challenge = cup.get("challenge", {})
        challenge_id = challenge.get("id")
        challenge_end = challenge.get("endDate")
        if not challenge_id:
            self._reset_state()
            return
        if challenge_end and challenge_end > datetime.now(timezone.utc).timestamp():
            return

        edition = cup.get("edition", 1)
        map_info = await self._get_map_info()
        await self._post_qualifier(cotd, challenge_id, map_info, edition)

        competition = cup.get("competition", {})
        competition_id = competition.get("id")
        if competition_id:
            self._current_competition_id = competition_id
            self._seen_completed_match_ids.clear()
            self._state = self.STATE_BRACKET_PLAY
            self.last_challenge_id = challenge_id
            logger.info(f"State → BRACKET_PLAY (competition {competition_id})")
        else:
            self._reset_state()

    async def _tick_bracket(self, cotd: COTDClient):
        comp_id = getattr(self, "_current_competition_id", None)
        if not comp_id:
            self._reset_state()
            return

        try:
            matches = await cotd.get_rounds_and_matches(comp_id)
        except Exception as e:
            logger.debug(f"Bracket poll failed: {e}")
            return

        if not matches:
            logger.debug("No matches yet in bracket phase")
            return

        db = self.bot.db
        players = await db.get_all_players()
        belgian_ids = {p["account_id"] for p in players}
        name_map = {p["account_id"]: p["player_name"] for p in players}
        edition = self._current_cup.get("edition", 1) if self._current_cup else 1
        map_info = await self._get_map_info()

        all_done = True
        for match in matches:
            mid = match.get("id") or match.get("matchId")
            if not mid:
                continue
            is_completed = match.get("completed", match.get("isCompleted", False))
            if not is_completed:
                all_done = False
                continue

            if mid in self._seen_completed_match_ids:
                continue

            div_num = (match.get("position", 0) or 0) + 1
            if div_num > 10:
                continue

            result = await cotd.get_bracket_division_results(mid, div_num, belgian_ids)
            if result and result.get("entries"):
                self._seen_completed_match_ids.add(mid)
                self._rounds_entries_buffer.extend(result["entries"])

        if all_done:
            if self._rounds_entries_buffer:
                channel = await self._get_channel()
                if channel:
                    embed = COTDEmbed.build_rounds(
                        edition, map_info, self._rounds_entries_buffer, name_map,
                    )
                    await channel.send(embed=embed)
                    logger.info(
                        f"COTD #{edition} consolidated rounds posted: "
                        f"{len(self._rounds_entries_buffer)} Belgian players across "
                        f"{len(self._seen_completed_match_ids)} divisions"
                    )
            else:
                logger.info(f"COTD #{edition} bracket phase complete — no Belgian entries found")
            self._reset_state()

    def _reset_state(self):
        self._state = self.STATE_IDLE
        self._current_cup = None
        self._current_competition_id = None
        self._seen_completed_match_ids.clear()
        self._rounds_entries_buffer.clear()
        logger.info("State → IDLE")

    async def _discover_belgian_players(self):
        nadeo = self.bot.nadeo_client
        oauth = self.bot.oauth_client
        db = self.bot.db
        if not nadeo:
            return
        try:
            totd_client = TOTDClient(nadeo)
            totd = await totd_client.get_current_totd(oauth_client=oauth)
            map_uid = totd.get("map_uid")
            if not map_uid:
                return
            leaderboard = await totd_client.get_totd_leaderboard(map_uid, limit=3000)
            belgian_zone_ids = await totd_client.get_belgian_zone_ids()
            all_players = await db.get_all_players()
            tracked_ids = {p["account_id"] for p in all_players}
            new_players = []
            for entry in leaderboard:
                aid = entry["account_id"]
                if aid not in tracked_ids and entry.get("zone_id") in belgian_zone_ids:
                    new_players.append(aid)
            if new_players:
                for i in range(0, len(new_players), 50):
                    batch = new_players[i:i + 50]
                    try:
                        if oauth:
                            names = await oauth.get_display_names(batch)
                        else:
                            names = {aid: aid for aid in batch}
                        for aid, name in names.items():
                            await db.save_discovered_player(aid, name)
                            tracked_ids.add(aid)
                            logger.info(f"Startup discovery -> tracked: {name} ({aid})")
                    except Exception as e:
                        logger.warning(f"Startup discovery batch resolve failed: {e}")
                logger.info(f"Discovered and tracked {len(new_players)} Belgian players at startup")
        except Exception as e:
            logger.warning(f"Startup player discovery failed: {e}")

    async def _acknowledge_current_challenge(self) -> Optional[Dict[str, Any]]:
        nadeo = self.bot.nadeo_client
        if not nadeo:
            return None
        try:
            cotd_client = COTDClient(nadeo)
            cup = await cotd_client.get_current_cup()
            if cup and isinstance(cup, dict):
                challenge = cup.get("challenge", {})
                challenge_id = challenge.get("id")
                if challenge_id:
                    self.last_challenge_id = challenge_id
                    edition = cup.get("edition", 1)
                    logger.info(
                        f"Acknowledged existing challenge {challenge_id} "
                f"({self._format_cup_label(cup.get('startDate', 0), edition)}) "
                f"— will wait for next rotation"
                    )
                    return cup
                else:
                    logger.info("Current cup has no challenge — no active COTD (204)")
            else:
                logger.info("No active COTD at startup (204) — ready to detect next rotation")
        except Exception as e:
            logger.warning(f"Failed to acknowledge current challenge: {e}")
        return None

    async def _get_channel(self) -> Optional[discord.TextChannel]:
        db = self.bot.db
        channel_id_str = (
            await db.get_config("cotd_channel_id")
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

    async def _post_qualifier(
        self,
        cotd_client: COTDClient,
        challenge_id: int,
        map_info: Dict,
        edition: int,
    ):
        db = self.bot.db
        belgian_players = await db.get_all_players()
        belgian_ids = {p["account_id"] for p in belgian_players}
        name_map = {p["account_id"]: p["player_name"] for p in belgian_players}

        all_results = await cotd_client.get_all_qualifier_results(
            challenge_id
        )

        unknown_ids = [
            e["account_id"] for e in all_results
            if e["account_id"] not in belgian_ids
        ]
        if unknown_ids:
            try:
                totd_client = TOTDClient(self.bot.nadeo_client)
                belgian_zone_ids = await totd_client.get_belgian_zone_ids()
                zone_map = await totd_client.get_totd_zone_map(
                    oauth_client=self.bot.oauth_client
                )
                oauth = self.bot.oauth_client
                for aid in unknown_ids:
                    zone_id = zone_map.get(aid)
                    if zone_id and zone_id in belgian_zone_ids:
                        if aid not in belgian_ids:
                            belgian_ids.add(aid)
                newly_discovered = [a for a in belgian_ids if a not in name_map]
                if newly_discovered and oauth:
                    resolved = await self._resolve_new_players(newly_discovered, db)
                    name_map.update(resolved)
            except Exception as e:
                logger.warning(f"Zone-based discovery failed (continuing with tracked IDs): {e}")

        belgian_results = cotd_client.filter_belgian(all_results, belgian_ids)
        divisions = cotd_client.group_by_division(belgian_results)

        qualifier_entries = []
        for div, entries in divisions.items():
            for e in entries:
                e["division"] = div
                qualifier_entries.append(e)
        qualifier_entries.sort(key=lambda e: (e["division"], e["world_rank"]))

        new_ids = [
            e["account_id"] for e in qualifier_entries
            if e["account_id"] not in name_map
        ]
        if new_ids:
            resolved = await self._resolve_new_players(new_ids, db)
            name_map.update(resolved)

        cutoffs = COTDClient.get_division_cutoffs(all_results)
        cutoff_entry = cutoffs.get("div1_cutoff")

        embed = COTDEmbed.build_qualifier(
            edition,
            map_info,
            qualifier_entries,
            name_map,
            cutoff_entry=cutoff_entry,
        )

        channel = await self._get_channel()
        if channel:
            await channel.send(embed=embed)
            logger.info(
                f"COTD #{edition} qualifier posted: "
                f"{len(qualifier_entries)} Belgian players (fetched {len(all_results)} global)"
            )

    async def _post_rounds(
        self,
        rounds_results: List[Dict[str, str]],
        name_map: Dict[str, str],
        map_info: Dict,
        edition: int,
        db,
    ):
        new_ids = [
            r["account_id"] for r in rounds_results
            if r["account_id"] not in name_map
        ]
        if new_ids:
            resolved = await self._resolve_new_players(new_ids, db)
            name_map.update(resolved)

        embed = COTDEmbed.build_rounds(
            edition, map_info, rounds_results, name_map,
        )

        channel = await self._get_channel()
        if channel:
            await channel.send(embed=embed)
            logger.info(
                f"COTD #{edition} rounds posted: "
                f"{len(rounds_results)} Belgian players"
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
                    await db.save_discovered_player(aid, name)
                    name_map[aid] = name
            except Exception as e:
                logger.error(f"Failed to resolve names batch: {e}")
        return name_map

    async def _retry_with_backoff(self, coro_factory, max_retries: int = 5):
        last_exc = None
        for attempt in range(max_retries):
            try:
                return await coro_factory()
            except Exception as e:
                last_exc = e
                if attempt == max_retries - 1:
                    break
                delay = 30 * (2 ** attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {delay}s"
                )
                await asyncio.sleep(delay)
        raise last_exc

    @app_commands.command(
        name="cotd-results",
        description="Post COTD qualifier and rounds results manually (admin only)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cotd_results(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        logger.info(f"{interaction.user} triggered /cotd-results manually")
        nadeo_client = self.bot.nadeo_client
        if not nadeo_client:
            await interaction.followup.send("Nadeo client unavailable.", ephemeral=True)
            return

        cotd_client = COTDClient(nadeo_client)
        cup = await cotd_client.get_last_completed_cup()
        if not cup:
            await interaction.followup.send("No completed COTD found.", ephemeral=True)
            return

        challenge = cup.get("challenge", {})
        challenge_id = challenge.get("id")
        competition = cup.get("competition", {})
        competition_id = competition.get("id")
        edition = cup.get("edition", 1)
        start_date = cup.get("startDate", 0)
        cup_label = self._format_cup_label(start_date, edition)

        if not challenge_id:
            await interaction.followup.send("No challenge data in cup.", ephemeral=True)
            return

        try:
            map_info = await self._get_map_info()
            channel = await self._get_channel()
            db = self.bot.db

            if not channel:
                await interaction.followup.send("COTD channel not configured.", ephemeral=True)
                return

            await self._post_qualifier(cotd_client, challenge_id, map_info, edition)

            if competition_id:
                all_players = await db.get_all_players()
                belgian_ids = {p["account_id"] for p in all_players}
                name_map = {p["account_id"]: p["player_name"] for p in all_players}
                status = await cotd_client.get_rounds_status(competition_id, belgian_ids)

                if status["total_matches"] > 0 and status["all_completed"]:
                    results = await cotd_client.get_belgian_rounds_results(competition_id, belgian_ids)
                    if results:
                        new_ids = [r["account_id"] for r in results if r["account_id"] not in name_map]
                        if new_ids:
                            resolved = await self._resolve_new_players(new_ids, db)
                            name_map.update(resolved)
                        embed = COTDEmbed.build_rounds(
                            edition, map_info, results, name_map,
                        )
                        await channel.send(embed=embed)
                        logger.info(f"{cup_label} completed rounds posted via /cotd-results")
                elif status["total_matches"] > 0 and not status["all_completed"]:
                    await self._send_rounds_intermediate_embed(
                        channel, edition, map_info, status, name_map,
                    )
                    logger.info(f"{cup_label} intermediate rounds posted via /cotd-results")

            msg = f"{cup_label}: results posted to {channel.mention}."
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in /cotd-results: {e}")
            await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

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
            await db.set_config("cotd_channel_id", str(channel.id))
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

    async def _send_rounds_intermediate_embed(
        self,
        destination,
        edition: int,
        map_info: Dict,
        status: Dict,
        name_map: Dict[str, str],
    ):
        embed = discord.Embed(
            title="Cup of the Day - Rounds Results (In Progress)",
            description=COTDEmbed._build_description(map_info),
            colour=COTDEmbed.BELGIAN_RED,
            timestamp=datetime.now(timezone.utc),
        )

        by_division: Dict[int, Dict] = {}
        for entry in status["completed"]:
            div = entry.get("division", 0)
            if 1 <= div <= 10:
                by_division.setdefault(div, {"completed": [], "in_progress": []})
                by_division[div]["completed"].append(entry)

        for entry in status["in_progress"]:
            div = entry.get("division", 0)
            if 1 <= div <= 10:
                by_division.setdefault(div, {"completed": [], "in_progress": []})
                by_division[div]["in_progress"].append(entry)

        if not by_division:
            embed.add_field(
                name="\u200b",
                value="No Belgian players found in the top 10 divisions.",
                inline=False,
            )
        else:
            for div in sorted(by_division.keys()):
                data = by_division[div]
                lines = []

                for p in sorted(data["completed"], key=lambda x: x["position"]):
                    name = name_map.get(p["account_id"], "Unknown")
                    position = p["position"]
                    emoji = COTDEmbed.PODIUM_EMOJIS.get(position)
                    if emoji:
                        lines.append(f"{emoji} {name}")
                    elif position > 0:
                        lines.append(f"**{position}.** {name}")
                    else:
                        lines.append(f"\u2014. {name}")

                for p in data["in_progress"]:
                    name = name_map.get(p["account_id"], "Unknown")
                    lines.append(f"\U0001f535 {name} *(in progress)*")

                alive = sum(1 for d in by_division.values()
                            for p in d["in_progress"] if p["division"] == div)
                div_label = f"**Division {div}**"
                if alive:
                    div_label += f" (\U0001f535 {alive} alive)"
                embed.add_field(
                    name=div_label,
                    value="\n".join(lines) if lines else "No Belgian players",
                    inline=False,
                )

        thumbnail = map_info.get("thumbnail_url", "")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        embed.set_footer(text=f"By Luckyboi61 \u2022 COTD #{edition}")

        await destination.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Cotd(bot))
