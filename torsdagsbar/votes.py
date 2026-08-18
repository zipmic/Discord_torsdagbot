"""Stemmer fra den ugentlige afstemning.

Afstemningen sendes af hovedbotten (``bot.py``), men torsdagsbaren har brug for
at vide, *hvad* folk lovede, for at kunne lave "du er sent på den", 🎯 Holdt hvad
du lovede, 🤥 Store ord, 🐌 Slow starter og 🎭 Surprise!.

To veje ind i databasen:

  * **Knap-tilstand** – hovedbotten kalder direkte, hver gang der trykkes.
  * **Discords indbyggede poll** – stemmerne ligger kun hos Discord, så de hentes
    med ``PollAnswer.voters()`` og skrives i databasen (``sync_native_votes``).

For at undgå en cirkulær import (``bot.py`` importerer ``torsdagsbar``) definerer
denne fil ``VoteOption``: en neutral beskrivelse af en svarmulighed, som
hovedbotten oversætter sine ``POLL_OPTIONS`` til ved opstart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from typing import Optional, Sequence

from zoneinfo import ZoneInfo

log = logging.getLogger("torsdagbot.torsdagsbar.votes")


@dataclass(frozen=True)
class VoteOption:
    """En svarmulighed, som torsdagsbaren kan regne på.

    ``promise_start`` / ``promise_end`` er det tidsrum, brugeren lover at komme i.
    Er ``promise_end`` None, er løftet åbent ("efter 21:00") – så kan man ikke
    komme for sent, og der beregnes ingen forsinkelse.
    ``absent`` markerer "jeg kommer ikke".
    """

    key: str
    label: str
    promise_start: Optional[dt_time] = None
    promise_end: Optional[dt_time] = None
    absent: bool = False

    @property
    def has_deadline(self) -> bool:
        """Kan man komme for sent til dette valg?"""
        return not self.absent and self.promise_end is not None


def find_option(options: Sequence[VoteOption], key: str) -> Optional[VoteOption]:
    for option in options:
        if option.key == key:
            return option
    return None


def promise_window(
    option: VoteOption,
    bar_date: date,
    tz: ZoneInfo,
    window_start: datetime,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Løftets start og slut som konkrete tidspunkter for en given aften.

    Tidspunkter, der ligger før registreringsvinduets start, tolkes som "efter
    midnat" og lægges på dagen efter (så et løfte om fx 01:00 ikke havner
    12 timer for tidligt).
    """

    def concrete(t: Optional[dt_time]) -> Optional[datetime]:
        if t is None:
            return None
        moment = datetime.combine(bar_date, t, tzinfo=tz)
        if moment < window_start:
            moment += timedelta(days=1)
        return moment

    return concrete(option.promise_start), concrete(option.promise_end)


async def sync_native_votes(
    client,
    db,
    bar_date: date,
    options: Sequence[VoteOption],
    poll_ref: dict,
) -> int:
    """Hent stemmerne fra Discords indbyggede poll og gem dem.

    Returnerer antallet af gemte stemmer, eller -1 hvis beskeden ikke (længere)
    indeholder en poll. Kaster ikke – fejl logges og giver -1, så en midlertidig
    netværksfejl aldrig kan vælte tick-loopet.
    """
    try:
        channel = client.get_channel(poll_ref["channel_id"])
        if channel is None:
            channel = await client.fetch_channel(poll_ref["channel_id"])
        message = await channel.fetch_message(poll_ref["message_id"])
    except Exception as exc:
        log.warning("Kunne ikke hente afstemningsbeskeden til stemme-synk: %s", exc)
        return -1

    poll = getattr(message, "poll", None)
    if poll is None:
        return -1  # knap-tilstand: stemmerne kommer ind via on_button_vote

    # Match svar til svarmulighed på teksten, med rækkefølgen som reserve.
    by_label = {option.label: option.key for option in options}
    votes: dict[int, str] = {}
    try:
        for index, answer in enumerate(poll.answers):
            key = by_label.get(answer.text)
            if key is None and index < len(options):
                key = options[index].key
            if key is None:
                continue
            async for voter in answer.voters():
                if getattr(voter, "bot", False):
                    continue
                votes[voter.id] = key
    except Exception as exc:
        log.warning("Kunne ikke hente stemmer fra afstemningen: %s", exc)
        return -1

    db.replace_votes(bar_date, votes, source="native")
    log.debug("Stemme-synk for %s: %d stemmer.", bar_date.isoformat(), len(votes))
    return len(votes)
