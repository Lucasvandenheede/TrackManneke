import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set

from .client import NadeoClient

logger = logging.getLogger(__name__)


class COTDClient:
    MEET_API = "https://meet.trackmania.nadeo.club/api"
    LIVE_API = "https://live-services.trackmania.nadeo.live/api/token"

    DIVISION_SIZE = 64
    MAX_DIVISIONS = 10

    def __init__(self, nadeo_client: NadeoClient):
        self.nadeo_client = nadeo_client

    def _is_204_exception(self, e: Exception) -> bool:
        return "204" in str(e)

    async def _get_json(self, url: str, region: str = "NadeoLiveServices") -> Any:
        async with self.nadeo_client.get(url, region=region) as resp:
            if resp.status == 204:
                raise Exception(f"GET {url} failed: 204 No Content")
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"GET {url} failed: {resp.status} - {text[:200]}")
            return await resp.json()

    async def _request_json_or_204(self, url: str, region: str = "NadeoLiveServices") -> Any:
        async with self.nadeo_client.get(url, region=region) as resp:
            if resp.status == 204:
                return None
            if resp.status != 200:
                text = await resp.text()
                logger.warning(f"GET {url} failed: {resp.status} - {text[:200]}")
                return None
            return await resp.json()

    async def get_current_cup(self) -> Optional[Dict[str, Any]]:
        url = f"{self.MEET_API}/cup-of-the-day/current"
        data = await self._request_json_or_204(url)
        if data is None:
            logger.info("cup-of-the-day/current returned 204 — no active COTD")
            return None
        return data if isinstance(data, dict) else None

    async def get_official_cups(
        self, length: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        url = f"{self.MEET_API}/cups-of-the-day?type=cotd&length={length}&offset={offset}"
        data = await self._request_json_or_204(url)
        if data is None:
            logger.warning("cups-of-the-day returned 204 (no data)")
            return []
        if isinstance(data, list):
            logger.info(f"cups-of-the-day returned {len(data)} cups (array)")
            return data
        if isinstance(data, dict):
            wrapped = data.get("COTDs", data.get("results", []))
            logger.info(f"cups-of-the-day returned {len(wrapped)} cups under 'COTDs' key")
            return wrapped
        logger.warning(f"cups-of-the-day returned unexpected type: {type(data).__name__}")
        return []

    async def get_last_completed_cup(self) -> Optional[Dict[str, Any]]:
        cups = await self.get_official_cups(length=50, offset=0)
        if not cups:
            logger.warning("No cups-of-the-day found")
            return None

        now_ts = int(datetime.now(timezone.utc).timestamp())
        eligible = []
        for cup in cups:
            competition = cup.get("competition") or {}
            if competition.get("partition") != "crossplay":
                continue
            start = cup.get("startDate") or cup.get("startTimestamp")
            if not start or start > now_ts:
                continue
            end = cup.get("endDate") or cup.get("endTimestamp")
            if not end or end > now_ts:
                continue
            eligible.append(cup)

        if not eligible:
            total = len(cups)
            non_crossplay = sum(
                1 for c in cups if (c.get("competition") or {}).get("partition") != "crossplay"
            )
            future = sum(
                1 for c in cups
                if (c.get("competition") or {}).get("partition") == "crossplay"
                and (c.get("startDate") or 0) > now_ts
            )
            logger.warning(
                f"No eligible crossplay cups for fallback "
                f"({total} total, {non_crossplay} non-crossplay, {future} future)"
            )
            return None

        eligible.sort(
            key=lambda c: c.get("endDate") or c.get("endTimestamp", 0),
            reverse=True,
        )
        latest = eligible[0]

        challenge_obj = latest.get("challenge") or {}
        competition_obj = latest.get("competition") or {}
        challenge_id = challenge_obj.get("id")
        competition_id = competition_obj.get("id")

        cup = {
            "edition": latest.get("edition", 1),
            "id": latest.get("id"),
            "startDate": latest.get("startDate") or latest.get("startTimestamp", 0),
            "endDate": latest.get("endDate") or latest.get("endTimestamp", 0),
            "challenge": {"id": challenge_id} if challenge_id else {},
            "competition": {"id": competition_id} if competition_id else {},
        }
        logger.info(
            f"Selected crossplay cup (competition {competition_id}, "
            f"challenge_id={challenge_id}, edition {cup['edition']})"
        )
        return cup

    async def get_competition_rounds(
        self, competition_id: int, length: int = 10
    ) -> List[Dict[str, Any]]:
        url = f"{self.MEET_API}/competitions/{competition_id}/rounds?length={length}&offset=0"
        try:
            data = await self._get_json(url)
        except Exception as e:
            logger.debug(f"competitions/{competition_id}/rounds: {e}")
            return []
        if isinstance(data, list):
            return data
        return data.get("rounds", []) or []

    async def get_round_matches(
        self, round_id: Any, length: int = 100
    ) -> List[Dict[str, Any]]:
        url = f"{self.MEET_API}/rounds/{round_id}/matches?length={length}&offset=0"
        try:
            data = await self._get_json(url)
        except Exception as e:
            logger.debug(f"rounds/{round_id}/matches: {e}")
            return []
        if isinstance(data, dict) and "matches" in data:
            return data["matches"]
        if isinstance(data, list):
            return data
        return []


    async def get_match_results(
        self, match_id: str, length: int = 64
    ) -> List[Dict[str, Any]]:
        url = f"{self.MEET_API}/matches/{match_id}/results?length={length}"
        data = await self._get_json(url)
        if isinstance(data, list):
            return data
        return data.get("results", []) or []

    async def get_challenge_leaderboard_page(
        self, challenge_id: Any, length: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        url = (
            f"{self.MEET_API}/challenges/{challenge_id}/leaderboard"
            f"?length={length}&offset={offset}"
        )
        async with self.nadeo_client.get(url) as resp:
            if resp.status != 200:
                logger.warning(
                    f"Failed to fetch challenge leaderboard at offset {offset}: {resp.status}"
                )
                return []
            data = await resp.json()

        results = data.get("results", [])
        entries = []
        for r in results:
            aid = r.get("player") or r.get("accountId")
            if aid:
                entries.append({
                    "account_id": aid,
                    "world_rank": r.get("rank", 0) or 0,
                    "time_ms": r.get("score", 0) or 0,
                })
        return entries

    async def get_challenge_leaderboard(
        self, challenge_id: Any, limit: int = 10000
    ) -> List[Dict[str, Any]]:
        page_size = 100
        all_entries = []
        seen_accounts = set()

        for offset in range(0, min(limit, 10000), page_size):
            entries = await self.get_challenge_leaderboard_page(
                challenge_id, length=page_size, offset=offset
            )
            filtered = [e for e in entries if e["account_id"] not in seen_accounts]
            for e in filtered:
                seen_accounts.add(e["account_id"])
            all_entries.extend(filtered)
            if len(entries) < page_size:
                break

        return all_entries

    @classmethod
    def get_division(cls, world_rank: int) -> int:
        if world_rank <= 0:
            return 0
        return (world_rank - 1) // cls.DIVISION_SIZE + 1

    @staticmethod
    def group_by_division(results: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
        groups: Dict[int, List[Dict[str, Any]]] = {}
        for r in results:
            rank = r.get("world_rank", 0)
            if rank:
                div = (rank - 1) // 64 + 1
                if 1 <= div <= 10:
                    groups.setdefault(div, []).append(r)
        return groups

    async def get_all_qualifier_results(
        self, challenge_id: Any, max_players: int = 3000
    ) -> List[Dict[str, Any]]:
        all_results = []
        page_size = 100
        for offset in range(0, max_players, page_size):
            entries = await self.get_challenge_leaderboard_page(
                challenge_id, length=page_size, offset=offset
            )
            all_results.extend(entries)
            if len(entries) < page_size:
                break
        return all_results[:max_players]

    @staticmethod
    def get_division_cutoffs(all_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        cutoffs = {}
        for div in range(1, 11):
            rank = div * 64
            entry = next(
                (r for r in all_results if int(r.get("world_rank", 0)) == rank), None
            )
            if entry:
                cutoffs[f"div{div}_cutoff"] = {
                    "world_rank": rank,
                    "account_id": entry.get("account_id", ""),
                    "time_ms": entry.get("time_ms", 0),
                }
            else:
                break
        return cutoffs

    @staticmethod
    def filter_belgian(
        results: List[Dict[str, Any]], belgian_ids: Set[str]
    ) -> List[Dict[str, Any]]:
        return [r for r in results if r["account_id"] in belgian_ids]

    async def get_rounds_and_matches(
        self, competition_id: int
    ) -> List[Dict[str, Any]]:
        rounds = await self.get_competition_rounds(competition_id)
        if not rounds:
            return []
        round_id = rounds[0].get("id") or rounds[0].get("roundId")
        if not round_id:
            return []
        return await self.get_round_matches(round_id)

    async def get_belgian_rounds_results(
        self, competition_id: int, belgian_ids: Set[str]
    ) -> List[Dict[str, str]]:
        matches = await self.get_rounds_and_matches(competition_id)
        if not matches:
            return []

        completed = [m for m in matches if m.get("completed", m.get("isCompleted", False))]
        if len(completed) != len(matches):
            return []

        results = []
        for match in completed:
            mid = match.get("id") or match.get("matchId")
            if not mid:
                continue
            div_num = (match.get("position", 0) or 0) + 1
            if div_num > 10:
                continue

            try:
                match_results = await self.get_match_results(mid, length=64)
            except Exception:
                continue
            for mr in match_results:
                aid = mr.get("participant") or mr.get("accountId") or mr.get("account_id")
                if aid and aid in belgian_ids:
                    results.append({
                        "account_id": aid,
                        "division": div_num,
                        "position": mr.get("rank", 0) or 0,
                    })

        results.sort(key=lambda e: (e["division"], e["position"]))
        return results

    async def get_rounds_status(
        self, competition_id: int, belgian_ids: Set[str]
    ) -> Dict[str, Any]:
        matches = await self.get_rounds_and_matches(competition_id)
        if not matches:
            return {"completed": [], "in_progress": [], "all_completed": False, "total_matches": 0, "completed_matches": 0}

        total = len(matches)
        completed_matches = [m for m in matches if m.get("completed", m.get("isCompleted", False))]
        in_progress_matches = [m for m in matches if not m.get("completed", m.get("isCompleted", False))]

        completed_results = []
        for match in completed_matches:
            mid = match.get("id") or match.get("matchId")
            if not mid:
                continue
            div_num = (match.get("position", 0) or 0) + 1
            if div_num > 10:
                continue
            try:
                match_results = await self.get_match_results(mid, length=64)
            except Exception:
                continue
            for mr in match_results:
                aid = mr.get("participant") or mr.get("accountId") or mr.get("account_id")
                if aid and aid in belgian_ids:
                    completed_results.append({
                        "account_id": aid,
                        "division": div_num,
                        "position": mr.get("rank", 0) or 0,
                    })

        in_progress_players = []
        for match in in_progress_matches:
            mid = match.get("id") or match.get("matchId")
            if not mid:
                continue
            div_num = (match.get("position", 0) or 0) + 1
            if div_num > 10:
                continue
            try:
                match_results = await self.get_match_results(mid, length=64)
            except Exception:
                continue
            for mr in match_results:
                aid = mr.get("participant") or mr.get("accountId") or mr.get("account_id")
                if aid and aid in belgian_ids:
                    in_progress_players.append({
                        "account_id": aid,
                        "division": div_num,
                        "match_id": mid,
                    })

        completed_results.sort(key=lambda e: (e["division"], e["position"]))
        return {
            "completed": completed_results,
            "in_progress": in_progress_players,
            "all_completed": len(completed_matches) == total,
            "total_matches": total,
            "completed_matches": len(completed_matches),
        }

    async def get_bracket_division_results(
        self, match_id: Any, division_num: int, belgian_ids: Set[str]
    ) -> Optional[Dict[str, Any]]:
        try:
            data = await self.get_match_results(match_id, length=64)
        except Exception:
            return None
        if not data:
            return None
        belgian_entries = []
        for mr in data:
            aid = mr.get("participant") or mr.get("accountId") or mr.get("account_id")
            if aid and aid in belgian_ids:
                belgian_entries.append({
                    "account_id": aid,
                    "division": division_num,
                    "position": mr.get("rank", 0) or 0,
                })
        if not belgian_entries:
            return None
        belgian_entries.sort(key=lambda e: e["position"])
        return {
            "division": division_num,
            "entries": belgian_entries,
        }
