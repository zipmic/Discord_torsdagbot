"""Aftenens titler til fredagsopsummeringen — og tællere til profilkortet.

Alt beregnes ud fra de gemte sessioner og stemmer, så titlerne kan genberegnes
for enhver tidligere torsdagsbar. Ingen discord-import her, så det kan testes
uden en forbindelse.

Grundmængden er altid **de kvalificerede deltagere** (dem der optjente mindst
``min_minutes``), så et enkelt kort drop-in ikke kan stjæle en titel. Tider er
optjent tid (med-selskab-reglen); ankomst og afgang er rå tidsstempler.

En kategori uden gyldige data giver en tom liste — og udelades dermed helt af
opsummeringen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Sequence

from zoneinfo import ZoneInfo

from .period import Schedule
from .stats import Engine
from .votes import VoteOption, find_option, promise_window


@dataclass(frozen=True)
class AwardRules:
    """Grænserne for de kategorier, der har en."""

    marathon_seconds: int = 5 * 3600      # 🏃 mere end 5 timer
    speedrun_min_seconds: int = 10 * 60   # ⚡ mindst 10 minutter for at tælle
    big_words_seconds: int = 2 * 3600     # 🤥 mindst 2 timer for sent
    alone_min_seconds: int = 15 * 60      # ⏳ mindst 15 minutter alene for at tælle


@dataclass
class NightAwards:
    """Aftenens titler. Tomme lister betyder "ingen i denne kategori"."""

    bar_date: str

    kings: list[int] = field(default_factory=list)            # 👑 delt ved lige tid
    king_seconds: int = 0
    marathon: list[tuple[int, int]] = field(default_factory=list)  # 🏃 (uid, sek)
    early_birds: list[int] = field(default_factory=list)       # 🐦
    early_bird_at: Optional[datetime] = None
    # True når ankomsten er selve vinduets start, dvs. de sad der allerede.
    early_bird_from_open: bool = False
    closers: list[int] = field(default_factory=list)           # 🦉
    closer_at: Optional[datetime] = None
    # True når afgangen er selve vinduets slut, dvs. de sad der til det sidste.
    closer_at_close: bool = False
    kept_promise: list[int] = field(default_factory=list)      # 🎯
    surprises: list[int] = field(default_factory=list)         # 🎭
    speedrun: list[int] = field(default_factory=list)          # ⚡
    speedrun_seconds: int = 0
    waiting: list[int] = field(default_factory=list)            # ⏳ længst alene
    waiting_seconds: int = 0
    big_words: list[tuple[int, int]] = field(default_factory=list)   # 🤥 (uid, forsinkelse)
    slow_starters: list[tuple[int, int]] = field(default_factory=list)  # 🐌 (uid, forsinkelse)

    @property
    def has_any(self) -> bool:
        return bool(
            self.kings or self.marathon or self.early_birds or self.closers
            or self.kept_promise or self.surprises or self.speedrun
            or self.waiting or self.big_words or self.slow_starters
        )


@dataclass
class AwardTally:
    """Hvor mange gange en bruger har fået hver titel (til profilkortet)."""

    king: int = 0
    marathon: int = 0
    early_bird: int = 0
    closer: int = 0
    speedrun: int = 0
    surprise: int = 0
    big_words: int = 0
    slow_starter: int = 0
    # ⏳ Waiting for players...: antal gange vundet + samlet ventetid i perioden.
    waiting: int = 0
    alone_seconds: int = 0
    # 🎯 Holdt hvad du lovede: holdt / antal aftener med et løfte.
    kept: int = 0
    promised: int = 0

    @property
    def kept_pct(self) -> Optional[float]:
        if not self.promised:
            return None
        return self.kept / self.promised * 100.0


def _min_holders(values: dict[int, int]) -> tuple[list[int], int]:
    """Alle brugere med den laveste værdi (delt ved lige)."""
    if not values:
        return [], 0
    best = min(values.values())
    return sorted(uid for uid, v in values.items() if v == best), best


def _max_holders(values: dict[int, int]) -> tuple[list[int], int]:
    if not values:
        return [], 0
    best = max(values.values())
    return sorted(uid for uid, v in values.items() if v == best), best


def _earliest(moments: dict[int, datetime]) -> tuple[list[int], Optional[datetime]]:
    if not moments:
        return [], None
    best = min(moments.values())
    return sorted(uid for uid, m in moments.items() if m == best), best


def _latest(moments: dict[int, datetime]) -> tuple[list[int], Optional[datetime]]:
    if not moments:
        return [], None
    best = max(moments.values())
    return sorted(uid for uid, m in moments.items() if m == best), best


def compute_night_awards(
    engine: Engine,
    bar_date: str,
    votes: dict[int, str],
    options: Sequence[VoteOption],
    schedule: Schedule,
    rules: AwardRules = AwardRules(),
) -> NightAwards:
    """Beregn alle aftenens titler for én torsdagsbar."""
    awards = NightAwards(bar_date=bar_date)

    if bar_date in engine.cancelled:
        return awards  # aflyst aften: ingen titler

    qualified = engine.qualifiers(bar_date)
    if not qualified:
        return awards

    try:
        day = date.fromisoformat(bar_date)
    except ValueError:
        return awards
    window_start, window_end = schedule.window_of(day)

    arrivals_all = engine.night_arrivals(bar_date)
    departures_all = engine.night_departures(bar_date)
    arrivals = {uid: t for uid, t in arrivals_all.items() if uid in qualified}
    departures = {uid: t for uid, t in departures_all.items() if uid in qualified}

    # 👑 Aftenens konge – længst optjent tid, delt ved præcis lige tid.
    #
    # Med selskabskravet er optjent tid alene ikke nok til at kåre én konge:
    # alle, der dækker hele det "sociale" tidsrum, får præcis samme optjente
    # tid, selv om den ene sad flere timer længere i baren. Derfor brydes
    # uafgjort på den rå tid i baren, så kronen kun deles, når begge dele er
    # lige. Optjent tid er stadig det primære mål, så man kan ikke vinde
    # kronen på tid, man sad alene.
    awards.kings, awards.king_seconds = _max_holders(qualified)
    if awards.king_seconds <= 0:
        awards.kings = []          # ingen optjent tid = ingen konge
    elif len(awards.kings) > 1:
        presence = engine.night_presence(bar_date)
        longest_present = max(presence.get(uid, 0) for uid in awards.kings)
        awards.kings = [
            uid for uid in awards.kings if presence.get(uid, 0) == longest_present
        ]

    # 🏃 Marathonmand – alle over grænsen.
    awards.marathon = sorted(
        ((uid, sec) for uid, sec in qualified.items() if sec > rules.marathon_seconds),
        key=lambda kv: -kv[1],
    )

    # 🐦 Early Bird / 🦉 Lukkede baren
    #
    # Registreringen starter kl. 19:00 for alle, der allerede sad i kanalen, så
    # de får præcis samme ankomsttidspunkt – og tilsvarende samme afgang, hvis
    # de stadig sad der kl. 03:00. Deler SAMTLIGE deltagere titlen, siger den
    # ingenting, og så udelades den. Deler nogle af dem den, beholdes den, men
    # teksten fortæller hvorfor tidspunktet er ens.
    awards.early_birds, awards.early_bird_at = _earliest(arrivals)
    awards.early_bird_from_open = awards.early_bird_at == window_start
    if len(arrivals) > 1 and len(awards.early_birds) == len(arrivals):
        awards.early_birds, awards.early_bird_at = [], None
        awards.early_bird_from_open = False

    awards.closers, awards.closer_at = _latest(departures)
    awards.closer_at_close = awards.closer_at == window_end
    if len(departures) > 1 and len(awards.closers) == len(departures):
        awards.closers, awards.closer_at = [], None
        awards.closer_at_close = False

    # ⚡ Speedrun – korteste gyldige besøg (mindst 10 min).
    speedrun_candidates = {
        uid: sec for uid, sec in qualified.items() if sec >= rules.speedrun_min_seconds
    }
    awards.speedrun, awards.speedrun_seconds = _min_holders(speedrun_candidates)

    # ⏳ Waiting for players... – den, der sad længst i baren uden selskab.
    #
    # Her er grundmængden ALLE, der var i baren den aften – ikke kun de
    # kvalificerede. Den, der sad alene, optjener jo netop ingen tid og ville
    # ellers aldrig kunne få titlen, selv om det er præcis dem, den handler om.
    # Til gengæld kræves et minimum, så et kort ophold ikke vinder den.
    alone = {
        uid: sec
        for uid, sec in engine.night_alone(bar_date).items()
        if sec >= rules.alone_min_seconds
    }
    awards.waiting, awards.waiting_seconds = _max_holders(alone)

    # Resten kræver, at vi kender brugerens stemme.
    for uid, sec in qualified.items():
        option_key = votes.get(uid)
        if option_key is None:
            continue
        option = find_option(options, option_key)
        if option is None:
            continue
        arrival = arrivals.get(uid)

        # 🎭 Surprise! – stemte "kommer ikke", men dukkede op.
        if option.absent:
            awards.surprises.append(uid)
            continue

        if arrival is None or option.promise_start is None:
            continue

        start, end = promise_window(option, day, schedule.tz, window_start)

        # 🎯 Holdt hvad du lovede – inden for det lovede tidsrum. Et åbent løfte
        # ("efter 21:00") holdes ved at møde op efter starttidspunktet.
        if end is None:
            if arrival >= start:
                awards.kept_promise.append(uid)
            continue  # åbne løfter kan ikke komme for sent

        if start <= arrival <= end:
            awards.kept_promise.append(uid)
            continue

        # Kun forsinkelser efter løftets slut er interessante.
        delay = int((arrival - end).total_seconds())
        if delay <= 0:
            continue
        if delay >= rules.big_words_seconds:
            awards.big_words.append((uid, delay))  # 🤥 Store ord
        awards.slow_starters.append((uid, delay))

    awards.surprises.sort()
    awards.kept_promise.sort()
    awards.big_words.sort(key=lambda kv: -kv[1])

    # 🐌 Slow starter – kun den største forsinkelse (delt ved lige).
    if awards.slow_starters:
        worst = max(delay for _, delay in awards.slow_starters)
        awards.slow_starters = sorted(
            ((uid, d) for uid, d in awards.slow_starters if d == worst),
            key=lambda kv: kv[0],
        )

    return awards


def tally_for_user(
    engine: Engine,
    user_id: int,
    votes_by_night: dict[str, dict[int, str]],
    options: Sequence[VoteOption],
    schedule: Schedule,
    rules: AwardRules = AwardRules(),
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> AwardTally:
    """Tæl hvor mange gange en bruger har fået hver titel i en periode."""
    tally = AwardTally()
    for bar_date in engine.dates_in_period(start, end):
        votes = votes_by_night.get(bar_date, {})
        awards = compute_night_awards(engine, bar_date, votes, options, schedule, rules)

        if user_id in awards.kings:
            tally.king += 1
        if any(uid == user_id for uid, _ in awards.marathon):
            tally.marathon += 1
        if user_id in awards.early_birds:
            tally.early_bird += 1
        if user_id in awards.closers:
            tally.closer += 1
        if user_id in awards.speedrun:
            tally.speedrun += 1
        if user_id in awards.surprises:
            tally.surprise += 1
        if any(uid == user_id for uid, _ in awards.big_words):
            tally.big_words += 1
        if any(uid == user_id for uid, _ in awards.slow_starters):
            tally.slow_starter += 1
        if user_id in awards.waiting:
            tally.waiting += 1

        # 🎯-statistikken: alle aftener hvor brugeren afgav et løfte.
        option_key = votes.get(user_id)
        option = find_option(options, option_key) if option_key else None
        if option is not None and not option.absent and option.promise_start is not None:
            tally.promised += 1
            if user_id in awards.kept_promise:
                tally.kept += 1

    # Ventetiden tælles over ALLE aftener i perioden – også dem hvor brugeren
    # sad helt alene, og natten derfor ikke blev en tællende torsdagsbar.
    tally.alone_seconds = engine.alone_seconds(user_id, start, end)
    return tally


# ---------------------------------------------------------------------------
# 🎖️ Automatiske badges
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Badge:
    emoji: str
    name: str
    description: str


def earned_badges(
    *,
    nights: int,
    longest_streak: int,
    tally: AwardTally,
) -> list[Badge]:
    """Badges udledt af data. Listen er bevidst nem at udvide."""
    badges: list[Badge] = []

    for grænse, navn in ((100, "Legende"), (50, "Veteran"), (25, "Fast inventar"), (10, "Stamgæst")):
        if nights >= grænse:
            badges.append(Badge("🍻", navn, f"{grænse}+ torsdagsbarer"))
            break

    if longest_streak >= 5:
        badges.append(Badge("🔥", "Streak-mester", f"Længste streak: {longest_streak}"))
    if tally.king >= 3:
        badges.append(Badge("👑", "Kongelig", f"Aftenens konge {tally.king} gange"))
    if tally.marathon >= 3:
        badges.append(Badge("🏃", "Marathonløber", f"{tally.marathon} marathon-aftener"))
    if tally.speedrun >= 3:
        badges.append(Badge("⚡", "Speedrunner", f"{tally.speedrun} speedruns"))
    if tally.closer >= 3:
        badges.append(Badge("🦉", "Natteravn", f"Lukkede baren {tally.closer} gange"))
    if tally.early_bird >= 3:
        badges.append(Badge("🐦", "Morgenfugl", f"Først online {tally.early_bird} gange"))
    if tally.promised >= 5 and (tally.kept_pct or 0) >= 80:
        badges.append(Badge("🎯", "Pålidelig", f"Holder løftet {tally.kept_pct:.0f}% af gangene"))
    if tally.surprise >= 3:
        badges.append(Badge("🎭", "Uforudsigelig", f"{tally.surprise} overraskelser"))
    if tally.waiting >= 3:
        badges.append(Badge("⏳", "Tålmodig", f"Ventede længst på selskab {tally.waiting} gange"))

    return badges


def typical_arrival_minutes(
    engine: Engine,
    user_id: int,
    schedule: Schedule,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Optional[int]:
    """Brugerens typiske ankomsttid som minutter efter registreringens start.

    Median frem for gennemsnit, så en enkelt meget sen aften ikke trækker tallet
    skævt. Måles fra vinduets start (fx 19:00), så ankomster efter midnat
    håndteres korrekt.
    """
    offsets: list[int] = []
    for bar_date in engine.dates_in_period(start, end):
        if user_id not in engine.qualifiers(bar_date):
            continue
        arrival = engine.night_arrivals(bar_date).get(user_id)
        if arrival is None:
            continue
        try:
            day = date.fromisoformat(bar_date)
        except ValueError:
            continue
        window_start, window_end = schedule.window_of(day)
        offsets.append(
            int((arrival.astimezone(schedule.tz) - window_start).total_seconds() // 60)
        )
    if not offsets:
        return None
    offsets.sort()
    mid = len(offsets) // 2
    if len(offsets) % 2:
        return offsets[mid]
    return (offsets[mid - 1] + offsets[mid]) // 2
