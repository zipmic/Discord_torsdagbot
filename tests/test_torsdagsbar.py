"""Integrationstests for torsdagsbar-udvidelsen.

Kører uden en rigtig Discord-forbindelse ved hjælp af små fake-objekter.
Dækker de scenarier, opgaven beder om:
  * voice-registrering
  * skift mellem voicekanaler
  * genstart midt i en session
  * fredagsopsummering (kun én gang)
  * streaks
  * rekorder
  * live-kommando
  * leaderboard
  * aflyste torsdagsbarer
  * manuelle rettelser

Køres direkte:  python tests/test_torsdagsbar.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Gør pakken importérbar, når testen køres fra repo-roden.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zoneinfo import ZoneInfo

from torsdagsbar.config import TorsdagsbarConfig
from torsdagsbar.database import Database
from torsdagsbar.period import Schedule
from torsdagsbar.stats import Engine
from torsdagsbar.tracker import VoiceTracker

TZ = ZoneInfo("Europe/Copenhagen")
SERVER = 1000
CH_A = 2001  # to registrerede voicekanaler
CH_B = 2002
CH_OTHER = 2099  # en ikke-registreret kanal


# ---------------------------------------------------------------------------
# Fake discord-objekter
# ---------------------------------------------------------------------------
class FakeGuild:
    def __init__(self, gid): self.id = gid
    def get_member(self, uid): return None  # tving fallback til gemt navn


class FakeMember:
    def __init__(self, uid, name, bot=False, guild_id=SERVER):
        self.id = uid
        self.display_name = name
        self.bot = bot
        self.guild = FakeGuild(guild_id)


class FakeChannel:
    def __init__(self, cid, guild_id=SERVER):
        self.id = cid
        self.guild = FakeGuild(guild_id)
        self.members: list = []


class FakeVoiceState:
    def __init__(self, channel): self.channel = channel


class FakeClient:
    """Nok af en discord.Client til trackeren og modulet."""

    def __init__(self):
        self.channels = {
            CH_A: FakeChannel(CH_A),
            CH_B: FakeChannel(CH_B),
            CH_OTHER: FakeChannel(CH_OTHER),
        }

    def get_channel(self, cid):
        return self.channels.get(cid)

    def get_guild(self, gid):
        return FakeGuild(gid)


def make_config(db_path, min_minutes=5, require_company=True):
    return TorsdagsbarConfig(
        enabled=True,
        server_id=SERVER,
        voice_channel_ids=[CH_A, CH_B],
        summary_channel_id=3000,
        schedule=Schedule(TZ),
        min_minutes=min_minutes,
        tick_seconds=30,
        db_path=db_path,
        require_company=require_company,
    )


# ---------------------------------------------------------------------------
# Testhjælp: en tracker med kontrollerbart "nu"
# ---------------------------------------------------------------------------
class Harness:
    def __init__(self, db, config):
        self.client = FakeClient()
        self.db = db
        self.config = config
        self.tracker = VoiceTracker(self.client, config, db)
        self._now = datetime(2026, 5, 14, 18, 0, tzinfo=TZ)  # torsdag 18:00
        self.tracker.now = lambda: self._now

    def set_now(self, dt): self._now = dt

    def place(self, member, channel):
        """Sæt en bruger i en kanal i fake-cachen."""
        for ch in self.client.channels.values():
            ch.members = [m for m in ch.members if m.id != member.id]
        if channel is not None:
            channel.members.append(member)

    async def join(self, member, channel):
        before = FakeVoiceState(None)
        self.place(member, channel)
        after = FakeVoiceState(channel)
        await self.tracker.on_voice_state_update(member, before, after)

    async def move(self, member, from_ch, to_ch):
        before = FakeVoiceState(from_ch)
        self.place(member, to_ch)
        after = FakeVoiceState(to_ch)
        await self.tracker.on_voice_state_update(member, before, after)

    async def leave(self, member, from_ch):
        before = FakeVoiceState(from_ch)
        self.place(member, None)
        after = FakeVoiceState(None)
        await self.tracker.on_voice_state_update(member, before, after)


def check(name, cond):
    print(f"  [{'OK ' if cond else 'FEJL'}] {name}")
    assert cond, name


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
async def test_basic_registration():
    print("\n== Grundlæggende registrering + minimum + botfiltrering ==")
    with tempfile.TemporaryDirectory() as d:
        db = Database(Path(d) / "t.db")
        # Denne test handler om tracking + minimum + botfiltrering, ikke om
        # selskabsreglen, så vi slår den fra her.
        cfg = make_config(Path(d) / "t.db", require_company=False)
        h = Harness(db, cfg)
        chA = h.client.channels[CH_A]

        christian = FakeMember(11, "Christian")
        kort = FakeMember(12, "Kortvarig")
        en_bot = FakeMember(99, "MusikBot", bot=True)

        h.set_now(datetime(2026, 5, 14, 20, 0, tzinfo=TZ))
        await h.join(christian, chA)
        await h.join(en_bot, chA)      # skal ignoreres
        await h.join(kort, chA)

        check("åben session for Christian", db.get_open_session(11) is not None)
        check("ingen session for bot", db.get_open_session(99) is None)

        # Christian sidder 2 timer, Kortvarig kun 3 min
        h.set_now(datetime(2026, 5, 14, 22, 0, tzinfo=TZ))
        await h.leave(christian, chA)
        h.set_now(datetime(2026, 5, 14, 20, 3, tzinfo=TZ))
        await h.leave(kort, chA)

        eng = Engine(db.load_sessions(), db.load_nights(), db.load_corrections(),
                     cfg.min_seconds, require_company=cfg.require_company)
        ns = eng.night_summary("2026-05-14")
        names = {u for u, _ in ns.participants}
        check("Christian med i opsummering", 11 in names)
        check("Kortvarig (3<5 min) IKKE med", 12 not in names)
        check("Christians tid = 2 timer", eng._qualifiers("2026-05-14")[11] == 7200)
        db.close()


async def test_channel_switch():
    print("\n== Skift mellem registrerede kanaler tæller ikke som at gå ==")
    with tempfile.TemporaryDirectory() as d:
        db = Database(Path(d) / "t.db")
        cfg = make_config(Path(d) / "t.db")
        h = Harness(db, cfg)
        chA, chB, chOther = h.client.channels[CH_A], h.client.channels[CH_B], h.client.channels[CH_OTHER]
        emil = FakeMember(21, "Emil")

        h.set_now(datetime(2026, 5, 14, 19, 30, tzinfo=TZ))
        await h.join(emil, chA)
        sid1 = db.get_open_session(21).id

        # Skifter til den anden registrerede kanal -> samme session
        h.set_now(datetime(2026, 5, 14, 20, 0, tzinfo=TZ))
        await h.move(emil, chA, chB)
        s = db.get_open_session(21)
        check("stadig samme session efter kanalskift", s is not None and s.id == sid1)
        check("kanal opdateret til B", s.channel_id == CH_B)

        # Skifter til en IKKE-registreret kanal -> tæller som at gå
        h.set_now(datetime(2026, 5, 14, 21, 0, tzinfo=TZ))
        await h.move(emil, chB, chOther)
        check("session lukket ved skift til ikke-registreret kanal", db.get_open_session(21) is None)
        sess = db.load_sessions(user_id=21)
        check("varighed = 1.5 time (19:30-21:00)", sess[0].duration_seconds == 5400)
        db.close()


async def test_restart_mid_session():
    print("\n== Genstart midt i en session (gendannelse) ==")
    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        cfg = make_config(dbpath)
        db = Database(dbpath)
        h = Harness(db, cfg)
        chA = h.client.channels[CH_A]
        dennis = FakeMember(31, "Dennis")

        h.set_now(datetime(2026, 5, 14, 19, 0, tzinfo=TZ))
        await h.join(dennis, chA)
        db.set_heartbeat(datetime(2026, 5, 14, 19, 0, tzinfo=TZ).astimezone(timezone.utc))
        check("session åben før genstart", db.get_open_session(31) is not None)

        # --- botten genstarter: ny db-forbindelse, ny tracker ---
        db.close()
        db2 = Database(dbpath)
        h2 = Harness(db2, cfg)
        chA2 = h2.client.channels[CH_A]
        h2.set_now(datetime(2026, 5, 14, 20, 0, tzinfo=TZ))
        # Dennis sidder der stadig -> placer ham i den nye fake-cache
        h2.place(dennis, chA2)
        await h2.tracker.recover()
        s = db2.get_open_session(31)
        check("Dennis' session fortsætter efter genstart", s is not None)
        check("start bevaret (19:00)", s.joined_at.astimezone(TZ).hour == 19)

        # Han går kl 21 -> total 2 timer, ikke tabt
        h2.set_now(datetime(2026, 5, 14, 21, 0, tzinfo=TZ))
        await h2.leave(dennis, chA2)
        sess = db2.load_sessions(user_id=31)
        check("samlet 2 timer bevaret hen over genstart", sess[0].duration_seconds == 7200)

        # --- genstart hvor brugeren IKKE længere er der ---
        h2.set_now(datetime(2026, 5, 14, 22, 0, tzinfo=TZ))
        await h2.join(dennis, chA2)  # ny session
        db2.set_heartbeat(datetime(2026, 5, 14, 22, 30, tzinfo=TZ).astimezone(timezone.utc))
        db2.close()
        db3 = Database(dbpath)
        h3 = Harness(db3, cfg)
        h3.set_now(datetime(2026, 5, 14, 23, 0, tzinfo=TZ))
        # Dennis er IKKE i nogen kanal nu (tom cache)
        await h3.tracker.recover()
        check("efterladt session lukket efter genstart", db3.get_open_session(31) is None)
        sess = db3.load_sessions(user_id=31)
        # sidste session lukket ved heartbeat (22:30) -> 30 min
        sidste = max(sess, key=lambda s: s.joined_at)
        check("efterladt session lukket ved heartbeat (~30 min)", sidste.duration_seconds == 1800)
        db3.close()


async def test_online_at_1900_and_0300():
    print("\n== Online allerede 19:00 og stadig online 03:00 ==")
    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        cfg = make_config(dbpath)
        db = Database(dbpath)
        h = Harness(db, cfg)
        chA = h.client.channels[CH_A]
        alex = FakeMember(41, "Alex")

        # Botten kører før 19:00, Alex sidder allerede i kanalen kl 18:30
        h.set_now(datetime(2026, 5, 14, 18, 30, tzinfo=TZ))
        h.place(alex, chA)
        await h.tracker.recover()  # udenfor vindue -> ingen session endnu
        check("ingen registrering før 19:00", db.get_open_session(41) is None)

        # Klokken bliver 19:00 -> tick åbner session med start 19:00
        h.set_now(datetime(2026, 5, 14, 19, 0, 20, tzinfo=TZ))
        await h.tracker.tick()
        s = db.get_open_session(41)
        check("session åbnet ved 19:00-overgang", s is not None)
        check("start sat til præcis 19:00", s.joined_at.astimezone(TZ).strftime("%H:%M") == "19:00")

        # Klokken passerer 03:00 -> tick lukker automatisk ved 03:00
        h.set_now(datetime(2026, 5, 15, 3, 0, 30, tzinfo=TZ))
        await h.tracker.tick()
        check("session lukket ved 03:00", db.get_open_session(41) is None)
        sess = db.load_sessions(user_id=41)
        end = sess[0].left_at.astimezone(TZ)
        check("afsluttet præcis 03:00", end.strftime("%H:%M") == "03:00")
        check("varighed = 8 timer (19-03)", sess[0].duration_seconds == 8 * 3600)
        db.close()


async def test_live_status():
    print("\n== Live-status ==")
    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        # Tester live-mekanikken (tid tilbage, tælling), ikke selskabsreglen.
        cfg = make_config(dbpath, require_company=False)
        db = Database(dbpath)
        h = Harness(db, cfg)
        chA = h.client.channels[CH_A]
        a = FakeMember(51, "Christian"); b = FakeMember(52, "Emil")

        h.set_now(datetime(2026, 5, 14, 20, 0, tzinfo=TZ))
        await h.join(a, chA)
        h.set_now(datetime(2026, 5, 14, 20, 30, tzinfo=TZ))
        await h.join(b, chA)

        h.set_now(datetime(2026, 5, 14, 22, 18, tzinfo=TZ))
        status = await h.tracker.live_status()
        check("live aktiv", status["active"])
        check("2 online", status["current_count"] == 2)
        check("Christian 2t18m foreløbig", status["online"][0]["seconds"] == (2 * 3600 + 18 * 60))
        rest = status["time_left"]
        check("tid tilbage til 03:00 = 4t42m", int(rest.total_seconds()) == (4 * 3600 + 42 * 60))

        # Udenfor vinduet
        h.set_now(datetime(2026, 5, 16, 12, 0, tzinfo=TZ))  # lørdag
        status2 = await h.tracker.live_status()
        check("live ikke aktiv udenfor vindue", not status2["active"])
        check("næste start er en torsdag 19:00", status2["next_start"].strftime("%A %H:%M").endswith("19:00"))
        db.close()


async def test_summary_once():
    print("\n== Fredagsopsummering sendes kun én gang ==")
    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        cfg = make_config(dbpath)
        db = Database(dbpath)
        # En session så der er noget at opsummere
        db.add_manual_session(61, "Christian", date(2026, 5, 14),
                              datetime(2026, 5, 14, 17, 0, tzinfo=timezone.utc),
                              datetime(2026, 5, 14, 20, 0, tzinfo=timezone.utc))

        from torsdagsbar.module import TorsdagsbarModule
        client = FakeClient()
        # Fake opsummeringskanal der tæller sendte beskeder
        sent = []
        class FakeText:
            async def send(self, **kw): sent.append(kw)
        import torsdagsbar.module as M
        # gør isinstance(channel, TextChannel) sand ved at patche
        orig = M.discord.TextChannel
        M.discord.TextChannel = FakeText
        client.channels[3000] = FakeText()
        mod = TorsdagsbarModule(client, cfg, db)
        mod.tracker.now = lambda: datetime(2026, 5, 15, 12, 0, tzinfo=TZ)  # fredag 12:00

        await mod._maybe_send_due_summary()
        await mod._maybe_send_due_summary()  # anden gang skal IKKE sende igen
        check("opsummering sendt netop én gang", len(sent) == 1)
        check("markeret som sendt i db", db.is_summary_sent("2026-05-14"))

        # Admin kan gensende med force
        await mod.send_summary(date(2026, 5, 14), force=True)
        check("force gensender", len(sent) == 2)
        M.discord.TextChannel = orig
        db.close()


async def test_streaks_records_leaderboard_cancel_corrections():
    print("\n== Streaks, rekorder, leaderboard, aflysning, rettelser (E2E via DB) ==")
    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        # Tester streak/rekord/leaderboard-logikken med enkeltbrugere pr. nat;
        # selskabsreglen testes separat, så den slås fra her.
        cfg = make_config(dbpath, require_company=False)
        db = Database(dbpath)

        def manual(uid, name, day, hours):
            j = datetime(2026, 5, day, 17, 0, tzinfo=timezone.utc)
            l = j + timedelta(hours=hours)
            db.add_manual_session(uid, name, date(2026, 5, day), j, l)

        # Torsdage 7,14,21,28
        for day in (7, 14, 21, 28):
            manual(1, "Christian", day, 2)     # alle 4
        manual(2, "Emil", 7, 1.5); manual(2, "Emil", 14, 3); manual(2, "Emil", 28, 0.2)
        manual(4, "Alex", 14, 5)               # rekord enkeltsession

        eng = Engine(db.load_sessions(), db.load_nights(), db.load_corrections(), cfg.min_seconds, require_company=cfg.require_company)
        check("Christian streak 4", eng.streak(1).current == 4)
        rec = eng.records()
        check("længste enkelt = Alex 5t", rec["longest_single"]["sessions"][0].user_id == 4)
        lb = eng.leaderboard("tid")
        check("leaderboard nr1 = Christian", lb[0].user_id == 1)

        # Aflys 21/5: Christian streak må ikke brydes (han var der, men natten bliver neutral)
        db.set_cancelled(date(2026, 5, 21), True, "test")
        eng = Engine(db.load_sessions(), db.load_nights(), db.load_corrections(), cfg.min_seconds, require_company=cfg.require_company)
        check("21/5 ikke længere tællende", "2026-05-21" not in eng.counting_dates)
        check("Christian streak nu 3 (21 neutral)", eng.streak(1).current == 3)

        # Manuel rettelse: giv Emil +40 min den 28/5 så han når over noget
        before = eng._qualifiers("2026-05-28").get(2, 0)
        db.add_correction(2, date(2026, 5, 28), 40 * 60, "glemt", 9999)
        eng = Engine(db.load_sessions(), db.load_nights(), db.load_corrections(), cfg.min_seconds, require_company=cfg.require_company)
        after = eng._qualifiers("2026-05-28").get(2, 0)
        check("rettelse lagt til Emils tid", after == before + 40 * 60)
        db.close()


async def test_leaderboard_command_send():
    print("\n== /leaderboard-kommandoen sender uden at crashe (én og flere sider) ==")
    from torsdagsbar.module import TorsdagsbarModule
    from torsdagsbar.commands import build_group

    class FakeResponse:
        async def defer(self, **kw): pass

    class FakeFollowup:
        def __init__(self): self.calls = []
        async def send(self, **kw):
            # Efterlign discord.py: view=None er ikke tilladt.
            if "view" in kw and kw["view"] is None:
                raise TypeError("expected view parameter to be of type View, not NoneType")
            self.calls.append(kw)

    class FakeInteraction:
        def __init__(self, uid):
            self.user = FakeMember(uid, "Tester")
            self.response = FakeResponse()
            self.followup = FakeFollowup()

    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        cfg = make_config(dbpath)
        db = Database(dbpath)
        # Én deltager -> kun én side (den situation der crashede før)
        db.add_manual_session(1, "Solo", date(2026, 5, 14),
                              datetime(2026, 5, 14, 17, 0, tzinfo=timezone.utc),
                              datetime(2026, 5, 14, 19, 0, tzinfo=timezone.utc))
        mod = TorsdagsbarModule(FakeClient(), cfg, db)
        mod.tracker.now = lambda: datetime(2026, 5, 20, 12, 0, tzinfo=TZ)
        group = build_group(mod)
        cmd = group.get_command("leaderboard")

        it = FakeInteraction(1)
        await cmd.callback(it, sortering=None, periode=None)
        check("én side: sendt uden fejl", len(it.followup.calls) == 1)
        check("én side: ingen view vedhæftet", "view" not in it.followup.calls[0])

        # Mange deltagere -> flere sider -> view SKAL med
        for uid in range(2, 20):
            db.add_manual_session(uid, f"Bruger{uid}", date(2026, 5, 14),
                                  datetime(2026, 5, 14, 17, 0, tzinfo=timezone.utc),
                                  datetime(2026, 5, 14, 17, 0, tzinfo=timezone.utc) + timedelta(minutes=uid * 6))
        it2 = FakeInteraction(1)
        await cmd.callback(it2, sortering=None, periode=None)
        check("flere sider: view vedhæftet", it2.followup.calls[0].get("view") is not None)
        db.close()


async def test_live_counts_in_leaderboard():
    print("\n== Igangværende deltagelse tæller med i statistik/leaderboard ==")
    from torsdagsbar.module import TorsdagsbarModule
    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        # Tester at åbne (live) sessioner medregnes; selskabsreglen testes separat.
        cfg = make_config(dbpath, require_company=False)
        db = Database(dbpath)
        h = Harness(db, cfg)
        chA = h.client.channels[CH_A]
        per = FakeMember(71, "IgangværendePer")

        # Per går ind kl. 20:00 og er der stadig (åben session)
        h.set_now(datetime(2026, 5, 14, 20, 0, tzinfo=TZ))
        await h.join(per, chA)

        mod = TorsdagsbarModule(h.client, cfg, db)
        # Kun 2 minutter inde -> under minimum -> må IKKE tælle endnu
        mod.tracker.now = lambda: datetime(2026, 5, 14, 20, 2, tzinfo=TZ)
        eng = await mod.build_engine()
        lb = eng.leaderboard("tid")
        check("under 5 min: endnu ikke på leaderboard", all(r.user_id != 71 for r in lb))

        # 40 minutter inde -> over minimum -> skal tælle med LIVE
        mod.tracker.now = lambda: datetime(2026, 5, 14, 20, 40, tzinfo=TZ)
        eng = await mod.build_engine()
        lb = eng.leaderboard("tid")
        row = next((r for r in lb if r.user_id == 71), None)
        check("over 5 min: på leaderboard mens det er i gang", row is not None)
        check("live-tid ~40 min", row is not None and row.total_seconds == 40 * 60)

        # build_engine(live=False) skal IKKE tælle den åbne session
        eng2 = await mod.build_engine(live=False)
        check("uden live: åben session tælles ikke", all(r.user_id != 71 for r in eng2.leaderboard("tid")))
        db.close()


async def test_company_gating():
    print("\n== Kun tid MED selskab tæller (anti-solo-farming) ==")
    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        cfg = make_config(dbpath)
        db = Database(dbpath)

        def sess(uid, name, day, jh, jm, lh, lm):
            j = datetime(2026, 5, day, jh, jm, tzinfo=timezone.utc)
            l = datetime(2026, 5, day, lh, lm, tzinfo=timezone.utc)
            db.add_manual_session(uid, name, date(2026, 5, day), j, l, source="auto")

        # 14/5: Christian sidder 17-21 (4t), men Emil er der kun 18:00-18:30 (30 min)
        sess(1, "Christian", 14, 17, 0, 21, 0)
        sess(2, "Emil", 14, 18, 0, 18, 30)
        # 21/5: Alex HELT alene 17-22 (5t solo) -> skal give 0
        sess(4, "Alex", 21, 17, 0, 22, 0)

        eng = Engine(db.load_sessions(), db.load_nights(), db.load_corrections(), cfg.min_seconds, require_company=cfg.require_company)
        # Christian optjener kun de 30 min hvor Emil også var der
        check("Christian optjener kun 30 min (med selskab)", eng.night_user["2026-05-14"].get(1) == 1800)
        check("Emil optjener 30 min", eng.night_user["2026-05-14"].get(2) == 1800)
        # Alex helt alene -> 0 -> under minimum -> ikke tællende nat
        check("Alex (solo hele aftenen) optjener 0", eng.night_user.get("2026-05-21", {}).get(4, 0) == 0)
        check("solo-nat 21/5 er IKKE en tællende nat", "2026-05-21" not in eng.counting_dates)

        # Leaderboard: kun Christian+Emil, ikke Alex
        lb = eng.leaderboard("tid")
        ids = {r.user_id for r in lb}
        check("Alex ikke på leaderboard (kun solo-tid)", 4 not in ids)
        check("Christian+Emil på leaderboard", 1 in ids and 2 in ids)

        # RETROAKTIVT: gammel solo-data giver 0 uden migrering
        check("retroaktiv: solo-nat giver 0 timer", eng.user_stats(4).total_seconds == 0)

        # require_company=False -> gammel adfærd (solo tæller)
        eng_off = Engine(db.load_sessions(), db.load_nights(), db.load_corrections(),
                         cfg.min_seconds, require_company=False)
        check("uden krav: Alex' 5 solo-timer tæller", eng_off.night_user["2026-05-21"].get(4) == 5 * 3600)
        db.close()


async def test_live_company_gating():
    print("\n== Live: solo giver 0 optjent, men vises stadig som online ==")
    with tempfile.TemporaryDirectory() as d:
        dbpath = Path(d) / "t.db"
        cfg = make_config(dbpath)
        db = Database(dbpath)
        h = Harness(db, cfg)
        chA = h.client.channels[CH_A]
        per = FakeMember(81, "SoloPer")

        h.set_now(datetime(2026, 5, 14, 20, 0, tzinfo=TZ))
        await h.join(per, chA)
        h.set_now(datetime(2026, 5, 14, 21, 0, tzinfo=TZ))  # 1 time alene
        status = await h.tracker.live_status()
        online = {o["user_id"]: o for o in status["online"]}
        check("SoloPer vises som online", 81 in online)
        check("men optjent tid = 0 (ingen selskab)", online[81]["seconds"] == 0)

        # Nu kommer en anden ind -> begge begynder at optjene
        ven = FakeMember(82, "Ven")
        await h.join(ven, chA)
        h.set_now(datetime(2026, 5, 14, 21, 30, tzinfo=TZ))  # 30 min sammen
        status2 = await h.tracker.live_status()
        online2 = {o["user_id"]: o for o in status2["online"]}
        check("SoloPer optjener nu 30 min (selskab)", online2[81]["seconds"] == 30 * 60)
        check("Ven optjener 30 min", online2[82]["seconds"] == 30 * 60)
        db.close()


async def main():
    await test_basic_registration()
    await test_channel_switch()
    await test_restart_mid_session()
    await test_online_at_1900_and_0300()
    await test_live_status()
    await test_summary_once()
    await test_streaks_records_leaderboard_cancel_corrections()
    await test_leaderboard_command_send()
    await test_live_counts_in_leaderboard()
    await test_company_gating()
    await test_live_company_gating()
    print("\nALLE TORSDAGSBAR-TESTS BESTÅET ✅")


if __name__ == "__main__":
    asyncio.run(main())
