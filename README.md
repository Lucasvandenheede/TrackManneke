# TrackManneke

TrackManneke is a Discord bot engineered to track and surface live performance data for the Belgian Trackmania community. It monitors global Nadeo API feeds to isolate, record, and showcase Belgian player rankings across Cup of the Day (COTD), Track of the Day (TOTD), and campaign leaderboards.

---

## 🚀 Features

*   **⏱️ TOTD Live Leaderboards** — Aggregates and updates regional rankings for active Tracks of the Day, posting final standings right before the next track rotation. Supports manual queries via the `/totd-leaderboard` slash command.
*   **🏆 COTD Analytics** — Automatically broadcasts Belgian qualifier standings and brackets/rounds results immediately following the conclusion of main events.

---

## 🛠️ Tech Stack

*   **Language:** Python 3.10+ (Asyncio / aiohttp)
*   **Discord Framework:** `py-cord` / `discord.py` (Slash Commands & Component Interactions)
*   **Data Layer:** SQLite (Optimized for asynchronous execution and relational tracking)
*   **External Integrations:** Nadeo & Ubisoft Core Services APIs (`NadeoLiveServices`, OAuth Client Credentials flow, Meet Endpoints)

---

## 🗺️ Under Development & Future Roadmap

### 🏁 1. Dynamic Tournament & Lineup Manager
An admin-driven module designed to simplify registration and team composition for major endurance or team events (e.g., TFH, TSCC).
*   **Event Dispatcher:** Admins trigger a command to spin up an event registration message in designated channels (e.g., `#events`).
*   **Availability Tracking:** Community members react or interact with buttons to register interest. The bot dynamically populates an updated roster card inside dedicated project channels:
    > **TSCC Interested Roster:**
    > *   `Luckyboi61`
    > *   `Xertzy`
*   **Lineup Architecture:** Admins can draft and lock finalized rosters through the bot, publishing the official team lineups cleanly to the server:
    > **Team Blagium (TFH #1):**
    > *   `Luckyboi61`
    > *   `Cherry`

### 🏅 2. Real-time Personal Best (PB) Record Tracker
An asynchronous listener that monitors cached database positions against active Nadeo Leaderboard endpoints, instantly broadcasting historical regional achievements when a tracked Belgian player drives a new personal best.

*   **Campaign Tracking Output Format:**
    > **Campaign:**
    > **Luckyboi61** drove a new PB!
    > 🗺️ *Spring 2026 - 09*
    > 🥇 **BE:** 1 (`#10` World) | ⏱️ **0:21.633** (`-0.011`) | *Was BE 1 (#60 World)*
*   **Weekly Shorts Tracking Output Format:**
    > **Weekly Shorts:**
    > **Luckyboi61** drove a new PB!
    > 🗺️ *Week 395 – Map 5 - TAKEOFF* by `markreele`
    > 🥇 **BE:** 1 (`#69` World)

### 📅 3. COTW Support
Extends the internal state-machine driving the daily COTD live-polling structures to natively catch, parse, and partition results for weekly **Cup of the Week** competitive cycles.

### 📊 4. Weekly Community Shorts
Automated, cron-scheduled reporting tasks that bundle up regional performance telemetry over a 7-day window to celebrate and showcase the most active or top-performing Belgian drivers of the week.

---
By Luckyboi61 for the Belgian Community
