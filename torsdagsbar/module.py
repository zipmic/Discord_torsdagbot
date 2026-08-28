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

from .commands import build_group, build_quote_commands
from .config import TorsdagsbarConfig
from .database import Database
from .period import clamp
from .stats import Engine
from .tracker import VoiceTracker
from .awards import (
    AwardRules,
    AwardTally,
    compute_night_awards,
    earned_badges,
    tally_for_user,
    typical_arrival_minutes,
)
from .votes import VoteOption, find_option, promise_window, sync_native_votes
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
        vote_options: Optional[list[VoteOption]] = None,
    ) -> None:
        self.client = client
        self.config = config
        self.db = db
        self.tz = config.schedule.tz
        self.schedule = config.schedule
        # Afstemningens svarmuligheder (leveres af hovedbotten).
        self.vote_options: list[VoteOption] = list(vote_options or [])

        self.tracker = VoiceTracker(client, config, db)
        self._summary_lock = asyncio.Lock()
        self._started = False
        self._late_lock = asyncio.Lock()
        # Hvornår stemmerne sidst blev hentet fra Discords indbyggede poll.
        self._last_vote_sync: Optional[datetime] = None

    # -- livscyklus ---------------------------------------------------------
    async def setup(self) -> None:
        """Registrér kommandoer og start baggrundstasken. Kaldes fra setup_hook."""
        # Fjern evt. tidligere kommandoer (ved reconnect genopbygges træet).
        for command in [build_group(self), *build_quote_commands(self)]:
            try:
                self.client.tree.remove_command(command.name)
            except Exception:
                pass
            self.client.tree.add_command(command)
        log.info("Torsdagsbar: /torsdagsbar-, /quote- og /quotes-kommandoer registreret.")

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

    # -- afstemningen (broen fra hovedbotten) ------------------------------
    async def on_poll_sent(
        self, message_id: int, channel_id: Optional[int], mode: str, now: datetime
    ) -> None:
        """Hovedbotten har sendt ugens afstemning – husk hvor den står."""
        if channel_id is None:
            return
        bar_date = self.schedule.poll_bar_date(now)
        await asyncio.to_thread(
            self.db.record_poll_message, bar_date, message_id, channel_id, mode
        )
        # Hent stemmerne snarest muligt ved næste tick.
        self._last_vote_sync = None
        log.info(
            "Torsdagsbar: afstemningen for %s registreret (%s, besked %s).",
            bar_date.isoformat(), mode, message_id,
        )

    async def on_button_vote(self, user_id: int, option_key: str, now: datetime) -> None:
        """En bruger trykkede på en knap i afstemningen."""
        bar_date = self.schedule.poll_bar_date(now)
        await asyncio.to_thread(
            self.db.upsert_vote, bar_date, user_id, option_key, "buttons"
        )

    async def _maybe_sync_votes(self) -> None:
        """Hent stemmerne fra Discords indbyggede poll med jævne mellemrum.

        Kører fra afstemningen er sendt, til fredagsopsummeringen er skrevet –
        derefter er stemmerne alligevel låst fast i databasen.
        """
        if not self.vote_options:
            return
        now = self.tracker.now()
        if (
            self._last_vote_sync is not None
            and (now - self._last_vote_sync).total_seconds() < self.config.vote_sync_seconds
        ):
            return

        # Først den bar, afstemningen handler om. Er der endnu ikke sendt en
        # afstemning for den, synkroniseres den forrige bar videre, indtil dens
        # opsummering er skrevet – ellers ville sene stemmeskift gå tabt i
        # timerne mellem baren lukker og opsummeringen sendes.
        kandidater = [self.schedule.poll_bar_date(now)]
        tidligere = self.schedule.most_recent_bar_date(now)
        if tidligere not in kandidater:
            kandidater.append(tidligere)

        bar_date = None
        poll_ref = None
        for kandidat in kandidater:
            if now > self.schedule.summary_time_of(kandidat):
                continue
            poll_ref = await asyncio.to_thread(
                self.db.get_poll_message, kandidat.isoformat()
            )
            if poll_ref is not None:
                bar_date = kandidat
                break
        if poll_ref is None or bar_date is None:
            return
        self._last_vote_sync = now
        if poll_ref.get("mode") != "native":
            return  # knap-stemmer kommer ind direkte via on_button_vote

        antal = await sync_native_votes(
            self.client, self.db, bar_date, self.vote_options, poll_ref
        )
        if antal >= 0:
            log.debug("Torsdagsbar: %d stemmer synkroniseret for %s.", antal, bar_date)

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
            await self._maybe_sync_votes()
            await self._maybe_send_late_notices()
            await self._maybe_send_due_summary()
        except Exception:
            log.exception("Torsdagsbar: uventet fejl i tick-loop.")

    @tick_loop.before_loop
    async def _before_tick(self) -> None:
        try:
            await self.client.wait_until_ready()
        except RuntimeError:
            # Klienten er ikke logget ind (kan ske i test eller hvis der lukkes
            # ned midt i opstarten). Loopet må ikke dø af det.
            pass

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
    def year_bounds(self, year: int) -> tuple[str, str, str]:
        """(start, slut, label) for et helt kalenderår."""
        return f"{year}-01-01", f"{year}-12-31", str(year)

    def period_bounds(
        self, periode: str, year: Optional[int] = None
    ) -> tuple[Optional[str], Optional[str], str]:
        """(start_date, end_date, label) ud fra et periode-valg.

        Et konkret ``year`` overtrumfer periodevalget, så man altid kan slå et
        tidligere år op. Standardperioden er indeværende kalenderår, så
        statistikken naturligt starter forfra ved nytår – uden at gamle år går
        tabt (de kan hentes frem igen med "Sidste år" eller år:ÅÅÅÅ).
        """
        today = self.tracker.now().date()
        if year is not None:
            return self.year_bounds(year)
        label = fmt.PERIODE_NAVNE.get(periode, "Hele perioden")
        if periode == "i_år":
            start, end, _ = self.year_bounds(today.year)
            return start, end, f"I år ({today.year})"
        if periode == "sidste_år":
            start, end, _ = self.year_bounds(today.year - 1)
            return start, end, f"Sidste år ({today.year - 1})"
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

    # -- profilkort ---------------------------------------------------------
    async def build_profile(
        self, target, start: Optional[str], end: Optional[str], periode_label: str
    ):
        """Byg det samlede profilkort for en bruger."""
        engine = await self.build_engine()
        stats = engine.user_stats(target.id, start, end)
        votes_by_night = await asyncio.to_thread(self.db.load_votes, start, end, None)
        tally = tally_for_user(
            engine, target.id, votes_by_night, self.vote_options,
            self.schedule, self.award_rules, start, end,
        )
        badges = earned_badges(
            nights=stats.nights,
            longest_streak=engine.streak(target.id).longest,
            tally=tally,
        )
        minutter = typical_arrival_minutes(engine, target.id, self.schedule, start, end)
        ankomst = fmt.fmt_arrival_offset(
            minutter, self.schedule.start_hour, self.schedule.start_minute
        )
        antal_citater = await asyncio.to_thread(self.db.quote_count, target.id)
        avatar = getattr(getattr(target, "display_avatar", None), "url", None)
        return fmt.profile_embed(
            stats, engine, tally, badges, self.name_of, self.tz, periode_label,
            typical_arrival=ankomst,
            quote_count=antal_citater,
            avatar_url=avatar,
        )

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

    # -- aftentitler --------------------------------------------------------
    @property
    def award_rules(self) -> AwardRules:
        """Grænserne for aftenens titler, som de er sat i konfigurationen."""
        return AwardRules(
            marathon_seconds=int(self.config.marathon_hours * 3600),
            speedrun_min_seconds=self.config.speedrun_min_minutes * 60,
            big_words_seconds=int(self.config.big_words_hours * 3600),
            alone_min_seconds=self.config.waiting_min_minutes * 60,
        )

    async def night_awards(self, engine: Engine, bar_date: date):
        """Beregn aftenens titler for en given torsdagsbar."""
        votes = await asyncio.to_thread(self.db.votes_for_night, bar_date.isoformat())
        return compute_night_awards(
            engine, bar_date.isoformat(), votes, self.vote_options,
            self.schedule, self.award_rules,
        )

    # -- "du er sent på den" ------------------------------------------------
    async def _late_channel(self):
        """Kanalen til forsinkelsesbeskeder (falder tilbage til opsummeringen)."""
        channel_id = self.config.late_channel_id or self.config.summary_channel_id
        if channel_id is None:
            return None
        channel = self.client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.client.fetch_channel(channel_id)
            except Exception as exc:
                log.error("Torsdagsbar: kunne ikke finde kanalen til forsinkelser: %s", exc)
                return None
        return channel

    async def _maybe_send_late_notices(self) -> None:
        """Drill dem, der lovede at komme, men ikke er dukket op endnu.

        Kun for løfter med et konkret sluttidspunkt: "efter 21:00", "efter 22:00"
        og "jeg kommer ikke" kan man ikke komme for sent til. Højst én besked pr.
        bruger pr. aften, og kun inden for karensvinduet efter deadline, så en
        bot der starter sent ikke spammer med timegamle forsinkelser.
        """
        if not self.config.late_enabled or not self.vote_options:
            return
        now = self.tracker.now()
        bar_date = self.schedule.current_bar_date(now)
        if bar_date is None:
            return  # kun mens torsdagsbaren kører

        async with self._late_lock:
            night = await asyncio.to_thread(self.db.get_night, bar_date.isoformat())
            if night is not None and night.cancelled:
                return

            votes = await asyncio.to_thread(self.db.votes_for_night, bar_date.isoformat())
            if not votes:
                return

            sessions = await asyncio.to_thread(
                self.db.load_sessions, bar_date.isoformat(), bar_date.isoformat(), None, True
            )
            ankommet = {s.user_id for s in sessions}
            allerede = await asyncio.to_thread(
                self.db.late_notified_users, bar_date.isoformat()
            )
            window_start, _ = self.schedule.window_of(bar_date)
            karens = timedelta(minutes=self.config.late_grace_minutes)

            for user_id, option_key in votes.items():
                if user_id in ankommet or user_id in allerede:
                    continue
                option = find_option(self.vote_options, option_key)
                if option is None or not option.has_deadline:
                    continue
                _, deadline = promise_window(option, bar_date, self.tz, window_start)
                if deadline is None or not (deadline <= now <= deadline + karens):
                    continue
                # mark_late_notice er atomisk: True kun første gang.
                if not await asyncio.to_thread(self.db.mark_late_notice, bar_date, user_id):
                    continue
                await self._send_late_message(user_id, option)

    async def _send_late_message(self, user_id: int, option: VoteOption) -> None:
        channel = await self._late_channel()
        if channel is None:
            return
        tekst = fmt.late_message(f"<@{user_id}>", option.label)
        try:
            await channel.send(
                tekst,
                allowed_mentions=discord.AllowedMentions(
                    users=True, everyone=False, roles=False, replied_user=False
                ),
            )
            log.info(
                "Torsdagsbar: forsinkelsesbesked sendt til %s (%s).",
                self.name_of(user_id), option.label,
            )
        except discord.Forbidden:
            log.error("Torsdagsbar: mangler rettigheder til at sende forsinkelsesbesked.")
        except discord.HTTPException as exc:
            log.error("Torsdagsbar: kunne ikke sende forsinkelsesbesked: %s", exc)

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
            awards = await self.night_awards(engine, bar_date)
            embed = fmt.summary_embed(
                ns, self.name_of, self.tz,
                show_records=self.config.summary_show_records,
                awards=awards,
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
