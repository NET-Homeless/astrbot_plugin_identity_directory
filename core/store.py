"""SQLite persistence layer for the identity directory.

Design notes:
- WAL journal + busy_timeout for safe concurrent access from the event loop
  and web handlers.
- Schema versioning via PRAGMA user_version with ordered migrations.
- All writes go through DirectoryStore methods; no SQL leaks upward.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Iterable
from pathlib import Path

from .models import (
    Account,
    AccountView,
    Alias,
    AliasSource,
    Membership,
    Person,
    PersonView,
)

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS persons (
    person_id      TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    notes          TEXT NOT NULL DEFAULT '',
    tags           TEXT NOT NULL DEFAULT '',          -- comma-separated
    is_bot         INTEGER NOT NULL DEFAULT 0,
    is_archived    INTEGER NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id       TEXT PRIMARY KEY,
    platform         TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    username         TEXT NOT NULL DEFAULT '',
    person_id        TEXT REFERENCES persons(person_id) ON DELETE SET NULL,
    first_seen       REAL NOT NULL,
    last_seen        REAL NOT NULL,
    UNIQUE (platform, platform_user_id)
);
CREATE INDEX IF NOT EXISTS idx_accounts_person ON accounts(person_id);

CREATE TABLE IF NOT EXISTS memberships (
    membership_id TEXT PRIMARY KEY,
    account_id    TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    group_id      TEXT NOT NULL,
    current_card  TEXT NOT NULL DEFAULT '',
    first_seen    REAL NOT NULL,
    last_seen     REAL NOT NULL,
    UNIQUE (account_id, group_id)
);
CREATE INDEX IF NOT EXISTS idx_memberships_group ON memberships(group_id);

CREATE TABLE IF NOT EXISTS aliases (
    alias_id   TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    platform   TEXT NOT NULL,
    group_id   TEXT,                                 -- NULL = platform-wide
    source     TEXT NOT NULL DEFAULT 'observed',
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    UNIQUE (account_id, name, platform, group_id)
);
CREATE INDEX IF NOT EXISTS idx_aliases_name ON aliases(name);
CREATE INDEX IF NOT EXISTS idx_aliases_account ON aliases(account_id);
"""

_MIGRATIONS: dict[int, str] = {1: _SCHEMA_V1}


def _new_id() -> str:
    return uuid.uuid4().hex


