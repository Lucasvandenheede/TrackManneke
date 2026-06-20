# TrackManneke

Discord bot that tracks Belgian Trackmania players across COTD (Cup of the Day) and TOTD (Track of the Day) leaderboards. Built so the Belgian TM community can follow their own without manually scanning thousands of global entries.

## Features

- **COTD State Machine** — Automatically detects new COTD rotations, fetches qualifier results (top 3000), filters Belgian players, posts division-grouped leaderboards. Transitions to bracket phase and per-division round results as matches complete.
- **TOTD Leaderboard** — Daily snapshot (18:59 Paris time) of Belgian player rankings on the current Track of the Day. Manual `/totd-leaderboard` command also available.
- **Player Discovery** — Startup and daily runs scan the TOTD leaderboard for players with Belgian zone IDs. Also discovers Belgian players from COTD qualifiers via zone-map matching.
- **Discord Integration** — Configurable COTD/TOTD channels, ephemeral command responses, owner-only setup commands.

## Upcoming

- Historical COTD stats and per-player performance tracking
- Web dashboard for Belgian TM leaderboards
- Team/clan filter support
- Automated deployment health checks

## Tech

Python + discord.py, Nadeo/Ubisoft APIs (Meet, LiveServices, OAuth), SQLite.
