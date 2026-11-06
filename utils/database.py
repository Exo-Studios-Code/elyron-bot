"""
Database module for Blox Strike PUG League Bot.
Backend: Turso (libSQL / SQLite-compatible, hosted free tier).
Driver:  libsql-client  (pip install libsql-client)

Configuration (add to .env):
    TURSO_DATABASE_URL=libsql://your-db-name.turso.io
    TURSO_AUTH_TOKEN=your-token-here

For local development without a Turso account, set:
    TURSO_DATABASE_URL=file:data/dev.db
    TURSO_AUTH_TOKEN=   (leave empty)

The SQL syntax is 100% standard SQLite - nothing changes there.
What IS different from aiosqlite:
  - No cursor objects. Execute returns a ResultSet directly.
  - Rows are tuples, not sqlite3.Row. We convert via _row() helper.
  - lastrowid  →  result.last_insert_rowid
  - IntegrityError / OperationalError  →  libsql_client.LibsqlError
  - conn.commit() is not needed - Turso auto-commits each statement.
  - Batch DDL (CREATE TABLE, CREATE INDEX) sent in one round-trip via c.batch().
  - Retries: transient HTTP/network errors are retried up to 3 times.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import libsql_client
from libsql_client import LibsqlError

from utils.config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# How many times to retry a statement on transient network/HTTP errors before
# giving up. Turso's free tier occasionally returns 503 under burst load.
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3
_RETRY_DELAY = 0.5  # seconds between retries


class Database:
    """
    Async database handler backed by Turso (libSQL).
    Drop-in replacement for the old aiosqlite-based Database class -
    all method signatures and return types are identical.
    """

    def __init__(self):
        url = os.getenv("TURSO_DATABASE_URL", f"file:{Config.DATABASE_PATH}")
        token = os.getenv("TURSO_AUTH_TOKEN") or None
        self._url = url
        self._token = token
        self._client: Optional[libsql_client.Client] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _exec(self, sql: str, args: Optional[List[Any]] = None) -> libsql_client.ResultSet:
        """Execute a single statement with retry on transient errors."""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                if args:
                    return await self._client.execute(sql, args)
                return await self._client.execute(sql)
            except LibsqlError as e:
                msg = str(e).upper()
                # Constraint violations are not transient - re-raise immediately.
                if any(k in msg for k in ("CONSTRAINT", "UNIQUE", "DUPLICATE")):
                    raise
                if attempt == _MAX_RETRIES:
                    logger.error(f"DB error after {_MAX_RETRIES} attempts: {e}\nSQL: {sql}")
                    raise
                logger.warning(f"Transient DB error (attempt {attempt}): {e}. Retrying…")
                await asyncio.sleep(_RETRY_DELAY * attempt)

    def _row(self, rs: libsql_client.ResultSet, index: int = 0) -> Optional[Dict]:
        """Convert a ResultSet row (tuple) to a dict using rs.columns."""
        if not rs.rows or index >= len(rs.rows):
            return None
        return dict(zip(rs.columns, rs.rows[index]))

    def _rows(self, rs: libsql_client.ResultSet) -> List[Dict]:
        """Convert all ResultSet rows to dicts."""
        return [dict(zip(rs.columns, row)) for row in rs.rows]

    def _scalar(self, rs: libsql_client.ResultSet, col: int = 0) -> Any:
        """Return a single scalar value from the first row."""
        if not rs.rows:
            return None
        return rs.rows[0][col]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self):
        """Open connection to Turso and set up the schema."""
        self._client = libsql_client.create_client(
            url=self._url,
            auth_token=self._token,
        )
        await self._create_tables()
        await self._migrate_schema()
        await self._check_season()
        logger.info(f"Database connected to Turso ({self._url}).")

    async def close(self):
        if self._client:
            await self._client.close()

    # ------------------------------------------------------------------
    # Schema setup
    # ------------------------------------------------------------------

    async def _create_tables(self):
        """Create all tables in a single batch round-trip."""
        statements = [
            # Seasons
            """CREATE TABLE IF NOT EXISTS seasons (
                season_id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_date TIMESTAMP NOT NULL,
                end_date   TIMESTAMP NOT NULL,
                is_active  BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            # Players
            """CREATE TABLE IF NOT EXISTS players (
                player_id       INTEGER PRIMARY KEY,
                discord_id      INTEGER UNIQUE NOT NULL,
                username        TEXT NOT NULL,
                elo             INTEGER DEFAULT 1000,
                wins            INTEGER DEFAULT 0,
                losses          INTEGER DEFAULT 0,
                roblox_username TEXT,
                roblox_user_id  INTEGER,
                roblox_avatar_url TEXT,
                season_id       INTEGER NOT NULL,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (season_id) REFERENCES seasons(season_id)
            )""",
            # Parties
            """CREATE TABLE IF NOT EXISTS parties (
                party_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                leader_id  INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (leader_id) REFERENCES players(discord_id)
            )""",
            # Party members
            """CREATE TABLE IF NOT EXISTS party_members (
                party_id   INTEGER NOT NULL,
                discord_id INTEGER NOT NULL,
                PRIMARY KEY (party_id, discord_id),
                FOREIGN KEY (party_id)   REFERENCES parties(party_id),
                FOREIGN KEY (discord_id) REFERENCES players(discord_id)
            )""",
            # PUG teams (ephemeral, one per Matchroom)
            """CREATE TABLE IF NOT EXISTS pug_teams (
                team_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                captain_id INTEGER NOT NULL,
                elo        INTEGER DEFAULT 1000,
                wins       INTEGER DEFAULT 0,
                losses     INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            # PUG team members
            """CREATE TABLE IF NOT EXISTS pug_team_members (
                team_id    INTEGER NOT NULL,
                discord_id INTEGER NOT NULL,
                PRIMARY KEY (team_id, discord_id),
                FOREIGN KEY (team_id)    REFERENCES pug_teams(team_id),
                FOREIGN KEY (discord_id) REFERENCES players(discord_id)
            )""",
            # Queue
            """CREATE TABLE IF NOT EXISTS queue_players (
                discord_id INTEGER PRIMARY KEY,
                elo        INTEGER NOT NULL,
                party_id   INTEGER,
                joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (discord_id) REFERENCES players(discord_id),
                FOREIGN KEY (party_id)   REFERENCES parties(party_id)
            )""",
            # Queue host info (server link + friend link submitted when starting the queue)
            """CREATE TABLE IF NOT EXISTS queue_host (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                server_link TEXT,
                friend_link TEXT,
                host_id     INTEGER,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            # Persistent queue UI messages
            """CREATE TABLE IF NOT EXISTS queue_messages (
                message_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                guild_id   INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            # Matches
            """CREATE TABLE IF NOT EXISTS matches (
                match_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                team1_id        INTEGER NOT NULL,
                team2_id        INTEGER NOT NULL,
                winner_id       INTEGER,
                map_played      TEXT,
                team1_elo_before INTEGER NOT NULL,
                team2_elo_before INTEGER NOT NULL,
                team1_elo_after  INTEGER,
                team2_elo_after  INTEGER,
                elo_change       INTEGER,
                status           TEXT DEFAULT 'pending',
                reported_by      INTEGER,
                confirmed_by     INTEGER,
                season_id        INTEGER NOT NULL,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at     TIMESTAMP,
                FOREIGN KEY (team1_id)  REFERENCES pug_teams(team_id),
                FOREIGN KEY (team2_id)  REFERENCES pug_teams(team_id),
                FOREIGN KEY (winner_id) REFERENCES pug_teams(team_id),
                FOREIGN KEY (season_id) REFERENCES seasons(season_id)
            )""",
            # Map vetos
            """CREATE TABLE IF NOT EXISTS map_vetos (
                veto_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id   INTEGER NOT NULL,
                team_id    INTEGER NOT NULL,
                map_name   TEXT NOT NULL,
                veto_order INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(match_id),
                FOREIGN KEY (team_id)  REFERENCES pug_teams(team_id)
            )""",
            # Season archives
            """CREATE TABLE IF NOT EXISTS season_archives (
                archive_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                season_id   INTEGER NOT NULL,
                data_type   TEXT NOT NULL,
                data_json   TEXT NOT NULL,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (season_id) REFERENCES seasons(season_id)
            )""",
            # Match channels (private Discord channels auto-created per Matchroom)
            """CREATE TABLE IF NOT EXISTS match_channels (
                match_id         INTEGER PRIMARY KEY,
                guild_id         INTEGER NOT NULL,
                category_id      INTEGER,
                lobby_channel_id INTEGER,
                team1_voice_id   INTEGER,
                team2_voice_id   INTEGER,
                server_link      TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(match_id)
            )""",
            # Queue leave cooldowns (anti-abuse: 5 min cooldown after leaving)
            """CREATE TABLE IF NOT EXISTS queue_cooldowns (
                discord_id  INTEGER PRIMARY KEY,
                left_at     TIMESTAMP NOT NULL,
                FOREIGN KEY (discord_id) REFERENCES players(discord_id)
            )""",
            # Match disputes (when admin overrides a reported result)
            """CREATE TABLE IF NOT EXISTS match_disputes (
                dispute_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id     INTEGER NOT NULL UNIQUE,
                opened_by    INTEGER NOT NULL,
                reason       TEXT,
                resolved_by  INTEGER,
                resolution   TEXT,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at  TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(match_id)
            )""",
            # Per-match player statistics (one row per player per match, populated by OCR)
            """CREATE TABLE IF NOT EXISTS match_player_stats (
                stat_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id        INTEGER NOT NULL,
                discord_id      INTEGER,
                roblox_username TEXT NOT NULL,
                display_name    TEXT,
                team_side       TEXT NOT NULL,
                kills           INTEGER DEFAULT 0,
                deaths          INTEGER DEFAULT 0,
                assists         INTEGER DEFAULT 0,
                mvps            INTEGER DEFAULT 0,
                score           INTEGER DEFAULT 0,
                money           INTEGER DEFAULT 0,
                ocr_confidence  TEXT DEFAULT 'unknown',
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id)   REFERENCES matches(match_id),
                FOREIGN KEY (discord_id) REFERENCES players(discord_id)
            )""",
            # Career aggregate stats per player (updated after every confirmed match)
            """CREATE TABLE IF NOT EXISTS player_career_stats (
                discord_id      INTEGER PRIMARY KEY,
                total_kills     INTEGER DEFAULT 0,
                total_deaths    INTEGER DEFAULT 0,
                total_assists   INTEGER DEFAULT 0,
                total_mvps      INTEGER DEFAULT 0,
                total_score     INTEGER DEFAULT 0,
                matches_with_stats INTEGER DEFAULT 0,
                FOREIGN KEY (discord_id) REFERENCES players(discord_id)
            )""",
            # Indexes
            "CREATE INDEX IF NOT EXISTS idx_players_season ON players(season_id)",
            "CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status)",
            "CREATE INDEX IF NOT EXISTS idx_queue_joined   ON queue_players(joined_at)",
            "CREATE INDEX IF NOT EXISTS idx_players_elo    ON players(elo DESC)",
        ]
        await self._client.batch(statements)

    async def _migrate_schema(self):
        """Add columns that didn't exist in earlier schema versions."""
        pass  # Tímhle se migrace přeskočí a bot hned pojede dál

    async def _check_season(self):
        """Ensure there's always an active season."""
        rs = await self._exec("SELECT season_id FROM seasons WHERE is_active = 1")
        if not rs.rows:
            await self.create_new_season()

    # ------------------------------------------------------------------
    # Seasons
    # ------------------------------------------------------------------

    async def create_new_season(self) -> int:
        start = datetime.now()
        end   = start + timedelta(days=Config.SEASON_DURATION_DAYS)
        await self._exec("UPDATE seasons SET is_active = 0")
        rs = await self._exec(
            "INSERT INTO seasons (start_date, end_date, is_active) VALUES (?, ?, 1)",
            [str(start), str(end)],
        )
        season_id = rs.last_insert_rowid
        await self._exec(
            "UPDATE players SET elo = ?, wins = 0, losses = 0, season_id = ?",
            [Config.STARTING_ELO, season_id],
        )
        logger.info(f"Created season {season_id} and reset ELOs.")
        return season_id

    async def get_active_season(self) -> Optional[int]:
        rs = await self._exec("SELECT season_id FROM seasons WHERE is_active = 1")
        return self._scalar(rs)

    # ------------------------------------------------------------------
    # Players
    # ------------------------------------------------------------------

    async def create_or_get_player(self, discord_id: int, username: str) -> int:
        season_id = await self.get_active_season()
        rs = await self._exec("SELECT player_id FROM players WHERE discord_id = ?", [discord_id])
        if rs.rows:
            return rs.rows[0][0]
        rs2 = await self._exec(
            "INSERT INTO players (discord_id, username, season_id, elo) VALUES (?, ?, ?, ?)",
            [discord_id, username, season_id, Config.STARTING_ELO],
        )
        return rs2.last_insert_rowid

    async def get_player(self, discord_id: int) -> Optional[Dict]:
        rs = await self._exec("SELECT * FROM players WHERE discord_id = ?", [discord_id])
        return self._row(rs)

    async def update_player_stats(self, discord_id: int, elo: int, won: bool):
        if won:
            await self._exec(
                "UPDATE players SET elo = ?, wins = wins + 1 WHERE discord_id = ?",
                [elo, discord_id],
            )
        else:
            await self._exec(
                "UPDATE players SET elo = ?, losses = losses + 1 WHERE discord_id = ?",
                [elo, discord_id],
            )

    async def get_top_players(self, limit: int = 10) -> List[Dict]:
        rs = await self._exec(
            "SELECT * FROM players ORDER BY elo DESC, wins DESC LIMIT ?", [limit]
        )
        return self._rows(rs)

    async def get_all_players(self) -> List[Dict]:
        rs = await self._exec("SELECT * FROM players ORDER BY elo DESC")
        return self._rows(rs)

    async def get_player_rank_by_elo(self, discord_id: int) -> Optional[int]:
        player = await self.get_player(discord_id)
        if not player:
            return None
        rs = await self._exec("SELECT COUNT(*) FROM players WHERE elo > ?", [player["elo"]])
        higher = self._scalar(rs) or 0
        return higher + 1

    # ------------------------------------------------------------------
    # Roblox account linking
    # ------------------------------------------------------------------

    async def set_roblox_account(
        self,
        discord_id: int,
        roblox_username: str,
        roblox_user_id: Optional[int] = None,
        avatar_url: Optional[str] = None,
    ):
        await self._exec(
            "UPDATE players SET roblox_username = ?, roblox_user_id = ?, roblox_avatar_url = ? WHERE discord_id = ?",
            [roblox_username, roblox_user_id, avatar_url, discord_id],
        )

    async def is_registered(self, discord_id: int) -> bool:
        rs = await self._exec("SELECT roblox_username FROM players WHERE discord_id = ?", [discord_id])
        row = self._row(rs)
        return bool(row and row.get("roblox_username"))

    # ------------------------------------------------------------------
    # Parties
    # ------------------------------------------------------------------

    async def create_party(self, leader_id: int) -> int:
        rs = await self._exec("INSERT INTO parties (leader_id) VALUES (?)", [leader_id])
        party_id = rs.last_insert_rowid
        await self._exec(
            "INSERT INTO party_members (party_id, discord_id) VALUES (?, ?)",
            [party_id, leader_id],
        )
        return party_id

    async def get_party_by_id(self, party_id: int) -> Optional[Dict]:
        rs = await self._exec("SELECT * FROM parties WHERE party_id = ?", [party_id])
        return self._row(rs)

    async def get_player_party(self, discord_id: int) -> Optional[Dict]:
        rs = await self._exec(
            """SELECT p.* FROM parties p
               JOIN party_members pm ON p.party_id = pm.party_id
               WHERE pm.discord_id = ?""",
            [discord_id],
        )
        return self._row(rs)

    async def get_party_members(self, party_id: int) -> List[Dict]:
        rs = await self._exec(
            """SELECT p.* FROM players p
               JOIN party_members pm ON p.discord_id = pm.discord_id
               WHERE pm.party_id = ?""",
            [party_id],
        )
        return self._rows(rs)

    async def add_player_to_party(self, party_id: int, discord_id: int):
        await self._exec(
            "INSERT INTO party_members (party_id, discord_id) VALUES (?, ?)",
            [party_id, discord_id],
        )

    async def remove_player_from_party(self, discord_id: int):
        await self._exec("DELETE FROM party_members WHERE discord_id = ?", [discord_id])

    async def set_party_leader(self, party_id: int, leader_id: int):
        await self._exec(
            "UPDATE parties SET leader_id = ? WHERE party_id = ?",
            [leader_id, party_id],
        )

    async def delete_party(self, party_id: int):
        await self._client.batch([
            ("DELETE FROM party_members WHERE party_id = ?", [party_id]),
            ("DELETE FROM parties WHERE party_id = ?", [party_id]),
        ])

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    async def add_solo_player_to_queue(self, discord_id: int, elo: int) -> bool:
        try:
            await self._exec(
                "INSERT INTO queue_players (discord_id, elo) VALUES (?, ?)",
                [discord_id, elo],
            )
            return True
        except LibsqlError:
            return False

    async def add_party_to_queue(self, party_id: int):
        members = await self.get_party_members(party_id)
        stmts = [
            ("INSERT OR IGNORE INTO queue_players (discord_id, elo, party_id) VALUES (?, ?, ?)",
             [m["discord_id"], m["elo"], party_id])
            for m in members
        ]
        if stmts:
            await self._client.batch(stmts)

    async def remove_player_from_queue(self, discord_id: int):
        await self._exec("DELETE FROM queue_players WHERE discord_id = ?", [discord_id])

    async def remove_party_from_queue(self, party_id: int):
        await self._exec("DELETE FROM queue_players WHERE party_id = ?", [party_id])

    async def get_all_queued_players(self) -> List[Dict]:
        rs = await self._exec(
            """SELECT q.*, p.username, p.roblox_username, p.roblox_avatar_url
               FROM queue_players q
               JOIN players p ON q.discord_id = p.discord_id
               ORDER BY q.joined_at ASC"""
        )
        return self._rows(rs)

    async def is_player_in_queue(self, discord_id: int) -> bool:
        rs = await self._exec("SELECT 1 FROM queue_players WHERE discord_id = ?", [discord_id])
        return bool(rs.rows)

    async def is_party_in_queue(self, party_id: int) -> bool:
        rs = await self._exec("SELECT 1 FROM queue_players WHERE party_id = ?", [party_id])
        return bool(rs.rows)

    async def is_player_in_active_match(self, discord_id: int) -> bool:
        rs = await self._exec(
            """SELECT 1 FROM matches m
               JOIN pug_team_members ptm ON m.team1_id = ptm.team_id OR m.team2_id = ptm.team_id
               WHERE ptm.discord_id = ? AND m.status IN ('pending', 'reported')""",
            [discord_id],
        )
        return bool(rs.rows)

    # ------------------------------------------------------------------
    # Queue host info (server link + friend link entered when starting the queue)
    # ------------------------------------------------------------------

    async def set_queue_host_info(self, host_id: int, server_link: str, friend_link: str):
        """Upsert the single row tracking who started the queue and their links."""
        await self._exec(
            """INSERT INTO queue_host (id, host_id, server_link, friend_link, created_at)
               VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(id) DO UPDATE SET
                   host_id = excluded.host_id,
                   server_link = excluded.server_link,
                   friend_link = excluded.friend_link,
                   created_at = excluded.created_at""",
            [host_id, server_link, friend_link],
        )

    async def get_queue_host_info(self) -> Optional[Dict]:
        rs = await self._exec("SELECT * FROM queue_host WHERE id = 1")
        return self._row(rs)

    async def clear_queue_host_info(self):
        await self._exec("DELETE FROM queue_host WHERE id = 1")

    # ------------------------------------------------------------------
    # PUG teams & matches
    # ------------------------------------------------------------------

    async def create_pug_team(self, name: str, captain_id: int, discord_ids: List[int]) -> int:
        rs = await self._exec(
            "INSERT INTO pug_teams (name, captain_id) VALUES (?, ?)",
            [name, captain_id],
        )
        team_id = rs.last_insert_rowid
        member_stmts = [
            ("INSERT INTO pug_team_members (team_id, discord_id) VALUES (?, ?)", [team_id, d])
            for d in discord_ids
        ]
        if member_stmts:
            await self._client.batch(member_stmts)
        return team_id

    async def get_team_by_id(self, team_id: int) -> Optional[Dict]:
        rs = await self._exec("SELECT * FROM pug_teams WHERE team_id = ?", [team_id])
        return self._row(rs)

    async def get_team_members(self, team_id: int) -> List[Dict]:
        rs = await self._exec(
            """SELECT p.* FROM players p
               JOIN pug_team_members ptm ON p.discord_id = ptm.discord_id
               WHERE ptm.team_id = ?""",
            [team_id],
        )
        return self._rows(rs)

    async def update_team_stats(self, team_id: int, elo: int, won: bool):
        if won:
            await self._exec("UPDATE pug_teams SET elo = ?, wins = wins + 1 WHERE team_id = ?", [elo, team_id])
        else:
            await self._exec("UPDATE pug_teams SET elo = ?, losses = losses + 1 WHERE team_id = ?", [elo, team_id])

    async def create_match(self, team1_id: int, team2_id: int, team1_elo: int, team2_elo: int) -> int:
        season_id = await self.get_active_season()
        rs = await self._exec(
            """INSERT INTO matches
               (team1_id, team2_id, team1_elo_before, team2_elo_before, season_id, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            [team1_id, team2_id, team1_elo, team2_elo, season_id],
        )
        return rs.last_insert_rowid

    async def get_match(self, match_id: int) -> Optional[Dict]:
        rs = await self._exec("SELECT * FROM matches WHERE match_id = ?", [match_id])
        return self._row(rs)

    async def update_match_report(self, match_id: int, winner_id: int, reported_by: int):
        await self._exec(
            "UPDATE matches SET winner_id = ?, reported_by = ?, status = 'reported' WHERE match_id = ?",
            [winner_id, reported_by, match_id],
        )

    async def confirm_match(
        self,
        match_id: int,
        confirmed_by: int,
        team1_elo_after: int,
        team2_elo_after: int,
        elo_change: int,
    ):
        await self._exec(
            """UPDATE matches
               SET confirmed_by = ?, status = 'confirmed',
                   team1_elo_after = ?, team2_elo_after = ?, elo_change = ?,
                   completed_at = CURRENT_TIMESTAMP
               WHERE match_id = ?""",
            [confirmed_by, team1_elo_after, team2_elo_after, elo_change, match_id],
        )

    async def get_team_matches(self, team_id: int, limit: int = 10) -> List[Dict]:
        rs = await self._exec(
            """SELECT * FROM matches
               WHERE (team1_id = ? OR team2_id = ?) AND status = 'confirmed'
               ORDER BY completed_at DESC LIMIT ?""",
            [team_id, team_id, limit],
        )
        return self._rows(rs)

    async def get_active_team_for_player(self, discord_id: int) -> Optional[Dict]:
        """Find the ephemeral PUG team a player is currently on in an unresolved match."""
        rs = await self._exec(
            """SELECT t.* FROM pug_teams t
               JOIN pug_team_members ptm ON t.team_id = ptm.team_id
               JOIN matches m ON (m.team1_id = t.team_id OR m.team2_id = t.team_id)
               WHERE ptm.discord_id = ? AND m.status IN ('pending', 'reported')
               ORDER BY m.created_at DESC LIMIT 1""",
            [discord_id],
        )
        return self._row(rs)

    async def get_player_match_history(self, discord_id: int, limit: int = 10) -> List[Dict]:
        """Get a player's confirmed match history across all their PUG teams."""
        rs = await self._exec(
            """SELECT DISTINCT m.* FROM matches m
               JOIN pug_team_members ptm ON (ptm.team_id = m.team1_id OR ptm.team_id = m.team2_id)
               WHERE ptm.discord_id = ? AND m.status = 'confirmed'
               ORDER BY m.completed_at DESC LIMIT ?""",
            [discord_id, limit],
        )
        return self._rows(rs)

    # ------------------------------------------------------------------
    # Map veto & queue UI
    # ------------------------------------------------------------------

    async def save_map_ban(self, match_id: int, team_id: int, map_name: str, veto_order: int):
        await self._exec(
            "INSERT INTO map_vetos (match_id, team_id, map_name, veto_order) VALUES (?, ?, ?, ?)",
            [match_id, team_id, map_name, veto_order],
        )

    async def get_match_vetos(self, match_id: int) -> List[Dict]:
        rs = await self._exec(
            "SELECT * FROM map_vetos WHERE match_id = ? ORDER BY veto_order ASC", [match_id]
        )
        return self._rows(rs)

    async def set_match_map(self, match_id: int, map_name: str):
        await self._exec("UPDATE matches SET map_played = ? WHERE match_id = ?", [map_name, match_id])

    async def save_queue_message(self, message_id: int, channel_id: int, guild_id: int):
        await self._exec(
            "INSERT OR REPLACE INTO queue_messages (message_id, channel_id, guild_id) VALUES (?, ?, ?)",
            [message_id, channel_id, guild_id],
        )

    async def get_queue_messages(self) -> List[Dict]:
        rs = await self._exec("SELECT * FROM queue_messages")
        return self._rows(rs)

    async def delete_queue_message(self, message_id: int):
        await self._exec("DELETE FROM queue_messages WHERE message_id = ?", [message_id])

    # ------------------------------------------------------------------
    # Match channels
    # ------------------------------------------------------------------

    async def save_match_channels(
        self,
        match_id: int,
        guild_id: int,
        category_id: Optional[int],
        lobby_channel_id: Optional[int],
        team1_voice_id: Optional[int],
        team2_voice_id: Optional[int],
    ):
        await self._exec(
            """INSERT OR REPLACE INTO match_channels
               (match_id, guild_id, category_id, lobby_channel_id, team1_voice_id, team2_voice_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [match_id, guild_id, category_id, lobby_channel_id, team1_voice_id, team2_voice_id],
        )

    async def get_match_channels(self, match_id: int) -> Optional[Dict]:
        rs = await self._exec("SELECT * FROM match_channels WHERE match_id = ?", [match_id])
        return self._row(rs)

    async def set_match_server_link(self, match_id: int, link: str):
        await self._exec(
            "UPDATE match_channels SET server_link = ? WHERE match_id = ?", [link, match_id]
        )

    async def get_finished_match_channels(self) -> List[Dict]:
        rs = await self._exec(
            """SELECT mc.* FROM match_channels mc
               JOIN matches m ON mc.match_id = m.match_id
               WHERE m.status IN ('confirmed', 'cancelled')
                  OR mc.created_at <= datetime('now', '-6 hours')"""
        )
        return self._rows(rs)

    async def delete_match_channels_record(self, match_id: int):
        await self._exec("DELETE FROM match_channels WHERE match_id = ?", [match_id])

    # ------------------------------------------------------------------
    # Season archives
    # ------------------------------------------------------------------

    async def get_top_players_for_archive(self, limit: int = 100) -> List[Dict]:
        return await self.get_top_players(limit)

    # ------------------------------------------------------------------
    # Queue cooldowns (anti-abuse)
    # ------------------------------------------------------------------

    async def set_queue_cooldown(self, discord_id: int):
        """Record the timestamp when a player left the queue."""
        await self._exec(
            "INSERT OR REPLACE INTO queue_cooldowns (discord_id, left_at) VALUES (?, CURRENT_TIMESTAMP)",
            [discord_id],
        )

    async def get_queue_cooldown_remaining(self, discord_id: int) -> int:
        """
        Returns how many seconds remain on the cooldown, or 0 if the player
        is free to re-join. Cooldown duration is Config.QUEUE_LEAVE_COOLDOWN_SECONDS.
        """
        rs = await self._exec(
            "SELECT left_at FROM queue_cooldowns WHERE discord_id = ?",
            [discord_id],
        )
        if not rs.rows:
            return 0
        from datetime import datetime, timezone
        left_at_str = rs.rows[0][0]
        left_at = datetime.fromisoformat(left_at_str)
        # Turso stores CURRENT_TIMESTAMP as naive UTC
        if left_at.tzinfo is None:
            left_at = left_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - left_at).total_seconds()
        remaining = Config.QUEUE_LEAVE_COOLDOWN_SECONDS - elapsed
        return max(0, int(remaining))

    async def clear_queue_cooldown(self, discord_id: int):
        await self._exec("DELETE FROM queue_cooldowns WHERE discord_id = ?", [discord_id])

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------

    async def open_dispute(self, match_id: int, opened_by: int, reason: str) -> int:
        rs = await self._exec(
            """INSERT INTO match_disputes (match_id, opened_by, reason)
               VALUES (?, ?, ?)""",
            [match_id, opened_by, reason],
        )
        return rs.last_insert_rowid

    async def get_dispute(self, match_id: int) -> Optional[Dict]:
        rs = await self._exec(
            "SELECT * FROM match_disputes WHERE match_id = ?", [match_id]
        )
        return self._row(rs)

    async def get_all_open_disputes(self) -> List[Dict]:
        rs = await self._exec(
            """SELECT md.*, m.team1_id, m.team2_id, m.winner_id, m.status,
                      m.team1_elo_before, m.team2_elo_before, m.map_played
               FROM match_disputes md
               JOIN matches m ON md.match_id = m.match_id
               WHERE md.resolved_by IS NULL
               ORDER BY md.created_at ASC"""
        )
        return self._rows(rs)

    async def resolve_dispute(self, match_id: int, resolved_by: int, resolution: str):
        await self._exec(
            """UPDATE match_disputes
               SET resolved_by = ?, resolution = ?, resolved_at = CURRENT_TIMESTAMP
               WHERE match_id = ?""",
            [resolved_by, resolution, match_id],
        )

    async def admin_override_match_winner(
        self,
        match_id: int,
        new_winner_id: int,
        admin_id: int,
        team1_elo_after: int,
        team2_elo_after: int,
        elo_change: int,
    ):
        """Force-set the winner and mark match as confirmed with admin override flag."""
        await self._exec(
            """UPDATE matches
               SET winner_id = ?, status = 'confirmed',
                   confirmed_by = ?, team1_elo_after = ?, team2_elo_after = ?,
                   elo_change = ?, completed_at = CURRENT_TIMESTAMP
               WHERE match_id = ?""",
            [new_winner_id, admin_id, team1_elo_after, team2_elo_after, elo_change, match_id],
        )

    # ------------------------------------------------------------------
    # Match player statistics (OCR-populated)
    # ------------------------------------------------------------------

    async def save_match_player_stats(self, rows: List[Dict], confidence: str):
        """
        Bulk-insert per-player stats extracted from a scoreboard screenshot.
        Also resolves each player's discord_id from their roblox_username if possible.
        """
        if not rows:
            return

        # Try to resolve roblox_username -> discord_id for each row
        stmts = []
        for row in rows:
            # Look up discord_id by roblox_username (case-insensitive)
            rs = await self._exec(
                "SELECT discord_id FROM players WHERE LOWER(roblox_username) = LOWER(?)",
                [row["roblox_username"]],
            )
            discord_id = self._scalar(rs) if rs.rows else None

            stmts.append((
                """INSERT OR REPLACE INTO match_player_stats
                   (match_id, discord_id, roblox_username, display_name, team_side,
                    kills, deaths, assists, mvps, score, money, ocr_confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    row["match_id"], discord_id, row["roblox_username"],
                    row["display_name"], row["team_side"],
                    row["kills"], row["deaths"], row["assists"],
                    row["mvps"], row["score"], row["money"], confidence,
                ],
            ))

        await self._client.batch(stmts)

    async def get_match_player_stats(self, match_id: int) -> List[Dict]:
        """All player stat rows for a given match, ordered by score desc."""
        rs = await self._exec(
            """SELECT * FROM match_player_stats
               WHERE match_id = ? ORDER BY score DESC, kills DESC""",
            [match_id],
        )
        return self._rows(rs)

    async def update_career_stats_from_match(self, match_id: int):
        """
        Roll the per-match stats for `match_id` into each player's career
        aggregate. Only runs for players whose discord_id could be resolved
        (i.e. they were registered when the screenshot was parsed).
        Call this once, after save_match_player_stats, when the match is confirmed.
        """
        rows = await self.get_match_player_stats(match_id)
        stmts = []
        for row in rows:
            if not row.get("discord_id"):
                continue
            stmts.append((
                """INSERT INTO player_career_stats
                   (discord_id, total_kills, total_deaths, total_assists,
                    total_mvps, total_score, matches_with_stats)
                   VALUES (?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(discord_id) DO UPDATE SET
                       total_kills    = total_kills    + excluded.total_kills,
                       total_deaths   = total_deaths   + excluded.total_deaths,
                       total_assists  = total_assists  + excluded.total_assists,
                       total_mvps     = total_mvps     + excluded.total_mvps,
                       total_score    = total_score    + excluded.total_score,
                       matches_with_stats = matches_with_stats + 1""",
                [
                    row["discord_id"],
                    row["kills"], row["deaths"], row["assists"],
                    row["mvps"], row["score"],
                ],
            ))
        if stmts:
            await self._client.batch(stmts)

    async def get_player_career_stats(self, discord_id: int) -> Optional[Dict]:
        rs = await self._exec(
            "SELECT * FROM player_career_stats WHERE discord_id = ?", [discord_id]
        )
        return self._row(rs)

    async def get_player_recent_match_stats(self, discord_id: int, limit: int = 5) -> List[Dict]:
        """Last N match stat rows for a player, newest first."""
        rs = await self._exec(
            """SELECT mps.*, m.map_played, m.completed_at, m.status
               FROM match_player_stats mps
               JOIN matches m ON mps.match_id = m.match_id
               WHERE mps.discord_id = ? AND m.status = 'confirmed'
               ORDER BY m.completed_at DESC LIMIT ?""",
            [discord_id, limit],
        )
        return self._rows(rs)