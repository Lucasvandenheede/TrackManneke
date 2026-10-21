import os
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "src/db/trackmania.db", dsn: Optional[str] = None):
        self.db_path = db_path
        self.dsn = dsn or os.getenv("DATABASE_URL")
        self._conn = None
        self._is_pg = False

    async def connect(self) -> None:
        if self.dsn and self.dsn.startswith("postgresql://"):
            import asyncpg
            self._conn = await asyncpg.connect(self.dsn)
            self._is_pg = True
            logger.info("Connected to PostgreSQL")
        else:
            import aiosqlite
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(str(self.db_path))
            self._conn.row_factory = aiosqlite.Row
            self._is_pg = False
            logger.info(f"Connected to SQLite: {self.db_path}")
        await self._init_schema()

    async def disconnect(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed")

    async def _init_schema(self) -> None:
        players_table = """
            CREATE TABLE IF NOT EXISTS players (
                account_id TEXT PRIMARY KEY,
                player_name TEXT NOT NULL UNIQUE,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        config_table = """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """
        if self._is_pg:
            await self._conn.execute(players_table)
            await self._conn.execute(config_table)
        else:
            await self._conn.execute(players_table)
            await self._conn.execute(config_table)
            await self._conn.commit()
        logger.debug("Database schema initialized")

    async def add_player(self, account_id: str, player_name: str) -> bool:
        try:
            if self._is_pg:
                result = await self._conn.execute(
                    "INSERT INTO players (account_id, player_name) VALUES ($1, $2) ON CONFLICT (account_id) DO NOTHING",
                    account_id, player_name,
                )
                inserted = int(result.split()[-1]) > 0
            else:
                cursor = await self._conn.execute(
                    "INSERT INTO players (account_id, player_name) VALUES (?, ?)",
                    (account_id, player_name),
                )
                await self._conn.commit()
                inserted = cursor.lastrowid is not None
            if inserted:
                logger.info(f"Added player: {player_name} ({account_id})")
                return True
            logger.warning(f"Player already exists: {player_name} ({account_id})")
            return False
        except Exception:
            logger.warning(f"Player already exists: {player_name} ({account_id})")
            return False

    async def remove_player(self, account_id: str) -> bool:
        if self._is_pg:
            result = await self._conn.execute(
                "DELETE FROM players WHERE account_id = $1", account_id,
            )
            removed = int(result.split()[-1]) > 0
        else:
            cursor = await self._conn.execute(
                "DELETE FROM players WHERE account_id = ?", (account_id,),
            )
            await self._conn.commit()
            removed = cursor.rowcount > 0
        if removed:
            logger.info(f"Removed player: {account_id}")
        else:
            logger.warning(f"Player not found: {account_id}")
        return removed

    async def get_player(self, account_id: str) -> Optional[Dict[str, Any]]:
        if self._is_pg:
            row = await self._conn.fetchrow(
                "SELECT account_id, player_name FROM players WHERE account_id = $1",
                account_id,
            )
        else:
            cursor = await self._conn.execute(
                "SELECT account_id, player_name FROM players WHERE account_id = ?",
                (account_id,),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_players(self) -> List[Dict[str, Any]]:
        if self._is_pg:
            rows = await self._conn.fetch(
                "SELECT account_id, player_name FROM players ORDER BY player_name",
            )
        else:
            cursor = await self._conn.execute(
                "SELECT account_id, player_name FROM players ORDER BY player_name",
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def player_exists(self, account_id: str) -> bool:
        if self._is_pg:
            row = await self._conn.fetchrow(
                "SELECT 1 FROM players WHERE account_id = $1", account_id,
            )
            return row is not None
        else:
            cursor = await self._conn.execute(
                "SELECT 1 FROM players WHERE account_id = ?", (account_id,),
            )
            return (await cursor.fetchone()) is not None

    async def save_discovered_player(self, account_id: str, player_name: str) -> bool:
        try:
            if self._is_pg:
                result = await self._conn.execute(
                    "INSERT INTO players (account_id, player_name) VALUES ($1, $2) ON CONFLICT (account_id) DO NOTHING",
                    account_id, player_name,
                )
                inserted = int(result.split()[-1]) > 0
            else:
                cursor = await self._conn.execute(
                    "INSERT OR IGNORE INTO players (account_id, player_name) VALUES (?, ?)",
                    (account_id, player_name),
                )
                await self._conn.commit()
                inserted = cursor.rowcount > 0
            if inserted:
                logger.info(f"Discovered new player: {player_name} ({account_id})")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to save discovered player: {e}")
            return False

    async def get_player_count(self) -> int:
        if self._is_pg:
            row = await self._conn.fetchrow("SELECT COUNT(*) AS cnt FROM players")
            return row["cnt"] if row else 0
        else:
            cursor = await self._conn.execute("SELECT COUNT(*) FROM players")
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def set_config(self, key: str, value: str) -> None:
        if self._is_pg:
            await self._conn.execute(
                "INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2",
                key, value,
            )
        else:
            await self._conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, value),
            )
            await self._conn.commit()
        logger.info(f"Set config: {key} = {value}")

    async def get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if self._is_pg:
            row = await self._conn.fetchrow(
                "SELECT value FROM config WHERE key = $1", key,
            )
            return row["value"] if row else default
        else:
            cursor = await self._conn.execute(
                "SELECT value FROM config WHERE key = ?", (key,),
            )
            row = await cursor.fetchone()
            return row[0] if row else default
