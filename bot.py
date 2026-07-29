"""
TorsdagBot – automatisk ugentlig Discord-afstemning.

Botten sender hver torsdag kl. 15:00 (Europe/Copenhagen) en afstemning i en
bestemt kanal: "DET ER TORSDAG! Meld din ankost!!" – med svarmuligheder for,
hvornår man kommer online om aftenen.

Funktioner:
  * Bruger Discords indbyggede poll-funktion (discord.py >= 2.5) hvis den er
    tilgængelig – ellers falder den automatisk tilbage til knapper med
    persistente Views.
  * Tidszone-korrekt planlægning (sommer-/vintertid) via zoneinfo.
  * Sender kun én afstemning pr. torsdag – også ved genstart. Datoen gemmes i
    en lille JSON-fil ved siden af programmet/.exe-filen.
  * Ejerbeskyttet slash-kommando /testvote til test uden at vente til torsdag.
  * Automatisk genforbindelse og tydelig logning.

Alle stier (.env, config.json, state-fil, logfil) findes ud fra placeringen af
.exe-filen (når den er pakket med PyInstaller) – ikke ud fra terminalens
aktuelle mappe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Tidszone – zoneinfo er en del af standardbiblioteket fra Python 3.9.
# På Windows findes der ikke en systemtidszone-database, derfor kræves pakken
# "tzdata" (den ligger i requirements.txt og bundles af build.bat).
# ---------------------------------------------------------------------------
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - kun relevant på Python < 3.9
    print("Denne bot kræver Python 3.9 eller nyere (zoneinfo mangler).")
    raise

# ---------------------------------------------------------------------------
# Tredjeparts-afhængigheder med en venlig fejlbesked hvis de mangler.
# ---------------------------------------------------------------------------
try:
    import aiohttp
    import discord
    from discord import app_commands
    from discord.ext import tasks
    from dotenv import load_dotenv
except ImportError as exc:  # pragma: no cover
    print(
        "Manglende afhængighed: {0}\n"
        "Installer dem med:\n"
        "    python -m pip install -r requirements.txt".format(exc)
    )
    sys.exit(1)


APP_NAME = "TorsdagBot"
APP_VERSION = "1.0.0"

# Statefilens skema-version, så filen kan opgraderes senere uden at gå i stykker.
STATE_VERSION = 1

# Hvor mange gamle afstemninger vi maksimalt gemmer stemmer for.
MAX_STORED_POLLS = 25


# ===========================================================================
# 1. Filplacering (vigtigt for PyInstaller)
# ===========================================================================
def get_app_dir() -> Path:
    """Returnér mappen hvor .env, config.json, state og log skal ligge.

    * Når programmet er pakket med PyInstaller (sys.frozen), bruger vi mappen
      hvor .exe-filen ligger – IKKE sys._MEIPASS (den midlertidige udpaknings-
      mappe) og IKKE os.getcwd() (terminalens mappe).
    * Når vi kører som almindeligt Python-script, bruger vi mappen hvor bot.py
      ligger.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = get_app_dir()
ENV_FILE = APP_DIR / ".env"
CONFIG_FILE = APP_DIR / "config.json"
STATE_FILE = APP_DIR / "poll_state.json"
LOG_FILE = APP_DIR / "torsdagbot.log"

log = logging.getLogger("torsdagbot")


