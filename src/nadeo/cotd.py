import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set

from .client import NadeoClient

logger = logging.getLogger(__name__)


class COTDClient:
    MEET_API = "https://meet.trackmania.nadeo.live/api"
    LIVE_API = "https://live-services.trackmania.nadeo.live/api/token"

    DIVISION_SIZE = 64
    MAX_DIVISIONS = 10

    CUP_NAME_PATTERNS = {
        "cotd": "cup of the day",
        "cotn": "cup of the night",
        "cotm": "cup of the morning",
    }

    CUP_LABELS = {
        "cotd": "Cup of the Day",
        "cotn": "Cup of the Night",
        "cotm": "Cup of the Morning",
    }

    def __init__(self, nadeo_client: NadeoClient):
        self.nadeo_client = nadeo_client

    async def _get_json(self, url: str, region: str = "NadeoLiveServices") -> Any:
        async with self.nadeo_client.get(url, region=region) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"GET {url} failed: {resp.status} - {text[:200]}")
            return await resp.json()

    async def get_current_cup(self) -> Optional[Dict[str, Any]]:
        url = f"{self.MEET_API}/cup-of-the-day/current"
        try:
            data = await self._get_json(url)
            return data if data else None
        except Exception as e:
            logger.debug(f"cup-of-the-day/current not available: {e}")
            return None

    async def get_cup_by_offset(self, edition: int) -> Optional[Dict[str, Any]]:
        url = f"{self.MEET_API}/cup-of-the-day/current?edition={edition}"
        try:
            data = await self._get_json(url)
            return data if data else None
        except Exception as e:
            logger.debug(f"cup-of-the-day/current?edition={edition} failed: {e}")
            return None

    async def find_cup(self, cup_type: str) -> Dict[str, Any]:
        cup_type = cup_type.lower()
        if cup_type not in self.CUP_NAME_PATTERNS:
            raise ValueError(f"Unknown cup type: {cup_type}")

        cup = await self.get_current_cup()
        if cup:
            return cup

        raise Exception(
            f"cup-of-the-day/current returned no data for {cup_type}"
        )

    @staticmethod
    def _extract_id(value: Any) -> Optional[Any]:
        if value is None:
            return None
        if isinstance(value, (str, int)):
            return value
        if isinstance(value, dict):
            for key in ("id", "uid", "competitionId", "challengeId"):
                if key in value:
                    return value[key]
        return value

    @staticmethod
    def _extract_competition_id(cup: Dict[str, Any]) -> Optional[Any]:
        for key in ("competitionId", "competition_id", "competitionUid", "competition"):
            if key in cup:
                return COTDClient._extract_id(cup[key])
        return None

    @staticmethod
    def _extract_challenge_id(
        cup: Dict[str, Any], competition: Dict[str, Any]
    ) -> Optional[Any]:
        challenge_obj = cup.get("challenge")
        if isinstance(challenge_obj, dict):
            cid = challenge_obj.get("id")
            if cid:
                return cid
        for source in (cup, competition):
            for key in ("challengeId", "challenge_id"):
                if key in source and source[key]:
                    val = source[key]
                    if isinstance(val, dict):
                        if val.get("id"):
                            return val["id"]
                    elif val is not None:
                        return val
        return None

    async def get_competition(self, competition_id: int) -> Dict[str, Any]:
        url = f"{self.MEET_API}/competitions/{competition_id}"
        return await self._get_json(url)

    async def get_competition_rounds(
        self, competition_id: int, length: int = 100
    ) -> List[Dict[str, Any]]:
        url = f"{self.MEET_API}/competitions/{competition_id}/rounds?length={length}&offset=0"
        data = await self._get_json(url)
        if isinstance(data, list):
            return data
        return data.get("rounds", []) or []

    async def get_round_matches(
        self, round_id: Any, length: int = 200
    ) -> List[Dict[str, Any]]:
        url = f"{self.MEET_API}/rounds/{round_id}/matches?length={length}&offset=0"
        try:
            data = await self._get_json(url)
        except Exception as e:
            logger.debug(f"rounds/{round_id}/matches not available: {e}")
            return []
        if isinstance(data, list):
            return data
        return data.get("matches", []) or []

    async def get_match_results(self, match_id: str) -> List[Dict[str, Any]]:
        url = f"{self.MEET_API}/matches/{match_id}/results"
        data = await self._get_json(url)
        if isinstance(data, list):
            return data
        return data.get("results", []) or []

    async def get_challenge_leaderboard(
        self, challenge_id: Any, limit: int = 10000
    ) -> List[Dict[str, Any]]:
        page_size = 100
        all_entries = []
        seen_accounts = set()

        for offset in range(0, min(limit, 10000), page_size):
            url = (
                f"{self.MEET_API}/challenges/{challenge_id}/leaderboard"
                f"?length={page_size}&offset={offset}"
            )
            async with self.nadeo_client.get(url) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"Failed to fetch challenge leaderboard at offset {offset}: {resp.status}"
                    )
                    break
                data = await resp.json()

            results = data.get("results", [])
            if not results:
                break

            page_entries = []
            for r in results:
                aid = r.get("player") or r.get("accountId")
                if aid and aid not in seen_accounts:
                    seen_accounts.add(aid)
                    page_entries.append({
                        "account_id": aid,
                        "world_rank": r.get("rank", 0) or 0,
                        "time_ms": r.get("score", 0) or 0,
                    })

            if not page_entries:
                break
            all_entries.extend(page_entries)

            if len(page_entries) < page_size:
                break

        return all_entries

    @classmethod
    def get_division(cls, world_rank: int) -> int:
        if world_rank <= 0:
            return 0
        return (world_rank - 1) // cls.DIVISION_SIZE + 1

    async def _fetch_all_match_results(
        self, rounds: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        match_ids = []
        match_round_map: Dict[str, int] = {}

        round_match_lists = await asyncio.gather(
            *(self.get_round_matches(
                r.get("id") or r.get("roundId") or r.get("roundUid")
            ) for r in rounds),
            return_exceptions=True,
        )

        for round_data, match_list in zip(rounds, round_match_lists):
            round_id = (
                round_data.get("id")
                or round_data.get("roundId")
                or round_data.get("roundUid")
                or 0
            )
            if isinstance(match_list, Exception):
                logger.warning(
                    f"Failed to fetch matches for round {round_id}: {match_list}"
                )
                continue
            for match in match_list:
                mid = match.get("id") or match.get("matchId") or match.get("matchUid")
                if mid:
                    match_ids.append(mid)
                    match_round_map[mid] = round_id

        if not match_ids:
            return []

        results_lists = await asyncio.gather(
            *(self.get_match_results(mid) for mid in match_ids),
            return_exceptions=True,
        )

        aggregated = []
        for mid, results in zip(match_ids, results_lists):
            if isinstance(results, Exception):
                logger.warning(f"Failed to fetch match {mid} results: {results}")
                continue
            round_id = match_round_map[mid]
            for r in results:
                r["_round_id"] = round_id
                r["_match_id"] = mid
            aggregated.extend(results)

        return aggregated

    async def fetch_qualifier_data(
        self,
        cup_type: str,
        belgian_ids: Set[str],
    ) -> Dict[str, Any]:
        cup_type = cup_type.lower()
        cup = await self.find_cup(cup_type)
        cup_label = self.CUP_LABELS.get(cup_type, cup.get("name", "Cup of the Day"))

        competition_id = self._extract_competition_id(cup)
        if not competition_id:
            raise Exception(f"Cup has no competition ID: {list(cup.keys())}")

        competition = await self.get_competition(competition_id)
        challenge_id = self._extract_challenge_id(cup, competition)
        if not challenge_id:
            raise Exception(
                f"No challenge ID in cup or competition. "
                f"cup={list(cup.keys())}, competition={list(competition.keys())}"
            )

        leaderboard = await self.get_challenge_leaderboard(challenge_id, limit=10000)

        qualifier_entries: List[Dict[str, Any]] = []
        qualifier_by_aid: Dict[str, Dict[str, Any]] = {}
        for entry in leaderboard:
            aid = entry["account_id"]
            if aid not in belgian_ids:
                continue
            rank = entry["world_rank"]
            division = self.get_division(rank)
            if division < 1 or division > self.MAX_DIVISIONS:
                continue
            qual_entry = {
                "account_id": aid,
                "world_rank": rank,
                "time_ms": entry["time_ms"],
                "division": division,
            }
            qualifier_entries.append(qual_entry)
            qualifier_by_aid[aid] = qual_entry

        qualifier_entries.sort(key=lambda e: (e["division"], e["world_rank"]))

        return {
            "cup_type": cup_type,
            "cup_label": cup_label,
            "cup": cup,
            "competition": competition,
            "challenge_id": challenge_id,
            "competition_id": competition_id,
            "qualifier": qualifier_entries,
            "qualifier_by_aid": qualifier_by_aid,
        }

    async def fetch_rounds_data(
        self,
        cup_type: str,
        belgian_ids: Set[str],
    ) -> Dict[str, Any]:
        qual_data = await self.fetch_qualifier_data(cup_type, belgian_ids)
        qualifier_by_aid = qual_data["qualifier_by_aid"]
        competition_id = qual_data["competition_id"]

        rounds = await self.get_competition_rounds(competition_id)
        all_results = await self._fetch_all_match_results(rounds)

        player_best: Dict[str, Dict[str, Any]] = {}
        for result in all_results:
            aid = result.get("accountId") or result.get("account_id")
            if not aid or aid not in belgian_ids:
                continue
            if aid not in qualifier_by_aid:
                continue
            position = result.get("position", 0) or 0
            round_id = result.get("_round_id", 0) or 0
            existing = player_best.get(aid)
            if not existing or round_id > existing["round_id"]:
                player_best[aid] = {
                    "account_id": aid,
                    "position": position,
                    "round_id": round_id,
                }

        rounds_entries: List[Dict[str, Any]] = []
        for player in player_best.values():
            qual = qualifier_by_aid[player["account_id"]]
            rounds_entries.append({
                "account_id": player["account_id"],
                "division": qual["division"],
                "position": player["position"],
            })

        rounds_entries.sort(key=lambda e: (e["division"], e["position"]))

        return {**qual_data, "rounds": rounds_entries}
