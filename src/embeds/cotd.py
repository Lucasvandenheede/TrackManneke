from collections import defaultdict
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
    def _group_by_division(
        entries: List[Dict[str, Any]],
    ) -> "defaultdict[int, List[Dict[str, Any]]]":
        groups: "defaultdict[int, List[Dict[str, Any]]]" = defaultdict(list)
        for entry in entries:
            div = entry.get("division", 0)
            if div < 1:
                continue
            groups[div].append(entry)
        return groups

    @staticmethod
    def _resolve_names(
        entries: List[Dict[str, Any]], name_map: Dict[str, str]
    ) -> None:
        for entry in entries:
            aid = entry.get("account_id", "")
            entry["player_name"] = name_map.get(aid, "Unknown")

    @staticmethod
    def build_qualifier(
        cup_label: str,
        map_info: Dict[str, Any],
        qualifier_entries: List[Dict[str, Any]],
        name_map: Dict[str, str],
    ) -> discord.Embed:
        COTDEmbed._resolve_names(qualifier_entries, name_map)

        embed = discord.Embed(
            title=f"{cup_label} - Qualifier Results",
            description=COTDEmbed._build_description(map_info),
            colour=COTDEmbed.BELGIAN_RED,
        )

        groups = COTDEmbed._group_by_division(qualifier_entries)
        if not groups:
            embed.add_field(
                name="\u200b",
                value=(
                    "No Belgian players found in the Top 10 divisions for this qualifier."
                ),
                inline=False,
            )
        else:
            for div in sorted(groups.keys()):
                players = sorted(groups[div], key=lambda p: p["world_rank"])
                lines = []
                for p in players:
                    time_str = format_time_ms(p["time_ms"])
                    name = p.get("player_name", "Unknown")
                    lines.append(
                        f"**{p['world_rank']}.** {name} ({time_str})"
                    )
                embed.add_field(
                    name=f"**Division {div}**",
                    value="\n".join(lines),
                    inline=False,
                )

        thumbnail = map_info.get("thumbnail_url", "")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.set_footer(text="By Luckyboi61")
        return embed

    @staticmethod
    def build_rounds(
        cup_label: str,
        map_info: Dict[str, Any],
        rounds_entries: List[Dict[str, Any]],
        name_map: Dict[str, str],
    ) -> discord.Embed:
        COTDEmbed._resolve_names(rounds_entries, name_map)

        embed = discord.Embed(
            title=f"{cup_label} - Rounds Results",
            description=COTDEmbed._build_description(map_info),
            colour=COTDEmbed.BELGIAN_RED,
        )

        groups = COTDEmbed._group_by_division(rounds_entries)
        if not groups:
            embed.add_field(
                name="\u200b",
                value=(
                    "No Belgian players found in the Top 10 divisions for this round."
                ),
                inline=False,
            )
        else:
            for div in sorted(groups.keys()):
                players = sorted(groups[div], key=lambda p: p["position"])
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
                        lines.append(name)
                embed.add_field(
                    name=f"**Division {div}**",
                    value="\n".join(lines),
                    inline=False,
                )

        thumbnail = map_info.get("thumbnail_url", "")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.set_footer(text="By Luckyboi61")
        return embed
