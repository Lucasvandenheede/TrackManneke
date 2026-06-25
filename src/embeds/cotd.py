from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Any, List
import discord
import src.config as config
from src.utils.formatters import format_time_ms


class COTDEmbed:
    BELGIAN_RED = 0xFF0000

    PODIUM_EMOJIS = {
        1: "\U0001f3c6",
        2: "\U0001f948",
        3: "\U0001f949",
    }

    @staticmethod
    def _build_description(map_info: Dict[str, Any]) -> str:
        name = map_info.get("name", "Unknown Map")
        author = map_info.get("author_name", "Unknown")
        author_id = map_info.get("author_account_id", "")
        author_time_ms = map_info.get("author_time", 0)
        author_time = format_time_ms(author_time_ms)
        map_uid = map_info.get("map_uid", "")
        season_uid = map_info.get("season_uid", "")

        if season_uid and map_uid:
            map_url = (
                f"https://trackmania.io/#/totd/leaderboard/{season_uid}/{map_uid}"
            )
        elif map_uid:
            map_url = f"https://trackmania.io/#/map/{map_uid}"
        else:
            map_url = ""

        if author_id:
            player_url = f"https://trackmania.io/#/player/{author_id}"
        else:
            player_url = ""

        if map_url:
            map_line = f"[{name}]({map_url})"
        else:
            map_line = name

        if player_url:
            author_line = f"by [{author}]({player_url})"
        else:
            author_line = f"by {author}"

        return f"{map_line}\n{author_line}\n{config.EMOTE_AT} {author_time}"

    @staticmethod
    def _resolve_names(
        entries: List[Dict[str, Any]], name_map: Dict[str, str]
    ) -> None:
        for entry in entries:
            aid = entry.get("account_id", "")
            entry["player_name"] = name_map.get(aid, entry.get("player_name", "Unknown"))

    @staticmethod
    def _format_time_for_entry(entry: Dict[str, Any]) -> str:
        raw = entry.get("time_ms", entry.get("score", 0))
        if isinstance(raw, int) and raw > 0:
            return format_time_ms(raw)
        return str(raw) if raw else "-:--.---"

    @staticmethod
    def build_qualifier(
        edition: int,
        map_info: Dict[str, Any],
        qualifier_entries: List[Dict[str, Any]],
        name_map: Dict[str, str],
        cutoff_entry: Dict[str, Any] = None,
    ) -> discord.Embed:
        COTDEmbed._resolve_names(qualifier_entries, name_map)

        embed = discord.Embed(
            title="Cup of the Day - Qualifier Results",
            description=COTDEmbed._build_description(map_info),
            colour=COTDEmbed.BELGIAN_RED,
            timestamp=datetime.now(timezone.utc),
        )

        cutoff_line = None
        if cutoff_entry:
            cutoff_time = COTDEmbed._format_time_for_entry(cutoff_entry)
            cutoff_line = f"**64.** cutoff ({cutoff_time})"

        by_division = defaultdict(list)
        for entry in qualifier_entries:
            div = entry.get("division", 0)
            if 1 <= div <= 10:
                by_division[div].append(entry)

        all_divs = set(by_division.keys())
        if cutoff_line:
            all_divs.add(1)

        if not all_divs:
            embed.add_field(
                name="\u200b",
                value="No Belgian players found in divisions 1-10.",
                inline=False,
            )
        else:
            for div in sorted(all_divs):
                players = sorted(by_division.get(div, []), key=lambda p: p["world_rank"])
                lines = []
                for p in players:
                    time_str = COTDEmbed._format_time_for_entry(p)
                    name = p.get("player_name", "Unknown")
                    lines.append(
                        f"**{p['world_rank']}.** {name} ({time_str})"
                    )

                if div == 1 and cutoff_line:
                    lines.append(cutoff_line)

                embed.add_field(
                    name=f"**Division {div}**",
                    value="\n".join(lines),
                    inline=False,
                )

        thumbnail = map_info.get("thumbnail_url", "")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.set_footer(text=f"By Luckyboi61 \u2022 COTD #{edition}")

        return embed

    @staticmethod
    def build_rounds(
        edition: int,
        map_info: Dict[str, Any],
        rounds_entries: List[Dict[str, Any]],
        name_map: Dict[str, str],
    ) -> discord.Embed:
        COTDEmbed._resolve_names(rounds_entries, name_map)

        embed = discord.Embed(
            title="Cup of the Day - Rounds Results",
            description=COTDEmbed._build_description(map_info),
            colour=COTDEmbed.BELGIAN_RED,
            timestamp=datetime.now(timezone.utc),
        )

        by_division = defaultdict(list)
        for entry in rounds_entries:
            div = entry.get("division", 0)
            if 1 <= div <= 10:
                by_division[div].append(entry)

        if not by_division:
            embed.add_field(
                name="\u200b",
                value="No Belgian players found in the top 10 divisions.",
                inline=False,
            )
        else:
            for div in sorted(by_division.keys()):
                players = sorted(by_division[div], key=lambda p: p["position"])
                lines = []
                for p in players:
                    name = p.get("player_name", "Unknown")
                    position = p["position"]
                    emoji = COTDEmbed.PODIUM_EMOJIS.get(position)
                    if emoji:
                        lines.append(f"{emoji} {name}")
                    elif position > 0:
                        lines.append(f"**{position}.** {name}")
                    else:
                        lines.append(f"\u2014. {name}")
                embed.add_field(
                    name=f"**Division {div}**",
                    value="\n".join(lines),
                    inline=False,
                )

        thumbnail = map_info.get("thumbnail_url", "")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.set_footer(text=f"By Luckyboi61 \u2022 COTD #{edition}")
        return embed
