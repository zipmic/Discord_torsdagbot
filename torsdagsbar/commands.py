"""Slash-kommandoen /torsdagsbar med alle underkommandoer.

Gruppen bygges med ``build_group(module)`` og tilføjes til klientens
CommandTree. Alle svar vises i pæne embeds; tunge opslag defer'es først.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dt_time
from typing import Optional

import discord
from discord import app_commands

from . import formatting as fmt
from .stats import SORT_KEYS

log = logging.getLogger("torsdagbot.torsdagsbar.commands")

# Valgmuligheder til perioder og sorteringer.
PERIODE_CHOICES = [
    app_commands.Choice(name="Sidste uge", value="sidste_uge"),
    app_commands.Choice(name="Denne måned", value="denne_måned"),
    app_commands.Choice(name="Sidste 3 måneder", value="sidste_3_måneder"),
    app_commands.Choice(name="Sidste 6 måneder", value="sidste_6_måneder"),
    app_commands.Choice(name="Hele perioden", value="hele_perioden"),
]

SORT_CHOICES = [
    app_commands.Choice(name="Samlet tid", value="tid"),
    app_commands.Choice(name="Antal torsdagsbarer", value="antal"),
    app_commands.Choice(name="Gennemsnitlig tid", value="gennemsnit"),
    app_commands.Choice(name="Nuværende streak", value="streak"),
    app_commands.Choice(name="Længste streak", value="længste_streak"),
    app_commands.Choice(name="Længste enkeltdeltagelse", value="længste_enkelt"),
]

KORRIGER_CHOICES = [
    app_commands.Choice(name="Tilføj tid", value="tilføj"),
    app_commands.Choice(name="Sæt samlet tid", value="sæt"),
    app_commands.Choice(name="Nulstil rettelser", value="nulstil"),
]


def _parse_date_arg(value: str) -> Optional[date]:
    try:
        return fmt.parse_date(value)
    except ValueError:
        return None


class LeaderboardView(discord.ui.View):
    """Blader-knapper til leaderboardet (næste/forrige side)."""

    def __init__(self, module, rows, sort_key, sort_label, periode_label, per_page):
        super().__init__(timeout=180)
        self.module = module
        self.rows = rows
        self.sort_key = sort_key
        self.sort_label = sort_label
        self.periode_label = periode_label
        self.per_page = per_page
        self.page = 0
        self.pages = max(1, (len(rows) + per_page - 1) // per_page)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.pages - 1

    def embed(self) -> discord.Embed:
        return fmt.leaderboard_embed(
            self.rows, self.module.name_of, self.sort_key, self.sort_label,
            self.periode_label, self.page, self.pages, self.per_page,
        )

    @discord.ui.button(label="◀ Forrige", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Næste ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.pages - 1, self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


def build_group(module) -> app_commands.Group:
    """Byg /torsdagsbar-gruppen bundet til et TorsdagsbarModule."""

    group = app_commands.Group(
        name="torsdagsbar",
        description="Statistik og registrering for torsdagsbaren.",
        guild_only=True,
    )

    async def deny_if_not_admin(interaction: discord.Interaction) -> bool:
        if module.is_admin(interaction):
            return True
        await interaction.response.send_message(
            "Denne kommando kræver administratorrettigheder eller den valgte rolle.",
            ephemeral=True,
        )
        log.info("Torsdagsbar: afvist admin-kommando fra %s (%s).",
                 interaction.user, interaction.user.id)
        return False

    # ------------------------------------------------------------------ stats
    @group.command(name="stats", description="Vis deltagelsesstatistik for dig selv eller en anden.")
    @app_commands.describe(bruger="Hvis bruger? (udelad = dig selv)", periode="Hvilken periode?")
    @app_commands.choices(periode=PERIODE_CHOICES)
    async def stats_cmd(
        interaction: discord.Interaction,
        bruger: Optional[discord.Member] = None,
        periode: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        periode_value = periode.value if periode else "hele_perioden"
        start, end, label = module.period_bounds(periode_value)
        target = bruger or interaction.user
        engine = await module.build_engine()
        stats = engine.user_stats(target.id, start, end)
        top = engine.leaderboard("tid", start, end, limit=10)
        embed = fmt.stats_embed(stats, engine, module.name_of, module.tz, label, top)
        await interaction.followup.send(embed=embed)

    # ----------------------------------------------------------------- streak
    @group.command(name="streak", description="Vis din (eller en andens) streak.")
    @app_commands.describe(bruger="Hvis streak? (udelad = dig selv)")
    async def streak_cmd(
        interaction: discord.Interaction,
        bruger: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        target = bruger or interaction.user
        engine = await module.build_engine()
        stats = engine.user_stats(target.id)
        embed = fmt.streak_embed(stats, engine, module.name_of, engine.active_streaks())
        await interaction.followup.send(embed=embed)

    # --------------------------------------------------------------- rekorder
    @group.command(name="rekorder", description="Vis rekorder for hele historikken eller en periode.")
    @app_commands.describe(periode="Afgræns til en periode (udelad = hele historikken)")
    @app_commands.choices(periode=PERIODE_CHOICES)
    async def rekorder_cmd(
        interaction: discord.Interaction,
        periode: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        periode_value = periode.value if periode else "hele_perioden"
        start, end, label = module.period_bounds(periode_value)
        engine = await module.build_engine()
        rec = engine.records(start, end)
        embed = fmt.records_embed(rec, engine, module.name_of, module.tz, label)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------- live
    @group.command(name="live", description="Vis den aktuelle status for torsdagsbaren.")
    async def live_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        status = await module.tracker.live_status()
        embed = _live_embed(module, status)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------ leaderboard
    @group.command(name="leaderboard", description="Vis ranglisten over deltagelse.")
    @app_commands.describe(sortering="Hvad skal der sorteres efter?", periode="Hvilken periode?")
    @app_commands.choices(sortering=SORT_CHOICES, periode=PERIODE_CHOICES)
    async def leaderboard_cmd(
        interaction: discord.Interaction,
        sortering: Optional[app_commands.Choice[str]] = None,
        periode: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        sort_key = sortering.value if sortering else "tid"
        sort_label = sortering.name if sortering else SORT_KEYS["tid"]
        periode_value = periode.value if periode else "hele_perioden"
        start, end, label = module.period_bounds(periode_value)
        engine = await module.build_engine()
        rows = engine.leaderboard(sort_key, start, end, limit=None)
        view = LeaderboardView(
            module, rows, sort_key, sort_label, label, module.config.leaderboard_size
        )
        await interaction.followup.send(embed=view.embed(), view=view if view.pages > 1 else None)

    # ----------------------------------------------------------- status (admin)
    @group.command(name="status", description="(Admin) Vis registreringens og databasens status.")
    async def status_cmd(interaction: discord.Interaction) -> None:
        if not await deny_if_not_admin(interaction):
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        status = await module.tracker.live_status()
        healthy = await asyncio.to_thread(module.db.healthy)
        now = module.tracker.now()
        embed = discord.Embed(title="🔧 Torsdagsbar — status", colour=fmt.FARVE)
        if status["active"]:
            embed.add_field(name="Registrering", value="🟢 Aktiv nu", inline=False)
            if status["online"]:
                linjer = [
                    f"- {o['name']} — {fmt.fmt_duration(o['seconds'])}"
                    for o in status["online"]
                ]
                embed.add_field(name="Registreres lige nu", value="\n".join(linjer), inline=False)
            else:
                embed.add_field(name="Registreres lige nu", value="Ingen i kanalerne.", inline=False)
        else:
            nxt = status["next_start"]
            embed.add_field(
                name="Registrering",
                value=f"⚪ Ikke aktiv. Næste: {nxt.strftime('%A %d-%m %H:%M')}",
                inline=False,
            )
        embed.add_field(name="Database", value="🟢 OK" if healthy else "🔴 Fejl", inline=True)
        næste_ops = module.next_summary_time(now)
        embed.add_field(
            name="Næste opsummering",
            value=næste_ops.strftime("%A %d-%m %H:%M"),
            inline=True,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------ opsummering (admin)
    @group.command(name="opsummering", description="(Admin) Vis eller gensend en opsummering for en dato.")
    @app_commands.describe(dato="Torsdagsdato ÅÅÅÅ-MM-DD", gensend="Send den i opsummeringskanalen?")
    async def opsummering_cmd(
        interaction: discord.Interaction,
        dato: str,
        gensend: bool = False,
    ) -> None:
        if not await deny_if_not_admin(interaction):
            return
        d = _parse_date_arg(dato)
        if d is None:
            await interaction.response.send_message(
                "Ugyldig dato. Brug formatet ÅÅÅÅ-MM-DD, fx 2026-05-14.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        if gensend:
            sent = await module.send_summary(d, force=True)
            besked = ("✅ Opsummeringen blev sendt i opsummeringskanalen."
                      if sent else "❌ Kunne ikke sende opsummeringen – tjek loggen.")
            await interaction.followup.send(besked, ephemeral=True)
        else:
            engine = await module.build_engine()
            ns = engine.night_summary(d.isoformat())
            embed = fmt.summary_embed(ns, module.name_of, module.tz,
                                      show_records=module.config.summary_show_records)
            await interaction.followup.send(
                content="Forhåndsvisning (kun dig). Brug `gensend:True` for at sende den offentligt.",
                embed=embed, ephemeral=True,
            )

    # -------------------------------------------------------- korriger (admin)
    @group.command(name="korriger", description="(Admin) Ret en brugers deltagelsestid for en dato.")
    @app_commands.describe(
        bruger="Hvilken bruger?",
        dato="Torsdagsdato ÅÅÅÅ-MM-DD",
        handling="Tilføj tid, sæt samlet tid, eller nulstil rettelser",
        minutter="Antal minutter (ikke nødvendigt ved 'nulstil')",
        begrundelse="Valgfri note",
    )
    @app_commands.choices(handling=KORRIGER_CHOICES)
    async def korriger_cmd(
        interaction: discord.Interaction,
        bruger: discord.Member,
        dato: str,
        handling: app_commands.Choice[str],
        minutter: Optional[int] = None,
        begrundelse: Optional[str] = None,
    ) -> None:
        if not await deny_if_not_admin(interaction):
            return
        d = _parse_date_arg(dato)
        if d is None:
            await interaction.response.send_message(
                "Ugyldig dato. Brug ÅÅÅÅ-MM-DD.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)

        await asyncio.to_thread(module.db.upsert_user, bruger.id, bruger.display_name)

        if handling.value == "nulstil":
            n = await asyncio.to_thread(module.db.clear_corrections, bruger.id, d)
            await interaction.followup.send(
                f"✅ Nulstillede {n} rettelse(r) for {bruger.display_name} den {dato}.",
                ephemeral=True,
            )
            log.info("Torsdagsbar: %s nulstillede rettelser for %s (%s).",
                     interaction.user, bruger.id, dato)
            return

        if minutter is None:
            await interaction.followup.send(
                "Angiv antal minutter for denne handling.", ephemeral=True
            )
            return

        if handling.value == "tilføj":
            delta = int(minutter) * 60
            await asyncio.to_thread(
                module.db.add_correction, bruger.id, d, delta, begrundelse, interaction.user.id
            )
            besked = f"✅ Tilføjede {minutter} minutter til {bruger.display_name} den {dato}."
        else:  # sæt samlet tid
            # Beregn nuværende total (sessioner + eksisterende rettelser) og lav
            # en delta, så totalen rammer det ønskede.
            sessions = await asyncio.to_thread(
                module.db.load_sessions, d.isoformat(), d.isoformat(), bruger.id, False
            )
            auto = sum(int(s.duration_seconds or 0) for s in sessions)
            corr = await asyncio.to_thread(module.db.correction_total, bruger.id, d.isoformat())
            current = auto + corr
            target = int(minutter) * 60
            delta = target - current
            await asyncio.to_thread(
                module.db.add_correction, bruger.id, d, delta, begrundelse or "sat manuelt",
                interaction.user.id,
            )
            besked = (
                f"✅ Satte {bruger.display_name}s samlede tid den {dato} til "
                f"{fmt.fmt_duration(target)} (justering: {delta // 60:+d} min)."
            )
        await interaction.followup.send(besked, ephemeral=True)
        log.info("Torsdagsbar: %s korrigerede %s (%s): %s.",
                 interaction.user, bruger.id, dato, handling.value)

    # ----------------------------------------------------------- aflys (admin)
    @group.command(name="aflys", description="(Admin) Markér en torsdag som aflyst (påvirker ikke streaks).")
    @app_commands.describe(dato="Torsdagsdato ÅÅÅÅ-MM-DD", fortryd="Fortryd en tidligere aflysning?", note="Valgfri note")
    async def aflys_cmd(
        interaction: discord.Interaction,
        dato: str,
        fortryd: bool = False,
        note: Optional[str] = None,
    ) -> None:
        if not await deny_if_not_admin(interaction):
            return
        d = _parse_date_arg(dato)
        if d is None:
            await interaction.response.send_message("Ugyldig dato. Brug ÅÅÅÅ-MM-DD.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        await asyncio.to_thread(module.db.set_cancelled, d, not fortryd, note)
        if fortryd:
            besked = f"✅ Aflysningen for {dato} er fortrudt – dagen tæller igen."
        else:
            besked = f"✅ {dato} er markeret som aflyst/ikke-statistikgivende."
        await interaction.followup.send(besked, ephemeral=True)
        log.info("Torsdagsbar: %s satte aflyst=%s for %s.", interaction.user, not fortryd, dato)

    # ------------------------------------------------------- genberegn (admin)
    @group.command(name="genberegn", description="(Admin) Genberegn statistik, streaks og rekorder.")
    async def genberegn_cmd(interaction: discord.Interaction) -> None:
        if not await deny_if_not_admin(interaction):
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        # Alt beregnes altid ud fra sessionerne, så "genberegn" bygger blot
        # motoren op igen og bekræfter, at tallene er konsistente.
        engine = await module.build_engine()
        antal_naetter = len(engine.counting_dates)
        antal_sessioner = len(engine.sessions)
        antal_brugere = len({s.user_id for s in engine.sessions})
        embed = discord.Embed(
            title="♻️ Genberegning færdig",
            description=(
                f"Statistik, streaks og rekorder er genberegnet ud fra de gemte sessioner.\n\n"
                f"- Sessioner: **{antal_sessioner}**\n"
                f"- Tællende torsdagsbarer: **{antal_naetter}**\n"
                f"- Unikke deltagere: **{antal_brugere}**"
            ),
            colour=fmt.FARVE,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        log.info("Torsdagsbar: %s kørte genberegn.", interaction.user)

    return group


def _live_embed(module, status: dict) -> discord.Embed:
    if not status["active"]:
        nxt = status["next_start"]
        embed = discord.Embed(
            title="Torsdagsbar — ikke aktiv",
            description=(
                "Der registreres ikke lige nu.\n\n"
                f"**Næste torsdagsbar:** {fmt.fmt_date(nxt.date())} "
                f"{fmt.fmt_clock(nxt, module.tz)}"
            ),
            colour=fmt.FARVE,
        )
        return embed

    linjer = []
    for o in status["online"]:
        linjer.append(f"- {o['name']} — {fmt.fmt_duration(o['seconds'])}")
    beskrivelse = "\n".join(linjer) if linjer else "Ingen sidder i kanalerne lige nu."
    embed = discord.Embed(title="🍻 Torsdagsbar live", description=beskrivelse, colour=fmt.FARVE)
    embed.add_field(name="Aktuelt online", value=str(status["current_count"]), inline=True)
    embed.add_field(name="Unikke deltagere i aften", value=str(status["unique_count"]), inline=True)
    embed.add_field(name="Samlet deltagelsestid", value=fmt.fmt_duration(status["total_seconds"]), inline=True)
    embed.set_footer(
        text=f"Registreringen slutter {fmt.fmt_clock(status['end'], module.tz)} "
        f"· {fmt.fmt_countdown(status['time_left'])} tilbage"
    )
    return embed
