"""Sammenkoblingen af torsdagsbar-funktionen med Discord-klienten.

``TorsdagsbarModule`` ejer databasen, voice-trackeren, den periodiske tick-task
og fredagsopsummeringen. Den kobles på den eksisterende ``TorsdagBot`` uden at
røre afstemningen.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import discord
from discord.ext import tasks

from .config import TorsdagsbarConfig
from .database import Database
from .period import clamp
from .stats import Engine
from . import formatting as fmt

log = logging.getLogger("torsdagbot.torsdagsbar")


def subtract_months(d: date, months: int) -> date:
    """Træk et antal måneder fra en dato (klamper dagen ved månedsskift)."""
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # Klamp dagen til månedens længde.
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = (next_month_first - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


class TorsdagsbarModule:
    def __init__(
        self,
        client: discord.Client,
        config: TorsdagsbarConfig,
        db: Database,
    ) -> None:
        self.client = client
        self.config = config
        self.db = db
        self.tz = config.schedule.tz
        self.schedule = config.schedule

        # Importér her for at undgå cirkulær import (tracker/commands bruger os ikke).
        from .tracker import VoiceTracker

        self.tracker = VoiceTracker(client, config, db)
        self._summary_lock = asyncio.Lock()
        self._started = False

    # -- livscyklus ---------------------------------------------------------
    async def setup(self) -> None:
        """Registrér kommandoer og start baggrundstasken. Kaldes fra setup_hook."""
        from .commands import build_group

        group = build_group(self)
        # Fjern en evt. tidligere gruppe (ved reconnect genopbygges træet).
        try:
            self.client.tree.remove_command(group.name)
        except Exception:
            pass
        self.client.tree.add_command(group)
        log.info("Torsdagsbar: /%s-kommandoer registreret.", group.name)

        self.tick_loop.change_interval(seconds=self.config.tick_seconds)
        if not self.tick_loop.is_running():
            self.tick_loop.start()

    async def on_ready(self) -> None:
        """Genopret registreringen ud fra databasen og de aktuelle voice-states."""
        try:
            await self.tracker.recover()
        except Exception:
            log.exception("Torsdagsbar: fejl under gendannelse ved opstart.")
        # Send evt. en manglende fredagsopsummering (fx efter genstart kl. 12).
        await self._maybe_send_due_summary()
        self._log_status_line()

    async def on_voice_state_update(self, member, before, after) -> None:
        await self.tracker.on_voice_state_update(member, before, after)

    async def close(self) -> None:
        if self.tick_loop.is_running():
            self.tick_loop.cancel()
        await self.tracker.flush_on_shutdown()

    def _log_status_line(self) -> None:
        now = self.tracker.now()
        active = self.schedule.current_bar_date(now)
        if active:
            log.info("Torsdagsbar AKTIV nu (%s). Registrerer voice indtil kl. %02d:%02d.",
                     active.isoformat(), self.schedule.end_hour, self.schedule.end_minute)
        else:
            nxt = self.schedule.next_start(now)
            log.info("Torsdagsbar: næste registrering starter %s.",
                     nxt.strftime("%A %d-%m-%Y kl. %H:%M %Z"))

    # -- baggrundstask ------------------------------------------------------
    @tasks.loop(seconds=30)
    async def tick_loop(self) -> None:
        try:
            await self.tracker.tick()
            await self._maybe_send_due_summary()
        except Exception:
            log.exception("Torsdagsbar: uventet fejl i tick-loop.")

    @tick_loop.before_loop
    async def _before_tick(self) -> None:
        await self.client.wait_until_ready()

    # -- databaseadgang -> statistik-motor ---------------------------------
    async def build_engine(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        live: bool = True,
    ) -> Engine:
        """Byg en statistik-motor. Streaks kræver fuld historik, så motoren
        indlæser altid ALLE sessioner; periodefiltrering sker i metoderne.

        Med ``live=True`` (standard) medregnes åbne sessioner, mens
        torsdagsbaren er i gang: de får en foreløbig varighed op til "nu"
        (klampet til registreringsvinduet). Så viser statistik og leaderboard
        den løbende tid med det samme i stedet for først, når folk går.
        """
        sessions = await asyncio.to_thread(
            self.db.load_sessions, None, None, None, live
        )
        if live:
            now = self.tracker.now()
            for s in sessions:
                if s.left_at is not None:
                    continue
                try:
                    bar = date.fromisoformat(s.bar_date)
                except ValueError:
                    # Kan ikke placere sessionen i et vindue – spring den over.
                    s.duration_seconds = None
                    continue
                _, window_end = self.schedule.window_of(bar)
                joined_local = s.joined_at.astimezone(self.tz)
                provisional = clamp(now, joined_local, window_end)
                s.left_at = provisional
                s.duration_seconds = max(0, int((provisional - joined_local).total_seconds()))
        nights = await asyncio.to_thread(self.db.load_nights)
        corrections = await asyncio.to_thread(self.db.load_corrections, None, None, None)
        return Engine(
            sessions,
            nights,
            corrections,
            self.config.min_seconds,
            require_company=self.config.require_company,
        )

    # -- navneopslag --------------------------------------------------------
    def name_of(self, user_id: int) -> str:
        """Foretræk det aktuelle visningsnavn fra serveren, ellers det gemte."""
        if self.config.server_id:
            guild = self.client.get_guild(self.config.server_id)
            if guild is not None:
                member = guild.get_member(user_id)
                if member is not None:
                    return member.display_name
        stored = self.db.display_name(user_id)
        return stored or str(user_id)

    # -- perioder -----------------------------------------------------------
    def period_bounds(self, periode: str) -> tuple[Optional[str], Optional[str], str]:
        """(start_date, end_date, label) ud fra et periode-valg."""
        today = self.tracker.now().date()
        label = fmt.PERIODE_NAVNE.get(periode, "Hele perioden")
        if periode == "sidste_uge":
            return (today - timedelta(days=7)).isoformat(), today.isoformat(), label
        if periode == "denne_måned":
            return today.replace(day=1).isoformat(), today.isoformat(), label
        if periode == "sidste_3_måneder":
            return subtract_months(today, 3).isoformat(), today.isoformat(), label
        if periode == "sidste_6_måneder":
            return subtract_months(today, 6).isoformat(), today.isoformat(), label
        return None, None, "Hele perioden"

    def next_summary_time(self, now: Optional[datetime] = None) -> datetime:
        """Hvornår sendes den næste automatiske fredagsopsummering?"""
        now = now or self.tracker.now()
        mr = self.schedule.most_recent_bar_date(now)
        st = self.schedule.summary_time_of(mr)
        if st > now:
            return st
        return self.schedule.summary_time_of(mr + timedelta(days=7))

    # -- adgangskontrol -----------------------------------------------------
    def is_admin(self, interaction: discord.Interaction) -> bool:
        user = interaction.user
        member = user if isinstance(user, discord.Member) else None
        if member is None and self.config.server_id:
            guild = self.client.get_guild(self.config.server_id)
            if guild is not None:
                member = guild.get_member(user.id)
        if member is None:
            return False
        perms = getattr(member, "guild_permissions", None)
        if perms is not None and (perms.administrator or perms.manage_guild):
            return True
        role_ids = {r.id for r in getattr(member, "roles", [])}
        role_names = {r.name.lower() for r in getattr(member, "roles", [])}
        if self.config.admin_role_id and self.config.admin_role_id in role_ids:
            return True
        if self.config.admin_role_name and self.config.admin_role_name.lower() in role_names:
            return True
        return False

    # -- fredagsopsummering -------------------------------------------------
    async def _maybe_send_due_summary(self) -> None:
        now = self.tracker.now()
        bar_date = self.schedule.due_summary_bar_date(now, self.config.summary_catch_up_hours)
        if bar_date is None:
            return
        if await asyncio.to_thread(self.db.is_summary_sent, bar_date.isoformat()):
            return
        await self.send_summary(bar_date, force=False)

    async def send_summary(self, bar_date: date, force: bool = False) -> bool:
        """Send (eller gensend) fredagsopsummeringen for en torsdagsbar.

        Returnerer True hvis en besked blev sendt. Sender kun én gang pr. bar,
        medmindre ``force`` er sat (bruges af admin-kommandoen).
        """
        async with self._summary_lock:
            already = await asyncio.to_thread(self.db.is_summary_sent, bar_date.isoformat())
            if already and not force:
                return False

            channel = self.client.get_channel(self.config.summary_channel_id)
            if channel is None:
                try:
                    channel = await self.client.fetch_channel(self.config.summary_channel_id)
                except discord.HTTPException as exc:
                    log.error("Torsdagsbar: kunne ikke finde opsummeringskanalen %s: %s",
                              self.config.summary_channel_id, exc)
                    return False
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                log.error("Torsdagsbar: opsummeringskanalen %s er ikke en tekstkanal.",
                          self.config.summary_channel_id)
                return False

            engine = await self.build_engine()
            ns = engine.night_summary(bar_date.isoformat())
            embed = fmt.summary_embed(
                ns, self.name_of, self.tz, show_records=self.config.summary_show_records
            )
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                log.error("Torsdagsbar: mangler rettigheder til at skrive i opsummeringskanalen.")
                return False
            except discord.HTTPException as exc:
                log.error("Torsdagsbar: kunne ikke sende opsummering: %s", exc)
                return False

            if not force:
                await asyncio.to_thread(self.db.mark_summary_sent, bar_date, True)
            log.info("Torsdagsbar: opsummering sendt for %s (%d deltagere%s).",
                     bar_date.isoformat(), ns.participant_count,
                     ", gensendt" if force else "")
            return True
