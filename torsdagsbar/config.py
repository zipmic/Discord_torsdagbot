"""Indstillinger for torsdagsbaren.

Alt kan sættes uden at ændre koden. Ikke-hemmelige indstillinger ligger i
``config.json`` under nøglen ``"torsdagsbar"``; enkelte kan overstyres med
miljøvariabler (fx i .env) med præfikset ``TB_``.

Discord-tokenet hører til hovedbotten og læses aldrig her.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from zoneinfo import ZoneInfo

from .period import Schedule

log = logging.getLogger("torsdagbot.torsdagsbar.config")


class TorsdagsbarConfigError(Exception):
    """Rejses ved en klar fejl i torsdagsbar-konfigurationen."""


@dataclass
class TorsdagsbarConfig:
    enabled: bool
    server_id: Optional[int]
    voice_channel_ids: list[int]
    summary_channel_id: Optional[int]

    schedule: Schedule

    min_minutes: int = 5
    admin_role_id: Optional[int] = None
    admin_role_name: Optional[str] = None
    leaderboard_size: int = 10
    summary_show_records: bool = True
    summary_catch_up_hours: int = 6
    # Når True optjenes tid kun, mens mindst én ANDEN bruger også er i baren.
    require_company: bool = True

    # Sekunder mellem trackerens periodiske tjek (heartbeat, 19:00/03:00-grænser).
    tick_seconds: int = 30

    db_path: Path = field(default_factory=lambda: Path("torsdagsbar.db"))

    # Server til øjeblikkelig synk af slash-kommandoer (genbruges fra hovedbot).
    guild_id: Optional[int] = None

    @property
    def min_seconds(self) -> int:
        return max(0, self.min_minutes) * 60

    def is_tracked_channel(self, channel_id: Optional[int]) -> bool:
        return channel_id is not None and channel_id in self.voice_channel_ids


# ---------------------------------------------------------------------------
# Indlæsning
# ---------------------------------------------------------------------------
def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):  # undgå at True bliver til 1
        return None
    text = str(value).split("#", 1)[0].strip().replace("_", "").replace(" ", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _as_int_list(value: Any) -> list[int]:
    """Accepterer en liste, et enkelt tal, eller en komma-/mellemrumssepareret streng."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).replace(",", " ").split()
    result: list[int] = []
    for item in items:
        num = _as_int(item)
        if num is not None:
            result.append(num)
    return result


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "ja", "y", "on"}


