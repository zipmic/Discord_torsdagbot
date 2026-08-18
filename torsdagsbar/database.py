"""SQLite-lag for torsdagsbaren.

Ingen discord-afhængigheder – kun ren datalagring, så laget kan testes for sig.

Designprincipper:
  * Alle tidspunkter gemmes som **UTC** i ISO 8601-format. De vises først som
    dansk lokal tid i selve Discord-beskederne.
  * Bruger-ID er den primære identifikation. Visningsnavne gemmes ved siden af,
    fordi de kan ændres.
  * Sessioner er kilden til sandhed. Totaler, streaks og rekorder beregnes
    (og kan genberegnes) ud fra sessionerne – de caches ikke som facit.
  * Databasen oprettes automatisk, hvis den ikke findes, og har indekser på de
    felter, statistik og leaderboard slår op på.
  * Adgang er trådsikker via en RLock, så flere ``asyncio.to_thread``-kald ikke
    kolliderer.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("torsdagbot.torsdagsbar.db")

SCHEMA_VERSION = 2


# ---------------------------------------------------------------------------
# Små dataklasser til rækker (nemmere at arbejde med end rå tupler).
# ---------------------------------------------------------------------------
@dataclass
class Session:
    id: int
    user_id: int
    display_name: str
    bar_date: str          # 'YYYY-MM-DD'
    channel_id: Optional[int]
    joined_at: datetime    # UTC, tz-aware
    left_at: Optional[datetime]  # UTC, tz-aware; None = åben
    duration_seconds: Optional[int]
    source: str            # 'auto' | 'manual' | 'recovered'

    @property
    def is_open(self) -> bool:
        return self.left_at is None


@dataclass
class Night:
    bar_date: str
    cancelled: bool
    summary_sent: bool
    summary_sent_at: Optional[datetime]
    note: Optional[str]


@dataclass
class Correction:
    id: int
    user_id: int
    bar_date: str
    delta_seconds: int
    reason: Optional[str]
    admin_id: Optional[int]


@dataclass
class Vote:
    bar_date: str
    user_id: int
    option_key: str
    voted_at: Optional[datetime]
    source: str


@dataclass
class Quote:
    id: int
    user_id: int
    text: str
    added_by: Optional[int]
    created_at: Optional[datetime]


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("Tidspunkter skal være tz-aware før lagring.")
    return value.astimezone(timezone.utc).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_quote(row) -> "Quote":
    return Quote(
        id=row["id"],
        user_id=row["user_id"],
        text=row["text"],
        added_by=row["added_by"],
        created_at=_parse_dt(row["created_at"]),
    )


class Database:
    """Trådsikker indpakning omkring en enkelt SQLite-forbindelse."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        # check_same_thread=False + RLock: sikkert på tværs af to_thread-workers.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
        self._init_schema()

    # -- opsætning ----------------------------------------------------------
    def _init_schema(self) -> None:
        with self._lock, self._conn:  # "with conn" = én transaktion
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id      INTEGER PRIMARY KEY,
                    display_name TEXT,
                    updated_at   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id          INTEGER NOT NULL,
                    display_name     TEXT,
                    bar_date         TEXT NOT NULL,
                    channel_id       INTEGER,
                    joined_at        TEXT NOT NULL,
                    left_at          TEXT,
                    duration_seconds INTEGER,
                    source           TEXT NOT NULL DEFAULT 'auto',
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bar_nights (
                    bar_date        TEXT PRIMARY KEY,
                    cancelled       INTEGER NOT NULL DEFAULT 0,
                    summary_sent    INTEGER NOT NULL DEFAULT 0,
                    summary_sent_at TEXT,
                    note            TEXT,
                    updated_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS corrections (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL,
                    bar_date      TEXT NOT NULL,
                    delta_seconds INTEGER NOT NULL,
                    reason        TEXT,
                    admin_id      INTEGER,
                    created_at    TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user
                    ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_date
                    ON sessions(bar_date);
                CREATE INDEX IF NOT EXISTS idx_sessions_user_date
                    ON sessions(user_id, bar_date);
                CREATE INDEX IF NOT EXISTS idx_sessions_open
                    ON sessions(left_at);
                CREATE INDEX IF NOT EXISTS idx_corrections_date
                    ON corrections(bar_date);
                CREATE INDEX IF NOT EXISTS idx_corrections_user_date
                    ON corrections(user_id, bar_date);

                -- Skema v2: stemmer, poll-beskeder, citater og forsinkelsesbeskeder.

                -- Én aktiv stemme pr. bruger pr. torsdagsbar (som Discords poll).
                CREATE TABLE IF NOT EXISTS poll_votes (
                    bar_date   TEXT NOT NULL,
                    user_id    INTEGER NOT NULL,
                    option_key TEXT NOT NULL,
                    voted_at   TEXT NOT NULL,
                    source     TEXT NOT NULL DEFAULT 'native',
                    PRIMARY KEY (bar_date, user_id)
                );

                -- Hvor aftenens afstemning blev sendt, så stemmerne kan hentes.
                CREATE TABLE IF NOT EXISTS poll_messages (
                    bar_date   TEXT PRIMARY KEY,
                    message_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    mode       TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS quotes (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    text       TEXT NOT NULL,
                    added_by   INTEGER,
                    created_at TEXT NOT NULL
                );

                -- Højst én "du er sent på den"-besked pr. bruger pr. aften.
                CREATE TABLE IF NOT EXISTS late_notices (
                    bar_date TEXT NOT NULL,
                    user_id  INTEGER NOT NULL,
                    sent_at  TEXT NOT NULL,
                    PRIMARY KEY (bar_date, user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_votes_date ON poll_votes(bar_date);
                CREATE INDEX IF NOT EXISTS idx_votes_user ON poll_votes(user_id);
                CREATE INDEX IF NOT EXISTS idx_quotes_user ON quotes(user_id);
                """
            )
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def healthy(self) -> bool:
        """Enkelt sundhedstjek – bruges af /torsdagsbar status."""
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error as exc:
            log.error("Database-sundhedstjek fejlede: %s", exc)
            return False

    # -- meta ---------------------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def set_heartbeat(self, moment: Optional[datetime] = None) -> None:
        self.set_meta("heartbeat", _fmt_dt(moment or _utcnow()))

    def get_heartbeat(self) -> Optional[datetime]:
        return _parse_dt(self.get_meta("heartbeat"))

    # -- brugere ------------------------------------------------------------
    def upsert_user(self, user_id: int, display_name: Optional[str]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO users(user_id, display_name, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "display_name = COALESCE(excluded.display_name, users.display_name), "
                "updated_at = excluded.updated_at",
                (user_id, display_name, _fmt_dt(_utcnow())),
            )

    def display_name(self, user_id: int) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT display_name FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["display_name"] if row and row["display_name"] else None

    def all_display_names(self) -> dict[int, str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id, display_name FROM users"
            ).fetchall()
        return {r["user_id"]: (r["display_name"] or str(r["user_id"])) for r in rows}

    # -- sessioner ----------------------------------------------------------
    def _row_to_session(self, row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            display_name=row["display_name"] or str(row["user_id"]),
            bar_date=row["bar_date"],
            channel_id=row["channel_id"],
            joined_at=_parse_dt(row["joined_at"]),
            left_at=_parse_dt(row["left_at"]),
            duration_seconds=row["duration_seconds"],
            source=row["source"],
        )

    def get_open_session(self, user_id: int) -> Optional[Session]:
        """Den (evt.) åbne session for en bruger. Der bør højst være én."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE user_id = ? AND left_at IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def list_open_sessions(self) -> list[Session]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE left_at IS NULL ORDER BY joined_at"
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def open_session(
        self,
        user_id: int,
        display_name: Optional[str],
        bar_date: date,
        channel_id: Optional[int],
        joined_at: datetime,
        source: str = "auto",
    ) -> int:
        """Åbn en ny session. Undgår dubletter: hvis brugeren allerede har en
        åben session, opdateres blot kanalen på den, og dens id returneres."""
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT id FROM sessions WHERE user_id = ? AND left_at IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE sessions SET channel_id = ?, updated_at = ? WHERE id = ?",
                    (channel_id, _fmt_dt(_utcnow()), existing["id"]),
                )
                return existing["id"]

            now = _fmt_dt(_utcnow())
            cur = self._conn.execute(
                "INSERT INTO sessions(user_id, display_name, bar_date, channel_id, "
                "joined_at, left_at, duration_seconds, source, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)",
                (
                    user_id,
                    display_name,
                    bar_date.isoformat(),
                    channel_id,
                    _fmt_dt(joined_at),
                    source,
                    now,
                    now,
                ),
            )
            # Sørg for at natten findes i bar_nights.
            self._ensure_night_locked(bar_date.isoformat())
            return int(cur.lastrowid)

    def set_session_channel(self, session_id: int, channel_id: Optional[int]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET channel_id = ?, updated_at = ? WHERE id = ?",
                (channel_id, _fmt_dt(_utcnow()), session_id),
            )

    def close_session(self, session_id: int, left_at: datetime) -> Optional[int]:
        """Luk en session og udregn varigheden. Returnerer varigheden i sekunder.

        Er sluttidspunktet før starttidspunktet (kan ske ved ur-justeringer),
        sættes varigheden til 0 i stedet for et negativt tal.
        """
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT joined_at, left_at FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None or row["left_at"] is not None:
                return None  # findes ikke eller allerede lukket
            joined = _parse_dt(row["joined_at"])
            left = left_at.astimezone(timezone.utc)
            duration = max(0, int((left - joined).total_seconds()))
            self._conn.execute(
                "UPDATE sessions SET left_at = ?, duration_seconds = ?, updated_at = ? "
                "WHERE id = ?",
                (_fmt_dt(left), duration, _fmt_dt(_utcnow()), session_id),
            )
            return duration

    def close_all_open(
        self, left_at: datetime, only_before: Optional[datetime] = None
    ) -> int:
        """Luk alle åbne sessioner ved ``left_at``.

        ``only_before`` kan bruges til at klampe sluttidspunktet (fx til 03:00).
        Returnerer antal lukkede sessioner.
        """
        closed = 0
        with self._lock:
            for session in self.list_open_sessions():
                end = left_at
                if only_before is not None and end > only_before:
                    end = only_before
                if end < session.joined_at:
                    end = session.joined_at
                if self.close_session(session.id, end) is not None:
                    closed += 1
        return closed

    def add_manual_session(
        self,
        user_id: int,
        display_name: Optional[str],
        bar_date: date,
        joined_at: datetime,
        left_at: datetime,
        source: str = "manual",
    ) -> int:
        """Indsæt en færdig (lukket) session – bruges af /torsdagsbar korriger."""
        duration = max(0, int((left_at - joined_at).total_seconds()))
        with self._lock, self._conn:
            now = _fmt_dt(_utcnow())
            cur = self._conn.execute(
                "INSERT INTO sessions(user_id, display_name, bar_date, channel_id, "
                "joined_at, left_at, duration_seconds, source, created_at, updated_at) "
                "VALUES(?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    display_name,
                    bar_date.isoformat(),
                    _fmt_dt(joined_at),
                    _fmt_dt(left_at),
                    duration,
                    source,
                    now,
                    now,
                ),
            )
            self._ensure_night_locked(bar_date.isoformat())
            return int(cur.lastrowid)

    def load_sessions(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user_id: Optional[int] = None,
        include_open: bool = False,
    ) -> list[Session]:
        """Hent sessioner (lukkede som standard) i et dato-interval."""
        query = ["SELECT * FROM sessions WHERE 1=1"]
        params: list[object] = []
        if not include_open:
            query.append("AND left_at IS NOT NULL")
        if start_date:
            query.append("AND bar_date >= ?")
            params.append(start_date)
        if end_date:
            query.append("AND bar_date <= ?")
            params.append(end_date)
        if user_id is not None:
            query.append("AND user_id = ?")
            params.append(user_id)
        query.append("ORDER BY bar_date, user_id, joined_at")
        with self._lock:
            rows = self._conn.execute(" ".join(query), params).fetchall()
        return [self._row_to_session(r) for r in rows]

    # -- nætter (bar_nights) ------------------------------------------------
    def _ensure_night_locked(self, bar_date: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO bar_nights(bar_date, updated_at) VALUES(?, ?)",
            (bar_date, _fmt_dt(_utcnow())),
        )

    def ensure_night(self, bar_date: date) -> None:
        with self._lock, self._conn:
            self._ensure_night_locked(bar_date.isoformat())

    def get_night(self, bar_date: str) -> Optional[Night]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM bar_nights WHERE bar_date = ?", (bar_date,)
            ).fetchone()
        if row is None:
            return None
        return Night(
            bar_date=row["bar_date"],
            cancelled=bool(row["cancelled"]),
            summary_sent=bool(row["summary_sent"]),
            summary_sent_at=_parse_dt(row["summary_sent_at"]),
            note=row["note"],
        )

    def load_nights(self) -> dict[str, Night]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM bar_nights").fetchall()
        return {
            r["bar_date"]: Night(
                bar_date=r["bar_date"],
                cancelled=bool(r["cancelled"]),
                summary_sent=bool(r["summary_sent"]),
                summary_sent_at=_parse_dt(r["summary_sent_at"]),
                note=r["note"],
            )
            for r in rows
        }

    def set_cancelled(self, bar_date: date, cancelled: bool, note: Optional[str] = None) -> None:
        with self._lock, self._conn:
            self._ensure_night_locked(bar_date.isoformat())
            self._conn.execute(
                "UPDATE bar_nights SET cancelled = ?, note = COALESCE(?, note), "
                "updated_at = ? WHERE bar_date = ?",
                (1 if cancelled else 0, note, _fmt_dt(_utcnow()), bar_date.isoformat()),
            )

    def is_summary_sent(self, bar_date: str) -> bool:
        night = self.get_night(bar_date)
        return bool(night and night.summary_sent)

    def mark_summary_sent(self, bar_date: date, sent: bool = True) -> None:
        with self._lock, self._conn:
            self._ensure_night_locked(bar_date.isoformat())
            self._conn.execute(
                "UPDATE bar_nights SET summary_sent = ?, summary_sent_at = ?, "
                "updated_at = ? WHERE bar_date = ?",
                (
                    1 if sent else 0,
                    _fmt_dt(_utcnow()) if sent else None,
                    _fmt_dt(_utcnow()),
                    bar_date.isoformat(),
                ),
            )

    # -- rettelser (corrections) -------------------------------------------
    def add_correction(
        self,
        user_id: int,
        bar_date: date,
        delta_seconds: int,
        reason: Optional[str],
        admin_id: Optional[int],
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO corrections(user_id, bar_date, delta_seconds, reason, "
                "admin_id, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    bar_date.isoformat(),
                    int(delta_seconds),
                    reason,
                    admin_id,
                    _fmt_dt(_utcnow()),
                ),
            )
            self._ensure_night_locked(bar_date.isoformat())
            return int(cur.lastrowid)

    def clear_corrections(self, user_id: int, bar_date: date) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM corrections WHERE user_id = ? AND bar_date = ?",
                (user_id, bar_date.isoformat()),
            )
            return cur.rowcount

    def load_corrections(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> list[Correction]:
        query = ["SELECT * FROM corrections WHERE 1=1"]
        params: list[object] = []
        if start_date:
            query.append("AND bar_date >= ?")
            params.append(start_date)
        if end_date:
            query.append("AND bar_date <= ?")
            params.append(end_date)
        if user_id is not None:
            query.append("AND user_id = ?")
            params.append(user_id)
        with self._lock:
            rows = self._conn.execute(" ".join(query), params).fetchall()
        return [
            Correction(
                id=r["id"],
                user_id=r["user_id"],
                bar_date=r["bar_date"],
                delta_seconds=r["delta_seconds"],
                reason=r["reason"],
                admin_id=r["admin_id"],
            )
            for r in rows
        ]

    def correction_total(self, user_id: int, bar_date: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(delta_seconds), 0) AS s FROM corrections "
                "WHERE user_id = ? AND bar_date = ?",
                (user_id, bar_date),
            ).fetchone()
        return int(row["s"]) if row else 0

    # =======================================================================
    # Skema v2: stemmer, poll-beskeder, citater, forsinkelsesbeskeder
    # =======================================================================

    # -- afstemningens stemmer ---------------------------------------------
    def record_poll_message(
        self, bar_date: date, message_id: int, channel_id: int, mode: str
    ) -> None:
        """Husk hvor aftenens afstemning blev sendt, så stemmerne kan hentes."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO poll_messages(bar_date, message_id, channel_id, mode, "
                "created_at) VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(bar_date) DO UPDATE SET "
                "message_id = excluded.message_id, channel_id = excluded.channel_id, "
                "mode = excluded.mode",
                (bar_date.isoformat(), message_id, channel_id, mode, _fmt_dt(_utcnow())),
            )
            self._ensure_night_locked(bar_date.isoformat())

    def get_poll_message(self, bar_date: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM poll_messages WHERE bar_date = ?", (bar_date,)
            ).fetchone()
        if row is None:
            return None
        return {
            "bar_date": row["bar_date"],
            "message_id": row["message_id"],
            "channel_id": row["channel_id"],
            "mode": row["mode"],
        }

    def upsert_vote(
        self,
        bar_date: date,
        user_id: int,
        option_key: str,
        source: str = "native",
        voted_at: Optional[datetime] = None,
    ) -> None:
        """Gem en brugers stemme. Én aktiv stemme pr. bruger pr. aften – en ny
        stemme overskriver den gamle (som i Discords egen poll)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO poll_votes(bar_date, user_id, option_key, voted_at, source) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(bar_date, user_id) DO UPDATE SET "
                "option_key = excluded.option_key, voted_at = excluded.voted_at, "
                "source = excluded.source",
                (
                    bar_date.isoformat(),
                    user_id,
                    option_key,
                    _fmt_dt(voted_at or _utcnow()),
                    source,
                ),
            )

    def replace_votes(
        self, bar_date: date, votes: dict[int, str], source: str = "native"
    ) -> int:
        """Erstat alle stemmer for en aften i én transaktion.

        Bruges af synkroniseringen fra Discords indbyggede poll, hvor vi altid
        henter det fulde billede. Returnerer antallet af gemte stemmer.
        """
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM poll_votes WHERE bar_date = ? AND source = ?",
                (bar_date.isoformat(), source),
            )
            now = _fmt_dt(_utcnow())
            self._conn.executemany(
                "INSERT INTO poll_votes(bar_date, user_id, option_key, voted_at, source) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(bar_date, user_id) DO UPDATE SET "
                "option_key = excluded.option_key, voted_at = excluded.voted_at, "
                "source = excluded.source",
                [
                    (bar_date.isoformat(), uid, key, now, source)
                    for uid, key in votes.items()
                ],
            )
            self._ensure_night_locked(bar_date.isoformat())
            return len(votes)

    def votes_for_night(self, bar_date: str) -> dict[int, str]:
        """{user_id: option_key} for en enkelt aften."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id, option_key FROM poll_votes WHERE bar_date = ?",
                (bar_date,),
            ).fetchall()
        return {r["user_id"]: r["option_key"] for r in rows}

    def load_votes(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> dict[str, dict[int, str]]:
        """{bar_date: {user_id: option_key}} for et dato-interval."""
        query = ["SELECT bar_date, user_id, option_key FROM poll_votes WHERE 1=1"]
        params: list[object] = []
        if start_date:
            query.append("AND bar_date >= ?")
            params.append(start_date)
        if end_date:
            query.append("AND bar_date <= ?")
            params.append(end_date)
        if user_id is not None:
            query.append("AND user_id = ?")
            params.append(user_id)
        with self._lock:
            rows = self._conn.execute(" ".join(query), params).fetchall()
        result: dict[str, dict[int, str]] = {}
        for r in rows:
            result.setdefault(r["bar_date"], {})[r["user_id"]] = r["option_key"]
        return result

    # -- forsinkelsesbeskeder ----------------------------------------------
    def late_notice_sent(self, bar_date: str, user_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM late_notices WHERE bar_date = ? AND user_id = ?",
                (bar_date, user_id),
            ).fetchone()
        return row is not None

    def mark_late_notice(self, bar_date: date, user_id: int) -> bool:
        """Markér at brugeren har fået sin forsinkelsesbesked.

        Returnerer True hvis denne kaldelse var den første (og beskeden altså
        skal sendes) – gør det umuligt at sende to gange, også ved race.
        """
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO late_notices(bar_date, user_id, sent_at) "
                "VALUES(?, ?, ?)",
                (bar_date.isoformat(), user_id, _fmt_dt(_utcnow())),
            )
            return cur.rowcount > 0

    def late_notified_users(self, bar_date: str) -> set[int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id FROM late_notices WHERE bar_date = ?", (bar_date,)
            ).fetchall()
        return {r["user_id"] for r in rows}

    # -- citat-bogen --------------------------------------------------------
    def add_quote(
        self, user_id: int, text: str, added_by: Optional[int]
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO quotes(user_id, text, added_by, created_at) "
                "VALUES(?, ?, ?, ?)",
                (user_id, text, added_by, _fmt_dt(_utcnow())),
            )
            return int(cur.lastrowid)

    def get_quote(self, quote_id: int) -> Optional[Quote]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM quotes WHERE id = ?", (quote_id,)
            ).fetchone()
        return _row_to_quote(row) if row else None

    def delete_quote(self, quote_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM quotes WHERE id = ?", (quote_id,))
            return cur.rowcount > 0

    def quotes_for(self, user_id: int) -> list[Quote]:
        """Brugerens citater, nyeste først."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM quotes WHERE user_id = ? ORDER BY id DESC", (user_id,)
            ).fetchall()
        return [_row_to_quote(r) for r in rows]

    def random_quote(self) -> Optional[Quote]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM quotes ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
        return _row_to_quote(row) if row else None

    def quote_count(self, user_id: Optional[int] = None) -> int:
        with self._lock:
            if user_id is None:
                row = self._conn.execute("SELECT COUNT(*) AS n FROM quotes").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM quotes WHERE user_id = ?", (user_id,)
                ).fetchone()
        return int(row["n"]) if row else 0
