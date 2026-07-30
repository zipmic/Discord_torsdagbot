"""Genberegnelig statistik for torsdagsbaren.

Alt beregnes ud fra de gemte sessioner + nætter + rettelser, så tallene altid
kan genberegnes, hvis reglerne eller dataene ændrer sig. Ingen discord- eller
database-import her – motoren får rene dataklasser ind og giver rene resultater
ud, så den er nem at teste.

Vigtige regler:
  * En brugers "nat-total" = summen af brugerens lukkede sessioner den aften
    plus eventuelle manuelle rettelser (aldrig under 0).
  * En bruger "deltog" en aften, hvis nat-totalen er mindst minimumsgrænsen OG
    natten ikke er aflyst.
  * En "tællende nat" er en ikke-aflyst nat med mindst én kvalificeret deltager.
    Aflyste nætter (og helt tomme nætter) tæller neutralt og bryder ikke streaks.
  * En streak = antal tællende nætter i træk, hvor brugeren deltog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .database import Correction, Night, Session


# ---------------------------------------------------------------------------
# Resultat-dataklasser
# ---------------------------------------------------------------------------
@dataclass
class StreakInfo:
    user_id: int
    current: int = 0
    current_active: bool = False
    longest: int = 0
    longest_start: Optional[str] = None
    longest_end: Optional[str] = None


@dataclass
class UserStats:
    user_id: int
    total_seconds: int = 0
    nights: int = 0
    average_seconds: float = 0.0
    longest_single_seconds: int = 0
    longest_single_date: Optional[str] = None
    longest_single_start: Optional[datetime] = None
    longest_single_end: Optional[datetime] = None
    current_streak: int = 0
    longest_streak: int = 0
    rank: Optional[int] = None
    participants_in_period: int = 0


@dataclass
class LeaderboardRow:
    user_id: int
    value_seconds: int = 0           # den primære sorteringsværdi når den er tid
    value_number: float = 0.0        # den primære sorteringsværdi når den er et tal
    total_seconds: int = 0
    nights: int = 0
    average_seconds: float = 0.0
    current_streak: int = 0
    longest_streak: int = 0
    longest_single_seconds: int = 0


@dataclass
class NightSummary:
    bar_date: str
    cancelled: bool
    participants: list[tuple[int, int]] = field(default_factory=list)  # (user_id, seconds) sorteret faldende
    total_seconds: int = 0
    participant_count: int = 0
    first_join: Optional[datetime] = None
    last_leave: Optional[datetime] = None
    span_seconds: int = 0
    top_user: Optional[int] = None
    new_personal_records: list[int] = field(default_factory=list)   # user_ids
    new_participant_record: bool = False
    extended_streaks: list[tuple[int, int]] = field(default_factory=list)  # (user_id, streak)


# Sorteringsnøgler til leaderboardet.
SORT_KEYS = {
    "tid": "Samlet tid",
    "antal": "Antal torsdagsbarer",
    "gennemsnit": "Gennemsnitlig tid",
    "streak": "Nuværende streak",
    "længste_streak": "Længste streak",
    "længste_enkelt": "Længste enkeltdeltagelse",
}


class Engine:
    """Beregner alt ud fra fuld historik. Periodefiltrering sker i metoderne."""

    def __init__(
        self,
        sessions: list[Session],
        nights: dict[str, Night],
        corrections: list[Correction],
        min_seconds: int,
    ) -> None:
        self.sessions = [s for s in sessions if s.duration_seconds is not None]
        self.nights = nights
        self.min_seconds = max(0, int(min_seconds))

        self.cancelled: set[str] = {d for d, n in nights.items() if n.cancelled}

        # Seneste kendte visningsnavn pr. bruger (nyeste session vinder).
        self.names: dict[int, str] = {}
        for s in sorted(self.sessions, key=lambda x: x.joined_at):
            if s.display_name:
                self.names[s.user_id] = s.display_name

        # Nat-totaler: {bar_date: {user_id: sekunder}} (før minimumsfilter).
        self.night_user: dict[str, dict[int, int]] = {}
        for s in self.sessions:
            self.night_user.setdefault(s.bar_date, {})
            self.night_user[s.bar_date][s.user_id] = (
                self.night_user[s.bar_date].get(s.user_id, 0) + int(s.duration_seconds)
            )
        for c in corrections:
            self.night_user.setdefault(c.bar_date, {})
            self.night_user[c.bar_date][c.user_id] = (
                self.night_user[c.bar_date].get(c.user_id, 0) + int(c.delta_seconds)
            )
        # Klamp negative totaler (kan opstå ved store negative rettelser).
        for day in self.night_user.values():
            for uid in list(day):
                if day[uid] < 0:
                    day[uid] = 0

        # Tællende nætter: ikke aflyst + mindst én kvalificeret deltager.
        self.counting_dates: list[str] = sorted(
            d
            for d in self.night_user
            if d not in self.cancelled and self._qualifiers(d)
        )

        self._streaks: dict[int, StreakInfo] = self._compute_streaks()

    # -- grundlæggende opslag ----------------------------------------------
    def name(self, user_id: int) -> str:
        return self.names.get(user_id, str(user_id))

    def _qualifiers(self, bar_date: str) -> dict[int, int]:
        """{user_id: sekunder} for kvalificerede deltagere en given (ikke-aflyst) nat."""
        if bar_date in self.cancelled:
            return {}
        return {
            uid: sec
            for uid, sec in self.night_user.get(bar_date, {}).items()
            if sec >= self.min_seconds
        }

    def _in_period(self, bar_date: str, start: Optional[str], end: Optional[str]) -> bool:
        if start and bar_date < start:
            return False
        if end and bar_date > end:
            return False
        return True

    # -- streaks ------------------------------------------------------------
    def _compute_streaks(self) -> dict[int, StreakInfo]:
        result: dict[int, StreakInfo] = {}
        # Præberegn kvalificerede pr. tællende nat.
        quals = {d: set(self._qualifiers(d)) for d in self.counting_dates}
        all_users = {uid for d in self.counting_dates for uid in quals[d]}

        for uid in all_users:
            present = [uid in quals[d] for d in self.counting_dates]
            info = StreakInfo(user_id=uid)

            # Længste streak + hvornår.
            run = 0
            run_start_idx = 0
            best = 0
            best_start = best_end = None
            for i, p in enumerate(present):
                if p:
                    if run == 0:
                        run_start_idx = i
                    run += 1
                    if run > best:
                        best = run
                        best_start = self.counting_dates[run_start_idx]
                        best_end = self.counting_dates[i]
                else:
                    run = 0
            info.longest = best
            info.longest_start = best_start
            info.longest_end = best_end

            # Nuværende streak = sammenhængende bagerst, hvis med på seneste nat.
            current = 0
            for p in reversed(present):
                if p:
                    current += 1
                else:
                    break
            info.current = current
            info.current_active = current > 0 and present[-1]
            result[uid] = info
        return result

    def streak(self, user_id: int) -> StreakInfo:
        return self._streaks.get(user_id, StreakInfo(user_id=user_id))

    def active_streaks(self) -> list[StreakInfo]:
        """Aktive streaks sorteret efter længde (til top-10)."""
        return sorted(
            (s for s in self._streaks.values() if s.current_active),
            key=lambda s: (-s.current, self.name(s.user_id).lower()),
        )

    # -- per-bruger statistik ----------------------------------------------
    def user_stats(
        self, user_id: int, start: Optional[str] = None, end: Optional[str] = None
    ) -> UserStats:
        stats = UserStats(user_id=user_id)
        for bar_date in self.counting_dates:
            if not self._in_period(bar_date, start, end):
                continue
            sec = self._qualifiers(bar_date).get(user_id)
            if sec is None:
                continue
            stats.total_seconds += sec
            stats.nights += 1
        stats.average_seconds = stats.total_seconds / stats.nights if stats.nights else 0.0

        # Længste enkeltstående session i perioden.
        for s in self.sessions:
            if s.user_id != user_id or s.duration_seconds is None:
                continue
            if s.bar_date in self.cancelled or not self._in_period(s.bar_date, start, end):
                continue
            if s.duration_seconds > stats.longest_single_seconds:
                stats.longest_single_seconds = int(s.duration_seconds)
                stats.longest_single_date = s.bar_date
                stats.longest_single_start = s.joined_at
                stats.longest_single_end = s.left_at

        streak = self.streak(user_id)
        stats.current_streak = streak.current
        stats.longest_streak = streak.longest

        # Placering (efter samlet tid i perioden).
        board = self.leaderboard("tid", start, end, limit=None)
        for idx, row in enumerate(board, start=1):
            if row.user_id == user_id:
                stats.rank = idx
                break
        stats.participants_in_period = len(board)
        return stats

    # -- leaderboard --------------------------------------------------------
    def _period_user_totals(
        self, start: Optional[str], end: Optional[str]
    ) -> dict[int, dict[str, float]]:
        """Aggreger pr. bruger i perioden: tid, nætter, længste enkeltsession."""
        agg: dict[int, dict[str, float]] = {}
        for bar_date in self.counting_dates:
            if not self._in_period(bar_date, start, end):
                continue
            for uid, sec in self._qualifiers(bar_date).items():
                a = agg.setdefault(uid, {"total": 0, "nights": 0, "longest_single": 0})
                a["total"] += sec
                a["nights"] += 1
        for s in self.sessions:
            if s.duration_seconds is None or s.bar_date in self.cancelled:
                continue
            if not self._in_period(s.bar_date, start, end):
                continue
            if s.user_id in agg and s.duration_seconds > agg[s.user_id]["longest_single"]:
                agg[s.user_id]["longest_single"] = int(s.duration_seconds)
        return agg

    def leaderboard(
        self,
        sort_key: str = "tid",
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: Optional[int] = 10,
    ) -> list[LeaderboardRow]:
        agg = self._period_user_totals(start, end)
        rows: list[LeaderboardRow] = []
        for uid, a in agg.items():
            total = int(a["total"])
            nights = int(a["nights"])
            streak = self.streak(uid)
            row = LeaderboardRow(
                user_id=uid,
                total_seconds=total,
                nights=nights,
                average_seconds=total / nights if nights else 0.0,
                current_streak=streak.current,
                longest_streak=streak.longest,
                longest_single_seconds=int(a["longest_single"]),
            )
            rows.append(row)

        # Vælg sorteringsværdi.
        def key(r: LeaderboardRow):
            if sort_key == "tid":
                return (-r.total_seconds, self.name(r.user_id).lower())
            if sort_key == "antal":
                return (-r.nights, -r.total_seconds)
            if sort_key == "gennemsnit":
                return (-r.average_seconds, -r.total_seconds)
            if sort_key == "streak":
                return (-r.current_streak, -r.total_seconds)
            if sort_key == "længste_streak":
                return (-r.longest_streak, -r.total_seconds)
            if sort_key == "længste_enkelt":
                return (-r.longest_single_seconds, -r.total_seconds)
            return (-r.total_seconds,)

        rows.sort(key=key)
        # Sæt den relevante visningsværdi.
        for r in rows:
            if sort_key == "antal":
                r.value_number = r.nights
            elif sort_key == "gennemsnit":
                r.value_seconds = int(r.average_seconds)
            elif sort_key == "streak":
                r.value_number = r.current_streak
            elif sort_key == "længste_streak":
                r.value_number = r.longest_streak
            elif sort_key == "længste_enkelt":
                r.value_seconds = r.longest_single_seconds
            else:
                r.value_seconds = r.total_seconds
        return rows if limit is None else rows[:limit]

    # -- én bestemt nat (til opsummering) ----------------------------------
    def night_span(self, bar_date: str, user_ids: Optional[set[int]] = None):
        """(first_join, last_leave) blandt sessioner den nat for de valgte brugere."""
        first = last = None
        for s in self.sessions:
            if s.bar_date != bar_date or s.left_at is None:
                continue
            if user_ids is not None and s.user_id not in user_ids:
                continue
            if first is None or s.joined_at < first:
                first = s.joined_at
            if last is None or s.left_at > last:
                last = s.left_at
        return first, last

    def _new_personal_record_users(self, bar_date: str) -> list[int]:
        """Brugere hvis nat-total sætter en NY personlig rekord den aften."""
        if bar_date not in self.counting_dates:
            return []
        idx = self.counting_dates.index(bar_date)
        earlier = self.counting_dates[:idx]
        result = []
        for uid, sec in self._qualifiers(bar_date).items():
            prev_best = 0
            for d in earlier:
                prev_best = max(prev_best, self._qualifiers(d).get(uid, 0))
            if sec > prev_best and idx > 0:  # kræver mindst én tidligere nat
                result.append(uid)
        return result

    def _is_new_participant_record(self, bar_date: str) -> bool:
        if bar_date not in self.counting_dates:
            return False
        idx = self.counting_dates.index(bar_date)
        count = len(self._qualifiers(bar_date))
        prev_max = max(
            (len(self._qualifiers(d)) for d in self.counting_dates[:idx]), default=0
        )
        return idx > 0 and count > prev_max

    def night_summary(self, bar_date: str) -> NightSummary:
        night = self.nights.get(bar_date)
        cancelled = bool(night and night.cancelled)
        summary = NightSummary(bar_date=bar_date, cancelled=cancelled)
        if cancelled:
            return summary

        quals = self._qualifiers(bar_date)
        participants = sorted(quals.items(), key=lambda kv: (-kv[1], self.name(kv[0]).lower()))
        summary.participants = participants
        summary.participant_count = len(participants)
        summary.total_seconds = sum(sec for _, sec in participants)
        if participants:
            summary.top_user = participants[0][0]
            first, last = self.night_span(bar_date, {uid for uid, _ in participants})
            summary.first_join = first
            summary.last_leave = last
            if first and last:
                summary.span_seconds = max(0, int((last - first).total_seconds()))

        summary.new_personal_records = self._new_personal_record_users(bar_date)
        summary.new_participant_record = self._is_new_participant_record(bar_date)

        # Forlængede streaks: kvalificerede med nuværende streak >= 2, hvis denne
        # nat er den seneste tællende nat (dvs. streaken slutter her).
        if self.counting_dates and bar_date == self.counting_dates[-1]:
            for uid, _ in participants:
                st = self.streak(uid)
                if st.current >= 2:
                    summary.extended_streaks.append((uid, st.current))
            summary.extended_streaks.sort(key=lambda kv: -kv[1])
        return summary

    # -- rekorder -----------------------------------------------------------
    def records(self, start: Optional[str] = None, end: Optional[str] = None) -> dict:
        """Alle rekorder. Uden periode = hele historikken. Delte rekorder giver
        flere holdere."""
        rec: dict = {}

        # Flest deltagere på én nat.
        best_count = 0
        count_holders: list[str] = []
        for bar_date in self.counting_dates:
            if not self._in_period(bar_date, start, end):
                continue
            c = len(self._qualifiers(bar_date))
            if c > best_count:
                best_count, count_holders = c, [bar_date]
            elif c == best_count and c > 0:
                count_holders.append(bar_date)
        rec["most_participants"] = {
            "count": best_count,
            "dates": count_holders,
            "details": [self.night_summary(d) for d in count_holders],
        }

        # Længste samlede deltagertid på én aften (per bruger).
        best_night_total = 0
        night_total_holders: list[tuple[int, str]] = []
        for bar_date in self.counting_dates:
            if not self._in_period(bar_date, start, end):
                continue
            for uid, sec in self._qualifiers(bar_date).items():
                if sec > best_night_total:
                    best_night_total, night_total_holders = sec, [(uid, bar_date)]
                elif sec == best_night_total and sec > 0:
                    night_total_holders.append((uid, bar_date))
        rec["longest_night_total"] = {
            "seconds": best_night_total,
            "holders": night_total_holders,
        }

        # Længste individuelle (enkelt-)session.
        best_single = 0
        single_holders: list[Session] = []
        for s in self.sessions:
            if s.duration_seconds is None or s.bar_date in self.cancelled:
                continue
            if not self._in_period(s.bar_date, start, end):
                continue
            if s.duration_seconds > best_single:
                best_single, single_holders = int(s.duration_seconds), [s]
            elif s.duration_seconds == best_single and best_single > 0:
                single_holders.append(s)
        rec["longest_single"] = {"seconds": best_single, "sessions": single_holders}

        # Længste aktive streak / længste streak nogensinde (fuld historik).
        active = self.active_streaks()
        rec["longest_active_streak"] = active[0] if active else None
        best_ever = max(self._streaks.values(), key=lambda s: s.longest, default=None)
        rec["longest_streak_ever"] = best_ever if best_ever and best_ever.longest else None

        # Flest samlede torsdagsbarer / flest samlede timer (i perioden).
        agg = self._period_user_totals(start, end)
        if agg:
            most_nights_uid = max(agg, key=lambda u: (agg[u]["nights"], agg[u]["total"]))
            most_hours_uid = max(agg, key=lambda u: (agg[u]["total"], agg[u]["nights"]))
            rec["most_nights"] = {
                "user_id": most_nights_uid,
                "nights": int(agg[most_nights_uid]["nights"]),
                "seconds": int(agg[most_nights_uid]["total"]),
            }
            rec["most_hours"] = {
                "user_id": most_hours_uid,
                "seconds": int(agg[most_hours_uid]["total"]),
                "nights": int(agg[most_hours_uid]["nights"]),
            }
        else:
            rec["most_nights"] = None
            rec["most_hours"] = None
        return rec