def _read_section(config_file: Path) -> dict[str, Any]:
    """Læs "torsdagsbar"-sektionen fra config.json (tom hvis filen mangler)."""
    if not config_file.exists():
        return {}
    try:
        with config_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise TorsdagsbarConfigError(
            f"Kunne ikke læse {config_file.name}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        return {}
    section = data.get("torsdagsbar")
    if section is None:
        # Tillad også flade nøgler i toppen som fallback.
        return {}
    if not isinstance(section, dict):
        raise TorsdagsbarConfigError('"torsdagsbar" i config.json skal være et objekt.')
    return section


def load_torsdagsbar_config(
    app_dir: Path,
    config_file: Path,
    tz: ZoneInfo,
    guild_id: Optional[int] = None,
    env: Optional[dict[str, str]] = None,
) -> TorsdagsbarConfig:
    """Byg en ``TorsdagsbarConfig`` fra config.json + miljøvariabler.

    Fejler ikke hvis funktionen er slået fra – den returnerer bare en config
    med ``enabled=False``, så hovedbotten (afstemningen) kører uforstyrret.
    """
    env = env if env is not None else dict(os.environ)
    section = _read_section(config_file)

    def get(key: str, env_key: str, default: Any = None) -> Any:
        # Miljøvariabel vinder over config.json.
        if env_key in env and env[env_key].strip():
            return env[env_key]
        if key in section and section[key] is not None:
            return section[key]
        return default

    server_id = _as_int(get("server_id", "TB_SERVER_ID")) or (
        _as_int(get("guild_id", "TB_GUILD_ID")) or guild_id
    )
    voice_channel_ids = _as_int_list(get("voice_channel_ids", "TB_VOICE_CHANNEL_IDS"))
    # Tillad også ental-nøglen "voice_channel_id".
    if not voice_channel_ids:
        voice_channel_ids = _as_int_list(get("voice_channel_id", "TB_VOICE_CHANNEL_ID"))
    summary_channel_id = _as_int(get("summary_channel_id", "TB_SUMMARY_CHANNEL_ID"))

    # Tidspunkter.
    def geti(key: str, env_key: str, default: int) -> int:
        val = _as_int(get(key, env_key))
        return default if val is None else val

    schedule = Schedule(
        tz=tz,
        weekday=geti("weekday", "TB_WEEKDAY", 3),
        start_hour=geti("start_hour", "TB_START_HOUR", 19),
        start_minute=geti("start_minute", "TB_START_MINUTE", 0),
        end_hour=geti("end_hour", "TB_END_HOUR", 3),
        end_minute=geti("end_minute", "TB_END_MINUTE", 0),
        end_day_offset=geti("end_day_offset", "TB_END_DAY_OFFSET", 1),
        summary_weekday=geti("summary_weekday", "TB_SUMMARY_WEEKDAY", 4),
        summary_hour=geti("summary_hour", "TB_SUMMARY_HOUR", 12),
        summary_minute=geti("summary_minute", "TB_SUMMARY_MINUTE", 0),
    )

    min_minutes = geti("min_minutes", "TB_MIN_MINUTES", 5)
    admin_role_id = _as_int(get("admin_role_id", "TB_ADMIN_ROLE_ID"))
    admin_role_name_raw = get("admin_role_name", "TB_ADMIN_ROLE_NAME")
    admin_role_name = str(admin_role_name_raw).strip() if admin_role_name_raw else None
    leaderboard_size = geti("leaderboard_size", "TB_LEADERBOARD_SIZE", 10)
    leaderboard_size = max(1, min(leaderboard_size, 25))
    show_records = _as_bool(get("summary_show_records", "TB_SUMMARY_SHOW_RECORDS"), True)
    require_company = _as_bool(get("require_company", "TB_REQUIRE_COMPANY"), True)
    catch_up = geti("summary_catch_up_hours", "TB_SUMMARY_CATCH_UP_HOURS", 6)
    tick_seconds = geti("tick_seconds", "TB_TICK_SECONDS", 30)
    tick_seconds = max(10, min(tick_seconds, 300))

    db_name = get("db_filename", "TB_DB_FILENAME", "torsdagsbar.db")
    db_path = Path(db_name)
    if not db_path.is_absolute():
        db_path = app_dir / db_path

    # Slået til, hvis alle de nødvendige ID'er findes.
    enabled_flag = get("enabled", "TB_ENABLED")
    explicitly_enabled = _as_bool(enabled_flag, default=None) if enabled_flag is not None else None
    has_required = bool(server_id and voice_channel_ids and summary_channel_id)

    if explicitly_enabled is False:
        enabled = False
    elif explicitly_enabled is True:
        enabled = has_required
        if not has_required:
            log.warning(
                "Torsdagsbar er slået til, men mangler server_id, voice_channel_ids "
                "eller summary_channel_id i config.json. Funktionen deaktiveres."
            )
    else:
        enabled = has_required
        if not has_required:
            log.info(
                "Torsdagsbar-statistik er ikke konfigureret (mangler server_id/"
                "voice_channel_ids/summary_channel_id) – funktionen er slået fra. "
                "Afstemningen kører som normalt."
            )

    return TorsdagsbarConfig(
        enabled=enabled,
        server_id=server_id,
        voice_channel_ids=voice_channel_ids,
        summary_channel_id=summary_channel_id,
        schedule=schedule,
        min_minutes=min_minutes,
        admin_role_id=admin_role_id,
        admin_role_name=admin_role_name,
        leaderboard_size=leaderboard_size,
        summary_show_records=show_records,
        summary_catch_up_hours=catch_up,
        require_company=require_company,
        tick_seconds=tick_seconds,
        db_path=db_path,
        guild_id=guild_id,
    )
