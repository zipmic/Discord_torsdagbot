"""Dansk formatering og opbygning af Discord-embeds til torsdagsbaren.

Tidspunkter gemmes i UTC, men vises altid som dansk lokal tid her.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Optional

import discord
from zoneinfo import ZoneInfo

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
    "sidste_uge": "Sidste uge",
    "denne_måned": "Denne måned",
    "sidste_3_måneder": "Sidste 3 måneder",
    "sidste_6_måneder": "Sidste 6 måneder",
    "hele_perioden": "Hele perioden",
}


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


def summary_embed(
    ns: NightSummary,
    name_of: NameResolver,
    tz: ZoneInfo,
    *,
    show_records: bool = True,
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

    if show_records:
        ekstra = []
        if ns.top_user is not None:
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
