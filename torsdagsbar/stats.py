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
from datetime import datetime, timedelta
from typing import Optional

from .database import Correction, Night, Session


# ---------------------------------------------------------------------------
# Selskabs-beregning ("man optjener kun tid, når andre også er til stede")
# ---------------------------------------------------------------------------
def _merge_intervals(
    intervals: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """Slå en enkelt brugers (evt. overlappende) intervaller sammen til
    disjunkte intervaller, så brugeren aldrig tælles som "to personer"."""
    ivs = sorted((s, e) for s, e in intervals if e > s)
    merged: list[tuple[datetime, datetime]] = []
    for s, e in ivs:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def companioned_night(
    user_intervals: dict[int, list[tuple[datetime, datetime]]]
) -> dict[int, tuple[int, int, Optional[datetime], Optional[datetime]]]:
    """Beregn "tid med selskab" for hver bruger en enkelt aften.

    En brugers tid tælles kun i de øjeblikke, hvor MINDST ÉN anden rigtig bruger
    også er til stede i baren samtidig. Det udregnes ved at finde de tidsrum,
    hvor mindst to distinkte brugere er til stede (≥2), og skære hver brugers
    tilstedeværelse ned til de tidsrum.

    Input:  {user_id: [(start, slut), ...]}  (tz-aware datetimes)
    Output: {user_id: (total_sek, længste_sammenhængende_sek, start, slut)}
    """
    # 1) Slå hver brugers intervaller sammen (så én bruger = højst +1 ad gangen).
    merged = {uid: _merge_intervals(ivs) for uid, ivs in user_intervals.items()}

    # 2) Sweep: find tidsrum hvor ≥2 distinkte brugere er til stede.
    events: list[tuple[datetime, int]] = []
    for ivs in merged.values():
        for s, e in ivs:
            events.append((s, 1))
            events.append((e, -1))
    events.sort(key=lambda x: x[0])

    social: list[tuple[datetime, datetime]] = []
    count = 0
    social_start: Optional[datetime] = None
    for t, delta in events:
        prev = count
        count += delta
        if prev < 2 <= count:
            social_start = t
        elif prev >= 2 > count and social_start is not None:
            social.append((social_start, t))
            social_start = None

    # 3) Skær hver brugers tilstedeværelse ned til de "sociale" tidsrum.
    result: dict[int, tuple[int, int, Optional[datetime], Optional[datetime]]] = {}
    for uid, ivs in merged.items():
        total = timedelta()
        best = timedelta()
        best_span: tuple[Optional[datetime], Optional[datetime]] = (None, None)
        for s, e in ivs:
            for ss, se in social:
                lo = max(s, ss)
                hi = min(e, se)
                if hi > lo:
                    dur = hi - lo
                    total += dur
                    if dur > best:
                        best = dur
                        best_span = (lo, hi)
        result[uid] = (
            int(total.total_seconds()),
            int(best.total_seconds()),
            best_span[0],
            best_span[1],
        )
    return result


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
class StretchRecord:
    """Længste sammenhængende "med selskab"-stræk for en bruger en aften.

    Har de samme felter, som formatteringen forventer af en session, så den kan
    genbruges direkte i rekord-embed'en."""
    user_id: int
    bar_date: str
    duration_seconds: int
    joined_at: Optional[datetime]
    left_at: Optional[datetime]


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
        require_company: bool = True,
    ) -> None:
        self.sessions = [
            s for s in sessions if s.duration_seconds is not None and s.left_at is not None
        ]
        self.nights = nights
        self.min_seconds = max(0, int(min_seconds))
        # Når True tælles kun tid, hvor mindst én ANDEN bruger var til stede.
        self.require_company = require_company

        self.cancelled: set[str] = {d for d, n in nights.items() if n.cancelled}

        # Seneste kendte visningsnavn pr. bruger (nyeste session vinder).
        self.names: dict[int, str] = {}
        for s in sorted(self.sessions, key=lambda x: x.joined_at):
            if s.display_name:
                self.names[s.user_id] = s.display_name

        # Saml sessionernes intervaller pr. nat og bruger.
        intervals_by_night: dict[str, dict[int, list[tuple[datetime, datetime]]]] = {}
        for s in self.sessions:
            night = intervals_by_night.setdefault(s.bar_date, {})
            night.setdefault(s.user_id, []).append((s.joined_at, s.left_at))

        # Nat-totaler {bar_date: {user_id: sekunder}} og længste sammenhængende
        # "med selskab"-stræk {bar_date: {user_id: (sek, start, slut)}}.
        # Derudover den RÅ tid i baren {bar_date: {user_id: sekunder}}, som er
        # uafhængig af selskabskravet og bruges til at bryde uafgjorte titler.
        self.night_user: dict[str, dict[int, int]] = {}
        self.night_user_longest: dict[str, dict[int, tuple[int, datetime, datetime]]] = {}
        self.night_user_present: dict[str, dict[int, int]] = {}
        self.night_user_alone: dict[str, dict[int, int]] = {}
        for bar_date, users in intervals_by_night.items():
            merged_by_user = {uid: _merge_intervals(ivs) for uid, ivs in users.items()}
            presence = {
                uid: int(sum((e - s).total_seconds() for s, e in merged))
                for uid, merged in merged_by_user.items()
            }
            # Selskabstiden beregnes ALTID – også når selskabskravet er slået
            # fra – for ventetiden er tid i baren minus tid med selskab.
            comp = companioned_night(users)
            with_company = {uid: v[0] for uid, v in comp.items()}
            alone = {
                uid: max(0, sec - with_company.get(uid, 0))
                for uid, sec in presence.items()
            }
            if self.require_company:
                totals = dict(with_company)
                longest = {
                    uid: (v[1], v[2], v[3])
                    for uid, v in comp.items()
                    if v[1] > 0 and v[2] is not None and v[3] is not None
                }
            else:
                # Uden selskabskrav: rå summer + hele intervaller som "stræk".
                totals = dict(presence)
                longest = {}
                for uid, merged in merged_by_user.items():
                    if merged:
                        s, e = max(merged, key=lambda iv: iv[1] - iv[0])
                        longest[uid] = (int((e - s).total_seconds()), s, e)
            self.night_user[bar_date] = totals
            self.night_user_longest[bar_date] = longest
            self.night_user_present[bar_date] = presence
            self.night_user_alone[bar_date] = alone

        # Læg manuelle rettelser oveni nat-totalerne.
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

    def qualifiers(self, bar_date: str) -> dict[int, int]:
        """Offentligt navn for de kvalificerede deltagere en given aften."""
        return self._qualifiers(bar_date)

    def night_presence(self, bar_date: str) -> dict[int, int]:
        """Rå tid i baren pr. bruger den aften – UDEN selskabskravet.

        Bruges kun som tiebreaker for titler: den, der faktisk sad længst i
        baren, skal ikke dele en titel med en, der gik tidligere. Manuelle
        rettelser indgår ikke, da de hører til den optjente tid.
        """
        return dict(self.night_user_present.get(bar_date, {}))

    def night_total(self, bar_date: str, user_id: int) -> int:
        """Brugerens optjente nat-total inkl. eventuelle rettelser.

        Det er præcis det tal, statistikken viser – i modsætning til summen af
        rå sessionsvarigheder, som hverken tager højde for selskabskravet eller
        for overlappende sessioner.
        """
        return self.night_user.get(bar_date, {}).get(user_id, 0)

    def night_alone(self, bar_date: str) -> dict[int, int]:
        """Tid i baren UDEN selskab pr. bruger den aften ("ventetid").

        Tid i baren minus tid med selskab. Alle, der var i baren den aften, er
        med – også dem der ikke kvalificerede sig, for den der sad helt alene
        optjener netop ingen tid. Manuelle rettelser indgår ikke.
        """
        return dict(self.night_user_alone.get(bar_date, {}))

    def alone_seconds(
        self, user_id: int, start: Optional[str] = None, end: Optional[str] = None
    ) -> int:
        """Samlet ventetid for en bruger i en periode.

        Tæller alle ikke-aflyste aftener – også dem hvor brugeren sad helt
        alene, og natten derfor slet ikke blev en tællende torsdagsbar. Det er
        jo netop de aftener, ventetiden handler om.
        """
        total = 0
        for bar_date, per_user in self.night_user_alone.items():
            if bar_date in self.cancelled or not self._in_period(bar_date, start, end):
                continue
            total += per_user.get(user_id, 0)
        return total

    def night_arrivals(self, bar_date: str) -> dict[int, datetime]:
        """Tidligste ankomst pr. bruger den aften (rå tidsstempel, ikke gated)."""
        result: dict[int, datetime] = {}
        for s in self.sessions:
            if s.bar_date != bar_date:
                continue
            current = result.get(s.user_id)
            if current is None or s.joined_at < current:
                result[s.user_id] = s.joined_at
        return result

    def night_departures(self, bar_date: str) -> dict[int, datetime]:
        """Seneste afgang pr. bruger den aften (rå tidsstempel)."""
        result: dict[int, datetime] = {}
        for s in self.sessions:
            if s.bar_date != bar_date or s.left_at is None:
                continue
            current = result.get(s.user_id)
            if current is None or s.left_at > current:
                result[s.user_id] = s.left_at
        return result

    def dates_in_period(
        self, start: Optional[str] = None, end: Optional[str] = None
    ) -> list[str]:
        """De tællende torsdagsbarer inden for en periode."""
        return [d for d in self.counting_dates if self._in_period(d, start, end)]

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

        # Længste sammenhængende "med selskab"-stræk i perioden.
        for bar_date, per_user in self.night_user_longest.items():
            if bar_date in self.cancelled or not self._in_period(bar_date, start, end):
                continue
            entry = per_user.get(user_id)
            if entry and entry[0] > stats.longest_single_seconds:
                stats.longest_single_seconds = int(entry[0])
                stats.longest_single_date = bar_date
                stats.longest_single_start = entry[1]
                stats.longest_single_end = entry[2]

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

        # Længste sammenhængende "med selskab"-stræk (individuel deltagelse).
        best_single = 0
        single_holders: list[StretchRecord] = []
        for bar_date, per_user in self.night_user_longest.items():
            if bar_date in self.cancelled or not self._in_period(bar_date, start, end):
                continue
            for uid, (sec, s_start, s_end) in per_user.items():
                if sec > best_single:
                    best_single = int(sec)
                    single_holders = [StretchRecord(uid, bar_date, int(sec), s_start, s_end)]
                elif sec == best_single and sec > 0:
                    single_holders.append(StretchRecord(uid, bar_date, int(sec), s_start, s_end))
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
