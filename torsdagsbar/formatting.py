"""Dansk formatering og opbygning af Discord-embeds til torsdagsbaren.

Tidspunkter gemmes i UTC, men vises altid som dansk lokal tid her.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Optional

import discord
from zoneinfo import ZoneInfo

from .awards import AwardTally, Badge, NightAwards
from .stats import Engine, LeaderboardRow, NightSummary, UserStats

# Navneopslag: giver et brugervenligt navn ud fra et bruger-ID.
NameResolver = Callable[[int], str]

UGEDAGE = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MÅNEDER = [
    "januar", "februar", "marts", "april", "maj", "juni",
    "juli", "august", "september", "oktober", "november", "december",
]

FARVE = discord.Colour.from_rgb(240, 179, 63)  # varm "bar"-gul


# ---------------------------------------------------------------------------
# Tekst
# ---------------------------------------------------------------------------
def fmt_duration(seconds: Optional[float], *, kort: bool = False) -> str:
    """Formatér en varighed på dansk, fx '3 timer og 24 minutter'.

    ``kort=True`` giver en kompakt form som '3t 24m' (til leaderboard-tabeller).
    """
    total = int(seconds or 0)
    minutes = total // 60
    hours, mins = divmod(minutes, 60)

    if kort:
        if hours and mins:
            return f"{hours}t {mins:02d}m"
        if hours:
            return f"{hours}t"
        return f"{mins}m"

    time_ord = "time" if hours == 1 else "timer"
    min_ord = "minut" if mins == 1 else "minutter"
    if hours and mins:
        return f"{hours} {time_ord} og {mins} {min_ord}"
    if hours:
        return f"{hours} {time_ord}"
    return f"{mins} {min_ord}"


def parse_date(value: str) -> date:
    """Fortolk 'ÅÅÅÅ-MM-DD'. Rejser ValueError ved forkert format."""
    return date.fromisoformat(value.strip())


def fmt_date(d: date, *, stort: bool = True) -> str:
    """'torsdag den 14. maj 2026' (stort begyndelsesbogstav som standard)."""
    tekst = f"{UGEDAGE[d.weekday()]} den {d.day}. {MÅNEDER[d.month - 1]} {d.year}"
    return tekst[0].upper() + tekst[1:] if stort else tekst


def to_local(moment: datetime, tz: ZoneInfo) -> datetime:
    return moment.astimezone(tz)


def fmt_clock(moment: datetime, tz: ZoneInfo) -> str:
    """'kl. 19:04' i lokal tid."""
    return "kl. " + to_local(moment, tz).strftime("%H:%M")


def fmt_span(start: datetime, end: datetime, tz: ZoneInfo) -> str:
    """'fra kl. 19:00 til fredag kl. 02:47' – nævner ugedag hvis det skifter."""
    ls, le = to_local(start, tz), to_local(end, tz)
    hvis_ny_dag = ""
    if le.date() != ls.date():
        hvis_ny_dag = UGEDAGE[le.weekday()] + " "
    return f"fra {fmt_clock(start, tz)} til {hvis_ny_dag}{fmt_clock(end, tz)}"


def fmt_countdown(delta: timedelta) -> str:
    """'2 timer og 14 minutter' ud fra en tidsforskel (aldrig negativ)."""
    return fmt_duration(max(0, int(delta.total_seconds())))


PERIODE_NAVNE = {
    "i_år": "I år",
    "sidste_år": "Sidste år",
    "sidste_uge": "Sidste uge",
    "denne_måned": "Denne måned",
    "sidste_3_måneder": "Sidste 3 måneder",
    "sidste_6_måneder": "Sidste 6 måneder",
    "hele_perioden": "Hele perioden",
}


# "Du er sent på den" – flere tekster, så det ikke bliver det samme hver gang.
# {mention} = brugeren, {løfte} = det tidsrum de stemte på.
LATE_MESSAGES = (
    "Hva' jeg synes {mention} er sent på den!",
    "{mention} lovede {løfte}. Klokken er noget andet nu. 👀",
    "Vi venter stadig på {mention} … der blev sagt {løfte}. ⏰",
    "{mention} sagde {løfte}. Trafikken må være slem. 🚗",
    "Breaking news: {mention} er ikke dukket op endnu. Der blev ellers lovet {løfte}.",
    "{mention}, dit bord i baren står tomt. Du sagde jo {løfte}! 🍻",
    "Har nogen set {mention}? Sidst set love {løfte}. 🔍",
    "{mention} praktiserer akademisk kvarter i stor stil. Der blev stemt {løfte}.",
    "Sørme om ikke {mention} er sent på den igen. {løfte}, sagde du!",
    "{mention}: forventet {løfte}. Faktisk: fraværende. Vi noterer. 📋",
)


def late_message(mention: str, promise_label: str) -> str:
    """Vælg en tilfældig drilske-tekst til en forsinket bruger."""
    import random

    skabelon = random.choice(LATE_MESSAGES)
    return skabelon.format(mention=mention, løfte=promise_label)


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------
def _footer(embed: discord.Embed, periode_label: Optional[str] = None) -> None:
    tekst = "Torsdagsbar"
    if periode_label:
        tekst += f" · Periode: {periode_label}"
    embed.set_footer(text=tekst)


def stats_embed(
    stats: UserStats,
    engine: Engine,
    name_of: NameResolver,
    tz: ZoneInfo,
    periode_label: str,
    top: list[LeaderboardRow],
) -> discord.Embed:
    navn = name_of(stats.user_id)
    embed = discord.Embed(
        title=f"📊 Torsdagsbar-statistik — {navn}",
        colour=FARVE,
    )
    if stats.nights == 0:
        embed.description = "Ingen registreret deltagelse i den valgte periode."
        _footer(embed, periode_label)
        return embed

    embed.add_field(name="Samlet tid", value=fmt_duration(stats.total_seconds), inline=True)
    embed.add_field(name="Antal torsdagsbarer", value=str(stats.nights), inline=True)
    embed.add_field(
        name="Gennemsnit pr. gang",
        value=fmt_duration(stats.average_seconds),
        inline=True,
    )

    if stats.longest_single_seconds:
        dato = parse_date(stats.longest_single_date)
        linje = fmt_duration(stats.longest_single_seconds)
        if stats.longest_single_start and stats.longest_single_end:
            linje += f"\n{fmt_date(dato)}\n{fmt_span(stats.longest_single_start, stats.longest_single_end, tz)}"
        embed.add_field(name="Længste enkeltdeltagelse", value=linje, inline=False)

    embed.add_field(name="Nuværende streak", value=f"{stats.current_streak} 🔥", inline=True)
    embed.add_field(name="Længste streak", value=str(stats.longest_streak), inline=True)
    if stats.rank:
        embed.add_field(
            name="Placering",
            value=f"#{stats.rank} af {stats.participants_in_period}",
            inline=True,
        )

    if top:
        linjer = []
        for i, row in enumerate(top[:10], start=1):
            markør = "**" if row.user_id == stats.user_id else ""
            linjer.append(
                f"{i}. {markør}{name_of(row.user_id)}{markør} — "
                f"{fmt_duration(row.total_seconds, kort=True)}"
            )
        embed.add_field(name="Top 10 (samlet tid)", value="\n".join(linjer), inline=False)

    _footer(embed, periode_label)
    return embed


def streak_embed(
    stats: UserStats,
    engine: Engine,
    name_of: NameResolver,
    top_active: list,
) -> discord.Embed:
    navn = name_of(stats.user_id)
    streak = engine.streak(stats.user_id)
    embed = discord.Embed(title=f"🔥 Streak — {navn}", colour=FARVE)
    embed.add_field(
        name="Nuværende streak",
        value=f"{streak.current} torsdagsbarer" + (" (aktiv)" if streak.current_active else ""),
        inline=False,
    )
    if streak.longest:
        periode = ""
        if streak.longest_start and streak.longest_end:
            periode = (
                f"\nFra {fmt_date(parse_date(streak.longest_start), stort=False)} "
                f"til {fmt_date(parse_date(streak.longest_end), stort=False)}"
            )
        embed.add_field(
            name="Længste streak nogensinde",
            value=f"{streak.longest} torsdagsbarer{periode}",
            inline=False,
        )
    else:
        embed.description = "Ingen registreret streak endnu."

    if top_active:
        linjer = []
        for i, s in enumerate(top_active[:10], start=1):
            markør = "**" if s.user_id == stats.user_id else ""
            linjer.append(f"{i}. {markør}{name_of(s.user_id)}{markør} — {s.current} 🔥")
        embed.add_field(name="Top 10 aktive streaks", value="\n".join(linjer), inline=False)
    _footer(embed)
    return embed


def leaderboard_embed(
    rows: list[LeaderboardRow],
    name_of: NameResolver,
    sort_key: str,
    sort_label: str,
    periode_label: str,
    page: int,
    pages: int,
    per_page: int,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 Torsdagsbar Leaderboard — {sort_label}",
        colour=FARVE,
    )
    if not rows:
        embed.description = "Ingen deltagelse registreret i den valgte periode."
        _footer(embed, periode_label)
        return embed

    start = page * per_page
    linjer = []
    for offset, row in enumerate(rows[start : start + per_page]):
        plads = start + offset + 1
        værdi = _leaderboard_value(row, sort_key)
        ekstra = f" · {row.nights} torsdagsbarer"
        if sort_key not in ("antal",) and row.nights:
            ekstra += f" · {fmt_duration(row.total_seconds, kort=True)} i alt"
        linjer.append(f"**{plads}.** {name_of(row.user_id)} — {værdi}{ekstra}")
    embed.description = "\n".join(linjer)
    embed.set_footer(text=f"Torsdagsbar · Periode: {periode_label} · Side {page + 1}/{pages}")
    return embed


def _leaderboard_value(row: LeaderboardRow, sort_key: str) -> str:
    if sort_key == "antal":
        return f"{row.nights} torsdagsbarer"
    if sort_key == "gennemsnit":
        return fmt_duration(row.average_seconds)
    if sort_key == "streak":
        return f"{row.current_streak} 🔥"
    if sort_key == "længste_streak":
        return f"{row.longest_streak} torsdagsbarer"
    if sort_key == "længste_enkelt":
        return fmt_duration(row.longest_single_seconds)
    return fmt_duration(row.total_seconds)


def records_embed(
    rec: dict,
    engine: Engine,
    name_of: NameResolver,
    tz: ZoneInfo,
    periode_label: str,
) -> discord.Embed:
    embed = discord.Embed(title="📚 Torsdagsbar-rekorder", colour=FARVE)

    mp = rec["most_participants"]
    if mp["count"]:
        blokke = []
        for ns in mp["details"]:
            dato = parse_date(ns.bar_date)
            linje = f"**{ns.participant_count} deltagere**\n{fmt_date(dato)}"
            if ns.first_join and ns.last_leave:
                linje += f"\nRegistreret {fmt_span(ns.first_join, ns.last_leave, tz)}"
                linje += f"\nSamlet varighed: {fmt_duration(ns.span_seconds)}"
            navne = ", ".join(name_of(u) for u, _ in ns.participants)
            linje += f"\nDeltagere: {navne}"
            blokke.append(linje)
        embed.add_field(name="🥇 Flest deltagere", value="\n\n".join(blokke), inline=False)

    ls = rec["longest_single"]
    if ls["seconds"]:
        blokke = []
        for s in ls["sessions"]:
            dato = parse_date(s.bar_date)
            linje = f"**{name_of(s.user_id)}** — {fmt_duration(s.duration_seconds)}\n{fmt_date(dato)}"
            if s.joined_at and s.left_at:
                linje += f"\n{fmt_span(s.joined_at, s.left_at, tz)}"
            blokke.append(linje)
        embed.add_field(name="⏱️ Længste individuelle deltagelse", value="\n\n".join(blokke), inline=False)

    lnt = rec["longest_night_total"]
    if lnt["seconds"]:
        holders = "\n".join(
            f"{name_of(uid)} — {fmt_duration(lnt['seconds'])} ({fmt_date(parse_date(d), stort=False)})"
            for uid, d in lnt["holders"]
        )
        embed.add_field(name="🌙 Længste samlede tid på én aften", value=holders, inline=False)

    if rec.get("longest_active_streak"):
        s = rec["longest_active_streak"]
        embed.add_field(
            name="🔥 Længste aktive streak",
            value=f"{name_of(s.user_id)} — {s.current} torsdagsbarer",
            inline=True,
        )
    if rec.get("longest_streak_ever"):
        s = rec["longest_streak_ever"]
        embed.add_field(
            name="🏅 Længste streak nogensinde",
            value=f"{name_of(s.user_id)} — {s.longest} torsdagsbarer",
            inline=True,
        )
    if rec.get("most_nights"):
        m = rec["most_nights"]
        embed.add_field(
            name="📅 Flest torsdagsbarer",
            value=f"{name_of(m['user_id'])} — {m['nights']}",
            inline=True,
        )
    if rec.get("most_hours"):
        m = rec["most_hours"]
        embed.add_field(
            name="⌛ Flest samlede timer",
            value=f"{name_of(m['user_id'])} — {fmt_duration(m['seconds'])}",
            inline=True,
        )
    _footer(embed, periode_label)
    return embed


def _names(ids, name_of: NameResolver) -> str:
    return ", ".join(name_of(uid) for uid in ids)


def award_fields(
    awards: NightAwards, name_of: NameResolver, tz: ZoneInfo
) -> list[tuple[str, str]]:
    """Aftenens titler som (overskrift, tekst).

    Kategorier uden gyldige data giver ingen linje og udelades dermed helt.
    """
    felter: list[tuple[str, str]] = []
    if not awards.has_any:
        return felter

    if awards.kings:
        felter.append((
            "👑 Aftenens konge",
            f"{_names(awards.kings, name_of)} — {fmt_duration(awards.king_seconds)}",
        ))
    if awards.marathon:
        felter.append((
            "🏃 Marathonmand",
            "\n".join(
                f"{name_of(uid)} — {fmt_duration(sec)}" for uid, sec in awards.marathon
            ),
        ))
    if awards.early_birds and awards.early_bird_at:
        felter.append((
            "🐦 Early Bird",
            f"{_names(awards.early_birds, name_of)} ({fmt_clock(awards.early_bird_at, tz)})",
        ))
    if awards.closers and awards.closer_at:
        felter.append((
            "🦉 Lukkede baren",
            f"{_names(awards.closers, name_of)} ({fmt_clock(awards.closer_at, tz)})",
        ))
    if awards.kept_promise:
        felter.append((
            "🎯 Holdt hvad de lovede",
            _names(awards.kept_promise, name_of),
        ))
    if awards.surprises:
        felter.append((
            "🎭 Surprise!",
            f"{_names(awards.surprises, name_of)} — stemte \"kommer ikke\", men mødte op!",
        ))
    if awards.speedrun:
        felter.append((
            "⚡ Speedrun",
            f"{_names(awards.speedrun, name_of)} — {fmt_duration(awards.speedrun_seconds)}",
        ))
    if awards.waiting:
        felter.append((
            "⏳ Waiting for players...",
            f"{_names(awards.waiting, name_of)} — sad {fmt_duration(awards.waiting_seconds)} "
            f"alene i baren",
        ))
    if awards.big_words:
        felter.append((
            "🤥 Store ord",
            "\n".join(
                f"{name_of(uid)} — mødte op {fmt_duration(delay)} for sent"
                for uid, delay in awards.big_words
            ),
        ))
    if awards.slow_starters:
        felter.append((
            "🐌 Slow starter",
            "\n".join(
                f"{name_of(uid)} — forsinket {fmt_duration(delay)}"
                for uid, delay in awards.slow_starters
            ),
        ))
    return felter


def summary_embed(
    ns: NightSummary,
    name_of: NameResolver,
    tz: ZoneInfo,
    *,
    show_records: bool = True,
    awards: Optional[NightAwards] = None,
) -> discord.Embed:
    """Fredagsopsummeringen."""
    dato = parse_date(ns.bar_date)
    if ns.cancelled:
        embed = discord.Embed(
            title="Torsdagsbar aflyst",
            description=f"{fmt_date(dato)} var markeret som aflyst – ingen statistik.",
            colour=FARVE,
        )
        return embed

    if ns.participant_count == 0:
        embed = discord.Embed(
            title="Ingen torsdagsbar 😴",
            description=(
                f"Der blev ikke registreret nogen deltagere til torsdagsbaren "
                f"{fmt_date(dato, stort=False)}. Måske næste uge!"
            ),
            colour=FARVE,
        )
        return embed

    linjer = [
        f"- {name_of(uid)} — {fmt_duration(sec)}" for uid, sec in ns.participants
    ]
    beskrivelse = (
        "Sikke en dejlig torsdagsbar!\n\n"
        "**Følgende personer deltog:**\n" + "\n".join(linjer) +
        f"\n\n**Samlet deltagertid:** {fmt_duration(ns.total_seconds)}"
        f"\n**Antal deltagere:** {ns.participant_count}"
    )
    embed = discord.Embed(
        title=f"🍻 Torsdagsbar — {fmt_date(dato)}",
        description=beskrivelse,
        colour=FARVE,
    )

    # Aftenens titler (hver kategori udelades, hvis ingen opfylder den).
    if awards is not None:
        for navn, værdi in award_fields(awards, name_of, tz):
            embed.add_field(name=navn, value=værdi, inline=False)

    if show_records:
        ekstra = []
        # 👑 vises som sit eget felt ovenfor, når titlerne er med.
        if ns.top_user is not None and awards is None:
            top_sec = ns.participants[0][1]
            ekstra.append(f"👑 Længst til stede: **{name_of(ns.top_user)}** ({fmt_duration(top_sec)})")
        if ns.new_participant_record:
            ekstra.append(f"🎉 Ny rekord for flest deltagere: **{ns.participant_count}**!")
        if ns.new_personal_records:
            navne = ", ".join(name_of(u) for u in ns.new_personal_records)
            ekstra.append(f"⭐ Ny personlig rekord: {navne}")
        if ns.extended_streaks:
            navne = ", ".join(f"{name_of(u)} ({n} 🔥)" for u, n in ns.extended_streaks)
            ekstra.append(f"🔥 Forlængede streak: {navne}")
        if ekstra:
            embed.add_field(name="Aftenens højdepunkter", value="\n".join(ekstra), inline=False)

    if ns.first_join and ns.last_leave:
        embed.set_footer(
            text=f"Registreret {fmt_span(ns.first_join, ns.last_leave, tz)}"
        )
    return embed


# ---------------------------------------------------------------------------
# 🪪 Profilkort
# ---------------------------------------------------------------------------
def fmt_arrival_offset(minutes: Optional[int], window_start_hour: int, window_start_minute: int) -> str:
    """Omsæt "minutter efter registreringsstart" til et klokkeslæt, fx 'kl. 20:12'."""
    if minutes is None:
        return "—"
    total = window_start_hour * 60 + window_start_minute + minutes
    total %= 24 * 60
    return f"kl. {total // 60:02d}:{total % 60:02d}"


def profile_embed(
    stats: UserStats,
    engine: Engine,
    tally: AwardTally,
    badges: list[Badge],
    name_of: NameResolver,
    tz: ZoneInfo,
    periode_label: str,
    *,
    typical_arrival: str = "—",
    quote_count: int = 0,
    avatar_url: Optional[str] = None,
) -> discord.Embed:
    """Ét samlet kort med alt om en bruger."""
    navn = name_of(stats.user_id)
    streak = engine.streak(stats.user_id)
    embed = discord.Embed(title=f"🪪 {navn}", colour=FARVE)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    if stats.nights == 0:
        embed.description = "Ingen registreret deltagelse i den valgte periode."
        _footer(embed, periode_label)
        return embed

    embed.add_field(name="⏱️ Samlet tid", value=fmt_duration(stats.total_seconds), inline=True)
    embed.add_field(name="🍻 Torsdagsbarer", value=str(stats.nights), inline=True)
    embed.add_field(
        name="🔥 Streak",
        value=f"{streak.current} nu · {streak.longest} bedst",
        inline=True,
    )
    embed.add_field(name="🕒 Typisk ankomst", value=typical_arrival, inline=True)
    if stats.rank:
        embed.add_field(
            name="📊 Placering",
            value=f"#{stats.rank} af {stats.participants_in_period}",
            inline=True,
        )
    if stats.longest_single_seconds:
        embed.add_field(
            name="⌛ Længste enkeltdeltagelse",
            value=fmt_duration(stats.longest_single_seconds),
            inline=True,
        )

    # ⏳ Hvor længe man har ventet på selskab
    if tally.alone_seconds:
        værdi = fmt_duration(tally.alone_seconds)
        if tally.waiting:
            værdi += f" · vandt ⏳ {tally.waiting} gange"
        embed.add_field(name="⏳ Ventet på selskab", value=værdi, inline=True)

    # 🎯 Holdt hvad du lovede
    if tally.promised:
        embed.add_field(
            name="🎯 Holdt hvad du lovede",
            value=f"{tally.kept}/{tally.promised} torsdage ({tally.kept_pct:.0f} %)",
            inline=False,
        )

    # Titler – kun dem der faktisk er vundet.
    titler = [
        ("👑", "Aftenens konge", tally.king),
        ("🏃", "Marathonmand", tally.marathon),
        ("🐦", "Early Bird", tally.early_bird),
        ("🦉", "Lukkede baren", tally.closer),
        ("⚡", "Speedrun", tally.speedrun),
        ("🎭", "Surprise!", tally.surprise),
        ("⏳", "Waiting for players...", tally.waiting),
        ("🤥", "Store ord", tally.big_words),
        ("🐌", "Slow starter", tally.slow_starter),
    ]
    vundne = [f"{emoji} {navn_}: **{antal}**" for emoji, navn_, antal in titler if antal]
    if vundne:
        embed.add_field(name="🏅 Titler", value=" · ".join(vundne), inline=False)

    if badges:
        embed.add_field(
            name="🎖️ Badges",
            value="\n".join(f"{b.emoji} **{b.name}** — {b.description}" for b in badges),
            inline=False,
        )

    if quote_count:
        embed.add_field(name="💬 Citater", value=str(quote_count), inline=True)

    _footer(embed, periode_label)
    return embed


# ---------------------------------------------------------------------------
# 💬 Citat-bogen
# ---------------------------------------------------------------------------
def _quote_line(quote, name_of: NameResolver, tz: ZoneInfo, *, med_id: bool = True) -> str:
    dato = ""
    if quote.created_at:
        lokal = to_local(quote.created_at, tz)
        dato = f" · {lokal.strftime('%d-%m-%Y')}"
    tilføjet = f" · tilføjet af {name_of(quote.added_by)}" if quote.added_by else ""
    prefix = f"`#{quote.id}` " if med_id else ""
    return f"{prefix}*”{quote.text}”*{tilføjet}{dato}"


def quote_embed(quote, name_of: NameResolver, tz: ZoneInfo, *, titel: Optional[str] = None) -> discord.Embed:
    """Ét enkelt citat."""
    navn = name_of(quote.user_id)
    embed = discord.Embed(
        title=titel or f"💬 Citat — {navn}",
        description=f"*”{quote.text}”*\n\n— **{navn}**",
        colour=FARVE,
    )
    detaljer = []
    if quote.added_by:
        detaljer.append(f"Tilføjet af {name_of(quote.added_by)}")
    if quote.created_at:
        detaljer.append(to_local(quote.created_at, tz).strftime("%d-%m-%Y"))
    embed.set_footer(text=f"Citat #{quote.id}" + (" · " + " · ".join(detaljer) if detaljer else ""))
    return embed


def quotes_embed(
    quotes: list,
    user_id: int,
    name_of: NameResolver,
    tz: ZoneInfo,
    page: int,
    pages: int,
    per_page: int,
) -> discord.Embed:
    """Alle citater for én bruger, med sidetal."""
    navn = name_of(user_id)
    embed = discord.Embed(title=f"💬 Citat-bogen — {navn}", colour=FARVE)
    if not quotes:
        embed.description = f"Der er ingen citater gemt på {navn} endnu."
        embed.set_footer(text="Torsdagsbar · Tilføj et med /quote add")
        return embed

    start = page * per_page
    embed.description = "\n\n".join(
        _quote_line(q, name_of, tz) for q in quotes[start : start + per_page]
    )
    embed.set_footer(
        text=f"Torsdagsbar · {len(quotes)} citat(er) · Side {page + 1}/{pages}"
    )
    return embed
