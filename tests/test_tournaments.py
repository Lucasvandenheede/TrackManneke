import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src import tournament_queries as tq
from src.cogs import tournaments
from src.db.database import Database


@pytest.mark.parametrize(
    ("value", "expected"),
    [("6", "6"), ("3-5", "3-5"), (" 3 - 5 ", "3-5"), ("4-4", "4")],
)
def test_parse_team_size_accepts_fixed_sizes_and_ranges(value, expected):
    assert tournaments.parse_team_size(value) == expected


@pytest.mark.parametrize("value", ["0", "5-3", "1-100", "three", "3-5-7"])
def test_parse_team_size_rejects_invalid_sizes(value):
    with pytest.raises(ValueError):
        tournaments.parse_team_size(value)


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


def test_parse_sessions_accepts_start_only_and_mixed_entries(monkeypatch):
    monkeypatch.setattr(tournaments.config, "TIMEZONE", "Europe/Brussels")

    sessions = tournaments.parse_sessions(
        "05-12-2026 13:00\n06-12-2026 13:00 - 16:30"
    )

    assert sessions[0] == {
        "start": "2026-12-05T12:00:00+00:00",
        "end": None,
    }
    assert sessions[1] == {
        "start": "2026-12-06T12:00:00+00:00",
        "end": "2026-12-06T15:30:00+00:00",
    }


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


def test_announcement_ping_only_allows_the_selected_role():
    role = SimpleNamespace(id=123, mention="<@&123>")

    content, allowed_mentions = tournaments._announcement_ping(role)

    assert content == "<@&123>\n"
    assert allowed_mentions.to_dict() == {"roles": [123], "parse": []}


def test_announcement_ping_allows_two_selected_roles_without_duplicate_pings():
    first = SimpleNamespace(id=123, mention="<@&123>")
    second = SimpleNamespace(id=456, mention="<@&456>")

    content, allowed_mentions = tournaments._announcement_ping(first, second, first)

    assert content == "<@&123>\n<@&456>\n"
    assert allowed_mentions.to_dict() == {"roles": [123, 456], "parse": []}


def test_announcement_ping_is_empty_when_no_role_is_selected():
    content, allowed_mentions = tournaments._announcement_ping(None)

    assert content is None
    assert allowed_mentions.to_dict() == {"parse": []}


def test_announcement_shows_only_the_start_when_no_end_is_given(monkeypatch):
    monkeypatch.setattr(tournaments.config, "TIMEZONE", "Europe/Brussels")
    event = {
        "title": "Start-only event",
        "description": "",
        "sessions": json.dumps(tournaments.parse_sessions("05-12-2026 13:00")),
        "deadline": "2026-12-05T11:00:00+00:00",
        "team_size": 6,
        "status": "open",
    }

    embed = tournaments.build_announcement_embed(event, [])

    date_value = next(field.value for field in embed.fields if field.name == "📅 Dates")
    start_timestamp = int(datetime.fromisoformat(json.loads(event["sessions"])[0]["start"]).timestamp())
    assert f"<t:{start_timestamp}:t>" in date_value
    assert "–" not in date_value


def test_announcement_shows_end_date_for_overnight_session(monkeypatch):
    monkeypatch.setattr(tournaments.config, "TIMEZONE", "Europe/Brussels")
    event = {
        "title": "TFH 24H #5",
        "description": "",
        "sessions": json.dumps(
            tournaments.parse_sessions("14-11-2026 14:30 - 15-11-2026 15:00")
        ),
        "deadline": "2026-11-07T13:30:00+00:00",
        "team_size": "2-6",
        "status": "open",
    }

    embed = tournaments.build_announcement_embed(event, [])

    date_value = next(field.value for field in embed.fields if field.name == "📅 Dates")
    session = json.loads(event["sessions"])[0]
    assert "**14 November 2026**" in date_value
    assert "**15 November 2026**" in date_value
    assert f"<t:{int(datetime.fromisoformat(session['start']).timestamp())}:t>" in date_value
    assert f"<t:{int(datetime.fromisoformat(session['end']).timestamp())}:t>" in date_value


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
            team_size="3-5",
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
        assert event["team_size"] == "3-5"
        assert registrations == [{
            "user_id": 321,
            "display_name": "Luckyboi61",
            "response": "playing",
        }]

        await tq.delete_tournament(db, tournament_id)
        assert await tq.get_tournament(db, tournament_id) is None
    finally:
        await db.disconnect()
