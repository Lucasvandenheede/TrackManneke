import json
import logging
import re
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
import dateparser
from discord import app_commands
from discord.ext import commands, tasks

from src import config
from src import tournament_queries as tq

logger = logging.getLogger(__name__)

RESPONSES = {
    "playing": ("Playing", discord.ButtonStyle.success),
    "maybe": ("Maybe", discord.ButtonStyle.secondary),
    "declined": ("Can’t make it", discord.ButtonStyle.danger),
}


def parse_team_size(value: str) -> str:
    """Validate and normalize a fixed team size or inclusive size range."""
    match = re.fullmatch(r"\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*", value)
    if match is None:
        raise ValueError("Enter a team size like `6` or a range like `3-5`.")
    minimum = int(match.group(1))
    maximum = int(match.group(2) or minimum)
    if not 1 <= minimum <= maximum <= 99:
        raise ValueError("Team sizes must be between 1 and 99, with the smaller size first.")
    return str(minimum) if minimum == maximum else f"{minimum}-{maximum}"


def _event_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(config.TIMEZONE)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Configured timezone {config.TIMEZONE!r} is not valid.") from exc


def _parse_datetime(value: str, *, date_is_end_of_day: bool = False) -> datetime:
    value = value.strip()
    try:
        if date_is_end_of_day and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed = datetime.combine(datetime.fromisoformat(value).date(), time(23, 59))
        elif date_is_end_of_day and re.fullmatch(r"\d{1,2}-\d{1,2}-\d{4}", value):
            parsed = datetime.strptime(value, "%d-%m-%Y").replace(hour=23, minute=59)
        else:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                parsed = dateparser.parse(
                    value,
                    settings={
                        "TIMEZONE": _event_timezone().key,
                        "RETURN_AS_TIMEZONE_AWARE": True,
                        "DATE_ORDER": "DMY",
                        "PREFER_LOCALE_DATE_ORDER": False,
                        "PREFER_DATES_FROM": "future",
                    },
                )
                if parsed is None:
                    raise ValueError
                if date_is_end_of_day and not re.search(r"\d{1,2}:\d{2}", value):
                    parsed = parsed.replace(hour=23, minute=59, second=0, microsecond=0)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"Could not parse date/time {value!r}. Use DD-MM-YYYY HH:MM.") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_event_timezone())
    return parsed.astimezone(timezone.utc)