# ===========================================================================
# 2. Logning
# ===========================================================================
def setup_logging(level_name: str = "INFO") -> None:
    """Sæt logning op til både konsol og roterende logfil (UTF-8).

    Windows-konsollen bruger som standard en kodning der ikke kan vise
    danske tegn og emoji. Vi tvinger derfor UTF-8 på stdout/stderr, så
    logningen ikke fejler med UnicodeEncodeError.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            # Streamen kan være None eller ikke understøtte reconfigure.
            pass

    level = getattr(logging, level_name.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    # Fjern eventuelle tidligere handlers (fx ved genstart i samme proces).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        # Fx hvis mappen er skrivebeskyttet – vi fortsætter med konsol-logning.
        print(f"Kunne ikke oprette logfil ({LOG_FILE}): {exc}")

    # discord.py's egen logning: hold den lidt roligere end vores egen.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.WARNING)


# ===========================================================================
# 3. Afstemningens indhold
# ===========================================================================
@dataclass(frozen=True)
class PollOption:
    """Én svarmulighed i afstemningen."""

    key: str  # Stabilt id – bruges i custom_id og i state-filen.
    text: str  # Selve teksten.
    clock: str  # Ur-emoji (unicode) som står forrest i teksten.
    emoji_env: str = ""  # Valgfri server-emoji, sættes som EMOJI_<NAVN> i .env.

    @property
    def label(self) -> str:
        """Teksten på knappen / svarmuligheden i poll'en.

        Ur-emojien står i selve teksten, fordi unicode-emoji altid vises
        korrekt. Emoji-feltet på knappen bruges i stedet til en valgfri
        server-emoji (fx :clue:), som kun kan sendes med sit fulde ID.
        """
        return f"{self.clock} {self.text}"


POLL_QUESTION = "DET ER TORSDAG! Meld din ankost!!"

POLL_OPTIONS: tuple[PollOption, ...] = (
    PollOption("early", "Early Bird kl. 19:00–20:00", "🕖"),
    PollOption("t2000", "Mellem kl. 20:00–20:30", "🕗"),
    PollOption("t2030", "Mellem kl. 20:30–21:00", "🕣"),
    PollOption("e2100", "Efter 21:00 lol", "🕘", "clue"),
    PollOption("e2200", "Efter 22:00 lol", "🕙", "code"),
    PollOption("nope", "Jeg kommer ikke", "❌", "codeweiner"),
)

# Selve beskedteksten. @everyone står i "content", da det er den eneste måde
# Discord rent faktisk pinger alle på.
POLL_CONTENT = f"@everyone {POLL_QUESTION}"

# Server-emojis (fx :clue:) kan kun sendes af en bot i formen <:navn:id>.
CUSTOM_EMOJI_RE = re.compile(r"^<(a?):([A-Za-z0-9_]{2,32}):(\d{15,25})>$")

# Præfiks til knappernes custom_id. Skal være stabilt på tværs af genstarter,
# ellers virker persistente Views ikke.
CUSTOM_ID_PREFIX = "torsdagbot:vote:"


def option_by_key(key: str) -> Optional[PollOption]:
    for option in POLL_OPTIONS:
        if option.key == key:
            return option
    return None


def stemme_ord(antal: int) -> str:
    """Dansk ental/flertal for 'stemme'."""
    return "stemme" if antal == 1 else "stemmer"


def parse_custom_emoji(raw: str, navn: str) -> Optional[discord.PartialEmoji]:
    """Fortolk en emoji fra .env.

    Accepterer den fulde Discord-form ``<:clue:123456789012345678>`` (som man
    får ved at skrive ``\\:clue:`` i Discord) samt almindelige unicode-emoji.
    Alt andet ignoreres med en advarsel, så en tastefejl ikke forhindrer hele
    afstemningen i at blive sendt.
    """
    raw = raw.strip()
    if not raw:
        return None

    match = CUSTOM_EMOJI_RE.match(raw)
    if match:
        animeret, emoji_navn, emoji_id = match.groups()
        return discord.PartialEmoji(
            name=emoji_navn, id=int(emoji_id), animated=bool(animeret)
        )

    if raw.startswith(":") and raw.endswith(":"):
        log.warning(
            "EMOJI_%s er sat til %s. En bot kan ikke bruge :navn:-formen. "
            "Skriv \\%s i Discord (med backslash foran), tryk Enter, og kopiér "
            "den fulde form <:navn:id> ind i .env i stedet.",
            navn.upper(),
            raw,
            raw,
        )
        return None

    if len(raw) <= 8:  # Almindelig unicode-emoji, fx 🍺
        return discord.PartialEmoji(name=raw)

    log.warning("EMOJI_%s (%s) kunne ikke forstås som en emoji – springes over.", navn.upper(), raw)
    return None


# ===========================================================================
# 4. Konfiguration
# ===========================================================================
class ConfigError(Exception):
    """Rejses ved fejl i .env / config.json."""


@dataclass
class Config:
    token: str
    channel_id: int
    owner_id: Optional[int] = None
    guild_id: Optional[int] = None

    timezone_name: str = "Europe/Copenhagen"
    poll_weekday: int = 3  # 0 = mandag ... 3 = torsdag ... 6 = søndag
    poll_hour: int = 15
    poll_minute: int = 0

    # Hvor mange timer efter det planlagte tidspunkt botten stadig må sende en
    # "forsinket" afstemning (fx hvis computeren var slukket kl. 15:00).
    catch_up_hours: int = 6

    # Hvor ofte uret tjekkes (sekunder).
    check_interval_seconds: int = 20

    # "native" = Discords indbyggede poll, "buttons" = knapper med Views,
    # "auto" = native hvis biblioteket understøtter det, ellers knapper.
    poll_mode: str = "auto"

    # Hvor længe en indbygget Discord-poll er åben (timer, 1-168).
    poll_duration_hours: int = 8

    # Skal den automatiske ugentlige afstemning rent faktisk pinge @everyone?
    ping_everyone: bool = True

    # Skal /testvote pinge @everyone? Standard: nej (teksten er den samme,
    # men selve ping'et undertrykkes, så testen ikke forstyrrer serveren).
    test_ping_everyone: bool = False

    # Valgfrie server-emojis, fx {"clue": "<:clue:123456789012345678>"}.
    custom_emojis: dict[str, str] = field(default_factory=dict)

    log_level: str = "INFO"

    def poll_time(self) -> dt_time:
        return dt_time(hour=self.poll_hour, minute=self.poll_minute)


def _read_config_json() -> dict[str, Any]:
    """Læs config.json hvis den findes (valgfrit alternativ til .env)."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ConfigError(f"{CONFIG_FILE.name} skal indeholde et JSON-objekt.")
        # Nøgler gøres versalfølsomhedsuafhængige (CHANNEL_ID == channel_id).
        return {str(k).upper(): v for k, v in data.items()}
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{CONFIG_FILE.name} er ikke gyldig JSON: {exc}") from exc


