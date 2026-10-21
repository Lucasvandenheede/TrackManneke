"""Persistence helpers for Discord tournament sign-ups."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


STATUSES = ("playing", "maybe", "declined")


async def init_tournament_tables(db) -> None:
    if db._is_pg:
        await db._conn.execute("""
            CREATE TABLE IF NOT EXISTS tournaments (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                sessions TEXT NOT NULL,
                deadline TEXT NOT NULL,
                team_size TEXT NOT NULL,
                channel_id BIGINT NOT NULL,
                role_id BIGINT NOT NULL,
                message_id BIGINT,
                created_by BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                closed_message_updated BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db._conn.execute("""
            CREATE TABLE IF NOT EXISTS tournament_registrations (
                tournament_id BIGINT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                display_name TEXT NOT NULL,
                response TEXT NOT NULL CHECK (response IN ('playing', 'maybe', 'declined')),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tournament_id, user_id)
            )
        """)
        await db._conn.execute("""
            ALTER TABLE tournaments
            ALTER COLUMN team_size TYPE TEXT USING team_size::text
        """)
    else:
        await db._conn.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                sessions TEXT NOT NULL,
                deadline TEXT NOT NULL,
                team_size TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                message_id INTEGER,
                created_by INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                closed_message_updated INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tournament_registrations (
                tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                response TEXT NOT NULL CHECK (response IN ('playing', 'maybe', 'declined')),
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tournament_id, user_id)
            );
        """)
        await db._conn.commit()


def _placeholder(db, index: int) -> str:
    return f"${index}" if db._is_pg else "?"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_tournament(db, *, guild_id: int, title: str, description: str,
                            sessions: str, deadline: str, team_size: str,
                            channel_id: int, role_id: int, created_by: int) -> int:
    values = (guild_id, title, description, sessions, deadline, team_size,
              channel_id, role_id, created_by)
    if db._is_pg:
        row = await db._conn.fetchrow("""
            INSERT INTO tournaments
                (guild_id, title, description, sessions, deadline, team_size,
                 channel_id, role_id, created_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING id
        """, *values)
        return int(row["id"])
    cursor = await db._conn.execute("""
        INSERT INTO tournaments
            (guild_id, title, description, sessions, deadline, team_size,
             channel_id, role_id, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, values)
    await db._conn.commit()
    return int(cursor.lastrowid)


async def delete_tournament(db, tournament_id: int) -> None:
    if db._is_pg:
        await db._conn.execute("DELETE FROM tournaments WHERE id = $1", tournament_id)
    else:
        await db._conn.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))
        await db._conn.commit()


async def set_message_id(db, tournament_id: int, message_id: int) -> None:
    if db._is_pg:
        await db._conn.execute(
            "UPDATE tournaments SET message_id = $1 WHERE id = $2",
            message_id, tournament_id,
        )
    else:
        await db._conn.execute(
            "UPDATE tournaments SET message_id = ? WHERE id = ?",
            (message_id, tournament_id),
        )
        await db._conn.commit()


async def get_tournament(db, tournament_id: int) -> Optional[Dict[str, Any]]:
    if db._is_pg:
        row = await db._conn.fetchrow(
            "SELECT * FROM tournaments WHERE id = $1", tournament_id
        )
    else:
        cursor = await db._conn.execute(
            "SELECT * FROM tournaments WHERE id = ?", (tournament_id,)
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_all_tournaments(db) -> List[Dict[str, Any]]:
    if db._is_pg:
        rows = await db._conn.fetch("SELECT * FROM tournaments ORDER BY id")
    else:
        cursor = await db._conn.execute("SELECT * FROM tournaments ORDER BY id")
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_registrations(db, tournament_id: int) -> List[Dict[str, Any]]:
    if db._is_pg:
        rows = await db._conn.fetch(
            "SELECT user_id, display_name, response FROM tournament_registrations "
            "WHERE tournament_id = $1 ORDER BY lower(display_name), user_id",
            tournament_id,
        )
    else:
        cursor = await db._conn.execute(
            "SELECT user_id, display_name, response FROM tournament_registrations "
            "WHERE tournament_id = ? ORDER BY lower(display_name), user_id",
            (tournament_id,),
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def set_response(db, tournament_id: int, user_id: int,
                       display_name: str, response: str) -> None:
    if db._is_pg:
        updated_at = datetime.now(timezone.utc)
        await db._conn.execute("""
            INSERT INTO tournament_registrations
                (tournament_id, user_id, display_name, response, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (tournament_id, user_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                response = EXCLUDED.response,
                updated_at = EXCLUDED.updated_at
        """, tournament_id, user_id, display_name, response, updated_at)
    else:
        updated_at = _now_iso()
        await db._conn.execute("""
            INSERT INTO tournament_registrations
                (tournament_id, user_id, display_name, response, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (tournament_id, user_id) DO UPDATE SET
                display_name = excluded.display_name,
                response = excluded.response,
                updated_at = excluded.updated_at
        """, (tournament_id, user_id, display_name, response, updated_at))
        await db._conn.commit()


async def is_playing_in_other_open_tournament(db, *, guild_id: int,
                                               user_id: int, role_id: int,
                                               excluding_id: int) -> bool:
    if db._is_pg:
        row = await db._conn.fetchrow("""
            SELECT 1 FROM tournament_registrations r
            JOIN tournaments t ON t.id = r.tournament_id
            WHERE t.guild_id = $1 AND t.role_id = $2 AND t.id <> $3
              AND t.status = 'open' AND t.deadline > $4
              AND r.user_id = $5 AND r.response = 'playing'
            LIMIT 1
        """, guild_id, role_id, excluding_id, _now_iso(), user_id)
    else:
        cursor = await db._conn.execute("""
            SELECT 1 FROM tournament_registrations r
            JOIN tournaments t ON t.id = r.tournament_id
            WHERE t.guild_id = ? AND t.role_id = ? AND t.id <> ?
              AND t.status = 'open' AND t.deadline > ?
              AND r.user_id = ? AND r.response = 'playing'
            LIMIT 1
        """, (guild_id, role_id, excluding_id, _now_iso(), user_id))
        row = await cursor.fetchone()
    return row is not None


async def get_due_tournaments(db) -> List[Dict[str, Any]]:
    now = _now_iso()
    if db._is_pg:
        rows = await db._conn.fetch("""
            SELECT * FROM tournaments
            WHERE (status = 'open' AND deadline <= $1)
               OR (status = 'closed' AND closed_message_updated = FALSE)
            ORDER BY id
        """, now)
    else:
        cursor = await db._conn.execute("""
            SELECT * FROM tournaments
            WHERE (status = 'open' AND deadline <= ?)
               OR (status = 'closed' AND closed_message_updated = 0)
            ORDER BY id
        """, (now,))
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def close_tournament(db, tournament_id: int) -> None:
    if db._is_pg:
        await db._conn.execute(
            "UPDATE tournaments SET status = 'closed' WHERE id = $1",
            tournament_id,
        )
    else:
        await db._conn.execute(
            "UPDATE tournaments SET status = 'closed' WHERE id = ?",
            (tournament_id,),
        )
        await db._conn.commit()


async def mark_closed_message_updated(db, tournament_id: int) -> None:
    if db._is_pg:
        await db._conn.execute(
            "UPDATE tournaments SET closed_message_updated = TRUE WHERE id = $1",
            tournament_id,
        )
    else:
        await db._conn.execute(
            "UPDATE tournaments SET closed_message_updated = 1 WHERE id = ?",
            (tournament_id,),
        )
        await db._conn.commit()
