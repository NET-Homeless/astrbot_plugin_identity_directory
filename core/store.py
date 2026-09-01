"""SQLite persistence for the identity directory.

The store is deliberately synchronous. ``DirectoryService`` runs every store
operation on one dedicated executor, so a single SQLite connection is never
used concurrently by the event loop, web handlers, or background observers.
Composite writes use explicit ``BEGIN IMMEDIATE`` transactions.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import DirectoryConflictError, DirectoryNotFoundError
from .models import (
    Account,
    AccountView,
    Alias,
    AliasSource,
    Membership,
    Person,
    PersonView,
    Resolution,
)

SCHEMA_VERSION = 4

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS persons (
    person_id      TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    notes          TEXT NOT NULL DEFAULT '',
    tags           TEXT NOT NULL DEFAULT '',
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
    group_id   TEXT,
    source     TEXT NOT NULL DEFAULT 'observed',
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    UNIQUE (account_id, name, platform, group_id)
);
CREATE INDEX IF NOT EXISTS idx_aliases_name ON aliases(name);
CREATE INDEX IF NOT EXISTS idx_aliases_account ON aliases(account_id);
"""


def _new_id() -> str:
    return uuid.uuid4().hex


def _text(value: object, *, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} must not be empty")
    return result


def _escape_like(value: str) -> str:
    """Escape user input before embedding it in a SQLite LIKE pattern."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DirectoryStore:
    """Synchronous SQLite store; async callers must serialize access above it."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            detect_types=0,
            check_same_thread=False,
            isolation_level=None,
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
    # migrations and transactions
    # ------------------------------------------------------------------ #

    def _migrate(self) -> None:
        current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"unsupported directory schema version: {current}")

        if current < 1:
            self._conn.executescript(_SCHEMA_V1)
            self._conn.execute("PRAGMA user_version=1")
            current = 1

        if current < 2:
            self._migrate_to_v2()
        if current < 3:
            self._migrate_to_v3()
        if current < 4:
            self._migrate_to_v4()

    def _migrate_to_v3(self) -> None:
        """Merge legacy fallback-instance accounts into a real platform instance.

        Version 2 introduced ``platform_instance_id`` and migrated every old
        account with ``platform_instance_id = platform``. Once AstrBot exposes
        the configured instance ID, the same sender can therefore appear twice.
        A legacy row is safe to migrate only when exactly one non-fallback
        instance exists for the same ``(platform, platform_user_id)``.
        """
        with self._transaction():
            rows = self._conn.execute(
                "SELECT platform, platform_user_id, "
                "MIN(CASE WHEN platform_instance_id=platform THEN account_id END) AS legacy_id, "
                "MIN(CASE WHEN platform_instance_id<>platform THEN account_id END) AS current_id, "
                "SUM(CASE WHEN platform_instance_id=platform THEN 1 ELSE 0 END) AS legacy_count, "
                "SUM(CASE WHEN platform_instance_id<>platform THEN 1 ELSE 0 END) AS current_count "
                "FROM accounts GROUP BY platform, platform_user_id "
                "HAVING legacy_count=1 AND current_count=1"
            ).fetchall()
            for row in rows:
                self._merge_account_rows(str(row["legacy_id"]), str(row["current_id"]))
            self._conn.execute("PRAGMA user_version=3")

    def _migrate_to_v4(self) -> None:
        """Add self_persona column to persons table."""
        with self._transaction():
            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(persons)").fetchall()}
            if "self_persona" not in columns:
                self._conn.execute("ALTER TABLE persons ADD COLUMN self_persona TEXT NOT NULL DEFAULT ''")
            self._conn.execute("PRAGMA user_version=4")

    def _merge_account_rows(self, source_account_id: str, target_account_id: str) -> None:
        """Move all source relations into target, then delete the source account."""
        source = self._get_account(source_account_id)
        target = self._get_account(target_account_id)
        if source is None or target is None:
            raise DirectoryNotFoundError("account not found")
        if (source.platform, source.platform_user_id) != (target.platform, target.platform_user_id):
            raise DirectoryConflictError("accounts do not represent the same platform sender")

        memberships = self._conn.execute(
            "SELECT * FROM memberships WHERE account_id=? ORDER BY first_seen, membership_id",
            (source_account_id,),
        ).fetchall()
        for row in memberships:
            existing = self._conn.execute(
                "SELECT * FROM memberships WHERE account_id=? AND group_id=?",
                (target_account_id, row["group_id"]),
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    "UPDATE memberships SET account_id=? WHERE membership_id=?",
                    (target_account_id, row["membership_id"]),
                )
                continue
            source_is_newer = float(row["last_seen"]) > float(existing["last_seen"])
            current_card = (
                row["current_card"] if source_is_newer and row["current_card"] else existing["current_card"]
            )
            self._conn.execute(
                "UPDATE memberships SET current_card=?, first_seen=?, last_seen=? WHERE membership_id=?",
                (
                    current_card,
                    min(float(row["first_seen"]), float(existing["first_seen"])),
                    max(float(row["last_seen"]), float(existing["last_seen"])),
                    existing["membership_id"],
                ),
            )
            self._conn.execute("DELETE FROM memberships WHERE membership_id=?", (row["membership_id"],))

        aliases = self._conn.execute(
            "SELECT * FROM aliases WHERE account_id=? ORDER BY first_seen, alias_id",
            (source_account_id,),
        ).fetchall()
        for row in aliases:
            existing = self._conn.execute(
                "SELECT * FROM aliases WHERE account_id=? AND name=? AND platform=? "
                "AND (group_id IS ? OR group_id=?)",
                (target_account_id, row["name"], row["platform"], row["group_id"], row["group_id"]),
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    "UPDATE aliases SET account_id=? WHERE alias_id=?",
                    (target_account_id, row["alias_id"]),
                )
                continue
            source_kind = str(row["source"])
            target_kind = str(existing["source"])
            merged_kind = AliasSource.MANUAL.value if "manual" in {source_kind, target_kind} else target_kind
            self._conn.execute(
                "UPDATE aliases SET source=?, first_seen=?, last_seen=? WHERE alias_id=?",
                (
                    merged_kind,
                    min(float(row["first_seen"]), float(existing["first_seen"])),
                    max(float(row["last_seen"]), float(existing["last_seen"])),
                    existing["alias_id"],
                ),
            )
            self._conn.execute("DELETE FROM aliases WHERE alias_id=?", (row["alias_id"],))

        if source.person_id and target.person_id and source.person_id != target.person_id:
            now = time.time()
            self._conn.execute(
                "UPDATE accounts SET person_id=? WHERE person_id=?",
                (source.person_id, target.person_id),
            )
            self._conn.execute(
                "UPDATE person_redirects SET target_person_id=? WHERE target_person_id=?",
                (source.person_id, target.person_id),
            )
            self._conn.execute(
                "INSERT INTO person_redirects(source_person_id, target_person_id, merged_at) VALUES(?,?,?)",
                (target.person_id, source.person_id, now),
            )
            self._conn.execute("DELETE FROM persons WHERE person_id=?", (target.person_id,))
            self._conn.execute(
                "UPDATE persons SET updated_at=? WHERE person_id=?",
                (now, source.person_id),
            )
        elif target.person_id is None and source.person_id is not None:
            self._conn.execute(
                "UPDATE accounts SET person_id=? WHERE account_id=?",
                (source.person_id, target_account_id),
            )
        self._conn.execute(
            "UPDATE accounts SET username=CASE WHEN username='' THEN ? ELSE username END, "
            "first_seen=?, last_seen=?, suppress_auto_stub=? WHERE account_id=?",
            (
                source.username,
                min(source.first_seen, target.first_seen),
                max(source.last_seen, target.last_seen),
                int(source.suppress_auto_stub and target.suppress_auto_stub),
                target_account_id,
            ),
        )
        self._conn.execute("DELETE FROM accounts WHERE account_id=?", (source_account_id,))

    def _migrate_to_v2(self) -> None:
        """Rebuild accounts so the old two-column UNIQUE constraint disappears."""
        self._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute("DROP TABLE IF EXISTS accounts_v2")
            self._conn.execute(
                """
                CREATE TABLE accounts_v2 (
                    account_id          TEXT PRIMARY KEY,
                    platform            TEXT NOT NULL,
                    platform_instance_id TEXT NOT NULL,
                    platform_user_id    TEXT NOT NULL,
                    username            TEXT NOT NULL DEFAULT '',
                    person_id           TEXT REFERENCES persons(person_id) ON DELETE SET NULL,
                    first_seen          REAL NOT NULL,
                    last_seen           REAL NOT NULL,
                    suppress_auto_stub  INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (platform, platform_instance_id, platform_user_id)
                )
                """
            )
            self._conn.execute(
                """
                INSERT INTO accounts_v2(
                    account_id, platform, platform_instance_id, platform_user_id,
                    username, person_id, first_seen, last_seen, suppress_auto_stub
                )
                SELECT account_id, platform, platform, platform_user_id,
                       username, person_id, first_seen, last_seen, 0
                FROM accounts
                """
            )
            self._conn.execute(
                """
                CREATE TABLE memberships_v2 (
                    membership_id TEXT PRIMARY KEY,
                    account_id    TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
                    group_id      TEXT NOT NULL,
                    current_card  TEXT NOT NULL DEFAULT '',
                    first_seen    REAL NOT NULL,
                    last_seen     REAL NOT NULL,
                    UNIQUE (account_id, group_id)
                )
                """
            )
            self._conn.execute(
                """
                INSERT INTO memberships_v2(
                    membership_id, account_id, group_id, current_card, first_seen, last_seen
                )
                SELECT membership_id, account_id, group_id, current_card, first_seen, last_seen
                FROM memberships
                """
            )
            self._conn.execute(
                """
                CREATE TABLE aliases_v2 (
                    alias_id   TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
                    name       TEXT NOT NULL,
                    platform   TEXT NOT NULL,
                    group_id   TEXT,
                    source     TEXT NOT NULL DEFAULT 'observed',
                    first_seen REAL NOT NULL,
                    last_seen  REAL NOT NULL,
                    UNIQUE (account_id, name, platform, group_id)
                )
                """
            )
            self._conn.execute(
                """
                INSERT INTO aliases_v2(
                    alias_id, account_id, name, platform, group_id, source, first_seen, last_seen
                )
                SELECT alias_id, account_id, name, platform, group_id, source, first_seen, last_seen
                FROM aliases
                """
            )
            self._conn.execute("DROP TABLE aliases")
            self._conn.execute("DROP TABLE memberships")
            self._conn.execute("DROP TABLE accounts")
            self._conn.execute("ALTER TABLE accounts_v2 RENAME TO accounts")
            self._conn.execute("ALTER TABLE memberships_v2 RENAME TO memberships")
            self._conn.execute("ALTER TABLE aliases_v2 RENAME TO aliases")
            self._conn.execute("CREATE INDEX idx_accounts_person ON accounts(person_id)")
            self._conn.execute("CREATE INDEX idx_memberships_group ON memberships(group_id)")
            self._conn.execute("CREATE INDEX idx_aliases_name ON aliases(name)")
            self._conn.execute("CREATE INDEX idx_aliases_account ON aliases(account_id)")
            self._conn.execute(
                """
                CREATE TABLE person_redirects (
                    source_person_id TEXT PRIMARY KEY,
                    target_person_id TEXT NOT NULL,
                    merged_at        REAL NOT NULL
                )
                """
            )
            self._conn.execute("PRAGMA user_version=2")
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        finally:
            self._conn.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self._conn.in_transaction:
            raise RuntimeError("nested directory transaction")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    # ------------------------------------------------------------------ #
    # row mapping and identity redirects
    # ------------------------------------------------------------------ #

    @staticmethod
    def _person_from(row: sqlite3.Row) -> Person:
        tags = tuple(tag for tag in str(row["tags"] or "").split(",") if tag)
        self_persona = str(row["self_persona"] or "")
        return Person(
            person_id=row["person_id"],
            canonical_name=row["canonical_name"],
            notes=row["notes"],
            tags=tags,
            is_bot=bool(row["is_bot"]),
            is_archived=bool(row["is_archived"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            self_persona=self_persona,
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
            platform_instance_id=row["platform_instance_id"],
            suppress_auto_stub=bool(row["suppress_auto_stub"]),
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

    def _resolve_person_id(self, person_id: str | None) -> str | None:
        current = str(person_id or "").strip()
        if not current:
            return None
        visited: set[str] = set()
        while True:
            if current in visited:
                raise DirectoryConflictError("person redirect cycle detected")
            visited.add(current)
            row = self._conn.execute("SELECT person_id FROM persons WHERE person_id=?", (current,)).fetchone()
            if row is not None:
                return str(row["person_id"])
            redirect = self._conn.execute(
                "SELECT target_person_id FROM person_redirects WHERE source_person_id=?", (current,)
            ).fetchone()
            if redirect is None:
                return None
            current = str(redirect["target_person_id"])

    def resolve_person_id(self, person_id: str) -> str | None:
        return self._resolve_person_id(person_id)

    # ------------------------------------------------------------------ #
    # persons
    # ------------------------------------------------------------------ #

    def _create_person(
        self,
        canonical_name: str,
        *,
        notes: str = "",
        tags: Iterable[str] = (),
        is_bot: bool = False,
        self_persona: str = "",
    ) -> Person:
        name = _text(canonical_name, field="canonical_name")
        now = time.time()
        person = Person(
            person_id=_new_id(),
            canonical_name=name,
            notes=notes,
            tags=tuple(str(tag) for tag in tags),
            is_bot=is_bot,
            created_at=now,
            updated_at=now,
            self_persona=self_persona,
        )
        self._conn.execute(
            "INSERT INTO persons(person_id, canonical_name, notes, tags, is_bot,"
            " is_archived, created_at, updated_at, self_persona) VALUES(?,?,?,?,?,0,?,?,?)",
            (
                person.person_id,
                person.canonical_name,
                person.notes,
                ",".join(person.tags),
                int(person.is_bot),
                person.created_at,
                person.updated_at,
                person.self_persona,
            ),
        )
        return person

    def create_person(
        self,
        canonical_name: str,
        *,
        notes: str = "",
        tags: Iterable[str] = (),
        is_bot: bool = False,
        self_persona: str = "",
    ) -> Person:
        with self._transaction():
            return self._create_person(
                canonical_name, notes=notes, tags=tags, is_bot=is_bot, self_persona=self_persona
            )

    def update_person(
        self,
        person_id: str,
        *,
        canonical_name: str | None = None,
        notes: str | None = None,
        tags: Iterable[str] | None = None,
        is_bot: bool | None = None,
        is_archived: bool | None = None,
        self_persona: str | None = None,
    ) -> Person | None:
        with self._transaction():
            canonical_id = self._resolve_person_id(person_id)
            if canonical_id is None:
                return None
            current = self._get_person(canonical_id)
            if current is None:
                return None
            new_name = canonical_name if canonical_name is not None else current.canonical_name
            new_notes = notes if notes is not None else current.notes
            new_tags = tuple(tags) if tags is not None else current.tags
            new_bot = is_bot if is_bot is not None else current.is_bot
            new_archived = is_archived if is_archived is not None else current.is_archived
            new_persona = self_persona if self_persona is not None else current.self_persona
            now = time.time()
            self._conn.execute(
                "UPDATE persons SET canonical_name=?, notes=?, tags=?, is_bot=?,"
                " is_archived=?, updated_at=?, self_persona=? WHERE person_id=?",
                (
                    _text(new_name, field="canonical_name"),
                    new_notes,
                    ",".join(str(tag) for tag in new_tags),
                    int(new_bot),
                    int(new_archived),
                    now,
                    new_persona,
                    canonical_id,
                ),
            )
            return self._get_person(canonical_id)

    def _get_person(self, person_id: str) -> Person | None:
        row = self._conn.execute("SELECT * FROM persons WHERE person_id=?", (person_id,)).fetchone()
        return self._person_from(row) if row else None

    def get_person(self, person_id: str) -> Person | None:
        canonical_id = self._resolve_person_id(person_id)
        return self._get_person(canonical_id) if canonical_id else None

    def list_person_identity_ids(self, person_id: str) -> tuple[str, ...]:
        """Return canonical and merged source IDs for memory tag continuity."""
        canonical_id = self._resolve_person_id(person_id)
        if canonical_id is None:
            return ()
        rows = self._conn.execute(
            "SELECT source_person_id FROM person_redirects "
            "WHERE target_person_id=? ORDER BY merged_at, source_person_id",
            (canonical_id,),
        ).fetchall()
        return (canonical_id, *(str(row["source_person_id"]) for row in rows))

    def delete_person(self, person_id: str) -> bool:
        """Delete an unmerged person; merged targets remain protected."""
        with self._transaction():
            canonical_id = self._resolve_person_id(person_id)
            if canonical_id is None:
                return False
            redirect_count = self._conn.execute(
                "SELECT COUNT(*) FROM person_redirects WHERE target_person_id=?", (canonical_id,)
            ).fetchone()[0]
            if redirect_count:
                raise DirectoryConflictError("cannot delete a person that is the target of merge redirects")
            self._conn.execute(
                "UPDATE accounts SET suppress_auto_stub=1 WHERE person_id=?",
                (canonical_id,),
            )
            cur = self._conn.execute("DELETE FROM persons WHERE person_id=?", (canonical_id,))
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
            where.append("(canonical_name LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\')")
            like = f"%{_escape_like(query)}%"
            params.extend([like, like])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = self._conn.execute(f"SELECT COUNT(*) FROM persons {clause}", params).fetchone()[0]
        rows = self._conn.execute(
            f"SELECT * FROM persons {clause} ORDER BY updated_at DESC, person_id LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [self._person_from(row) for row in rows], int(total)

    def get_person_view(self, person_id: str) -> PersonView | None:
        person = self.get_person(person_id)
        if person is None:
            return None
        accounts = self.list_accounts(person_id=person.person_id)
        views = tuple(
            AccountView(
                account=account,
                memberships=tuple(self.list_memberships(account.account_id)),
                alias_count=self.count_aliases(account.account_id),
                person_name=person.canonical_name,
            )
            for account in accounts
        )
        return PersonView(person=person, accounts=views)

    # ------------------------------------------------------------------ #
    # accounts
    # ------------------------------------------------------------------ #

    @staticmethod
    def _instance_id(platform: str, platform_instance_id: str | None) -> str:
        return str(platform_instance_id or "").strip() or platform

    def _get_account_by_platform(
        self,
        platform: str,
        platform_user_id: str,
        platform_instance_id: str,
    ) -> Account | None:
        row = self._conn.execute(
            "SELECT * FROM accounts WHERE platform=? AND platform_instance_id=? AND platform_user_id=?",
            (platform, platform_instance_id, platform_user_id),
        ).fetchone()
        return self._account_from(row) if row else None

    def _upsert_account(
        self,
        platform: str,
        platform_user_id: str,
        *,
        platform_instance_id: str,
        username: str = "",
        touch: bool = True,
    ) -> tuple[Account, bool]:
        platform = _text(platform, field="platform")
        platform_user_id = _text(platform_user_id, field="platform_user_id")
        platform_instance_id = _text(platform_instance_id, field="platform_instance_id")
        username = str(username or "").strip()
        now = time.time()
        existing = self._get_account_by_platform(platform, platform_user_id, platform_instance_id)
        if existing is None:
            account = Account(
                account_id=_new_id(),
                platform=platform,
                platform_user_id=platform_user_id,
                username=username,
                first_seen=now,
                last_seen=now,
                platform_instance_id=platform_instance_id,
            )
            try:
                self._conn.execute(
                    "INSERT INTO accounts(account_id, platform, platform_instance_id, platform_user_id,"
                    " username, person_id, first_seen, last_seen, suppress_auto_stub)"
                    " VALUES(?,?,?,?,?,NULL,?,?,0)",
                    (
                        account.account_id,
                        account.platform,
                        account.platform_instance_id,
                        account.platform_user_id,
                        account.username,
                        account.first_seen,
                        account.last_seen,
                    ),
                )
            except sqlite3.IntegrityError:
                # Supports multiple DirectoryStore instances sharing a DB: the
                # unique key remains the final authority under SQLite locking.
                existing = self._get_account_by_platform(platform, platform_user_id, platform_instance_id)
                if existing is None:
                    raise
                return existing, False
            return account, True

        if touch or (username and username != existing.username):
            self._conn.execute(
                "UPDATE accounts SET last_seen=?, username=CASE WHEN ?='' THEN username ELSE ? END"
                " WHERE account_id=?",
                (now, username, username, existing.account_id),
            )
            refreshed = self._get_account(existing.account_id)
            if refreshed is not None:
                existing = refreshed
        return existing, False

    def upsert_account(
        self,
        platform: str,
        platform_user_id: str,
        *,
        platform_instance_id: str | None = None,
        username: str = "",
        touch: bool = True,
    ) -> tuple[Account, bool]:
        instance = self._instance_id(platform, platform_instance_id)
        with self._transaction():
            return self._upsert_account(
                platform,
                platform_user_id,
                platform_instance_id=instance,
                username=username,
                touch=touch,
            )

    def _get_account(self, account_id: str) -> Account | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
        return self._account_from(row) if row else None

    def get_account(self, account_id: str) -> Account | None:
        return self._get_account(account_id)

    def get_account_by_platform(
        self,
        platform: str,
        platform_user_id: str,
        platform_instance_id: str | None = None,
    ) -> Account | None:
        instance = self._instance_id(platform, platform_instance_id)
        return self._get_account_by_platform(platform, platform_user_id, instance)

    def _account_filter(
        self,
        *,
        person_id: str | None,
        unlinked: bool,
        platform: str | None,
        platform_instance_id: str | None,
        query: str,
    ) -> tuple[str, list[object]]:
        where: list[str] = []
        params: list[object] = []
        if person_id is not None:
            canonical_id = self._resolve_person_id(person_id)
            if canonical_id is None:
                return "WHERE 1=0", []
            where.append("accounts.person_id=?")
            params.append(canonical_id)
        if unlinked:
            where.append("accounts.person_id IS NULL")
        if platform:
            where.append("accounts.platform=?")
            params.append(platform)
        if platform_instance_id:
            where.append("accounts.platform_instance_id=?")
            params.append(platform_instance_id)
        if query:
            where.append(
                "(accounts.platform_user_id LIKE ? ESCAPE '\\' OR accounts.username LIKE ? ESCAPE '\\')"
            )
            like = f"%{_escape_like(query)}%"
            params.extend([like, like])
        return (f"WHERE {' AND '.join(where)}" if where else ""), params

    def list_accounts(
        self,
        *,
        person_id: str | None = None,
        unlinked: bool = False,
        platform: str | None = None,
        platform_instance_id: str | None = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[Account]:
        clause, params = self._account_filter(
            person_id=person_id,
            unlinked=unlinked,
            platform=platform,
            platform_instance_id=platform_instance_id,
            query=query,
        )
        rows = self._conn.execute(
            f"SELECT * FROM accounts {clause} ORDER BY last_seen DESC, account_id LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [self._account_from(row) for row in rows]

    def list_account_views(
        self,
        *,
        unlinked: bool = False,
        platform: str | None = None,
        platform_instance_id: str | None = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AccountView], int]:
        clause, params = self._account_filter(
            person_id=None,
            unlinked=unlinked,
            platform=platform,
            platform_instance_id=platform_instance_id,
            query=query,
        )
        from_clause = "accounts LEFT JOIN persons ON persons.person_id = accounts.person_id"
        total = int(self._conn.execute(f"SELECT COUNT(*) FROM {from_clause} {clause}", params).fetchone()[0])
        rows = self._conn.execute(
            f"SELECT accounts.*, persons.canonical_name AS person_name FROM {from_clause} {clause} "
            "ORDER BY accounts.last_seen DESC, accounts.account_id LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        views = [
            AccountView(
                account=self._account_from(row),
                memberships=tuple(self.list_memberships(row["account_id"])),
                alias_count=self.count_aliases(row["account_id"]),
                person_name=row["person_name"],
            )
            for row in rows
        ]
        return views, total

    def link_account(self, account_id: str, person_id: str) -> bool:
        with self._transaction():
            target_id = self._resolve_person_id(person_id)
            if target_id is None:
                raise DirectoryNotFoundError("person not found")
            if self._get_account(account_id) is None:
                raise DirectoryNotFoundError("account not found")
            self._conn.execute(
                "UPDATE accounts SET person_id=?, suppress_auto_stub=0 WHERE account_id=?",
                (target_id, account_id),
            )
            return True

    def unlink_account(self, account_id: str) -> bool:
        with self._transaction():
            cur = self._conn.execute(
                "UPDATE accounts SET person_id=NULL, suppress_auto_stub=1 WHERE account_id=?",
                (account_id,),
            )
            return cur.rowcount > 0

    def delete_account(self, account_id: str) -> bool:
        with self._transaction():
            cur = self._conn.execute("DELETE FROM accounts WHERE account_id=?", (account_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # atomic observation and repair
    # ------------------------------------------------------------------ #

    def register_observation(
        self,
        platform: str,
        platform_instance_id: str,
        platform_user_id: str,
        *,
        username: str = "",
        display_name: str = "",
        group_id: str | None = None,
        is_bot: bool = False,
        auto_track_display_names: bool = True,
        auto_stub_person: bool = True,
    ) -> Resolution:
        platform = _text(platform, field="platform")
        instance = _text(platform_instance_id or platform, field="platform_instance_id")
        user_id = _text(platform_user_id, field="platform_user_id")
        group_id = str(group_id or "").strip() or None
        display_name = str(display_name or "").strip()
        with self._transaction():
            account, created = self._upsert_account(
                platform,
                user_id,
                platform_instance_id=instance,
                username=username,
            )
            membership: Membership | None = None
            if group_id:
                membership, _ = self._upsert_membership(
                    account.account_id,
                    group_id,
                    card=display_name,
                )
            if auto_track_display_names and display_name:
                self._record_alias(
                    account.account_id,
                    display_name,
                    platform,
                    group_id=group_id,
                    source=AliasSource.OBSERVED,
                )

            person: Person | None = None
            if account.person_id:
                canonical_id = self._resolve_person_id(account.person_id)
                if canonical_id is not None and canonical_id != account.person_id:
                    self._conn.execute(
                        "UPDATE accounts SET person_id=? WHERE account_id=?",
                        (canonical_id, account.account_id),
                    )
                person = self._get_person(canonical_id) if canonical_id else None

            if person is None and auto_stub_person and not is_bot and not account.suppress_auto_stub:
                person = self._create_person(display_name or username or user_id, is_bot=False)
                self._conn.execute(
                    "UPDATE accounts SET person_id=?, suppress_auto_stub=0 WHERE account_id=?",
                    (person.person_id, account.account_id),
                )

            refreshed_account = self._get_account(account.account_id) or account
            return Resolution(
                account=refreshed_account,
                person=person,
                membership=membership,
                created=created,
            )

    def repair_unlinked_accounts(self, *, limit: int = 1000) -> int:
        with self._transaction():
            rows = self._conn.execute(
                "SELECT * FROM accounts WHERE person_id IS NULL AND suppress_auto_stub=0 "
                "ORDER BY last_seen DESC LIMIT ?",
                (limit,),
            ).fetchall()
            repaired = 0
            for row in rows:
                account = self._account_from(row)
                alias = self._conn.execute(
                    "SELECT name FROM aliases WHERE account_id=? ORDER BY last_seen DESC LIMIT 1",
                    (account.account_id,),
                ).fetchone()
                name = alias["name"] if alias else (account.username or account.platform_user_id)
                person = self._create_person(name)
                self._conn.execute(
                    "UPDATE accounts SET person_id=? WHERE account_id=?",
                    (person.person_id, account.account_id),
                )
                repaired += 1
            return repaired

    # ------------------------------------------------------------------ #
    # memberships
    # ------------------------------------------------------------------ #

    def _upsert_membership(
        self,
        account_id: str,
        group_id: str,
        *,
        card: str = "",
    ) -> tuple[Membership, bool]:
        group_id = _text(group_id, field="group_id")
        card = str(card or "").strip()
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
        new_card = card or membership.current_card
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

    def upsert_membership(
        self,
        account_id: str,
        group_id: str,
        *,
        card: str = "",
    ) -> tuple[Membership, bool]:
        with self._transaction():
            if self._get_account(account_id) is None:
                raise DirectoryNotFoundError("account not found")
            return self._upsert_membership(account_id, group_id, card=card)

    def list_memberships(self, account_id: str) -> list[Membership]:
        rows = self._conn.execute(
            "SELECT * FROM memberships WHERE account_id=? ORDER BY last_seen DESC",
            (account_id,),
        ).fetchall()
        return [self._membership_from(row) for row in rows]

    def update_membership_card(self, membership_id: str, card: str) -> bool:
        with self._transaction():
            cur = self._conn.execute(
                "UPDATE memberships SET current_card=?, last_seen=? WHERE membership_id=?",
                (str(card or "").strip(), time.time(), membership_id),
            )
            return cur.rowcount > 0

    def delete_membership(self, membership_id: str) -> bool:
        with self._transaction():
            cur = self._conn.execute("DELETE FROM memberships WHERE membership_id=?", (membership_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # aliases
    # ------------------------------------------------------------------ #

    def _record_alias(
        self,
        account_id: str,
        name: str,
        platform: str,
        *,
        group_id: str | None = None,
        source: AliasSource = AliasSource.OBSERVED,
    ) -> Alias | None:
        name = str(name or "").strip()
        if not name:
            return None
        platform = _text(platform, field="platform")
        group_id = str(group_id or "").strip() or None
        now = time.time()
        row = self._conn.execute(
            "SELECT * FROM aliases WHERE account_id=? AND name=? AND platform=?"
            " AND (group_id IS ? OR group_id=?)",
            (account_id, name, platform, group_id, group_id),
        ).fetchone()
        if row is not None:
            self._conn.execute("UPDATE aliases SET last_seen=? WHERE alias_id=?", (now, row["alias_id"]))
            refreshed = self._conn.execute(
                "SELECT * FROM aliases WHERE alias_id=?", (row["alias_id"],)
            ).fetchone()
            return self._alias_from(refreshed or row)
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
        self._conn.execute(
            "INSERT INTO aliases(alias_id, account_id, name, platform, group_id, source,"
            " first_seen, last_seen) VALUES(?,?,?,?,?,?,?,?)",
            (
                alias.alias_id,
                alias.account_id,
                alias.name,
                alias.platform,
                alias.group_id,
                alias.source.value,
                alias.first_seen,
                alias.last_seen,
            ),
        )
        return alias

    def record_alias(
        self,
        account_id: str,
        name: str,
        platform: str,
        *,
        group_id: str | None = None,
        source: AliasSource = AliasSource.OBSERVED,
    ) -> Alias | None:
        with self._transaction():
            if self._get_account(account_id) is None:
                raise DirectoryNotFoundError("account not found")
            return self._record_alias(
                account_id,
                name,
                platform,
                group_id=group_id,
                source=source,
            )

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
            f"SELECT * FROM aliases {clause} ORDER BY last_seen DESC, alias_id", params
        ).fetchall()
        return [self._alias_from(row) for row in rows]

    def count_aliases(self, account_id: str) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) FROM aliases WHERE account_id=?", (account_id,)).fetchone()[0]
        )

    def delete_alias(self, alias_id: str) -> bool:
        with self._transaction():
            cur = self._conn.execute("DELETE FROM aliases WHERE alias_id=?", (alias_id,))
            return cur.rowcount > 0

    def find_aliases_by_name(
        self,
        name: str,
        platform: str | None = None,
        *,
        platform_instance_id: str | None = None,
        group_id: str | None = None,
    ) -> list[Alias]:
        name = str(name or "").strip()
        if not name:
            return []
        where = ["a.name=?", "a.platform=account.platform"]
        params: list[object] = [name]
        if platform:
            where.append("account.platform=?")
            params.append(platform)
        if platform_instance_id:
            where.append("account.platform_instance_id=?")
            params.append(platform_instance_id)
        if group_id is None:
            ordering = "CASE WHEN a.group_id IS NULL THEN 0 ELSE 1 END, a.last_seen DESC, a.alias_id"
        else:
            ordering = (
                "CASE WHEN a.group_id=? THEN 0 WHEN a.group_id IS NULL THEN 1 ELSE 2 END, "
                "a.last_seen DESC, a.alias_id"
            )
            params.append(group_id)
        rows = self._conn.execute(
            "SELECT a.* FROM aliases a JOIN accounts account ON account.account_id=a.account_id "
            f"WHERE {' AND '.join(where)} ORDER BY {ordering}",
            params,
        ).fetchall()
        return [self._alias_from(row) for row in rows]

    # ------------------------------------------------------------------ #
    # merge and stable redirects
    # ------------------------------------------------------------------ #

    def merge_persons(self, source_person_id: str, target_person_id: str) -> bool:
        return self.merge_multiple_persons([source_person_id], target_person_id) > 0

    def merge_multiple_persons(self, source_person_ids: Iterable[str], target_person_id: str) -> int:
        source_ids = tuple(
            dict.fromkeys(str(value).strip() for value in source_person_ids if str(value).strip())
        )
        if not source_ids:
            raise DirectoryConflictError("at least one source person is required")
        with self._transaction():
            target_id = self._resolve_person_id(target_person_id)
            if target_id is None:
                raise DirectoryNotFoundError("target person not found")

            active_sources: list[str] = []
            for source_id in source_ids:
                source_canonical = self._resolve_person_id(source_id)
                if source_canonical is None:
                    raise DirectoryNotFoundError(f"source person not found: {source_id}")
                if source_canonical == target_id:
                    raise DirectoryConflictError("source and target must differ")
                if source_canonical != source_id:
                    raise DirectoryConflictError(f"source person already merged: {source_id}")
                active_sources.append(source_canonical)

            now = time.time()
            placeholders = ",".join("?" for _ in active_sources)
            for source_id in active_sources:
                self._conn.execute(
                    "UPDATE accounts SET person_id=? WHERE person_id=?",
                    (target_id, source_id),
                )
            self._conn.execute(
                f"UPDATE person_redirects SET target_person_id=? WHERE target_person_id IN ({placeholders})",
                (target_id, *active_sources),
            )
            for source_id in active_sources:
                self._conn.execute(
                    "INSERT INTO person_redirects(source_person_id, target_person_id, merged_at) VALUES(?,?,?)",
                    (source_id, target_id, now),
                )
                self._conn.execute("DELETE FROM persons WHERE person_id=?", (source_id,))
            self._conn.execute("UPDATE persons SET updated_at=? WHERE person_id=?", (now, target_id))
            return len(active_sources)

    # ------------------------------------------------------------------ #
    # stats
    # ------------------------------------------------------------------ #

    def stats(self) -> dict[str, int]:
        def count(table: str, extra: str = "") -> int:
            return int(self._conn.execute(f"SELECT COUNT(*) FROM {table} {extra}").fetchone()[0])

        return {
            "persons": count("persons", "WHERE is_archived=0"),
            "accounts": count("accounts"),
            "unlinked_accounts": count("accounts", "WHERE person_id IS NULL"),
            "repairable_unlinked_accounts": count(
                "accounts", "WHERE person_id IS NULL AND suppress_auto_stub=0"
            ),
            "memberships": count("memberships"),
            "aliases": count("aliases"),
            "person_redirects": count("person_redirects"),
        }