def load_config() -> Config:
    """Læs konfiguration fra .env (primært) og config.json (sekundært)."""
    # override=False betyder at rigtige miljøvariabler vinder over .env-filen.
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)
        log.info("Læste indstillinger fra %s", ENV_FILE)
    else:
        log.warning("Ingen .env-fil fundet i %s", APP_DIR)

    json_config = _read_config_json()
    if json_config:
        log.info("Læste indstillinger fra %s", CONFIG_FILE)

    def get_raw(key: str) -> Optional[str]:
        value = os.getenv(key)
        if value is None and key in json_config and json_config[key] is not None:
            value = str(json_config[key])
        if value is None:
            return None
        value = value.strip().strip('"').strip("'")
        return value or None

    def get_int(key: str, default: Optional[int] = None) -> Optional[int]:
        raw = get_raw(key)
        if raw is None:
            return default
        # Tillad fx "1234567890  # min kanal" og tusindtalsseparatorer.
        cleaned = raw.split("#", 1)[0].strip().replace("_", "").replace(" ", "")
        try:
            return int(cleaned)
        except ValueError as exc:
            raise ConfigError(
                f"{key} skal være et helt tal (Discord-ID), men var: {raw!r}"
            ) from exc

    def get_bool(key: str, default: bool) -> bool:
        raw = get_raw(key)
        if raw is None:
            return default
        return raw.lower() in {"1", "true", "yes", "ja", "y", "on"}

    # --- Token: MÅ kun komme fra miljø/.env – aldrig fra kildekoden. -------
    token = os.getenv("DISCORD_TOKEN")
    token = token.strip().strip('"').strip("'") if token else None
    if not token or token.lower().startswith("indsæt") or token.lower().startswith("indsaet"):
        raise ConfigError(
            "DISCORD_TOKEN mangler.\n"
            f"Opret filen  {ENV_FILE}  (kopiér .env.example) og indsæt bottens token.\n"
            "Tokenet skal stå i .env – aldrig i kildekoden."
        )

    channel_id = get_int("CHANNEL_ID")
    if not channel_id:
        raise ConfigError(
            "CHANNEL_ID mangler.\n"
            f"Angiv kanalens ID i {ENV_FILE} eller i {CONFIG_FILE}.\n"
            "Se README.md for hvordan du kopierer et kanal-ID (Developer Mode)."
        )

    owner_id = get_int("OWNER_ID")
    if owner_id is None:
        log.warning(
            "OWNER_ID er ikke sat – /testvote vil være deaktiveret indtil du "
            "tilføjer dit eget bruger-ID i .env."
        )

    weekday = get_int("POLL_WEEKDAY", 3) or 0
    if not 0 <= weekday <= 6:
        raise ConfigError("POLL_WEEKDAY skal være 0-6 (0 = mandag, 3 = torsdag).")

    hour = get_int("POLL_HOUR", 15) or 0
    minute = get_int("POLL_MINUTE", 0) or 0
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ConfigError("POLL_HOUR skal være 0-23 og POLL_MINUTE 0-59.")

    duration = get_int("POLL_DURATION_HOURS", 8) or 8
    duration = max(1, min(duration, 168))  # Discord tillader 1 time - 7 dage.

    catch_up = get_int("CATCH_UP_HOURS", 6)
    catch_up = 6 if catch_up is None else max(0, min(catch_up, 24))

    interval = get_int("CHECK_INTERVAL_SECONDS", 20) or 20
    interval = max(5, min(interval, 300))

    poll_mode = (get_raw("POLL_MODE") or "auto").lower()
    if poll_mode not in {"auto", "native", "buttons"}:
        raise ConfigError("POLL_MODE skal være 'auto', 'native' eller 'buttons'.")

    # Valgfrie server-emojis: EMOJI_CLUE, EMOJI_CODE, EMOJI_CODEWEINER ...
    custom_emojis: dict[str, str] = {}
    for option in POLL_OPTIONS:
        if not option.emoji_env:
            continue
        værdi = get_raw(f"EMOJI_{option.emoji_env.upper()}")
        if værdi:
            custom_emojis[option.emoji_env] = værdi

    return Config(
        token=token,
        channel_id=channel_id,
        owner_id=owner_id,
        guild_id=get_int("GUILD_ID"),
        timezone_name=get_raw("TIMEZONE") or "Europe/Copenhagen",
        poll_weekday=weekday,
        poll_hour=hour,
        poll_minute=minute,
        catch_up_hours=catch_up,
        check_interval_seconds=interval,
        poll_mode=poll_mode,
        poll_duration_hours=duration,
        ping_everyone=get_bool("PING_EVERYONE", True),
        test_ping_everyone=get_bool("TEST_PING_EVERYONE", False),
        custom_emojis=custom_emojis,
        log_level=(get_raw("LOG_LEVEL") or "INFO").upper(),
    )


def load_timezone(name: str) -> ZoneInfo:
    """Hent tidszonen med en tydelig fejl hvis tzdata mangler (Windows)."""
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(
            f"Tidszonen '{name}' kunne ikke findes.\n"
            "På Windows kræver Python en tidszone-database. Installer den med:\n"
            "    python -m pip install tzdata"
        ) from exc


