from datetime import datetime, timezone
from typing import Dict, Any, List
import discord
import src.config as config
from src.utils.formatters import format_time_ms

class TOTDEmbed:
    BELGIAN_RED = 0xFF0000
    LEADERBOARD_LIMIT = 25

    @staticmethod
    def build(map_data: Dict[str, Any], belgian_entries: List[Dict[str, Any]]) -> discord.Embed:
        map_name = map_data.get("name", "Unknown Map")
        map_uid = map_data.get("map_uid", "")
        season_uid = map_data.get("season_uid", "")
        author_name = map_data.get("author_name", "Unknown Author")
        author_id = map_data.get("author_account_id", "")
        medal_time_ms = map_data.get("medal_time", 0)
        medal_time_str = format_time_ms(medal_time_ms)
        image_url = map_data.get("image_url", "")

        totd_url = f"https://trackmania.io/#/totd/leaderboard/{season_uid}/{map_uid}" if season_uid and map_uid else ""
        player_url = f"https://trackmania.io/#/player/{author_id}" if author_id else ""

        if totd_url:
            map_line = f"[{map_name}]({totd_url})"
        else:
            map_line = map_name

        if player_url:
            author_line = f"by [{author_name}]({player_url})"
        else:
            author_line = f"by {author_name}"

        description = f"{map_line}\n{author_line}\n{config.EMOTE_AT} {medal_time_str}"

        embed = discord.Embed(
            title="Track of the Day - Leaderboard",
            description=description,
            colour=TOTDEmbed.BELGIAN_RED,
            timestamp=datetime.now(timezone.utc),
        )

        leaderboard_text = TOTDEmbed._format_leaderboard(belgian_entries)
        embed.add_field(name="Leaderboard", value=leaderboard_text, inline=False)

        if image_url:
            embed.set_thumbnail(url=image_url)

        embed.set_footer(text="By Luckyboi61")

        return embed

    @staticmethod
    def _format_leaderboard(entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return "No Belgian times tracked for this map."

        lines = []
        for belgian_rank, player in enumerate(entries[: TOTDEmbed.LEADERBOARD_LIMIT], 1):
            player_name = player.get("player_name", "Unknown")
            time_str = format_time_ms(player.get("time_ms", 0))
            world_rank = player.get("world_rank", 0)
            rank_str = f"#{world_rank}" if world_rank else "N/A"
            lines.append(f"{belgian_rank:2d}. ({rank_str}) {player_name} - {time_str}")

        return "\n".join(lines)
