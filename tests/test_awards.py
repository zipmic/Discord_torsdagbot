"""Tests for torsdagsbar v3: aftentitler, forsinkelser, år, citater og profil.

Kører uden en Discord-forbindelse. Køres direkte:
    python tests/test_awards.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import date, datetime, time as t, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zoneinfo import ZoneInfo

from torsdagsbar.awards import (
    AwardRules,
    compute_night_awards,
    earned_badges,
    tally_for_user,
    typical_arrival_minutes,
)
from torsdagsbar.config import TorsdagsbarConfig
from torsdagsbar.database import Database, Night, Session
from torsdagsbar.period import Schedule
from torsdagsbar.stats import Engine
from torsdagsbar.votes import VoteOption, promise_window

TZ = ZoneInfo("Europe/Copenhagen")
SCHEDULE = Schedule(TZ)
BD = "2026-05-14"          # en torsdag
BAR_DATE = date(2026, 5, 14)

OPTIONS = [
    VoteOption("early", "🕖 Early Bird kl. 19:00–20:00", t(19, 0), t(20, 0)),
    VoteOption("t2000", "🕗 Mellem kl. 20:00–20:30", t(20, 0), t(20, 30)),
    VoteOption("t2030", "🕣 Mellem kl. 20:30–21:00", t(20, 30), t(21, 0)),
    VoteOption("e2100", "🕘 Efter 21:00 lol", t(21, 0), None),
    VoteOption("e2200", "🕙 Efter 22:00 lol", t(22, 0), None),
    VoteOption("nope", "❌ Jeg kommer ikke", None, None, absent=True),
]


def check(name, cond):
    print(f"  [{'OK ' if cond else 'FEJL'}] {name}")
    assert cond, name


# ---------------------------------------------------------------------------
# Hjælp til at bygge en aften
# ---------------------------------------------------------------------------
class NightBuilder:
    def __init__(self, bar_date: str = BD):
        self.bar_date = bar_date
        self.sessions: list[Session] = []
        self._id = 0

    def add(self, uid, name, jh, jm, lh, lm, next_day=False, day=None):
        """Tilføj en session i lokal tid."""
        self._id += 1
        d = day or date.fromisoformat(self.bar_date)
        j = datetime(d.year, d.month, d.day, jh, jm, tzinfo=TZ)
        end_day = d + timedelta(days=1) if next_day else d
        l = datetime(end_day.year, end_day.month, end_day.day, lh, lm, tzinfo=TZ)
        self.sessions.append(
            Session(self._id, uid, name, self.bar_date, 555, j, l,
                    int((l - j).total_seconds()), "auto")
        )
        return self

    def engine(self, min_minutes=5, cancelled=False, extra_sessions=None):
        nights = {self.bar_date: Night(self.bar_date, cancelled, False, None, None)}
        sessions = self.sessions + list(extra_sessions or [])
        for s in sessions:
            nights.setdefault(s.bar_date, Night(s.bar_date, False, False, None, None))
        return Engine(sessions, nights, [], min_minutes * 60, require_company=False)


def awards_for(builder, votes, rules=AwardRules(), **kw):
    eng = builder.engine(**kw)
    return eng, compute_night_awards(eng, builder.bar_date, votes, OPTIONS, SCHEDULE, rules)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_king_and_marathon():
    print("\n== 👑 Aftenens konge (inkl. delt) og 🏃 Marathonmand ==")
    b = NightBuilder().add(1, "A", 19, 0, 22, 0).add(2, "B", 19, 0, 21, 0)
    _, a = awards_for(b, {})
    check("konge = A alene", a.kings == [1])
    check("kongens tid = 3 timer", a.king_seconds == 3 * 3600)
    check("ingen marathon under 5 timer", a.marathon == [])

    # Præcis lige tid -> delt titel
    b2 = NightBuilder().add(1, "A", 19, 0, 22, 0).add(2, "B", 19, 0, 22, 0)
    _, a2 = awards_for(b2, {})
    check("delt konge ved præcis lige tid", a2.kings == [1, 2])

    # Marathon: over 5 timer
    b3 = NightBuilder().add(1, "A", 19, 0, 1, 0, next_day=True).add(2, "B", 19, 0, 20, 0)
    _, a3 = awards_for(b3, {})
    check("A (6 timer) er marathonmand", [u for u, _ in a3.marathon] == [1])
    # Præcis 5 timer tæller ikke ("mere end 5 timer")
    b4 = NightBuilder().add(1, "A", 19, 0, 0, 0, next_day=True).add(2, "B", 19, 0, 20, 0)
    _, a4 = awards_for(b4, {})
    check("præcis 5 timer er IKKE marathon", a4.marathon == [])


def test_early_bird_and_closer():
    print("\n== 🐦 Early Bird og 🦉 Lukkede baren ==")
    b = (NightBuilder()
         .add(1, "A", 19, 30, 22, 0)
         .add(2, "B", 19, 5, 21, 0)
         .add(3, "C", 20, 0, 2, 35, next_day=True))
    _, a = awards_for(b, {})
    check("early bird = B (19:05)", a.early_birds == [2])
    check("early bird-tidspunkt", a.early_bird_at.astimezone(TZ).strftime("%H:%M") == "19:05")
    check("lukkede baren = C (02:35)", a.closers == [3])
    check("lukketidspunkt", a.closer_at.astimezone(TZ).strftime("%H:%M") == "02:35")


def test_kept_promise():
    print("\n== 🎯 Holdt hvad du lovede ==")
    b = (NightBuilder()
         .add(1, "A", 20, 17, 23, 0)   # stemte 20:00-20:30 -> holdt
         .add(2, "B", 21, 30, 23, 0)   # stemte efter 21:00 -> holdt (åbent løfte)
         .add(3, "C", 20, 45, 23, 0)   # stemte 20:00-20:30 -> for sent
         .add(4, "D", 21, 0, 23, 0))   # stemte efter 22:00, men kom 21:00 -> ikke holdt
    votes = {1: "t2000", 2: "e2100", 3: "t2000", 4: "e2200"}
    _, a = awards_for(b, votes)
    check("A holdt (20:17 i 20:00-20:30)", 1 in a.kept_promise)
    check("B holdt (åbent løfte, kom efter 21)", 2 in a.kept_promise)
    check("C holdt IKKE (kom 20:45)", 3 not in a.kept_promise)
    check("D holdt IKKE (kom før sit løfte)", 4 not in a.kept_promise)


def test_surprise():
    print("\n== 🎭 Surprise! ==")
    b = NightBuilder().add(1, "A", 20, 0, 22, 0).add(2, "B", 20, 0, 22, 0)
    _, a = awards_for(b, {1: "nope", 2: "t2000"})
    check("A stemte 'kommer ikke' men kom", a.surprises == [1])
    check("B er ikke en surprise", 2 not in a.surprises)
    check("'kommer ikke' giver ikke forsinkelse", a.slow_starters == [])


def test_speedrun():
    print("\n== ⚡ Speedrun (eksemplet fra specifikationen) ==")
    # A: 7 min (tæller ikke), B: 14 min (vinder), C: 32 min
    b = (NightBuilder()
         .add(1, "A", 20, 0, 20, 7)
         .add(2, "B", 20, 0, 20, 14)
         .add(3, "C", 20, 0, 20, 32))
    _, a = awards_for(b, {})
    check("B (14 min) vinder speedrun", a.speedrun == [2])
    check("speedrun-tid = 14 min", a.speedrun_seconds == 14 * 60)
    check("A (7 min) tæller ikke", 1 not in a.speedrun)

    # Ingen over 10 min -> kategorien er tom
    b2 = NightBuilder().add(1, "A", 20, 0, 20, 6).add(2, "B", 20, 0, 20, 8)
    _, a2 = awards_for(b2, {})
    check("ingen gyldige besøg -> tom kategori", a2.speedrun == [])


def test_big_words_and_slow_starter():
    print("\n== 🤥 Store ord og 🐌 Slow starter ==")
    # Stemte 19:00-20:00, kom 22:47 -> 2t47m for sent
    b = (NightBuilder()
         .add(1, "A", 22, 47, 23, 30)
         .add(2, "B", 21, 30, 23, 30)   # stemte 20:00-20:30 -> 1t00m for sent
         .add(3, "C", 23, 0, 23, 30)    # stemte 'efter 21' -> ingen forsinkelse
         .add(4, "D", 23, 30, 23, 59))  # stemte nope -> ingen forsinkelse
    votes = {1: "early", 2: "t2000", 3: "e2100", 4: "nope"}
    _, a = awards_for(b, votes)
    ids = [u for u, _ in a.big_words]
    check("A (2t47m) får Store ord", ids == [1])
    check("forsinkelsen regnes fra løftets slut", a.big_words[0][1] == 2 * 3600 + 47 * 60)
    check("B (1 time) får IKKE Store ord", 2 not in ids)
    check("slow starter = A (største forsinkelse)", [u for u, _ in a.slow_starters] == [1])
    check("åbne løfter tæller ikke som forsinket", 3 not in [u for u, _ in a.slow_starters])
    check("'kommer ikke' tæller ikke som forsinket", 4 not in [u for u, _ in a.slow_starters])

    # Netop under 2 timer -> ingen Store ord, men stadig slow starter
    b2 = NightBuilder().add(1, "A", 21, 59, 23, 0).add(2, "B", 20, 0, 23, 0)
    _, a2 = awards_for(b2, {1: "early", 2: "t2000"})
    check("1t59m giver ikke Store ord", a2.big_words == [])
    check("men er stadig slow starter", [u for u, _ in a2.slow_starters] == [1])


def test_empty_and_cancelled():
    print("\n== Tomme kategorier og aflyste aftener ==")
    b = NightBuilder().add(1, "A", 20, 0, 20, 30).add(2, "B", 20, 0, 20, 30)
    _, a = awards_for(b, {})
    check("ingen marathon", a.marathon == [])
    check("ingen store ord", a.big_words == [])
    check("ingen surprise", a.surprises == [])
    check("men konge findes", bool(a.kings))

    _, a2 = awards_for(b, {}, cancelled=True)
    check("aflyst aften giver ingen titler", not a2.has_any)


def test_embed_omits_empty():
    print("\n== Opsummeringens embed udelader tomme kategorier ==")
    from torsdagsbar import formatting as fmt

    b = NightBuilder().add(1, "A", 20, 0, 22, 0).add(2, "B", 20, 0, 21, 0)
    eng, a = awards_for(b, {})
    felter = dict(fmt.award_fields(a, lambda u: f"Bruger{u}", TZ))
    check("👑 med", any("konge" in k for k in felter))
    check("🏃 udeladt", not any("Marathon" in k for k in felter))
    check("🎭 udeladt", not any("Surprise" in k for k in felter))
    check("🤥 udeladt", not any("Store ord" in k for k in felter))

    ns = eng.night_summary(BD)
    embed = fmt.summary_embed(ns, lambda u: f"Bruger{u}", TZ, awards=a)
    navne = [f.name for f in embed.fields]
    check("embed har konge-felt", any("konge" in n for n in navne))
    check("embed har ingen tomme kategorier", not any("Marathon" in n for n in navne))


def test_tally_and_badges():
    print("\n== Titel-tællere og 🎖️ badges ==")
    sessions, nights, votes_by_night = [], {}, {}
    sid = 0
    # 6 torsdage hvor A altid er konge og altid holder sit løfte
    for i, day in enumerate([7, 14, 21, 28, 4, 11]):
        month = 5 if day > 3 and i < 4 else 6
        d = date(2026, month, day)
        bd = d.isoformat()
        nights[bd] = Night(bd, False, False, None, None)
        for uid, name, hours in ((1, "A", 4), (2, "B", 1)):
            sid += 1
            j = datetime(d.year, d.month, d.day, 19, 30, tzinfo=TZ)
            l = j + timedelta(hours=hours)
            sessions.append(Session(sid, uid, name, bd, 555, j, l,
                                    int((l - j).total_seconds()), "auto"))
        votes_by_night[bd] = {1: "early", 2: "early"}

    eng = Engine(sessions, nights, [], 5 * 60, require_company=False)
    tally = tally_for_user(eng, 1, votes_by_night, OPTIONS, SCHEDULE)
    check("A var konge 6 gange", tally.king == 6)
    check("A holdt løftet 6/6", (tally.kept, tally.promised) == (6, 6))
    check("procent = 100", round(tally.kept_pct) == 100)

    badges = earned_badges(nights=6, longest_streak=6, tally=tally)
    navne = {b.name for b in badges}
    check("🔥 Streak-mester optjent", "Streak-mester" in navne)
    check("👑 Kongelig optjent", "Kongelig" in navne)
    check("🎯 Pålidelig optjent", "Pålidelig" in navne)
    check("🍻 Stamgæst IKKE optjent (kun 6 aftener)", "Stamgæst" not in navne)

    minutter = typical_arrival_minutes(eng, 1, SCHEDULE)
    check("typisk ankomst = 30 min efter 19:00", minutter == 30)
    from torsdagsbar import formatting as fmt
    check("vises som kl. 19:30", fmt.fmt_arrival_offset(minutter, 19, 0) == "kl. 19:30")


def test_promise_window():
    print("\n== Løftevinduer ==")
    ws, _ = SCHEDULE.window_of(BAR_DATE)
    start, end = promise_window(OPTIONS[0], BAR_DATE, TZ, ws)
    check("early: 19:00-20:00 samme dag", start.hour == 19 and end.hour == 20)
    start2, end2 = promise_window(OPTIONS[3], BAR_DATE, TZ, ws)
    check("efter 21: start 21:00, ingen slut", start2.hour == 21 and end2 is None)
    start3, end3 = promise_window(OPTIONS[5], BAR_DATE, TZ, ws)
    check("'kommer ikke' har intet vindue", start3 is None and end3 is None)


async def test_year_periods():
    print("\n== 📅 Årsbaseret statistik ==")
    from torsdagsbar.module import TorsdagsbarModule

    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        cfg = TorsdagsbarConfig(enabled=True, server_id=1, voice_channel_ids=[2],
                                summary_channel_id=3, schedule=SCHEDULE, db_path=dbpath)
        db = Database(dbpath)

        class C:
            def get_channel(self, i): return None
            def get_guild(self, i): return None

        mod = TorsdagsbarModule(C(), cfg, db, vote_options=OPTIONS)
        mod.tracker.now = lambda: datetime(2026, 5, 14, 20, 0, tzinfo=TZ)

        check("standard er i år", mod.period_bounds("i_år")[:2] == ("2026-01-01", "2026-12-31"))
        check("sidste år", mod.period_bounds("sidste_år")[:2] == ("2025-01-01", "2025-12-31"))
        check("år overtrumfer periode", mod.period_bounds("hele_perioden", 2024)[:2]
              == ("2024-01-01", "2024-12-31"))
        check("hele perioden er ubegrænset", mod.period_bounds("hele_perioden")[:2] == (None, None))

        # Statistik nulstilles pr. år, men gamle år kan stadig slås op
        for år, timer in ((2025, 3), (2026, 1)):
            j = datetime(år, 5, 14, 19, 0, tzinfo=TZ)
            for uid in (1, 2):
                db.add_manual_session(uid, f"U{uid}", date(år, 5, 14), j,
                                      j + timedelta(hours=timer))
        eng = await mod.build_engine()
        i_år = eng.user_stats(1, "2026-01-01", "2026-12-31")
        sidste_år = eng.user_stats(1, "2025-01-01", "2025-12-31")
        alt = eng.user_stats(1)
        check("i år = 1 time", i_år.total_seconds == 3600)
        check("sidste år = 3 timer (bevaret)", sidste_år.total_seconds == 3 * 3600)
        check("hele perioden = 4 timer", alt.total_seconds == 4 * 3600)
        check("streak løber over nytår", eng.streak(1).current == 2)
        db.close()


async def test_late_notices():
    print("\n== ⏰ 'Du er sent på den' ==")
    from torsdagsbar.module import TorsdagsbarModule

    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        cfg = TorsdagsbarConfig(enabled=True, server_id=1, voice_channel_ids=[2],
                                summary_channel_id=3, schedule=SCHEDULE, db_path=dbpath)
        db = Database(dbpath)
        sendt = []

        class FakeChannel:
            async def send(self, content=None, **kw):
                sendt.append(content)

        class C:
            def get_channel(self, i): return FakeChannel()
            def get_guild(self, i): return None

        mod = TorsdagsbarModule(C(), cfg, db, vote_options=OPTIONS)

        # 1=early(deadline 20:00), 2=efter 21 (åbent), 3=kommer ikke, 4=early men ankommet
        db.replace_votes(BAR_DATE, {1: "early", 2: "e2100", 3: "nope", 4: "early"}, "native")
        j = datetime(2026, 5, 14, 19, 30, tzinfo=TZ)
        db.add_manual_session(4, "Ankommet", BAR_DATE, j, j + timedelta(hours=1))

        mod.tracker.now = lambda: datetime(2026, 5, 14, 19, 55, tzinfo=TZ)
        await mod._maybe_send_late_notices()
        check("før deadline sendes intet", sendt == [])

        mod.tracker.now = lambda: datetime(2026, 5, 14, 20, 1, tzinfo=TZ)
        await mod._maybe_send_late_notices()
        check("præcis én besked efter deadline", len(sendt) == 1)
        check("beskeden tagger den rigtige bruger", "<@1>" in sendt[0])
        check("åbent løfte får ingen besked", "<@2>" not in " ".join(sendt))
        check("'kommer ikke' får ingen besked", "<@3>" not in " ".join(sendt))
        check("allerede ankommet får ingen besked", "<@4>" not in " ".join(sendt))

        await mod._maybe_send_late_notices()
        check("sender ikke igen (én pr. bruger pr. aften)", len(sendt) == 1)

        # Uden for karensvinduet
        db2path = Path(d) / "t2.db"
        db2 = Database(db2path)
        cfg2 = TorsdagsbarConfig(enabled=True, server_id=1, voice_channel_ids=[2],
                                 summary_channel_id=3, schedule=SCHEDULE, db_path=db2path,
                                 late_grace_minutes=90)
        sendt2 = []

        class FakeChannel2:
            async def send(self, content=None, **kw): sendt2.append(content)

        class C2:
            def get_channel(self, i): return FakeChannel2()
            def get_guild(self, i): return None

        mod2 = TorsdagsbarModule(C2(), cfg2, db2, vote_options=OPTIONS)
        db2.replace_votes(BAR_DATE, {1: "early"}, "native")
        mod2.tracker.now = lambda: datetime(2026, 5, 14, 23, 0, tzinfo=TZ)  # 3 t efter
        await mod2._maybe_send_late_notices()
        check("uden for karensvinduet sendes intet", sendt2 == [])
        db.close(); db2.close()


async def test_vote_sync():
    print("\n== Stemme-synk fra Discords indbyggede poll ==")
    from torsdagsbar.votes import sync_native_votes

    with tempfile.TemporaryDirectory() as d:
        db = Database(Path(d) / "t.db")

        class FakeVoter:
            def __init__(self, uid, bot=False): self.id = uid; self.bot = bot

        class FakeAnswer:
            def __init__(self, text, voters): self.text = text; self._voters = voters
            def voters(self):
                async def gen():
                    for v in self._voters:
                        yield v
                return gen()

        class FakePoll:
            def __init__(self, answers): self.answers = answers

        class FakeMessage:
            def __init__(self, poll): self.poll = poll

        class FakeChannel:
            def __init__(self, msg): self._msg = msg
            async def fetch_message(self, mid): return self._msg

        poll = FakePoll([
            FakeAnswer(OPTIONS[0].label, [FakeVoter(1), FakeVoter(99, bot=True)]),
            FakeAnswer(OPTIONS[1].label, [FakeVoter(2)]),
            FakeAnswer(OPTIONS[2].label, []),
            FakeAnswer(OPTIONS[3].label, [FakeVoter(3)]),
            FakeAnswer(OPTIONS[4].label, []),
            FakeAnswer(OPTIONS[5].label, [FakeVoter(4)]),
        ])

        class C:
            def get_channel(self, i): return FakeChannel(FakeMessage(poll))

        n = await sync_native_votes(C(), db, BAR_DATE, OPTIONS,
                                    {"channel_id": 1, "message_id": 2, "mode": "native"})
        votes = db.votes_for_night(BD)
        check("4 stemmer synket (botten sprunget over)", n == 4)
        check("stemmerne mappet korrekt",
              votes == {1: "early", 2: "t2000", 3: "e2100", 4: "nope"})
        check("botten er ikke med", 99 not in votes)

        # Skift af stemme overskriver
        poll.answers[0]._voters = []
        poll.answers[2]._voters = [FakeVoter(1)]
        await sync_native_votes(C(), db, BAR_DATE, OPTIONS,
                                {"channel_id": 1, "message_id": 2, "mode": "native"})
        check("ændret stemme overskriver", db.votes_for_night(BD)[1] == "t2030")
        db.close()


async def test_quotes_and_profile():
    print("\n== 💬 Citat-bog og 🪪 profilkort ==")
    from torsdagsbar.module import TorsdagsbarModule
    from torsdagsbar import formatting as fmt

    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        cfg = TorsdagsbarConfig(enabled=True, server_id=1, voice_channel_ids=[2],
                                summary_channel_id=3, schedule=SCHEDULE, db_path=dbpath)
        db = Database(dbpath)

        class C:
            def get_channel(self, i): return None
            def get_guild(self, i): return None

        mod = TorsdagsbarModule(C(), cfg, db, vote_options=OPTIONS)
        mod.tracker.now = lambda: datetime(2026, 5, 20, 12, 0, tzinfo=TZ)

        qid = db.add_quote(11, "Slog alle de andre ihjel med kniv", 22)
        db.add_quote(11, "Jeg er helt ædru", 33)
        quotes = db.quotes_for(11)
        check("2 citater gemt", len(quotes) == 2)
        check("nyeste først", quotes[0].text == "Jeg er helt ædru")
        check("husker hvem der tilføjede", quotes[1].added_by == 22)
        check("husker datoen", quotes[1].created_at is not None)

        e = fmt.quote_embed(quotes[1], lambda u: f"Bruger{u}", TZ)
        check("citat-embed viser teksten", "kniv" in e.description)
        e2 = fmt.quotes_embed(quotes, 11, lambda u: f"Bruger{u}", TZ, 0, 1, 5)
        check("liste-embed viser begge", e2.description.count("”") == 4)
        tom = fmt.quotes_embed([], 11, lambda u: f"Bruger{u}", TZ, 0, 1, 5)
        check("tom liste giver venlig besked", "ingen citater" in tom.description)

        # Profilkort
        for uge, dag in enumerate((7, 14, 21)):
            j = datetime(2026, 5, dag, 19, 30, tzinfo=TZ)
            for uid in (11, 12):
                db.add_manual_session(uid, f"U{uid}", date(2026, 5, dag), j,
                                      j + timedelta(hours=3 if uid == 11 else 1))
            db.upsert_vote(date(2026, 5, dag), 11, "early", "native")

        class FakeTarget:
            id = 11
            display_name = "Christian"
            display_avatar = None

        embed = await mod.build_profile(FakeTarget(), "2026-01-01", "2026-12-31", "I år (2026)")
        navne = [f.name for f in embed.fields]
        check("profil har samlet tid", any("Samlet tid" in n for n in navne))
        check("profil har torsdagsbarer", any("Torsdagsbarer" in n for n in navne))
        check("profil har streak", any("Streak" in n for n in navne))
        check("profil har typisk ankomst", any("Typisk ankomst" in n for n in navne))
        check("profil har holdt-hvad-du-lovede", any("lovede" in n for n in navne))
        check("profil har titler", any("Titler" in n for n in navne))
        check("profil har citater", any("Citater" in n for n in navne))
        db.close()


def test_all_submodules_eagerly_imported():
    """Alle undermoduler skal indlæses ved 'import torsdagsbar'.

    Et modul, der kun importeres inde i en funktion, bliver ikke fundet af
    PyInstallers statiske analyse og ryger derfor ikke med i .exe-filen. Det
    ramte os i praksis: commands.py manglede i buildet, så /torsdagsbar, /quote
    og /quotes forsvandt fra Discord, mens resten af botten kørte videre.
    """
    import importlib, sys

    for navn in list(sys.modules):
        if navn.startswith("torsdagsbar"):
            del sys.modules[navn]
    importlib.import_module("torsdagsbar")

    forventet = {
        "awards", "commands", "config", "database", "formatting",
        "module", "period", "stats", "tracker", "votes",
    }
    indlæst = {
        n.split(".", 1)[1] for n in sys.modules
        if n.startswith("torsdagsbar.") and "." not in n.split(".", 1)[1]
    }
    manglende = forventet - indlæst
    check(f"alle {len(forventet)} undermoduler indlæses ved import (mangler: {manglende or 'ingen'})",
          not manglende)


async def main():
    test_all_submodules_eagerly_imported()
    test_king_and_marathon()
    test_early_bird_and_closer()
    test_kept_promise()
    test_surprise()
    test_speedrun()
    test_big_words_and_slow_starter()
    test_empty_and_cancelled()
    test_embed_omits_empty()
    test_tally_and_badges()
    test_promise_window()
    await test_year_periods()
    await test_late_notices()
    await test_vote_sync()
    await test_quotes_and_profile()
    print("\nALLE AWARDS-TESTS BESTÅET ✅")


if __name__ == "__main__":
    asyncio.run(main())
