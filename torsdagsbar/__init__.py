"""Torsdagsbar – voice-registrering og statistik oven på TorsdagBot.

Pakken er en selvstændig udvidelse, der kobles ind i den eksisterende
``TorsdagBot``-klient. Den rører hverken den ugentlige afstemning eller nogen
af de eksisterende funktioner.

Ansvarsopdeling (så det er nemt at teste og vedligeholde):

  * ``period``     – ren tidslogik (registreringsvindue, bar-dato, DST).
  * ``database``   – SQLite-lag (skema, indekser, transaktioner). Ingen discord.
  * ``stats``      – genberegnelige beregninger (totaler, streaks, rekorder).
  * ``formatting`` – dansk formatering og opbygning af Discord-embeds.
  * ``tracker``    – lytter på voice-events og fører sessioner.
  * ``commands``   – /torsdagsbar-kommandogruppen.
  * ``config``     – indlæsning af indstillinger fra config.json/.env.
  * ``module``     – limer det hele sammen og kobler det på klienten.
"""

from .config import TorsdagsbarConfig, load_torsdagsbar_config
from .module import TorsdagsbarModule

__all__ = [
    "TorsdagsbarConfig",
    "load_torsdagsbar_config",
    "TorsdagsbarModule",
]
