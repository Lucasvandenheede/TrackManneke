import logging
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "trackmania.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            logger.info(f"Connected to database: {self.db_path}")
            self._init_schema()
        except sqlite3.Error as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("Database connection closed")

    def _init_schema(self) -> None:
        if not self._conn:
            raise RuntimeError("Database not connected")

        cursor = self._conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                account_id TEXT PRIMARY KEY,
                player_name TEXT NOT NULL UNIQUE,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        self._conn.commit()
        logger.debug("Database schema initialized")

    def add_player(self, account_id: str, player_name: str) -> bool:
        if not self._conn:
            raise RuntimeError("Database not connected")

        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO players (account_id, player_name)
                VALUES (?, ?)
                """,
                (account_id, player_name),
            )
            self._conn.commit()
            logger.info(f"Added player: {player_name} ({account_id})")
            return True
        except sqlite3.IntegrityError:
            logger.warning(
                f"Player already exists: {player_name} ({account_id})"
            )
            return False
        except sqlite3.Error as e:
            logger.error(f"Failed to add player: {e}")
            raise

    def remove_player(self, account_id: str) -> bool:
        if not self._conn:
            raise RuntimeError("Database not connected")

        try:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM players WHERE account_id = ?", (account_id,))
            self._conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"Removed player: {account_id}")
                return True
            else:
                logger.warning(f"Player not found: {account_id}")
                return False
        except sqlite3.Error as e:
            logger.error(f"Failed to remove player: {e}")
            raise

    def get_player(self, account_id: str) -> Optional[Dict[str, Any]]:
        if not self._conn:
            raise RuntimeError("Database not connected")

        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT account_id, player_name FROM players WHERE account_id = ?",
                (account_id,),
            )
            row = cursor.fetchone()

            if row:
                return dict(row)
            return None
        except sqlite3.Error as e:
            logger.error(f"Failed to get player: {e}")
            raise

    def get_all_players(self) -> List[Dict[str, Any]]:
        if not self._conn:
            raise RuntimeError("Database not connected")

        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT account_id, player_name FROM players ORDER BY player_name")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Failed to get all players: {e}")
            raise

    def player_exists(self, account_id: str) -> bool:
        if not self._conn:
            raise RuntimeError("Database not connected")

        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT 1 FROM players WHERE account_id = ?", (account_id,)
            )
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Failed to check player existence: {e}")
            raise

    def get_player_count(self) -> int:
        if not self._conn:
            raise RuntimeError("Database not connected")

        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM players")
            result = cursor.fetchone()
            return result[0] if result else 0
        except sqlite3.Error as e:
            logger.error(f"Failed to get player count: {e}")
            raise

    def set_config(self, key: str, value: str) -> None:
        if not self._conn:
            raise RuntimeError("Database not connected")

        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, value),
            )
            self._conn.commit()
            logger.info(f"Set config: {key} = {value}")
        except sqlite3.Error as e:
            logger.error(f"Failed to set config: {e}")
            raise

    def get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if not self._conn:
            raise RuntimeError("Database not connected")

        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default
        except sqlite3.Error as e:
            logger.error(f"Failed to get config: {e}")
            raise
