import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src import tournament_queries as tq
from src.cogs import tournaments
from src.db.database import Database


def test_parse_sessions_accepts_one_day_and_time_range_per_line(monkeypatch):
    monkeypatch.setattr(tournaments.config, "TIMEZONE", "Europe/Brussels")

    sessions = tournaments.parse_sessions(
        "5-12-2026 13:00 - 16:30\n"
        "6-12-2026 13:00 - 16:30\n"
        "12-12-2026 13:00 - 16:30\n"
        "13-12-2026 13:00 - 16:30"
    )

    assert len(sessions) == 4
    assert sessions[0] == {
        "start": "2026-12-05T12:00:00+00:00",
        "end": "2026-12-05T15:30:00+00:00",
    }
    assert sessions[-1]["start"] == "2026-12-13T12:00:00+00:00"


def test_parse_sessions_accepts_natural_language_date(monkeypatch):
    monkeypatch.setattr(tournaments.config, "TIMEZONE", "Europe/Brussels")

    sessions = tournaments.parse_sessions("20 October 2026 20:00 - 22:00")

    assert sessions == [{
        "start": "2026-10-20T18:00:00+00:00",
        "end": "2026-10-20T20:00:00+00:00",
    }]


def test_blank_deadline_defaults_to_one_hour_before_first_session(monkeypatch):
    monkeypatch.setattr(tournaments.config, "TIMEZONE", "Europe/Brussels")
    sessions = tournaments.parse_sessions(
        "13-12-2026 13:00 - 16:30\n05-12-2026 13:00 - 16:30"
    )

    deadline = tournaments.resolve_deadline("", sessions)

    assert deadline == datetime.fromisoformat(sessions[1]["start"]) - timedelta(hours=1)


def test_announcement_places_signup_lists_inline(monkeypatch):
    monkeypatch.setattr(tournaments.config, "TIMEZONE", "Europe/Brussels")
    event = {
        "title": "TSCC Fall 2026",
        "description": "Join a Belgian team.",
        "sessions": json.dumps(tournaments.parse_sessions("05-12-2026 13:00 - 16:30")),
        "deadline": "2026-12-05T11:00:00+00:00",
        "team_size": 6,
        "status": "open",
    }

    embed = tournaments.build_announcement_embed(event, [])

    assert [field.inline for field in embed.fields[-3:]] == [True, True, True]
    assert [field.name.split(" ", 1)[1] for field in embed.fields[-3:]] == [
        "Playing (0)", "Maybe (0)", "Can’t make it (0)"
    ]


@pytest.mark.asyncio
async def test_sqlite_tournament_publish_and_registration_persistence(tmp_path):
    db = Database(db_path=str(tmp_path / "tournament.sqlite3"), dsn="")
    await db.connect()
    try:
        await tq.init_tournament_tables(db)
        tournament_id = await tq.create_tournament(
            db,
            guild_id=123,
            title="TSCC Fall 2026",
            description="Join a Belgian team.",
            sessions="[]",
            deadline="2026-12-04T12:00:00+00:00",
            team_size=6,
            channel_id=456,
            role_id=789,
            created_by=987,
        )

        cog = tournaments.Tournaments(SimpleNamespace(db=db))
        choices = await cog.tournament_autocomplete(
            SimpleNamespace(guild_id=123), "fall"
        )
        assert len(choices) == 1
        assert choices[0].value == str(tournament_id)
        assert await cog.tournament_autocomplete(
            SimpleNamespace(guild_id=999), "fall"
        ) == []

        await tq.set_message_id(db, tournament_id, 654)
        await tq.set_response(db, tournament_id, 321, "Luckyboi61", "playing")

        event = await tq.get_tournament(db, tournament_id)
        registrations = await tq.get_registrations(db, tournament_id)
        assert event["message_id"] == 654
        assert registrations == [{
            "user_id": 321,
            "display_name": "Luckyboi61",
            "response": "playing",
        }]

        await tq.delete_tournament(db, tournament_id)
        assert await tq.get_tournament(db, tournament_id) is None
    finally:
        await db.disconnect()