class DirectoryStore:
    """Synchronous SQLite store. Calls are short; wrap in asyncio.to_thread
    at the service layer to keep the event loop responsive."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            detect_types=0,
            check_same_thread=False,
            isolation_level=None,  # explicit transactions
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ #
    # migrations
    # ------------------------------------------------------------------ #

    def _migrate(self) -> None:
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for version in range(current + 1, SCHEMA_VERSION + 1):
            script = _MIGRATIONS[version]
            with self._conn:
                self._conn.executescript(script)
                self._conn.execute(f"PRAGMA user_version={version}")

    # ------------------------------------------------------------------ #
    # row mapping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _person_from(row: sqlite3.Row) -> Person:
        tags = tuple(t for t in row["tags"].split(",") if t)
        return Person(
            person_id=row["person_id"],
            canonical_name=row["canonical_name"],
            notes=row["notes"],
            tags=tags,
            is_bot=bool(row["is_bot"]),
            is_archived=bool(row["is_archived"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _account_from(row: sqlite3.Row) -> Account:
        return Account(
            account_id=row["account_id"],
            platform=row["platform"],
            platform_user_id=row["platform_user_id"],
            username=row["username"],
            person_id=row["person_id"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
        )

    @staticmethod
    def _membership_from(row: sqlite3.Row) -> Membership:
        return Membership(
            membership_id=row["membership_id"],
            account_id=row["account_id"],
            group_id=row["group_id"],
            current_card=row["current_card"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
        )

    @staticmethod
    def _alias_from(row: sqlite3.Row) -> Alias:
        return Alias(
            alias_id=row["alias_id"],
            account_id=row["account_id"],
            name=row["name"],
            platform=row["platform"],
            group_id=row["group_id"],
            source=AliasSource(row["source"]),
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
        )

    # ------------------------------------------------------------------ #
    # persons
    # ------------------------------------------------------------------ #

    def create_person(
        self,
        canonical_name: str,
        *,
        notes: str = "",
        tags: Iterable[str] = (),
        is_bot: bool = False,
    ) -> Person:
        """Insert a new person. Duplicate display names are allowed — two
        senders sharing a name are usually different people, so stub persons
        are never reused. Merging is an explicit operator action."""
        now = time.time()
        person = Person(
            person_id=_new_id(),
            canonical_name=canonical_name,
            notes=notes,
            tags=tuple(tags),
            is_bot=is_bot,
            created_at=now,
            updated_at=now,
        )
        with self._conn:
            self._conn.execute(
                "INSERT INTO persons(person_id, canonical_name, notes, tags, is_bot,"
                " is_archived, created_at, updated_at) VALUES(?,?,?,?,?,0,?,?)",
                (
                    person.person_id,
                    person.canonical_name,
                    person.notes,
                    ",".join(person.tags),
                    int(person.is_bot),
                    person.created_at,
                    person.updated_at,
                ),
            )
        return person

    def update_person(
        self,
        person_id: str,
        *,
        canonical_name: str | None = None,
        notes: str | None = None,
        tags: Iterable[str] | None = None,
        is_bot: bool | None = None,
        is_archived: bool | None = None,
    ) -> Person | None:
        current = self.get_person(person_id)
        if current is None:
            return None
        new_name = canonical_name if canonical_name is not None else current.canonical_name
        new_notes = notes if notes is not None else current.notes
        new_tags = tuple(tags) if tags is not None else current.tags
        new_bot = is_bot if is_bot is not None else current.is_bot
        new_arch = is_archived if is_archived is not None else current.is_archived
        now = time.time()
        with self._conn:
            self._conn.execute(
                "UPDATE persons SET canonical_name=?, notes=?, tags=?, is_bot=?,"
                " is_archived=?, updated_at=? WHERE person_id=?",
                (new_name, new_notes, ",".join(new_tags), int(new_bot), int(new_arch), now, person_id),
            )
        return self.get_person(person_id)

    def get_person(self, person_id: str) -> Person | None:
        row = self._conn.execute("SELECT * FROM persons WHERE person_id=?", (person_id,)).fetchone()
        return self._person_from(row) if row else None

    def delete_person(self, person_id: str) -> bool:
        """Deletes person; linked accounts become unlinked (ON DELETE SET NULL)."""
        with self._conn:
            cur = self._conn.execute("DELETE FROM persons WHERE person_id=?", (person_id,))
        return cur.rowcount > 0

    def list_persons(
        self,
        *,
        query: str = "",
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Person], int]:
        where = [] if include_archived else ["is_archived=0"]
        params: list[object] = []
        if query:
            where.append("(canonical_name LIKE ? OR notes LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = self._conn.execute(f"SELECT COUNT(*) FROM persons {clause}", params).fetchone()[0]
        rows = self._conn.execute(
            f"SELECT * FROM persons {clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [self._person_from(r) for r in rows], total

    def get_person_view(self, person_id: str) -> PersonView | None:
        person = self.get_person(person_id)
        if person is None:
            return None
        accounts = self.list_accounts(person_id=person_id)
        views = tuple(
            AccountView(
                account=a,
                memberships=tuple(self.list_memberships(a.account_id)),
                alias_count=self.count_aliases(a.account_id),
            )
            for a in accounts
        )
        return PersonView(person=person, accounts=views)

    # ------------------------------------------------------------------ #
    # accounts
    # ------------------------------------------------------------------ #

    def upsert_account(
        self,
        platform: str,
        platform_user_id: str,
        *,
        username: str = "",
        touch: bool = True,
    ) -> tuple[Account, bool]:
        """Insert if missing, else update username/last_seen. Returns (account, created)."""
        now = time.time()
        existing = self.get_account_by_platform(platform, platform_user_id)
        if existing is None:
            account = Account(
                account_id=_new_id(),
                platform=platform,
                platform_user_id=platform_user_id,
                username=username,
                first_seen=now,
                last_seen=now,
            )
            with self._conn:
                self._conn.execute(
                    "INSERT INTO accounts(account_id, platform, platform_user_id, username,"
                    " person_id, first_seen, last_seen) VALUES(?,?,?,?,NULL,?,?)",
                    (
                        account.account_id,
                        account.platform,
                        account.platform_user_id,
                        account.username,
                        account.first_seen,
                        account.last_seen,
                    ),
                )
            return account, True

        if touch or (username and username != existing.username):
            with self._conn:
                self._conn.execute(
                    "UPDATE accounts SET last_seen=?, username=CASE WHEN ?='' THEN username ELSE ? END"
                    " WHERE account_id=?",
                    (now, username, username, existing.account_id),
                )
            existing = self.get_account(existing.account_id) or existing
        return existing, False

    def get_account(self, account_id: str) -> Account | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
        return self._account_from(row) if row else None

    def get_account_by_platform(self, platform: str, platform_user_id: str) -> Account | None:
        row = self._conn.execute(
            "SELECT * FROM accounts WHERE platform=? AND platform_user_id=?",
            (platform, platform_user_id),
        ).fetchone()
        return self._account_from(row) if row else None

    def list_accounts(
        self,
        *,
        person_id: str | None = None,
        unlinked: bool = False,
        platform: str | None = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[Account]:
        where: list[str] = []
        params: list[object] = []
        if person_id is not None:
            where.append("person_id=?")
            params.append(person_id)
        if unlinked:
            where.append("person_id IS NULL")
        if platform:
            where.append("platform=?")
            params.append(platform)
        if query:
            where.append("(platform_user_id LIKE ? OR username LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._conn.execute(
            f"SELECT * FROM accounts {clause} ORDER BY last_seen DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [self._account_from(r) for r in rows]

    def link_account(self, account_id: str, person_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE accounts SET person_id=? WHERE account_id=?",
                (person_id, account_id),
            )
        return cur.rowcount > 0

    def unlink_account(self, account_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute("UPDATE accounts SET person_id=NULL WHERE account_id=?", (account_id,))
        return cur.rowcount > 0

    def delete_account(self, account_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute("DELETE FROM accounts WHERE account_id=?", (account_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # memberships
    # ------------------------------------------------------------------ #

    def upsert_membership(
        self,
        account_id: str,
        group_id: str,
        *,
        card: str = "",
    ) -> tuple[Membership, bool]:
        """Insert if missing; update card + last_seen otherwise. Returns (membership, created)."""
        now = time.time()
        row = self._conn.execute(
            "SELECT * FROM memberships WHERE account_id=? AND group_id=?",
            (account_id, group_id),
        ).fetchone()
        if row is None:
            membership = Membership(
                membership_id=_new_id(),
                account_id=account_id,
                group_id=group_id,
                current_card=card,
                first_seen=now,
                last_seen=now,
            )
            with self._conn:
                self._conn.execute(
                    "INSERT INTO memberships(membership_id, account_id, group_id, current_card,"
                    " first_seen, last_seen) VALUES(?,?,?,?,?,?)",
                    (
                        membership.membership_id,
                        membership.account_id,
                        membership.group_id,
                        membership.current_card,
                        membership.first_seen,
                        membership.last_seen,
                    ),
                )
            return membership, True

        membership = self._membership_from(row)
        new_card = card if card else membership.current_card
        with self._conn:
            self._conn.execute(
                "UPDATE memberships SET last_seen=?, current_card=? WHERE membership_id=?",
                (now, new_card, membership.membership_id),
            )
        return (
            Membership(
                membership_id=membership.membership_id,
                account_id=membership.account_id,
                group_id=membership.group_id,
                current_card=new_card,
                first_seen=membership.first_seen,
                last_seen=now,
            ),
            False,
        )

    def list_memberships(self, account_id: str) -> list[Membership]:
        rows = self._conn.execute(
            "SELECT * FROM memberships WHERE account_id=? ORDER BY last_seen DESC",
            (account_id,),
        ).fetchall()
        return [self._membership_from(r) for r in rows]

    def update_membership_card(self, membership_id: str, card: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE memberships SET current_card=?, last_seen=? WHERE membership_id=?",
                (card, time.time(), membership_id),
            )
        return cur.rowcount > 0

    def delete_membership(self, membership_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute("DELETE FROM memberships WHERE membership_id=?", (membership_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # aliases
    # ------------------------------------------------------------------ #

    def record_alias(
        self,
        account_id: str,
        name: str,
        platform: str,
        *,
        group_id: str | None = None,
        source: AliasSource = AliasSource.OBSERVED,
    ) -> Alias | None:
        """Insert or refresh an alias. Returns None for empty names."""
        name = name.strip()
        if not name:
            return None
        now = time.time()
        row = self._conn.execute(
            "SELECT * FROM aliases WHERE account_id=? AND name=? AND platform=?"
            " AND (group_id IS ? OR group_id=?)",
            (account_id, name, platform, group_id, group_id),
        ).fetchone()
        if row is not None:
            with self._conn:
                self._conn.execute("UPDATE aliases SET last_seen=? WHERE alias_id=?", (now, row["alias_id"]))
            return self._alias_from(row)
        alias = Alias(
            alias_id=_new_id(),
            account_id=account_id,
            name=name,
            platform=platform,
            group_id=group_id,
            source=source,
            first_seen=now,
            last_seen=now,
        )
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO aliases(alias_id, account_id, name, platform, group_id, source,"
                    " first_seen, last_seen) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        alias.alias_id,
                        alias.account_id,
                        alias.name,
                        alias.platform,
                        alias.group_id,
                        str(alias.source),
                        alias.first_seen,
                        alias.last_seen,
                    ),
                )
        except sqlite3.IntegrityError:
            return None
        return alias

    def list_aliases(
        self,
        account_id: str | None = None,
        *,
        platform: str | None = None,
        name: str | None = None,
    ) -> list[Alias]:
        where: list[str] = []
        params: list[object] = []
        if account_id:
            where.append("account_id=?")
            params.append(account_id)
        if platform:
            where.append("platform=?")
            params.append(platform)
        if name:
            where.append("name=?")
            params.append(name)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._conn.execute(
            f"SELECT * FROM aliases {clause} ORDER BY last_seen DESC", params
        ).fetchall()
        return [self._alias_from(r) for r in rows]

    def count_aliases(self, account_id: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM aliases WHERE account_id=?", (account_id,)
        ).fetchone()[0]

    def delete_alias(self, alias_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute("DELETE FROM aliases WHERE alias_id=?", (alias_id,))
        return cur.rowcount > 0

    def find_aliases_by_name(self, name: str, platform: str | None = None) -> list[Alias]:
        return self.list_aliases(platform=platform, name=name)

    # ------------------------------------------------------------------ #
    # merge
    # ------------------------------------------------------------------ #

    def merge_persons(self, source_person_id: str, target_person_id: str) -> bool:
        """Move all accounts from source person to target, delete source."""
        return self.merge_multiple_persons([source_person_id], target_person_id) > 0

    def merge_multiple_persons(self, source_person_ids: Iterable[str], target_person_id: str) -> int:
        """Move all accounts from multiple source persons into target, delete sources."""
        if self.get_person(target_person_id) is None:
            return 0
        valid_sources = [
            sid
            for sid in set(source_person_ids)
            if sid and sid != target_person_id and self.get_person(sid) is not None
        ]
        if not valid_sources:
            return 0
        now = time.time()
        with self._conn:
            for sid in valid_sources:
                self._conn.execute(
                    "UPDATE accounts SET person_id=? WHERE person_id=?",
                    (target_person_id, sid),
                )
                self._conn.execute("DELETE FROM persons WHERE person_id=?", (sid,))
            self._conn.execute(
                "UPDATE persons SET updated_at=? WHERE person_id=?",
                (now, target_person_id),
            )
        return len(valid_sources)

    # ------------------------------------------------------------------ #
    # stats
    # ------------------------------------------------------------------ #

    def stats(self) -> dict[str, int]:
        def count(table: str, extra: str = "") -> int:
            return self._conn.execute(f"SELECT COUNT(*) FROM {table} {extra}").fetchone()[0]

        return {
            "persons": count("persons", "WHERE is_archived=0"),
            "accounts": count("accounts"),
            "unlinked_accounts": count("accounts", "WHERE person_id IS NULL"),
            "memberships": count("memberships"),
            "aliases": count("aliases"),
        }
