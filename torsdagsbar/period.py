"""Ren tidslogik for torsdagsbaren.

Alt herinde er tidszone-korrekt (Europe/Copenhagen) og indeholder INGEN
discord- eller database-kald, så det kan testes helt for sig selv.

Grundbegreber:

  * En "torsdagsbar" identificeres ved sin **torsdagsdato** (den lokale dato for
    selve torsdagen), fx 2026-05-14.
  * Registreringsvinduet for torsdag D går fra D kl. 19:00 til (D+1) kl. 03:00
    lokal tid. Vinduet krydser altså midnat.
  * Fredagsopsummeringen hører til torsdagen umiddelbart før og sendes fredag
    kl. 12:00.

Tidspunkterne 19:00 og 03:00 rammer aldrig sommertidsskiftets "huller" (som
ligger omkring kl. 02:00-03:00), så almindelig wall-clock-beregning er sikker.
Selve varigheder måles altid i faktisk forløben tid (UTC), så den ekstra/
manglende time ved sommertidsskift håndteres automatisk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Optional

from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Schedule:
    """Indstillelige tidspunkter for registrering og opsummering."""

    tz: ZoneInfo
    weekday: int = 3  # 0 = mandag ... 3 = torsdag
    start_hour: int = 19
    start_minute: int = 0
    end_hour: int = 3
    end_minute: int = 0
    # Antal døgn fra torsdagen til sluttidspunktet (03:00 er dagen efter -> 1).
    end_day_offset: int = 1
    summary_weekday: int = 4  # fredag
    summary_hour: int = 12
    summary_minute: int = 0

    # ---- grundlæggende byggeklodser --------------------------------------
    def start_of(self, bar_date: date) -> datetime:
        """Registreringens starttidspunkt (lokal, tz-aware) for en torsdagsbar."""
        return datetime.combine(
            bar_date, dt_time(self.start_hour, self.start_minute), tzinfo=self.tz
        )

    def end_of(self, bar_date: date) -> datetime:
        """Registreringens sluttidspunkt (lokal, tz-aware) for en torsdagsbar."""
        return datetime.combine(
            bar_date + timedelta(days=self.end_day_offset),
            dt_time(self.end_hour, self.end_minute),
            tzinfo=self.tz,
        )

    def window_of(self, bar_date: date) -> tuple[datetime, datetime]:
        """(start, slut) som lokale, tz-aware datetimes."""
        return self.start_of(bar_date), self.end_of(bar_date)

    def summary_time_of(self, bar_date: date) -> datetime:
        """Hvornår fredagsopsummeringen for en given torsdagsbar skal sendes."""
        days = (self.summary_weekday - bar_date.weekday()) % 7
        if days == 0:
            days = 7  # opsummeringen er altid EFTER selve torsdagen
        return datetime.combine(
            bar_date + timedelta(days=days),
            dt_time(self.summary_hour, self.summary_minute),
            tzinfo=self.tz,
        )

    # ---- opslag ud fra et vilkårligt tidspunkt ---------------------------
    def current_bar_date(self, now: datetime) -> Optional[date]:
        """Hvilken torsdagsbar er aktiv lige nu? None hvis vi er udenfor vinduet.

        ``now`` skal være tz-aware. Bruger den konkrete lokale dato/klokkeslæt.
        """
        local = now.astimezone(self.tz)

        # Er "i dag" en torsdag, og er klokken forbi starttidspunktet?
        if local.weekday() == self.weekday:
            start = self.start_of(local.date())
            end = self.end_of(local.date())
            if start <= local < end:
                return local.date()

        # Er "i dag" dagen efter torsdag (fredag), og er klokken før slut?
        prev = local.date() - timedelta(days=self.end_day_offset)
        if prev.weekday() == self.weekday:
            start = self.start_of(prev)
            end = self.end_of(prev)
            if start <= local < end:
                return prev

        return None

    def is_active(self, now: datetime) -> bool:
        return self.current_bar_date(now) is not None

    def next_start(self, now: datetime) -> datetime:
        """Næste kommende starttidspunkt (lokal). Hvis vi er aktive lige nu,
        returneres NÆSTE uges start."""
        local = now.astimezone(self.tz)
        days_ahead = (self.weekday - local.weekday()) % 7
        candidate = self.start_of(local.date() + timedelta(days=days_ahead))
        if candidate <= local:
            candidate = self.start_of(local.date() + timedelta(days=days_ahead + 7))
        return candidate

    def most_recent_bar_date(self, now: datetime) -> date:
        """Den seneste torsdagsdato til og med i dag (uanset klokkeslæt)."""
        local = now.astimezone(self.tz)
        days_since = (local.weekday() - self.weekday) % 7
        return local.date() - timedelta(days=days_since)

    def due_summary_bar_date(
        self, now: datetime, catch_up_hours: int = 6
    ) -> Optional[date]:
        """Hvilken torsdagsbar skal der (måske) sendes opsummering for nu?

        Returnerer torsdagsdatoen hvis vi er inden for ``catch_up_hours`` efter
        det planlagte opsummeringstidspunkt – ellers None. Om den rent faktisk
        er sendt før, afgøres af databasen, ikke her.
        """
        # Kandidat: torsdagen der hører til den seneste passerede opsummering.
        local = now.astimezone(self.tz)
        # Kig tilbage på de seneste to torsdage for at være robust omkring skift.
        for weeks_back in (0, 1):
            bar_date = self.most_recent_bar_date(now) - timedelta(weeks=weeks_back)
            summary_at = self.summary_time_of(bar_date)
            if summary_at <= local <= summary_at + timedelta(hours=catch_up_hours):
                return bar_date
        return None


def to_utc(moment: datetime) -> datetime:
    """Konvertér et tz-aware tidspunkt til UTC (til lagring i databasen)."""
    if moment.tzinfo is None:
        raise ValueError("Tidspunktet skal være tz-aware før lagring.")
    return moment.astimezone(timezone.utc)


def clamp(moment: datetime, low: datetime, high: datetime) -> datetime:
    """Begræns et tidspunkt til intervallet [low, high]."""
    if moment < low:
        return low
    if moment > high:
        return high
    return moment
