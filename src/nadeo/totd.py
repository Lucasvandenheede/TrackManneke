import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set

from .client import NadeoClient
from src.utils.formatters import strip_tm_formatting

logger = logging.getLogger(__name__)


class TOTDClient:
    LIVE_API = "https://live-services.trackmania.nadeo.live/api/token"
    CORE_API = "https://prod.trackmania.core.nadeo.online"
    BELGIUM_NAMES = {"belgium", "belgië", "belgique", "belgien"}

    def __init__(self, nadeo_client: NadeoClient):
        self.nadeo_client = nadeo_client
        self._belgian_zone_ids: Optional[Set[str]] = None
        self._all_zones: Optional[List[Dict[str, Any]]] = None

    async def _fetch_zones(self) -> List[Dict[str, Any]]:
        if self._all_zones is not None:
            return self._all_zones
        url = f"{self.CORE_API}/zones/"
        async with self.nadeo_client.get(url, region="NadeoServices") as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch zones: {resp.status}")
            self._all_zones = await resp.json()
        return self._all_zones

    def _build_zone_tree(self, zones: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        children: Dict[str, List[str]] = {}
        for z in zones:
            parent = z.get("parentId")
            if parent:
                children.setdefault(parent, []).append(z["zoneId"])
        return children

    async def _get_belgian_zone_ids(self) -> Set[str]:
        if self._belgian_zone_ids is not None:
            return self._belgian_zone_ids

        zones = await self._fetch_zones()
        zone_by_id = {z["zoneId"]: z for z in zones}

        belgium_root_ids = set()
        for z in zones:
            if z.get("name", "").strip().lower() in self.BELGIUM_NAMES:
                belgium_root_ids.add(z["zoneId"])

        if not belgium_root_ids:
            logger.warning("Could not find Belgium zone, no players will be auto-detected")
            self._belgian_zone_ids = set()
            return self._belgian_zone_ids

        tree = self._build_zone_tree(zones)
        result = set(belgium_root_ids)
        stack = list(belgium_root_ids)
        while stack:
            zid = stack.pop()
            for child in tree.get(zid, []):
                if child not in result:
                    result.add(child)
                    stack.append(child)

        logger.info(f"Found {len(result)} Belgian zone IDs")
        self._belgian_zone_ids = result
        return result

    async def get_current_totd(self, oauth_client=None) -> Dict[str, Any]:
        url = f"{self.LIVE_API}/campaign/month?offset=0&length=1"
        async with self.nadeo_client.get(url) as resp:
            if resp.status != 200:
                logger.error(f"Failed to fetch TOTD calendar: {resp.status}")
                raise Exception(f"Failed to fetch TOTD calendar: {resp.status}")
            data = await resp.json()

        if not data.get("monthList"):
            raise Exception("No TOTD calendar data available")

        now_ts = int(datetime.now(timezone.utc).timestamp())
        month_data = data["monthList"][0]
        current_entry = None
        for day in month_data.get("days", []):
            start = day.get("startTimestamp", 0)
            end = day.get("endTimestamp", 0)
            if start <= now_ts < end:
                current_entry = day
                break

        if not current_entry:
            raise Exception("No active TOTD found for the current time")

        map_uid = current_entry.get("mapUid")
        if not map_uid:
            raise Exception("TOTD map has not been announced yet for this time slot")

        map_url = f"{self.LIVE_API}/map/{map_uid}"
        async with self.nadeo_client.get(map_url) as resp:
            if resp.status != 200:
                logger.error(f"Failed to fetch map info: {resp.status}")
                raise Exception(f"Failed to fetch map info: {resp.status}")
            map_info = await resp.json()

        author_name = map_info.get("author", "Unknown")
        if oauth_client and map_info.get("author"):
            try:
                names = await oauth_client.get_display_names([map_info["author"]])
                if map_info["author"] in names:
                    author_name = names[map_info["author"]]
            except Exception as e:
                logger.warning(f"Failed to resolve author display name: {e}")

        return {
            "map_id": map_info.get("mapId", ""),
            "map_uid": map_uid,
            "season_uid": current_entry.get("seasonUid", ""),
            "name": strip_tm_formatting(map_info.get("name", "Unknown Map")),
            "author_account_id": map_info.get("author", ""),
            "author_name": author_name,
            "medal_time": map_info.get("authorTime", 0),
            "image_url": map_info.get("thumbnailUrl", ""),
            "totd_day": current_entry.get("monthDay"),
            "totd_year": month_data.get("year"),
            "totd_month": month_data.get("month"),
        }

    async def get_totd_leaderboard(
        self, map_uid: str, limit: int = 3000
    ) -> List[Dict[str, Any]]:
        page_size = 100
        all_entries = []
        seen_accounts = set()

        for offset in range(0, min(limit, 10000), page_size):
            url = (
                f"{self.LIVE_API}/leaderboard/group/Personal_Best/map/{map_uid}/top"
                f"?onlyWorld=true&length={page_size}&offset={offset}"
            )
            async with self.nadeo_client.get(url) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"Failed to fetch leaderboard at offset {offset}: {resp.status}"
                    )
                    break
                data = await resp.json()

            page_entries = []
            for zone in data.get("tops", []):
                for entry in zone.get("top", []):
                    aid = entry.get("accountId")
                    if aid and aid not in seen_accounts:
                        seen_accounts.add(aid)
                        page_entries.append({
                            "account_id": aid,
                            "zone_id": entry.get("zoneId", ""),
                            "zone_name": entry.get("zoneName", ""),
                            "world_rank": entry.get("position", 0),
                            "time_ms": entry.get("score", 0),
                        })

            if not page_entries:
                break
            all_entries.extend(page_entries)

            if len(page_entries) < page_size:
                break

        return all_entries

    async def get_belgian_zone_ids(self) -> Set[str]:
        return await self._get_belgian_zone_ids()

    async def get_totd_zone_map(
        self, oauth_client=None, limit: int = 3000
    ) -> Dict[str, str]:
        totd = await self.get_current_totd(oauth_client=oauth_client)
        map_uid = totd.get("map_uid")
        if not map_uid:
            return {}
        leaderboard = await self.get_totd_leaderboard(map_uid, limit=limit)
        return {e["account_id"]: e["zone_id"] for e in leaderboard if e.get("zone_id")}

    async def get_belgian_leaderboard(
        self, map_uid: str, tracked_players: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        tracked_ids = {p["account_id"] for p in tracked_players}
        name_map = {p["account_id"]: p["player_name"] for p in tracked_players}

        leaderboard = await self.get_totd_leaderboard(map_uid, limit=3000)

        belgian_zone_ids = await self._get_belgian_zone_ids()
        new_ids = set()

        results = []
        for entry in leaderboard:
            aid = entry["account_id"]
            is_belgian = aid in tracked_ids or entry.get("zone_id") in belgian_zone_ids
            if not is_belgian:
                continue

            if aid not in tracked_ids:
                new_ids.add(aid)

            results.append({
                "world_rank": entry["world_rank"],
                "account_id": aid,
                "player_name": name_map.get(aid, "Unknown"),
                "time_ms": entry["time_ms"],
            })

        results.sort(key=lambda x: x["world_rank"])

        return {
            "entries": results[:25],
            "new_player_ids": list(new_ids),
        }
