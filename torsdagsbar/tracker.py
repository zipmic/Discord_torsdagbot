"""Voice-registrering for torsdagsbaren.

Trackeren lytter på ``on_voice_state_update`` og fører en session pr. bruger,
mens de sidder i en af de registrerede voicekanaler inden for registrerings-
vinduet (torsdag 19:00 → fredag 03:00).

Robusthed:
  * Kun rigtige brugere registreres – botter springes over.
  * En bruger har højst én åben session ad gangen (dubletter ignoreres).
  * Skift mellem to registrerede kanaler tæller IKKE som at forlade baren.
  * Er man online kl. 19:00, starter registreringen kl. 19:00.
  * Er man online kl. 03:00, afsluttes registreringen automatisk kl. 03:00.
  * Ved genstart/nedbrud genoprettes åbne sessioner ud fra databasen og de
    brugere, der rent faktisk sidder i kanalerne nu.

Databasekald køres via ``asyncio.to_thread``, så event-loopet ikke blokeres.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import discord

from .config import TorsdagsbarConfig
from .database import Database
from .period import clamp

log = logging.getLogger("torsdagbot.torsdagsbar.tracker")


class VoiceTracker:
    def __init__(
        self,
        client: discord.Client,
        config: TorsdagsbarConfig,
        db: Database,
    ) -> None:
        self.client = client
        self.config = config
        self.db = db
        self.schedule = config.schedule
        self.tz = config.schedule.tz
        # Den bar-dato vi pt. betragter som aktiv (None = udenfor vinduet).
        # Bruges til at opdage 19:00- og 03:00-overgange.
        self._active_date: Optional[date] = None
        self._lock = asyncio.Lock()

    # -- hjælpere -----------------------------------------------------------
    def now(self) -> datetime:
        return datetime.now(self.tz)

    def is_tracked_channel(self, channel: Optional[discord.abc.GuildChannel]) -> bool:
        if channel is None:
            return False
        guild = getattr(channel, "guild", None)
        if guild is None or (self.config.server_id and guild.id != self.config.server_id):
            return False
        return channel.id in self.config.voice_channel_ids

    def _current_bar_date(self, now: Optional[datetime] = None) -> Optional[date]:
        return self.schedule.current_bar_date(now or self.now())

    def _present_members(self) -> dict[int, tuple[discord.Member, int]]:
        """Rigtige brugere der lige nu sidder i de registrerede kanaler.

        {user_id: (member, channel_id)}. Bygger på voice-state-cachen, som er
        tilgængelig med standard-intents (ingen privilegerede intents kræves).
        """
        result: dict[int, tuple[discord.Member, int]] = {}
        for channel_id in self.config.voice_channel_ids:
            channel = self.client.get_channel(channel_id)
            # Voice- og stage-kanaler har en .members-liste med de tilsluttede
            # brugere (fyldt af voice-state-cachen, uden privilegerede intents).
            members = getattr(channel, "members", None)
            if channel is None or members is None:
                continue
            guild = getattr(channel, "guild", None)
            if self.config.server_id and guild is not None and guild.id != self.config.server_id:
                continue
            for member in members:
                if getattr(member, "bot", False):
                    continue
                result[member.id] = (member, channel_id)
        return result

    # -- event fra discord --------------------------------------------------
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Kaldes af klienten ved hver voice-ændring."""
        if member.bot:
            return
        if self.config.server_id and getattr(member, "guild", None) and member.guild.id != self.config.server_id:
            return

        before_tracked = self.is_tracked_channel(before.channel)
        after_tracked = self.is_tracked_channel(after.channel)
        if not before_tracked and not after_tracked:
            return  # hændelsen har intet med torsdagsbaren at gøre

        now = self.now()
        bar_date = self._current_bar_date(now)

        async with self._lock:
            try:
                if after_tracked and bar_date is not None:
                    # Tilslutter sig / sidder stadig i en registreret kanal.
                    if before_tracked:
                        # Skift mellem to registrerede kanaler → opdater kun kanalen.
                        await self._update_channel(member, after.channel.id)
                    else:
                        await self._open(member, after.channel.id, now, bar_date)
                elif before_tracked and not after_tracked:
                    # Forlader torsdagsbaren (eller bliver koblet af).
                    await self._close(member, now, bar_date)
                # after_tracked men udenfor vinduet: ignorer (ingen registrering nu).
            except Exception:
                log.exception("Fejl i on_voice_state_update for %s", member)

    # -- session-operationer (kald med _lock holdt) -------------------------
    async def _open(
        self, member: discord.Member, channel_id: int, now: datetime, bar_date: date
    ) -> None:
        start, end = self.schedule.window_of(bar_date)
        joined = clamp(now, start, end)
        await asyncio.to_thread(self.db.upsert_user, member.id, member.display_name)
        sid = await asyncio.to_thread(
            self.db.open_session, member.id, member.display_name, bar_date, channel_id, joined, "auto"
        )
        log.info(
            "Registrering START: %s (%s) i kanal %s [session %s, %s]",
            member.display_name, member.id, channel_id, sid, bar_date.isoformat(),
        )

    async def _update_channel(self, member: discord.Member, channel_id: int) -> None:
        open_session = await asyncio.to_thread(self.db.get_open_session, member.id)
        if open_session is None:
            # Manglede en åben session (fx efter nedbrud) → åbn en ny.
            now = self.now()
            bar_date = self._current_bar_date(now)
            if bar_date is not None:
                await self._open(member, channel_id, now, bar_date)
            return
        await asyncio.to_thread(self.db.set_session_channel, open_session.id, channel_id)
        log.debug("Kanalskift: %s → kanal %s (session %s)", member.display_name, channel_id, open_session.id)

    async def _close(
        self, member: discord.Member, now: datetime, bar_date: Optional[date]
    ) -> None:
        open_session = await asyncio.to_thread(self.db.get_open_session, member.id)
        if open_session is None:
            return
        # Klamp sluttidspunktet til vinduets slutning for den nat, sessionen hører til.
        try:
            session_date = date.fromisoformat(open_session.bar_date)
        except ValueError:
            session_date = bar_date or now.date()
        _, end = self.schedule.window_of(session_date)
        left = clamp(now, open_session.joined_at.astimezone(self.tz), end)
        duration = await asyncio.to_thread(self.db.close_session, open_session.id, left)
        await asyncio.to_thread(self.db.upsert_user, member.id, member.display_name)
        log.info(
            "Registrering STOP: %s (%s) – varighed %s min [session %s]",
            member.display_name, member.id,
            (duration or 0) // 60, open_session.id,
        )

    # -- periodisk tjek + gendannelse --------------------------------------
    async def recover(self) -> None:
        """Genopret tilstanden efter (gen)start. Kaldes fra on_ready."""
        async with self._lock:
            now = self.now()
            bar_date = self._current_bar_date(now)
            self._active_date = bar_date

            present = self._present_members()
            open_sessions = await asyncio.to_thread(self.db.list_open_sessions)
            heartbeat = await asyncio.to_thread(self.db.get_heartbeat)

            # 1) Luk åbne sessioner for brugere, der ikke længere sidder i kanalerne.
            for sess in open_sessions:
                if sess.user_id in present:
                    continue  # de sidder her stadig → fortsæt sessionen uændret
                try:
                    session_date = date.fromisoformat(sess.bar_date)
                except ValueError:
                    session_date = now.date()
                _, end = self.schedule.window_of(session_date)
                # Bedste bud på sluttidspunkt: sidste heartbeat (da botten sidst
                # var i live), klampet til vinduet.
                guess = heartbeat.astimezone(self.tz) if heartbeat else now
                left = clamp(guess, sess.joined_at.astimezone(self.tz), end)
                await asyncio.to_thread(self.db.close_session, sess.id, left)
                log.info(
                    "Gendannelse: lukkede efterladt session for bruger %s ved %s.",
                    sess.user_id, left.strftime("%Y-%m-%d %H:%M"),
                )

            # 2) Er vi i vinduet: åbn sessioner for tilstedeværende uden en åben session.
            if bar_date is not None:
                open_ids = {
                    s.user_id
                    for s in await asyncio.to_thread(self.db.list_open_sessions)
                }
                for uid, (member, channel_id) in present.items():
                    if uid in open_ids:
                        continue
                    # Konservativt: start "nu" (vi kan ikke vide, hvornår de kom
                    # under nedtiden). Sessioner, der var åbne før, fortsætter urørt.
                    await self._open(member, channel_id, now, bar_date)

            await asyncio.to_thread(self.db.set_heartbeat, now.astimezone(timezone.utc))
            log.info(
                "Torsdagsbar-gendannelse færdig (%s, %d tilstede).",
                bar_date.isoformat() if bar_date else "udenfor vindue",
                len(present),
            )

    async def tick(self) -> None:
        """Periodisk tjek: heartbeat + håndtering af 19:00- og 03:00-overgange."""
        async with self._lock:
            now = self.now()
            await asyncio.to_thread(self.db.set_heartbeat, now.astimezone(timezone.utc))

            cur = self._current_bar_date(now)

            if cur != self._active_date:
                # Overgang ind i eller ud af registreringsvinduet.
                if self._active_date is not None and cur != self._active_date:
                    # Vinduet er slut (eller skiftede) → luk alt ved forrige slut.
                    _, prev_end = self.schedule.window_of(self._active_date)
                    closed = await asyncio.to_thread(
                        self.db.close_all_open, now.astimezone(timezone.utc), prev_end.astimezone(timezone.utc)
                    )
                    if closed:
                        log.info("Registreringsvindue slut – lukkede %d åbne sessioner ved 03:00.", closed)
                if cur is not None:
                    # Vinduet er lige begyndt → registrér dem, der allerede sidder der,
                    # med start på selve starttidspunktet (fx kl. 19:00).
                    start, _ = self.schedule.window_of(cur)
                    await self._open_present(start_at=start, bar_date=cur)
                self._active_date = cur
            elif cur is not None:
                # Igangværende: fang manglende join-/leave-events (sikkerhedsnet).
                await self._reconcile(now, cur)

    async def _open_present(self, start_at: datetime, bar_date: date) -> None:
        present = self._present_members()
        open_ids = {s.user_id for s in await asyncio.to_thread(self.db.list_open_sessions)}
        for uid, (member, channel_id) in present.items():
            if uid in open_ids:
                continue
            await asyncio.to_thread(self.db.upsert_user, member.id, member.display_name)
            sid = await asyncio.to_thread(
                self.db.open_session, member.id, member.display_name, bar_date, channel_id, start_at, "auto"
            )
            log.info(
                "Registrering START (allerede online ved start): %s (%s) [session %s]",
                member.display_name, member.id, sid,
            )

    async def _reconcile(self, now: datetime, bar_date: date) -> None:
        """Sikkerhedsnet: åbn manglende sessioner, luk sessioner for folk der er gået."""
        present = self._present_members()
        open_sessions = await asyncio.to_thread(self.db.list_open_sessions)
        open_by_user = {s.user_id: s for s in open_sessions}
        _, end = self.schedule.window_of(bar_date)

        # Åbn for tilstedeværende uden session (missede join-event).
        for uid, (member, channel_id) in present.items():
            if uid not in open_by_user:
                await self._open(member, channel_id, now, bar_date)

        # Luk sessioner for brugere, der ikke længere er tilstede (missede leave-event).
        for uid, sess in open_by_user.items():
            if uid not in present:
                left = clamp(now, sess.joined_at.astimezone(self.tz), end)
                dur = await asyncio.to_thread(self.db.close_session, sess.id, left)
                log.info(
                    "Sikkerhedsnet: lukkede session for bruger %s (ikke længere tilstede), "
                    "varighed %s min.", uid, (dur or 0) // 60,
                )

    async def flush_on_shutdown(self) -> None:
        """Luk pænt ned: gem heartbeat. Åbne sessioner bevares (left_at=NULL),
        så de kan genoptages ved næste opstart, hvis brugerne stadig sidder der."""
        try:
            await asyncio.to_thread(self.db.set_heartbeat, self.now().astimezone(timezone.utc))
        except Exception:
            log.debug("Kunne ikke gemme heartbeat ved nedlukning", exc_info=True)

    # -- live-status (til /torsdagsbar live og status) ----------------------
    async def live_status(self, now: Optional[datetime] = None) -> dict:
        now = now or self.now()
        bar_date = self._current_bar_date(now)
        if bar_date is None:
            return {
                "active": False,
                "next_start": self.schedule.next_start(now),
                "now": now,
            }

        start, end = self.schedule.window_of(bar_date)
        # Alle sessioner (inkl. åbne) for natten.
        sessions = await asyncio.to_thread(
            self.db.load_sessions, bar_date.isoformat(), bar_date.isoformat(), None, True
        )
        corr_total_by_user: dict[int, int] = {}
        for c in await asyncio.to_thread(self.db.load_corrections, bar_date.isoformat(), bar_date.isoformat(), None):
            corr_total_by_user[c.user_id] = corr_total_by_user.get(c.user_id, 0) + c.delta_seconds

        present = self._present_members()
        per_user: dict[int, dict] = {}
        for s in sessions:
            u = per_user.setdefault(s.user_id, {"seconds": 0, "name": s.display_name, "channel_id": s.channel_id, "joined_at": None})
            if s.left_at is not None:
                u["seconds"] += int(s.duration_seconds or 0)
            else:
                # Åben session: medregn tiden indtil nu (klampet til vinduet).
                live_end = clamp(now, s.joined_at.astimezone(self.tz), end)
                u["seconds"] += max(0, int((live_end - s.joined_at.astimezone(self.tz)).total_seconds()))
                u["joined_at"] = s.joined_at
                u["channel_id"] = s.channel_id
            u["name"] = s.display_name
        for uid, extra in corr_total_by_user.items():
            if uid in per_user:
                per_user[uid]["seconds"] = max(0, per_user[uid]["seconds"] + extra)

        online = []
        for uid, (member, channel_id) in present.items():
            info = per_user.get(uid, {"seconds": 0})
            online.append({
                "user_id": uid,
                "name": member.display_name,
                "channel_id": channel_id,
                "joined_at": info.get("joined_at"),
                "seconds": info.get("seconds", 0),
            })
        online.sort(key=lambda x: -x["seconds"])

        return {
            "active": True,
            "bar_date": bar_date,
            "now": now,
            "start": start,
            "end": end,
            "online": online,
            "current_count": len(online),
            "unique_count": len(per_user),
            "total_seconds": sum(u["seconds"] for u in per_user.values()),
            "time_left": end - now,
        }