def parse_sessions(value: str) -> list[dict[str, str]]:
    """Parse one session per line, or legacy ISO and compact schedules.

    Preferred examples: ``05-12-2026 13:00`` or ``05-12-2026 13:00 - 16:30``.
    """
    entries = [entry.strip() for entry in re.split(r"[;\n]+", value) if entry.strip()]
    new_format = []
    is_new_format = bool(entries)
    for entry in entries:
        match = re.fullmatch(r"(.+?)\s+-\s+(\d{1,2}:\d{2})", entry)
        if match:
            new_format.append(match)
        elif re.search(r"\s+-\s+", entry):
            # Leave legacy full start/end datetime pairs to the old parser below.
            is_new_format = False
            break
        else:
            new_format.append(None)
    if is_new_format:
        sessions = []
        for entry, match in zip(entries, new_format):
            start = _parse_datetime(match.group(1) if match else entry)
            if match is None:
                sessions.append({"start": start.isoformat(), "end": None})
                continue
            try:
                end_time = datetime.strptime(match.group(2), "%H:%M").time()
            except ValueError as exc:
                raise ValueError(f"Invalid end time in schedule entry {entry!r}.") from exc
            local_start = start.astimezone(_event_timezone())
            end = datetime.combine(local_start.date(), end_time, tzinfo=_event_timezone())
            if end <= local_start:
                raise ValueError("Each end time must be after its start time on that date.")
            sessions.append({"start": start.isoformat(), "end": end.astimezone(timezone.utc).isoformat()})
        if len(sessions) > 10:
            raise ValueError("Enter no more than 10 event sessions.")
        return sessions

    compact = re.fullmatch(
        r"\s*(.*?)\s*(?:\()?\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*\)?\s*",
        value,
    )
    if compact:
        date_part, start_time, end_time = compact.groups()
        # Require a month name and year so the shorthand is unambiguous.
        match = re.fullmatch(
            r"\s*(.*?)\s+([A-Za-z]+)\s+(\d{4})\s*", date_part
        )
        if match:
            days_part, month_name, year_text = match.groups()
            try:
                month = datetime.strptime(month_name, "%B").month
            except ValueError:
                try:
                    month = datetime.strptime(month_name, "%b").month
                except ValueError as exc:
                    raise ValueError(f"Unknown month name: {month_name!r}.") from exc
            year = int(year_text)
            day_tokens = re.findall(r"\d{1,2}(?:\s*-\s*\d{1,2})?", days_part)
            residue = re.sub(r"\d{1,2}(?:\s*-\s*\d{1,2})?", "", days_part)
            if not day_tokens or residue.strip(" ,&and"):
                raise ValueError(
                    "Use dates like `5-6 and 12-13 December 2026 (13:00-16:30)`."
                )
            days = []
            for token in day_tokens:
                bounds = [int(part.strip()) for part in token.split("-")]
                if len(bounds) == 1:
                    days.append(bounds[0])
                elif bounds[1] < bounds[0] or bounds[1] - bounds[0] > 30:
                    raise ValueError("Date ranges must go from an earlier day to a later day.")
                else:
                    days.extend(range(bounds[0], bounds[1] + 1))
            sessions = []
            for day in days:
                try:
                    start = datetime.strptime(
                        f"{year}-{month}-{day} {start_time}", "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=_event_timezone())
                    end = datetime.strptime(
                        f"{year}-{month}-{day} {end_time}", "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=_event_timezone())
                except ValueError as exc:
                    raise ValueError(f"Invalid date or time in the schedule: {exc}") from exc
                if end <= start:
                    raise ValueError("Every schedule end must be after its start.")
                sessions.append({
                    "start": start.astimezone(timezone.utc).isoformat(),
                    "end": end.astimezone(timezone.utc).isoformat(),
                })
            if len(sessions) > 10:
                raise ValueError("Enter no more than 10 event sessions.")
            return sessions

    sessions = []
    for entry in value.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        pair = re.split(r"\s+-\s+", entry, maxsplit=1)
        if len(pair) != 2:
            raise ValueError(
                "Each schedule entry needs a start and end separated by ' - '. "
                "Separate multiple sessions with semicolons."
            )
        start = _parse_datetime(pair[0])
        end = _parse_datetime(pair[1])
        if end <= start:
            raise ValueError("Every schedule end must be after its start.")
        sessions.append({"start": start.isoformat(), "end": end.isoformat()})

    if not sessions:
        raise ValueError("Enter at least one event date/time session.")
    if len(sessions) > 10:
        raise ValueError("Enter no more than 10 event sessions.")
    return sessions


def resolve_deadline(value: str, sessions: list[dict[str, str]]) -> datetime:
    """Use the supplied deadline, or default to one hour before the first session."""
    first_session = min(datetime.fromisoformat(session["start"]) for session in sessions)
    return (
        _parse_datetime(value, date_is_end_of_day=True)
        if value.strip()
        else first_session - timedelta(hours=1)
    )


def _timestamp(value: str, style: str = "F") -> str:
    stamp = int(datetime.fromisoformat(value).timestamp())
    return f"<t:{stamp}:{style}>"


def _announcement_ping(*roles: Optional[discord.Role]) -> tuple[Optional[str], discord.AllowedMentions]:
    selected_roles = []
    seen_ids = set()
    for role in roles:
        if role is not None and role.id not in seen_ids:
            selected_roles.append(role)
            seen_ids.add(role.id)
    if not selected_roles:
        return None, discord.AllowedMentions.none()
    return (
        "\n".join(role.mention for role in selected_roles) + "\n",
        discord.AllowedMentions(everyone=False, users=False, roles=selected_roles, replied_user=False),
    )


def build_announcement_embed(event: dict, registrations: list[dict]) -> discord.Embed:
    closed = event["status"] != "open"
    embed = discord.Embed(
        title=f"🏆 {event['title']}",
        description=event["description"] or "Join a Belgian team for this tournament.",
        colour=discord.Colour(0xFF0000) if closed else discord.Colour.green(),
    )
    embed.add_field(
        name="👥 Team size",
        value=f"{event['team_size']} players per team",
        inline=True,
    )
    schedule = json.loads(event["sessions"])
    schedule_lines = []
    for session in schedule:
        start = datetime.fromisoformat(session["start"])
        local_start = start.astimezone(_event_timezone())
        line = f"**{local_start.strftime('%d %B %Y')}** · <t:{int(start.timestamp())}:t>"
        if session.get("end"):
            end = datetime.fromisoformat(session["end"])
            line += f"–<t:{int(end.timestamp())}:t>"
        schedule_lines.append(line)
    embed.add_field(
        name="⏳ Registration deadline",
        value=(
            f"**{datetime.fromisoformat(event['deadline']).astimezone(_event_timezone()).strftime('%d %B %Y')}** "
            f"· {_timestamp(event['deadline'], 'R')}"
        ),
        inline=False,
    )
    embed.add_field(name="📅 Dates", value="\n".join(schedule_lines), inline=False)

    for status, (label, _) in RESPONSES.items():
        names = [
            discord.utils.escape_markdown(str(row["display_name"]))
            for row in registrations if row["response"] == status
        ]
        emoji = {"playing": "✅", "maybe": "🤔", "declined": "❌"}[status]
        heading = f"{emoji} {label} ({len(names)})"
        roster = "\n".join(names) if names else "—"
        if len(roster) > 1000:
            visible = []
            length = 0
            for name in names:
                if length + len(name) + 1 > 900:
                    break
                visible.append(name)
                length += len(name) + 1
            roster = "\n".join(visible) + f"\n…and {len(names) - len(visible)} more"
        embed.add_field(name=heading, value=roster, inline=True)

    if closed:
        embed.set_footer(text="Registration is closed")
    return embed


class TournamentRegistrationView(discord.ui.View):
    def __init__(self, cog: "Tournaments", tournament_id: int, *, closed: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        self.tournament_id = tournament_id
        for status, (label, style) in RESPONSES.items():
            button = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"tournament:{tournament_id}:{status}",
                disabled=closed,
            )
            button.callback = self._make_callback(status)
            self.add_item(button)

    def _make_callback(self, status: str):
        async def callback(interaction: discord.Interaction):
            await self.cog.handle_response(interaction, self.tournament_id, status)
        return callback


class TournamentPreviewView(discord.ui.View):
    def __init__(self, cog: "Tournaments", *, user_id: int, guild: discord.Guild,
                 channel: discord.TextChannel, role_id: Optional[int],
                 new_role_name: Optional[str], announcement_roles: list[discord.Role],
                 title: str, description: str,
                 sessions: list[dict[str, str]], deadline: str, team_size: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.guild = guild
        self.channel = channel
        self.role_id = role_id
        self.new_role_name = new_role_name
        self.announcement_roles = announcement_roles
        self.title = title
        self.description = description
        self.sessions = sessions
        self.deadline = deadline
        self.team_size = team_size

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the moderator who started this setup can confirm it.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Publish tournament", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        # This preview is shared in the staff channel, so update it publicly after publishing.
        await interaction.response.defer()
        created_role = None
        tournament_id = None
        try:
            if self.new_role_name:
                created_role = await self.guild.create_role(
                    name=self.new_role_name,
                    reason=f"Tournament role for {self.title}",
                )
                role_id = created_role.id
            else:
                role_id = self.role_id

            tournament_id = await tq.create_tournament(
                self.cog.bot.db,
                guild_id=self.guild.id,
                title=self.title,
                description=self.description,
                sessions=json.dumps(self.sessions),
                deadline=self.deadline,
                team_size=self.team_size,
                channel_id=self.channel.id,
                role_id=role_id,
                created_by=self.user_id,
            )
            event = await tq.get_tournament(self.cog.bot.db, tournament_id)
            view = TournamentRegistrationView(self.cog, tournament_id)
            ping_content, allowed_mentions = _announcement_ping(*self.announcement_roles)
            message = await self.channel.send(
                content=ping_content,
                embed=build_announcement_embed(event, []),
                view=view,
                allowed_mentions=allowed_mentions,
            )
            await tq.set_message_id(self.cog.bot.db, tournament_id, message.id)
            self.cog.bot.add_view(view, message_id=message.id)
            self.stop()
            await interaction.edit_original_response(
                content=(
                    f"Tournament **{discord.utils.escape_markdown(self.title)}** "
                    f"published in {self.channel.mention}."
                ),
                embed=None,
                view=None,
            )
        except Exception as exc:
            logger.exception("Could not publish tournament %r", self.title)
            if tournament_id is not None:
                try:
                    await tq.delete_tournament(self.cog.bot.db, tournament_id)
                except Exception:
                    logger.exception("Could not roll back tournament record %s", tournament_id)
            if created_role:
                try:
                    await created_role.delete(reason="Tournament publication failed")
                except Exception:
                    logger.warning("Could not remove unused role %s after failed publication", created_role.id)
            await interaction.followup.send(
                f"Could not publish the tournament: {exc}", ephemeral=False
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.stop()
        await interaction.response.edit_message(content="Tournament setup cancelled.", embed=None, view=None)


class TournamentDeleteView(discord.ui.View):
    def __init__(self, cog: "Tournaments", *, user_id: int, event: dict):
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = user_id
        self.event = event

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the moderator who started this deletion can confirm it.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Delete tournament", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        event_id = int(self.event["id"])
        try:
            await tq.delete_tournament(self.cog.bot.db, event_id)
        except Exception:
            logger.exception("Could not delete tournament %s", event_id)
            await interaction.edit_original_response(
                content="Could not delete the tournament. Its data is still in place.",
                embed=None,
                view=None,
            )
            return

        announcement_removed = True
        if self.event["message_id"]:
            channel = self.cog.bot.get_channel(int(self.event["channel_id"]))
            if channel is None:
                try:
                    channel = await self.cog.bot.fetch_channel(int(self.event["channel_id"]))
                except discord.HTTPException:
                    channel = None
            if channel is None:
                announcement_removed = False
            else:
                try:
                    message = await channel.fetch_message(int(self.event["message_id"]))
                    await message.delete()
                except discord.NotFound:
                    pass
                except discord.HTTPException:
                    announcement_removed = False
                    logger.exception("Could not remove announcement for deleted tournament %s", event_id)

        self.stop()
        title = discord.utils.escape_markdown(str(self.event["title"]))
        result = f"Tournament **{title}** and its saved sign-ups were deleted."
        if announcement_removed:
            result += " Its announcement was removed."
        else:
            result += " I couldn’t remove its announcement; please delete that message manually."
        result += " Player roles were left unchanged."
        await interaction.edit_original_response(content=result, embed=None, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.stop()
        await interaction.response.edit_message(
            content="Tournament deletion cancelled.", embed=None, view=None
        )


class TournamentSetupModal(discord.ui.Modal, title="Create a tournament"):
    title_input = discord.ui.TextInput(
        label="Tournament title", max_length=100,
        placeholder="e.g. TSCC Fall 2026",
    )
    description_input = discord.ui.TextInput(
        label="Description", style=discord.TextStyle.paragraph,
        required=False, max_length=1000,
        placeholder="What should players know? e.g. Info about the tournament, rules, or a link.",
    )
    team_size_input = discord.ui.TextInput(
        label="Team size", max_length=5,
        placeholder="3 players, or a range like 3-5",
    )
    sessions_input = discord.ui.TextInput(
        label="Schedule sessions", style=discord.TextStyle.paragraph,
        max_length=1000,
        placeholder="One per line, e.g. 05-12-2026 13:00 - 16:30",
    )
    deadline_input = discord.ui.TextInput(
        label="Registration deadline", max_length=30,
        required=False,
        placeholder="e.g. 27-11-2026 23:59; blank = 1 hour before the first session",
    )

    def __init__(self, cog: "Tournaments", *, channel: discord.TextChannel,
                 role: Optional[discord.Role], new_role_name: Optional[str],
                 announcement_role: Optional[discord.Role],
                 announcement_role_2: Optional[discord.Role]):
        super().__init__()
        self.cog = cog
        self.channel = channel
        self.role = role
        self.new_role_name = new_role_name
        self.announcement_roles = []
        for selected_role in (announcement_role, announcement_role_2):
            if selected_role and all(existing.id != selected_role.id for existing in self.announcement_roles):
                self.announcement_roles.append(selected_role)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not self.cog._can_manage(interaction.user):
            await interaction.response.send_message(
                "You need Administrator, Manage Server, or Manage Events permission to create tournaments.",
                ephemeral=True,
            )
            return
        try:
            title = self.title_input.value.strip()
            if not title:
                raise ValueError("Tournament title cannot be empty.")
            team_size = parse_team_size(self.team_size_input.value)
            sessions = parse_sessions(self.sessions_input.value)
            deadline_dt = resolve_deadline(self.deadline_input.value, sessions)
            now = datetime.now(timezone.utc)
            if deadline_dt <= now:
                raise ValueError("The registration deadline must be in the future.")
            if deadline_dt >= min(datetime.fromisoformat(s["start"]) for s in sessions):
                raise ValueError("The registration deadline must be before the first event session.")
            if (self.role is None) == (not self.new_role_name):
                raise ValueError("Choose one existing role or enter a new role name.")

            permissions = self.channel.permissions_for(interaction.guild.me)
            if not permissions.send_messages or not permissions.embed_links:
                raise ValueError("The bot needs Send Messages and Embed Links in the selected channel.")
            for announcement_role in self.announcement_roles:
                if announcement_role.is_default():
                    raise ValueError("The @everyone role cannot be used as an announcement role.")
                if not announcement_role.mentionable and not permissions.mention_everyone:
                    raise ValueError(
                        "The bot can only ping a role that is mentionable or when it has Mention @everyone permission."
                    )
            if self.role:
                if self.role.managed or self.role >= interaction.guild.me.top_role:
                    raise ValueError("The bot cannot assign that role because it is managed or above the bot’s highest role.")
                if not interaction.guild.me.guild_permissions.manage_roles:
                    raise ValueError("The bot needs Manage Roles to assign the selected role.")
            elif not interaction.guild.me.guild_permissions.manage_roles:
                raise ValueError("The bot needs Manage Roles to create and assign a tournament role.")

            preview_event = {
                "title": title,
                "description": self.description_input.value.strip(),
                "sessions": json.dumps(sessions),
                "deadline": deadline_dt.isoformat(),
                "team_size": team_size,
                "status": "open",
            }
            view = TournamentPreviewView(
                self.cog,
                user_id=interaction.user.id,
                guild=interaction.guild,
                channel=self.channel,
                role_id=self.role.id if self.role else None,
                new_role_name=self.new_role_name,
                announcement_roles=self.announcement_roles,
                title=title,
                description=self.description_input.value.strip(),
                sessions=sessions,
                deadline=deadline_dt.isoformat(),
                team_size=team_size,
            )
            preview_content = f"Review the announcement for {self.channel.mention}. Confirm to publish."
            if self.announcement_roles:
                role_mentions = " ".join(role.mention for role in self.announcement_roles)
                preview_content += f"\n\nAnnouncement ping: {role_mentions}"
            await interaction.response.send_message(
                content=preview_content,
                embed=build_announcement_embed(preview_event, []),
                view=view,
                ephemeral=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (ValueError, ZoneInfoNotFoundError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=False)


class Tournaments(commands.Cog):
    tournament = app_commands.Group(name="tournament", description="Create and manage tournaments")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await tq.init_tournament_tables(self.bot.db)
        for event in await tq.get_all_tournaments(self.bot.db):
            if event["message_id"]:
                view = TournamentRegistrationView(
                    self, int(event["id"]), closed=event["status"] != "open"
                )
                self.bot.add_view(view, message_id=int(event["message_id"]))
        self.close_due_tournaments.start()

    def cog_unload(self):
        self.close_due_tournaments.cancel()

    @staticmethod
    def _can_manage(member: discord.Member) -> bool:
        permissions = member.guild_permissions
        return permissions.administrator or permissions.manage_guild or permissions.manage_events

    @tournament.command(name="create", description="Create a tournament sign-up announcement")
    @app_commands.describe(
        channel="Server channel for the public sign-up message",
        role="Existing role to give to players who choose Playing",
        new_role_name="Create a role with this name instead of selecting an existing role",
        announcement_role="First optional role to ping above the public tournament post",
        announcement_role_2="Second optional role to ping above the public tournament post",
    )
    @app_commands.guild_only()
    async def create(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: Optional[discord.Role] = None,
        new_role_name: Optional[str] = None,
        announcement_role: Optional[discord.Role] = None,
        announcement_role_2: Optional[discord.Role] = None,
    ):
        if interaction.guild is None or not self._can_manage(interaction.user):
            await interaction.response.send_message(
                "You need Administrator, Manage Server, or Manage Events permission to create tournaments.",
                ephemeral=True,
            )
            return
        if (role is None) == (not new_role_name):
            await interaction.response.send_message(
                "Choose an existing role or provide a new role name, but not both.", ephemeral=True
            )
            return
        if new_role_name and len(new_role_name.strip()) > 100:
            await interaction.response.send_message("New role names must be 100 characters or fewer.", ephemeral=True)
            return
        if new_role_name:
            new_role_name = new_role_name.strip()
            if not new_role_name:
                await interaction.response.send_message("New role name cannot be empty.", ephemeral=True)
                return
        await interaction.response.send_modal(
            TournamentSetupModal(
                self,
                channel=channel,
                role=role,
                new_role_name=new_role_name,
                announcement_role=announcement_role,
                announcement_role_2=announcement_role_2,
            )
        )

    async def tournament_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild_id is None:
            return []
        query = current.casefold().strip()
        events = await tq.get_all_tournaments(self.bot.db)
        matches = [
            event for event in reversed(events)
            if int(event["guild_id"]) == interaction.guild_id
            and query in f"{event['title']} {event['status']} {event['id']}".casefold()
        ]
        return [
            app_commands.Choice(
                name=f"{str(event['title'])[:65]} · {event['status']} · #{event['id']}",
                value=str(event["id"]),
            )
            for event in matches[:25]
        ]

    @tournament.command(name="delete", description="Delete a tournament and its sign-ups")
    @app_commands.describe(tournament_id="Search tournaments by title or ID")
    @app_commands.autocomplete(tournament_id=tournament_autocomplete)
    @app_commands.guild_only()
    async def delete(self, interaction: discord.Interaction, tournament_id: str):
        if interaction.guild is None or not self._can_manage(interaction.user):
            await interaction.response.send_message(
                "You need Administrator, Manage Server, or Manage Events permission to delete tournaments.",
                ephemeral=True,
            )
            return
        try:
            event = await tq.get_tournament(self.bot.db, int(tournament_id))
        except ValueError:
            event = None
        if not event or int(event["guild_id"]) != interaction.guild_id:
            await interaction.response.send_message(
                "That tournament wasn’t found in this server.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            content=(
                f"Delete **{discord.utils.escape_markdown(str(event['title']))}**? "
                "This removes its announcement and saved sign-ups. Player roles stay unchanged."
            ),
            view=TournamentDeleteView(self, user_id=interaction.user.id, event=event),
            ephemeral=True,
        )

    async def handle_response(self, interaction: discord.Interaction,
                              tournament_id: int, response: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        event = await tq.get_tournament(self.bot.db, tournament_id)
        if not event or int(event["guild_id"]) != interaction.guild_id:
            await interaction.followup.send("This tournament is no longer available.", ephemeral=True)
            return
        if event["status"] != "open" or datetime.fromisoformat(event["deadline"]) <= datetime.now(timezone.utc):
            await interaction.followup.send("Registration for this tournament is closed.", ephemeral=True)
            await self._close_event(event)
            return
        if response not in RESPONSES or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("Could not record that response.", ephemeral=True)
            return

        registrations = await tq.get_registrations(self.bot.db, tournament_id)
        old = next((r for r in registrations if int(r["user_id"]) == interaction.user.id), None)
        previous_response = old["response"] if old else None
        await tq.set_response(
            self.bot.db, tournament_id, interaction.user.id,
            interaction.user.display_name, response,
        )
        role = interaction.guild.get_role(int(event["role_id"]))
        role_problem = None
        if role and response == "playing" and role not in interaction.user.roles:
            try:
                await interaction.user.add_roles(role, reason=f"Playing in tournament {event['title']}")
            except discord.HTTPException as exc:
                role_problem = "I saved your response, but couldn’t assign the tournament role."
                logger.warning("Could not assign tournament role %s to %s: %s", role.id, interaction.user.id, exc)
        elif role and previous_response == "playing" and response != "playing":
            still_playing = await tq.is_playing_in_other_open_tournament(
                self.bot.db,
                guild_id=int(event["guild_id"]),
                user_id=interaction.user.id,
                role_id=int(event["role_id"]),
                excluding_id=tournament_id,
            )
            if not still_playing and role in interaction.user.roles:
                try:
                    await interaction.user.remove_roles(role, reason=f"No longer playing in tournament {event['title']}")
                except discord.HTTPException as exc:
                    role_problem = "I saved your response, but couldn’t remove the tournament role."
                    logger.warning("Could not remove tournament role %s from %s: %s", role.id, interaction.user.id, exc)

        event = await tq.get_tournament(self.bot.db, tournament_id)
        registrations = await tq.get_registrations(self.bot.db, tournament_id)
        channel = interaction.guild.get_channel(int(event["channel_id"]))
        if channel and event["message_id"]:
            try:
                message = await channel.fetch_message(int(event["message_id"]))
                await message.edit(
                    embed=build_announcement_embed(event, registrations),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                logger.exception("Could not refresh tournament announcement %s", tournament_id)
        label = RESPONSES[response][0]
        await interaction.followup.send(
            f"Your response is now **{label}**." + (f" {role_problem}" if role_problem else ""),
            ephemeral=True,
        )

    async def _close_event(self, event: dict):
        if event["status"] == "open":
            await tq.close_tournament(self.bot.db, int(event["id"]))
        event = await tq.get_tournament(self.bot.db, int(event["id"]))
        channel = self.bot.get_channel(int(event["channel_id"]))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(event["channel_id"]))
            except discord.HTTPException:
                logger.warning("Could not fetch channel %s to close tournament %s", event["channel_id"], event["id"])
                return
        if event["message_id"]:
            try:
                message = await channel.fetch_message(int(event["message_id"]))
                registrations = await tq.get_registrations(self.bot.db, int(event["id"]))
                await message.edit(
                    embed=build_announcement_embed(event, registrations),
                    view=TournamentRegistrationView(self, int(event["id"]), closed=True),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.NotFound:
                logger.warning("Announcement message for tournament %s was deleted", event["id"])
            except discord.HTTPException:
                logger.exception("Could not close announcement for tournament %s", event["id"])
                return
        await tq.mark_closed_message_updated(self.bot.db, int(event["id"]))

    @tasks.loop(minutes=1)
    async def close_due_tournaments(self):
        for event in await tq.get_due_tournaments(self.bot.db):
            await self._close_event(event)

    @close_due_tournaments.before_loop
    async def before_close_due_tournaments(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Tournaments(bot))
