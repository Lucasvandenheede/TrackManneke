import logging
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager for tracking Belgian Trackmania players."""

    def __init__(self, db_path: str = "trackmania.db"):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """Connect to database and initialize schema."""
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
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("Database connection closed")

    def _init_schema(self) -> None:
        """Initialize database schema."""
        if not self._conn:
            raise RuntimeError("Database not connected")

        cursor = self._conn.cursor()

        # Create players table if it doesn't exist
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                account_id TEXT PRIMARY KEY,
                player_name TEXT NOT NULL UNIQUE,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self._conn.commit()
        logger.debug("Database schema initialized")

    def add_player(self, account_id: str, player_name: str) -> bool:
        """Add a player to tracking list.

        Args:
            account_id: Player's Nadeo account UUID
            player_name: Player's display name

        Returns:
            True if player was added, False if already exists

        Raises:
            sqlite3.Error: If database operation fails
        """
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
        """Remove a player from tracking list.

        Args:
            account_id: Player's Nadeo account UUID

        Returns:
            True if player was removed, False if not found

        Raises:
            sqlite3.Error: If database operation fails
        """
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
        """Get player by account ID.

        Args:
            account_id: Player's Nadeo account UUID

        Returns:
            Player dict with account_id and player_name, or None if not found
        """
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
        """Get all tracked players.

        Returns:
            List of player dicts with account_id and player_name
        """
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
        """Check if player is tracked.

        Args:
            account_id: Player's Nadeo account UUID

        Returns:
            True if player is tracked, False otherwise
        """
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
        """Get total number of tracked players.

        Returns:
            Number of players in database
        """
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