# ===========================================================================
# 5. State (huskes på disken ved siden af .exe-filen)
# ===========================================================================
@dataclass
class StateStore:
    """Lille JSON-baseret 'database' med seneste afstemningsdato og stemmer."""

    path: Path
    data: dict[str, Any] = field(default_factory=dict)

    # --- indlæsning / gemning ---------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            self.data = {"version": STATE_VERSION, "last_poll_date": None, "polls": {}}
            log.info("Ingen state-fil endnu – opretter ny ved %s", self.path)
            return
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("state-filen indeholder ikke et JSON-objekt")
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            # Ødelagt fil: tag en backup og start forfra, så botten stadig kører.
            backup = self.path.with_suffix(".corrupt.json")
            log.error("Kunne ikke læse %s (%s). Gemmer backup som %s.", self.path, exc, backup)
            try:
                self.path.replace(backup)
            except OSError:
                pass
            self.data = {"version": STATE_VERSION, "last_poll_date": None, "polls": {}}
            return

        data.setdefault("version", STATE_VERSION)
        data.setdefault("last_poll_date", None)
        data.setdefault("polls", {})
        if not isinstance(data["polls"], dict):
            data["polls"] = {}
        self.data = data
        log.info(
            "State indlæst fra %s (seneste afstemning: %s)",
            self.path,
            self.data.get("last_poll_date") or "ingen",
        )

    def save(self) -> None:
        """Skriv state atomisk (skriv til temp-fil, byt derefter om)."""
        tmp = self.path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.error("Kunne ikke gemme state-filen %s: %s", self.path, exc)

    async def save_async(self) -> None:
        """Gem uden at blokere event-loopet."""
        await asyncio.to_thread(self.save)

    # --- ugentlig afstemning ----------------------------------------------
    @property
    def last_poll_date(self) -> Optional[str]:
        value = self.data.get("last_poll_date")
        return value if isinstance(value, str) else None

    def mark_poll_done(self, day: date, status: str = "sent") -> None:
        self.data["last_poll_date"] = day.isoformat()
        self.data["last_poll_status"] = status
        self.data["last_poll_marked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    # --- stemmer (kun nødvendigt i knap-tilstand) --------------------------
    def get_poll(self, message_id: int) -> Optional[dict[str, Any]]:
        poll = self.data.get("polls", {}).get(str(message_id))
        return poll if isinstance(poll, dict) else None

    def ensure_poll(self, message_id: int, channel_id: int, is_test: bool = False) -> dict[str, Any]:
        """Hent eller opret stemme-posten for en besked."""
        polls: dict[str, Any] = self.data.setdefault("polls", {})
        key = str(message_id)
        poll = polls.get(key)
        if not isinstance(poll, dict):
            poll = {
                "channel_id": channel_id,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "is_test": is_test,
                "votes": {},
            }
            polls[key] = poll
            self._prune()
        if not isinstance(poll.get("votes"), dict):
            poll["votes"] = {}
        return poll

    def _prune(self) -> None:
        """Behold kun de nyeste MAX_STORED_POLLS afstemninger."""
        polls: dict[str, Any] = self.data.get("polls", {})
        if len(polls) <= MAX_STORED_POLLS:
            return
        # Beskeds-ID'er i Discord er snowflakes og stiger over tid – sortér på dem.
        for key in sorted(polls, key=lambda k: int(k) if k.isdigit() else 0)[:-MAX_STORED_POLLS]:
            polls.pop(key, None)


# ===========================================================================
# 6. Visning af resultatet (knap-tilstand)
# ===========================================================================
def count_votes(votes: dict[str, str]) -> dict[str, int]:
    counts = {option.key: 0 for option in POLL_OPTIONS}
    for key in votes.values():
        if key in counts:
            counts[key] += 1
    return counts


def build_result_embed(
    votes: dict[str, str],
    emojis: Optional[dict[str, Optional[discord.PartialEmoji]]] = None,
) -> discord.Embed:
    """Byg embed'en der viser svarmuligheder og antal stemmer.

    ``emojis`` er de valgfrie server-emojis pr. svarmulighed. De vises kun her
    i embed'en, hvor Discord altid gengiver dem korrekt.
    """
    counts = count_votes(votes)
    total = sum(counts.values())
    emojis = emojis or {}

    lines: list[str] = []
    for option in POLL_OPTIONS:
        antal = counts[option.key]
        andel = (antal / total * 100) if total else 0.0
        fyldt = round(andel / 10)
        bar = "▰" * fyldt + "▱" * (10 - fyldt)
        ekstra = emojis.get(option.key)
        lines.append(
            f"**{option.label}**{f' {ekstra}' if ekstra else ''}\n"
            f"`{bar}`  {antal} {stemme_ord(antal)} · {andel:.0f}%"
        )

    embed = discord.Embed(
        title=POLL_QUESTION,
        description="\n\n".join(lines),
        colour=discord.Colour.blurple(),
    )
    embed.set_footer(
        text=f"{total} {stemme_ord(total)} i alt · Tryk på en knap for at stemme "
        f"– du kan altid skifte svar."
    )
    return embed


class VoteButton(discord.ui.Button["PollView"]):
    """Én knap i afstemningen. custom_id er statisk, så View'et er persistent."""

    def __init__(self, bot: "TorsdagBot", option: PollOption, row: int = 0) -> None:
        super().__init__(
            label=option.label,
            emoji=bot.custom_emoji_for(option),
            style=discord.ButtonStyle.secondary,
            custom_id=f"{CUSTOM_ID_PREFIX}{option.key}",
            row=row,
        )
        self.bot = bot
        self.option = option

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bot.handle_vote(interaction, self.option)


class PollView(discord.ui.View):
    """Persistent View – timeout=None og faste custom_id'er.

    Ét enkelt View-objekt registreret med Client.add_view() håndterer ALLE
    afstemningsbeskeder, fordi knapperne genkendes på deres custom_id.
    Stemmerne slås op ud fra beskedens ID i state-filen.
    """

    # Antal knapper pr. række (Discord tillader højst 5).
    BUTTONS_PER_ROW = 3

    def __init__(self, bot: "TorsdagBot") -> None:
        super().__init__(timeout=None)
        for index, option in enumerate(POLL_OPTIONS):
            # Fordel knapperne jævnt på rækker, så de står pænt (3 + 3).
            self.add_item(VoteButton(bot, option, row=index // self.BUTTONS_PER_ROW))


# ===========================================================================
# 7. Selve botten
# ===========================================================================
class TorsdagBot(discord.Client):
    def __init__(self, config: Config, state: StateStore, tz: ZoneInfo) -> None:
        # Ingen privilegerede intents er nødvendige: botten læser ikke beskeder,
        # den sender kun beskeder og modtager interaktioner.
        intents = discord.Intents.default()
        intents.message_content = False
        intents.members = False
        intents.presences = False

        super().__init__(intents=intents)

        self.config = config
        self.state = state
        self.tz = tz
        self.tree = app_commands.CommandTree(self)

        self._state_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._retry_not_before: Optional[datetime] = None
        self._ready_logged = False
        self._emoji_cache: dict[str, Optional[discord.PartialEmoji]] = {}

        self._register_commands()

    # -- opstart ------------------------------------------------------------
    async def setup_hook(self) -> None:
        """Kaldes én gang inden botten forbinder til gateway'en."""
        # Registrér det persistente View, så knapper fra tidligere beskeder
        # stadig virker efter en genstart af botten.
        self.add_view(PollView(self))
        log.info("Persistent View registreret (knapper virker efter genstart).")

        # Synkronisér slash-kommandoer.
        try:
            if self.config.guild_id:
                guild = discord.Object(id=self.config.guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Slash-kommandoer synkroniseret til server %s.", self.config.guild_id)
            else:
                await self.tree.sync()
                log.info(
                    "Slash-kommandoer synkroniseret globalt "
                    "(kan tage op til en time før /testvote er synlig – "
                    "sæt GUILD_ID i .env for øjeblikkelig opdatering)."
                )
        except discord.HTTPException as exc:
            log.error("Kunne ikke synkronisere slash-kommandoer: %s", exc)

        self.scheduler_loop.start()

    async def on_ready(self) -> None:
        # on_ready kan blive kaldt flere gange (efter reconnect).
        log.info("Logget ind som %s (ID: %s)", self.user, getattr(self.user, "id", "?"))
        if not self._ready_logged:
            self._ready_logged = True
            log.info("%s v%s – programmappe: %s", APP_NAME, APP_VERSION, APP_DIR)
            log.info(
                "Planlagt afstemning: hver %s kl. %02d:%02d (%s)",
                ugedag_navn(self.config.poll_weekday),
                self.config.poll_hour,
                self.config.poll_minute,
                self.config.timezone_name,
            )
            log.info("Næste planlagte afstemning: %s", self._format_next_run())

        await self._check_channel_and_permissions()

    async def close(self) -> None:
        """Stop planlæggeren pænt, så den ikke kører videre på en lukket klient."""
        if self.scheduler_loop.is_running():
            self.scheduler_loop.cancel()
        await super().close()

    async def on_connect(self) -> None:
        log.info("Forbundet til Discord.")

    async def on_disconnect(self) -> None:
        log.warning("Forbindelsen til Discord blev afbrudt – forsøger at genoprette ...")

    async def on_resumed(self) -> None:
        log.info("Forbindelsen til Discord er genoprettet.")

    async def on_error(self, event_method: str, /, *args: Any, **kwargs: Any) -> None:
        log.exception("Uventet fejl i event '%s'", event_method)

    # -- hjælpefunktioner ---------------------------------------------------
    def now(self) -> datetime:
        return datetime.now(self.tz)

    def _next_run(self, reference: Optional[datetime] = None) -> datetime:
        """Beregn næste planlagte afstemningstidspunkt i lokal tid."""
        now = reference or self.now()
        target_time = self.config.poll_time()
        days_ahead = (self.config.poll_weekday - now.weekday()) % 7
        candidate = datetime.combine(
            now.date() + timedelta(days=days_ahead), target_time, tzinfo=self.tz
        )
        if candidate <= now:
            candidate = datetime.combine(
                now.date() + timedelta(days=days_ahead + 7), target_time, tzinfo=self.tz
            )
        return candidate

    def _format_next_run(self) -> str:
        nxt = self._next_run()
        return nxt.strftime("%A %d-%m-%Y kl. %H:%M %Z")

    async def _resolve_channel(self) -> discord.abc.Messageable:
        """Find kanalen og giv tydelige fejl hvis noget er galt."""
        channel = self.get_channel(self.config.channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(self.config.channel_id)
            except discord.NotFound as exc:
                raise RuntimeError(
                    f"Kanalen med ID {self.config.channel_id} findes ikke. "
                    "Kontrollér CHANNEL_ID i .env (husk Developer Mode → Kopiér kanal-ID)."
                ) from exc
            except discord.Forbidden as exc:
                raise RuntimeError(
                    f"Botten har ikke adgang til kanalen {self.config.channel_id}. "
                    "Giv botten rettigheden 'Vis kanal' (View Channel) i kanalens indstillinger."
                ) from exc
            except discord.HTTPException as exc:
                raise RuntimeError(f"Discord-fejl ved opslag af kanalen: {exc}") from exc

        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            raise RuntimeError(
                f"Kanal {self.config.channel_id} er ikke en tekstkanal "
                f"(type: {type(channel).__name__}). Vælg en almindelig tekstkanal."
            )
        return channel

    async def _check_channel_and_permissions(self) -> None:
        """Log tydeligt hvis kanalen mangler, eller rettigheder ikke er nok."""
        try:
            channel = await self._resolve_channel()
        except RuntimeError as exc:
            log.error("KANALFEJL: %s", exc)
            return

        guild_me = getattr(getattr(channel, "guild", None), "me", None)
        if guild_me is None:
            log.warning("Kunne ikke slå bottens rettigheder op i kanalen.")
            return

        perms = channel.permissions_for(guild_me)
        log.info("Kanal fundet: #%s (server: %s)", channel, channel.guild)

        mangler = [
            navn
            for navn, ok in (
                ("Vis kanal (View Channel)", perms.view_channel),
                ("Send beskeder (Send Messages)", perms.send_messages),
                ("Indlejre links (Embed Links)", perms.embed_links),
            )
            if not ok
        ]
        if mangler:
            log.error("MANGLENDE RETTIGHEDER i #%s: %s", channel, ", ".join(mangler))
        if not perms.mention_everyone:
            log.warning(
                "Botten mangler rettigheden 'Nævn @everyone' (Mention Everyone) i #%s. "
                "Beskeden sendes stadig, men @everyone vil ikke give en notifikation.",
                channel,
            )
        if isinstance(channel, discord.Thread) and channel.archived:
            log.warning("Tråden #%s er arkiveret – beskeder kan fejle.", channel)

    # -- afsendelse af afstemningen ----------------------------------------
    def custom_emoji_for(self, option: PollOption) -> Optional[discord.PartialEmoji]:
        """Slå den valgfrie server-emoji op for en svarmulighed.

        Findes emojien ikke på serveren (fx forkert ID i .env), springes den
        over med en advarsel, så afstemningen stadig kan sendes.
        """
        if not option.emoji_env:
            return None
        if option.key in self._emoji_cache:
            return self._emoji_cache[option.key]

        raw = self.config.custom_emojis.get(option.emoji_env)
        emoji = parse_custom_emoji(raw, option.emoji_env) if raw else None

        if emoji is None or emoji.id is None:
            # Ikke sat, ugyldig, eller en almindelig unicode-emoji: resultatet
            # kan ikke ændre sig, så det gemmes med det samme.
            self._emoji_cache[option.key] = emoji
            return emoji

        if not self.is_ready():
            # Serverens emoji-liste er ikke hentet endnu (fx når det persistente
            # View oprettes i setup_hook). Gem ikke resultatet endnu.
            return emoji

        if self.get_emoji(emoji.id) is None:
            log.warning(
                "Server-emojien %s (EMOJI_%s) blev ikke fundet – botten skal være "
                "medlem af den server, emojien hører til. Springer den over.",
                raw,
                option.emoji_env.upper(),
            )
            emoji = None

        self._emoji_cache[option.key] = emoji
        return emoji

    def option_emojis(self) -> dict[str, Optional[discord.PartialEmoji]]:
        """Alle valgfrie server-emojis, klar til brug i embed'en."""
        return {option.key: self.custom_emoji_for(option) for option in POLL_OPTIONS}

    def _native_poll_supported(self) -> bool:
        """Understøtter det installerede discord.py Discords indbyggede polls?"""
        return hasattr(discord, "Poll") and hasattr(discord.Poll, "add_answer")

    def _build_native_poll(self) -> "discord.Poll":
        poll = discord.Poll(
            question=POLL_QUESTION,
            duration=timedelta(hours=self.config.poll_duration_hours),
            multiple=False,  # Hver person kan kun have ét aktivt svar.
        )
        for option in POLL_OPTIONS:
            # Ur-emojien ligger i teksten; emoji-feltet bruges til server-emojien.
            poll.add_answer(text=option.label, emoji=self.custom_emoji_for(option))
        return poll

    async def send_poll(self, *, is_test: bool = False) -> discord.Message:
        """Send afstemningen til den konfigurerede kanal.

        Bruger Discords indbyggede poll hvis muligt, ellers knapper.
        Rejser RuntimeError med en læsbar besked ved fejl.
        """
        async with self._send_lock:
            channel = await self._resolve_channel()

            ping = self.config.test_ping_everyone if is_test else self.config.ping_everyone
            allowed = discord.AllowedMentions(
                everyone=ping, users=False, roles=False, replied_user=False
            )
            content = POLL_CONTENT
            if is_test:
                content += "\n_(test – ændrer ikke den ugentlige afstemning)_"

            brug_native = self.config.poll_mode in {"auto", "native"} and self._native_poll_supported()
            if self.config.poll_mode == "native" and not brug_native:
                log.warning(
                    "POLL_MODE=native, men det installerede discord.py understøtter ikke "
                    "indbyggede polls (kræver discord.py 2.5+). Bruger knapper i stedet."
                )

            if brug_native:
                try:
                    message = await channel.send(
                        content=content,
                        poll=self._build_native_poll(),
                        allowed_mentions=allowed,
                    )
                    log.info(
                        "Afstemning oprettet med Discords indbyggede poll "
                        "(besked-ID %s, kanal #%s%s).",
                        message.id,
                        channel,
                        ", test" if is_test else "",
                    )
                    return message
                except (TypeError, AttributeError) as exc:
                    # Biblioteket understøtter alligevel ikke poll-parameteren.
                    log.warning("Indbygget poll kunne ikke bruges (%s) – falder tilbage til knapper.", exc)
                except discord.HTTPException as exc:
                    log.warning(
                        "Discord afviste den indbyggede poll (%s) – falder tilbage til knapper.",
                        exc,
                    )

            # --- Knap-tilstand (persistente Views) ---------------------------
            try:
                message = await channel.send(
                    content=content,
                    embed=build_result_embed({}, self.option_emojis()),
                    view=PollView(self),
                    allowed_mentions=allowed,
                )
            except discord.Forbidden as exc:
                raise RuntimeError(
                    f"Botten mangler rettigheder til at skrive i #{channel}. "
                    "Giv den 'Send beskeder' og 'Indlejre links' (og 'Nævn @everyone')."
                ) from exc
            except discord.HTTPException as exc:
                raise RuntimeError(f"Discord-fejl ved afsendelse af afstemningen: {exc}") from exc

            async with self._state_lock:
                self.state.ensure_poll(message.id, channel.id, is_test=is_test)
                await self.state.save_async()

            log.info(
                "Afstemning oprettet med knapper (besked-ID %s, kanal #%s%s).",
                message.id,
                channel,
                ", test" if is_test else "",
            )
            return message

    # -- stemmehåndtering (knap-tilstand) ----------------------------------
    async def handle_vote(self, interaction: discord.Interaction, option: PollOption) -> None:
        """Registrér en brugers stemme og opdatér beskeden."""
        message = interaction.message
        if message is None:  # Bør ikke ske for komponent-interaktioner.
            await interaction.response.send_message(
                "Kunne ikke finde afstemningen. Prøv igen.", ephemeral=True
            )
            return

        user_id = str(interaction.user.id)
        try:
            async with self._state_lock:
                poll = self.state.ensure_poll(message.id, message.channel.id)
                votes: dict[str, str] = poll["votes"]
                tidligere = votes.get(user_id)
                if tidligere == option.key:
                    besked = f"Dit svar er stadig: **{option.label}**"
                elif tidligere is None:
                    besked = f"Tak! Dit svar er registreret: **{option.label}**"
                else:
                    gammel = option_by_key(tidligere)
                    besked = (
                        f"Dit svar er ændret fra **{gammel.label if gammel else tidligere}** "
                        f"til **{option.label}**"
                    )
                votes[user_id] = option.key
                snapshot = dict(votes)
                await self.state.save_async()

            # Kort, privat bekræftelse til brugeren.
            await interaction.response.send_message(besked, ephemeral=True)

            # Opdatér stemmetallene i den offentlige besked.
            try:
                await message.edit(embed=build_result_embed(snapshot, self.option_emojis()))
            except discord.Forbidden:
                log.error("Kunne ikke opdatere afstemningen – manglende rettigheder.")
            except discord.HTTPException as exc:
                log.error("Kunne ikke opdatere afstemningen: %s", exc)

            log.info(
                "Stemme registreret: %s (%s) → %s [besked %s]",
                interaction.user,
                interaction.user.id,
                option.label,
                message.id,
            )
        except Exception:
            log.exception("Fejl under registrering af stemme")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Noget gik galt – din stemme blev måske ikke gemt. Prøv igen.",
                    ephemeral=True,
                )

    # -- planlægning --------------------------------------------------------
    @tasks.loop(seconds=20)
    async def scheduler_loop(self) -> None:
        """Tjekker uret løbende og sender afstemningen når tiden er inde.

        Sender højst én gang pr. torsdag – også hvis botten genstartes.
        Hvis botten var slukket kl. 15:00, sendes afstemningen ved opstart,
        så længe der er gået mindre end CATCH_UP_HOURS timer.
        """
        try:
            now = self.now()

            if now.weekday() != self.config.poll_weekday:
                return

            i_dag = now.date().isoformat()
            if self.state.last_poll_date == i_dag:
                return  # Allerede sendt (eller bevidst sprunget over) i dag.

            planlagt = datetime.combine(now.date(), self.config.poll_time(), tzinfo=self.tz)
            if now < planlagt:
                return  # Endnu ikke tid.

            forsinkelse = now - planlagt
            if forsinkelse > timedelta(hours=self.config.catch_up_hours):
                log.warning(
                    "Afstemningen for %s blev ikke sendt: botten startede %.1f timer efter "
                    "det planlagte tidspunkt (CATCH_UP_HOURS=%d). Springer over til næste uge.",
                    i_dag,
                    forsinkelse.total_seconds() / 3600,
                    self.config.catch_up_hours,
                )
                async with self._state_lock:
                    self.state.mark_poll_done(now.date(), status="skipped_late")
                    await self.state.save_async()
                return

            # Efter en fejl venter vi lidt før vi prøver igen.
            if self._retry_not_before and now < self._retry_not_before:
                return

            if forsinkelse > timedelta(minutes=2):
                log.info(
                    "Sender forsinket afstemning for %s (%.0f minutter efter planlagt tid).",
                    i_dag,
                    forsinkelse.total_seconds() / 60,
                )
            else:
                log.info("Tid til den ugentlige afstemning (%s).", i_dag)

            try:
                await self.send_poll(is_test=False)
            except RuntimeError as exc:
                self._retry_not_before = now + timedelta(minutes=5)
                log.error("Afstemningen kunne ikke sendes: %s (prøver igen om 5 minutter)", exc)
                return
            except discord.DiscordException:
                self._retry_not_before = now + timedelta(minutes=5)
                log.exception("Discord-fejl under afsendelse (prøver igen om 5 minutter)")
                return

            async with self._state_lock:
                self.state.mark_poll_done(now.date(), status="sent")
                await self.state.save_async()
            self._retry_not_before = None
            log.info("Næste planlagte afstemning: %s", self._format_next_run())

        except Exception:
            # Loopet må aldrig dø – ellers stopper den ugentlige afstemning.
            log.exception("Uventet fejl i planlæggeren")

    @scheduler_loop.before_loop
    async def before_scheduler(self) -> None:
        await self.wait_until_ready()
        log.info("Planlæggeren er startet (tjekker uret hvert %d. sekund).", self.config.check_interval_seconds)

    # -- slash-kommandoer ---------------------------------------------------
    def _register_commands(self) -> None:
        @self.tree.command(
            name="testvote",
            description="Opret afstemningen med det samme (kun for bottens ejer).",
        )
        async def testvote(interaction: discord.Interaction) -> None:
            # Ejer-tjek: kun brugeren med OWNER_ID må bruge kommandoen.
            if self.config.owner_id is None:
                await interaction.response.send_message(
                    "OWNER_ID er ikke sat i .env, så kommandoen er deaktiveret.",
                    ephemeral=True,
                )
                return
            if interaction.user.id != self.config.owner_id:
                log.warning(
                    "Afvist /testvote fra %s (%s) – ikke ejeren.",
                    interaction.user,
                    interaction.user.id,
                )
                await interaction.response.send_message(
                    "Kun bottens ejer må bruge denne kommando.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True, thinking=True)
            log.info("/testvote kørt af ejeren %s (%s).", interaction.user, interaction.user.id)
            try:
                # is_test=True: rører IKKE datoen for den ugentlige afstemning.
                message = await self.send_poll(is_test=True)
            except RuntimeError as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                log.error("/testvote fejlede: %s", exc)
                return
            except discord.DiscordException as exc:
                await interaction.followup.send(f"❌ Discord-fejl: {exc}", ephemeral=True)
                log.exception("/testvote fejlede med en Discord-fejl")
                return

            await interaction.followup.send(
                f"✅ Testafstemning oprettet: {message.jump_url}\n"
                "Den ugentlige afstemning er uændret.",
                ephemeral=True,
            )

        @self.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction, error: app_commands.AppCommandError
        ) -> None:
            log.exception("Fejl i slash-kommando: %s", error)
            besked = "Der opstod en fejl under kommandoen. Se bottens log for detaljer."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(besked, ephemeral=True)
                else:
                    await interaction.response.send_message(besked, ephemeral=True)
            except discord.HTTPException:
                pass


def ugedag_navn(weekday: int) -> str:
    navne = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
    return navne[weekday % 7]


# ===========================================================================
# 8. Opstart med automatisk genforbindelse
# ===========================================================================
async def run_forever(config: Config, state: StateStore, tz: ZoneInfo) -> None:
    """Kør botten og genstart forbindelsen automatisk ved netværksfejl.

    discord.py genopretter selv gateway-forbindelsen (reconnect=True). Denne
    løkke håndterer de tilfælde hvor selve klienten stopper – fx hvis
    internettet er væk ved opstart.
    """
    backoff = 5
    max_backoff = 300

    while True:
        # En discord.Client kan ikke genbruges efter close() – opret en ny.
        bot = TorsdagBot(config, state, tz)
        startet = datetime.now()
        try:
            await bot.start(config.token, reconnect=True)
            log.info("Botten blev lukket normalt.")
            return

        except discord.LoginFailure:
            log.error(
                "Login mislykkedes: DISCORD_TOKEN er ugyldigt. "
                "Hent et nyt token i Discord Developer Portal og opdatér .env."
            )
            return

        except discord.PrivilegedIntentsRequired:
            log.error(
                "Discord kræver privilegerede intents som ikke er slået til. "
                "Botten burde ikke bruge dem – tjek Developer Portal → Bot → "
                "Privileged Gateway Intents."
            )
            return

        except (discord.GatewayNotFound, discord.ConnectionClosed, discord.HTTPException) as exc:
            log.error("Discord-forbindelsesfejl: %s", exc)

        except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as exc:
            log.error("Netværksfejl: %s", exc)

        except asyncio.CancelledError:
            log.info("Botten blev afbrudt.")
            raise

        except Exception:
            log.exception("Uventet fejl – botten forsøger at genstarte forbindelsen")

        finally:
            if not bot.is_closed():
                try:
                    await bot.close()
                except Exception:
                    log.debug("Fejl under lukning af klienten", exc_info=True)

        # Kørte botten fint i mere end et minut, er der tale om en ny, enkeltstående
        # fejl – så starter vi forfra med en kort ventetid.
        if (datetime.now() - startet).total_seconds() > 60:
            backoff = 5

        log.info("Forsøger at forbinde igen om %d sekunder ...", backoff)
        try:
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            raise
        backoff = min(backoff * 2, max_backoff)


def pause_hvis_exe() -> None:
    """Hold konsolvinduet åbent, så fejlbeskeder kan læses når man kører .exe."""
    if getattr(sys, "frozen", False):
        try:
            input("\nTryk Enter for at lukke ...")
        except (EOFError, KeyboardInterrupt):
            pass


def main() -> int:
    setup_logging()
    log.info("=" * 70)
    log.info("%s v%s starter", APP_NAME, APP_VERSION)
    log.info("Programmappe: %s", APP_DIR)

    try:
        config = load_config()
    except ConfigError as exc:
        log.error("KONFIGURATIONSFEJL:\n%s", exc)
        pause_hvis_exe()
        return 1

    # Sæt det ønskede logniveau nu hvor konfigurationen er læst.
    logging.getLogger().setLevel(getattr(logging, config.log_level, logging.INFO))

    try:
        tz = load_timezone(config.timezone_name)
    except ConfigError as exc:
        log.error("TIDSZONEFEJL:\n%s", exc)
        pause_hvis_exe()
        return 1

    log.info(
        "Konfiguration OK · kanal-ID: %s · ejer-ID: %s · tidszone: %s · tilstand: %s",
        config.channel_id,
        config.owner_id or "ikke sat",
        config.timezone_name,
        config.poll_mode,
    )
    log.info("Lokal tid lige nu: %s", datetime.now(tz).strftime("%A %d-%m-%Y %H:%M:%S %Z"))

    state = StateStore(STATE_FILE)
    state.load()

    # Tjek-intervallet er konfigurerbart – opdatér loopet før det startes.
    TorsdagBot.scheduler_loop.change_interval(seconds=config.check_interval_seconds)

    try:
        asyncio.run(run_forever(config, state, tz))
    except KeyboardInterrupt:
        log.info("Afbrudt af brugeren (Ctrl+C). Lukker ned.")
    except Exception:
        log.exception("Botten stoppede på grund af en uventet fejl")
        pause_hvis_exe()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
