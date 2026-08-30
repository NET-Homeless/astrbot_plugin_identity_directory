"""Identity resolution service — the plugin's public API surface.

Sits between the store (sync SQLite) and consumers (event hook, web API,
other plugins). All public methods are async; blocking SQLite work is
dispatched with asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .models import (
    Account,
    AccountView,
    Alias,
    AliasSource,
    Membership,
    MentionCandidate,
    Person,
    PersonView,
    Resolution,
    SenderSnapshot,
)
from .store import DirectoryStore

if TYPE_CHECKING:
    from pathlib import Path


class DirectoryConfig:
    """Typed view over the plugin config dict."""

    def __init__(self, raw: dict[str, Any] | None) -> None:
        raw = raw or {}
        self.observe_messages: bool = bool(raw.get("observe_messages", True))
        self.auto_track_display_names: bool = bool(raw.get("auto_track_display_names", True))
        self.auto_stub_person: bool = bool(raw.get("auto_stub_person", True))
        self.capture_bots: bool = bool(raw.get("capture_bots", False))


class DirectoryService:
    """Facade for all identity operations."""

    def __init__(self, db_path: Path, config: DirectoryConfig) -> None:
        self._store = DirectoryStore(db_path)
        self.config = config

    async def close(self) -> None:
        await asyncio.to_thread(self._store.close)

    # ------------------------------------------------------------------ #
    # event-side resolution
    # ------------------------------------------------------------------ #

    async def register_snapshot(self, snap: SenderSnapshot) -> Resolution | None:
        """Register an observed sender. Returns None if bots are skipped."""
        if snap.is_bot and not self.config.capture_bots:
            return None

        def _work() -> Resolution:
            account, created = self._store.upsert_account(
                snap.platform,
                snap.platform_user_id,
                username=snap.username,
            )
            membership: Membership | None = None
            if snap.group_id:
                membership, _ = self._store.upsert_membership(
                    account.account_id,
                    snap.group_id,
                    card=snap.display_name,
                )
            if self.config.auto_track_display_names and snap.display_name:
                # Group-scoped alias when in a group; platform-wide otherwise.
                self._store.record_alias(
                    account.account_id,
                    snap.display_name,
                    snap.platform,
                    group_id=snap.group_id,
                )
            person: Person | None = None
            if account.person_id:
                person = self._store.get_person(account.person_id)
            if person is None and self.config.auto_stub_person and not snap.is_bot:
                # Always create a fresh stub: two senders sharing a display
                # name are usually different people. Merging is an explicit
                # operator action in the UI, never implicit.
                person = self._store.create_person(
                    snap.display_name or snap.username or snap.platform_user_id,
                )
                self._store.link_account(account.account_id, person.person_id)
                account = self._store.get_account(account.account_id) or account
            return Resolution(
                account=account,
                person=person,
                membership=membership,
                created=created,
            )

        return await asyncio.to_thread(_work)

    async def resolve_sender(
        self,
        platform: str,
        platform_user_id: str,
        group_id: str | None = None,
    ) -> Resolution | None:
        """Read-only resolution of a known account."""

        def _work() -> Resolution | None:
            account = self._store.get_account_by_platform(platform, platform_user_id)
            if account is None:
                return None
            person = self._store.get_person(account.person_id) if account.person_id else None
            membership = None
            if group_id:
                membership = next(
                    (m for m in self._store.list_memberships(account.account_id) if m.group_id == group_id),
                    None,
                )
            return Resolution(account=account, person=person, membership=membership, created=False)

        return await asyncio.to_thread(_work)

    async def find_by_name(
        self,
        name: str,
        *,
        platform: str | None = None,
        group_id: str | None = None,
    ) -> list[MentionCandidate]:
        """Find persons by display name (alias), preferring group-scoped matches.

        Used for mention disambiguation: "@联系人乙" inside group G first matches
        aliases scoped to G, then platform-wide aliases.
        """

        def _work() -> list[MentionCandidate]:
            candidates: list[MentionCandidate] = []
            seen: set[str] = set()
            for alias in self._store.find_aliases_by_name(name, platform):
                account = self._store.get_account(alias.account_id)
                if account is None or account.person_id is None:
                    continue
                if account.person_id in seen:
                    continue
                person = self._store.get_person(account.person_id)
                if person is None or person.is_archived:
                    continue
                in_group = group_id is not None and alias.group_id == group_id
                seen.add(account.person_id)
                candidates.append(
                    MentionCandidate(
                        person=person,
                        account=account,
                        matched_name=alias.name,
                        in_group=in_group,
                    )
                )
            # Also match canonical names directly.
            persons, _ = self._store.list_persons(query=name, limit=20)
            for person in persons:
                if person.person_id in seen or person.canonical_name != name:
                    continue
                seen.add(person.person_id)
                account = next(iter(self._store.list_accounts(person_id=person.person_id)), None)
                if account is None:
                    continue
                candidates.append(
                    MentionCandidate(
                        person=person,
                        account=account,
                        matched_name=person.canonical_name,
                        in_group=False,
                    )
                )
            candidates.sort(key=lambda c: not c.in_group)  # group matches first
            return candidates

        return await asyncio.to_thread(_work)

    # ------------------------------------------------------------------ #
    # management API (web UI)
    # ------------------------------------------------------------------ #

    async def stats(self) -> dict[str, int]:
        return await asyncio.to_thread(self._store.stats)

    async def repair_unlinked_accounts(self) -> int:
        """Create/link stub persons for every account with no person.

        Returns the number of accounts repaired. Idempotent.
        """

        def _work() -> int:
            repaired = 0
            for account in self._store.list_accounts(unlinked=True, limit=1000):
                # Pick a reasonable display name: latest alias, username, or id.
                aliases = self._store.list_aliases(account.account_id)
                name = aliases[0].name if aliases else (account.username or account.platform_user_id)
                person = self._store.create_person(name)
                self._store.link_account(account.account_id, person.person_id)
                repaired += 1
            return repaired

        return await asyncio.to_thread(_work)

    async def list_persons(
        self, query: str = "", include_archived: bool = False, limit: int = 50, offset: int = 0
    ) -> tuple[list[Person], int]:
        return await asyncio.to_thread(
            self._store.list_persons,
            query=query,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )

    async def get_person_view(self, person_id: str) -> PersonView | None:
        return await asyncio.to_thread(self._store.get_person_view, person_id)

    async def create_person(
        self, canonical_name: str, notes: str = "", tags: Iterable[str] = (), is_bot: bool = False
    ) -> Person:
        return await asyncio.to_thread(
            self._store.create_person, canonical_name, notes=notes, tags=tags, is_bot=is_bot
        )

    async def update_person(self, person_id: str, **fields: Any) -> Person | None:
        return await asyncio.to_thread(self._store.update_person, person_id, **fields)

    async def delete_person(self, person_id: str) -> bool:
        return await asyncio.to_thread(self._store.delete_person, person_id)

    async def merge_persons(self, source_person_id: str, target_person_id: str) -> bool:
        return await asyncio.to_thread(self._store.merge_persons, source_person_id, target_person_id)

    async def merge_multiple_persons(self, source_person_ids: Iterable[str], target_person_id: str) -> int:
        return await asyncio.to_thread(
            self._store.merge_multiple_persons, source_person_ids, target_person_id
        )

    async def list_accounts(
        self,
        *,
        person_id: str | None = None,
        unlinked: bool = False,
        platform: str | None = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[Account]:
        return await asyncio.to_thread(
            self._store.list_accounts,
            person_id=person_id,
            unlinked=unlinked,
            platform=platform,
            query=query,
            limit=limit,
            offset=offset,
        )

    async def list_account_views(
        self,
        *,
        unlinked: bool = False,
        platform: str | None = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[AccountView]:
        accounts = await self.list_accounts(
            unlinked=unlinked, platform=platform, query=query, limit=limit, offset=offset
        )

        def _views() -> list[AccountView]:
            result: list[AccountView] = []
            for a in accounts:
                result.append(
                    AccountView(
                        account=a,
                        memberships=tuple(self._store.list_memberships(a.account_id)),
                        alias_count=self._store.count_aliases(a.account_id),
                    )
                )
            return result

        return await asyncio.to_thread(_views)

    async def get_account(self, account_id: str) -> Account | None:
        return await asyncio.to_thread(self._store.get_account, account_id)

    async def link_account(self, account_id: str, person_id: str) -> bool:
        return await asyncio.to_thread(self._store.link_account, account_id, person_id)

    async def unlink_account(self, account_id: str) -> bool:
        return await asyncio.to_thread(self._store.unlink_account, account_id)

    async def delete_account(self, account_id: str) -> bool:
        return await asyncio.to_thread(self._store.delete_account, account_id)

    async def list_aliases(self, account_id: str) -> list[Alias]:
        return await asyncio.to_thread(self._store.list_aliases, account_id)

    async def add_alias(
        self,
        account_id: str,
        name: str,
        platform: str,
        group_id: str | None = None,
    ) -> Alias | None:
        return await asyncio.to_thread(
            self._store.record_alias,
            account_id,
            name,
            platform,
            group_id=group_id,
            source=AliasSource.MANUAL,
        )

    async def delete_alias(self, alias_id: str) -> bool:
        return await asyncio.to_thread(self._store.delete_alias, alias_id)

    async def update_membership_card(self, membership_id: str, card: str) -> bool:
        return await asyncio.to_thread(self._store.update_membership_card, membership_id, card)

    async def delete_membership(self, membership_id: str) -> bool:
        return await asyncio.to_thread(self._store.delete_membership, membership_id)

    async def person_of_account(self, account_id: str) -> Person | None:
        def _work() -> Person | None:
            account = self._store.get_account(account_id)
            if account is None or account.person_id is None:
                return None
            return self._store.get_person(account.person_id)

        return await asyncio.to_thread(_work)
