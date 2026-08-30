"""Async identity resolution service and its public plugin API."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, TypeVar

from .errors import DirectoryClosedError
from .extractor import extract_snapshot
from .models import (
    Account,
    AccountView,
    Alias,
    AliasSource,
    MentionCandidate,
    Person,
    PersonView,
    Resolution,
    SenderSnapshot,
)
from .store import DirectoryStore

if TYPE_CHECKING:
    from pathlib import Path


logger = logging.getLogger(__name__)
T = TypeVar("T")


class DirectoryConfig:
    """Typed view over the plugin configuration."""

    def __init__(self, raw: dict[str, Any] | None) -> None:
        raw = raw or {}
        self.observe_messages: bool = bool(raw.get("observe_messages", True))
        self.auto_track_display_names: bool = bool(raw.get("auto_track_display_names", True))
        self.auto_stub_person: bool = bool(raw.get("auto_stub_person", True))
        self.capture_bots: bool = bool(raw.get("capture_bots", False))
        self.inject_identity_context: bool = bool(raw.get("inject_identity_context", True))

        # This integration is opt-in so installing this plugin never changes
        # the behavior or retention volume of the separately maintained
        # Hindsight plugin.
        self.hindsight_enabled: bool = bool(raw.get("hindsight_enabled", False))
        self.hindsight_recall_enabled: bool = bool(raw.get("hindsight_recall_enabled", True))
        self.hindsight_retain_enabled: bool = bool(raw.get("hindsight_retain_enabled", True))
        self.hindsight_cross_group_memory: bool = bool(raw.get("hindsight_cross_group_memory", False))
        self.hindsight_api_base: str = str(
            raw.get("hindsight_api_base", "http://host.docker.internal:8899") or ""
        ).strip()
        self.hindsight_api_key: str = str(raw.get("hindsight_api_key", "") or "").strip()
        self.hindsight_bank_id: str = str(raw.get("hindsight_bank_id", "group-mei") or "").strip()
        self.hindsight_recall_limit: int = _positive_int(raw.get("hindsight_recall_limit"), 5)
        self.hindsight_item_max_chars: int = _positive_int(raw.get("hindsight_item_max_chars"), 360)
        self.hindsight_retain_min_chars: int = _positive_int(raw.get("hindsight_retain_min_chars"), 8)
        self.hindsight_timeout_seconds: int = _positive_int(raw.get("hindsight_timeout_seconds"), 30)


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


class DirectoryService:
    """Serialize all SQLite work and coordinate the passive observer lifecycle."""

    def __init__(self, db_path: Path, config: DirectoryConfig) -> None:
        self._store = DirectoryStore(db_path)
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="identity-directory-db",
        )
        self._pending_observations: set[asyncio.Task[None]] = set()
        self._accepting_observations = True
        self._closed = False
        self.config = config

    async def _run(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if self._closed:
            raise DirectoryClosedError("identity directory is closed")
        loop = asyncio.get_running_loop()
        call = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(self._executor, call)

    # ------------------------------------------------------------------ #
    # passive observation lifecycle
    # ------------------------------------------------------------------ #

    def schedule_observation(self, snapshot: SenderSnapshot) -> bool:
        """Schedule passive registration and keep a strong task reference."""
        if self._closed or not self._accepting_observations:
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        task = loop.create_task(self._observe_in_background(snapshot))
        self._pending_observations.add(task)
        task.add_done_callback(self._finish_observation)
        return True

    async def _observe_in_background(self, snapshot: SenderSnapshot) -> None:
        try:
            await self.register_snapshot(snapshot)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — observation must never break delivery
            logger.exception("[identity-directory] passive sender registration failed")

    def _finish_observation(self, task: asyncio.Task[None]) -> None:
        self._pending_observations.discard(task)
        if task.cancelled():
            return
        try:
            task.exception()
        except asyncio.CancelledError:
            return

    async def drain_observations(self) -> None:
        """Wait for observations already accepted before plugin shutdown."""
        while self._pending_observations:
            tasks = tuple(self._pending_observations)
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        if self._closed:
            return
        self._accepting_observations = False
        await self.drain_observations()
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._executor, self._store.close)
        finally:
            self._closed = True
            self._executor.shutdown(wait=True, cancel_futures=True)

    # ------------------------------------------------------------------ #
    # event-side resolution
    # ------------------------------------------------------------------

    async def register_snapshot(self, snapshot: SenderSnapshot) -> Resolution | None:
        """Atomically record an observation and resolve its current person."""
        if snapshot.is_bot and not self.config.capture_bots:
            return None
        platform_instance_id = snapshot.platform_instance_id.strip() or snapshot.platform.strip()
        return await self._run(
            self._store.register_observation,
            snapshot.platform,
            platform_instance_id,
            snapshot.platform_user_id,
            username=snapshot.username,
            display_name=snapshot.display_name,
            group_id=snapshot.group_id,
            is_bot=snapshot.is_bot,
            auto_track_display_names=self.config.auto_track_display_names,
            auto_stub_person=self.config.auto_stub_person,
        )

    async def resolve_event(
        self,
        event: Any,
        *,
        register: bool | None = None,
    ) -> Resolution | None:
        """Extract and resolve an AstrBot event through the same public path."""
        snapshot = extract_snapshot(event)
        if snapshot is None:
            return None
        should_register = self.config.observe_messages if register is None else register
        if should_register:
            return await self.register_snapshot(snapshot)
        return await self.resolve_sender(
            snapshot.platform,
            snapshot.platform_user_id,
            snapshot.group_id,
            platform_instance_id=snapshot.platform_instance_id,
        )

    async def resolve_sender(
        self,
        platform: str,
        platform_user_id: str,
        group_id: str | None = None,
        *,
        platform_instance_id: str | None = None,
    ) -> Resolution | None:
        """Read-only resolution of a known platform account."""
        instance = platform_instance_id or platform
        return await self._run(
            self._resolve_sender_sync,
            platform,
            instance,
            platform_user_id,
            group_id,
        )

    def _resolve_sender_sync(
        self,
        platform: str,
        platform_instance_id: str,
        platform_user_id: str,
        group_id: str | None,
    ) -> Resolution | None:
        account = self._store.get_account_by_platform(
            platform,
            platform_user_id,
            platform_instance_id,
        )
        if account is None:
            return None
        person = self._store.get_person(account.person_id) if account.person_id else None
        membership = None
        if group_id:
            membership = next(
                (
                    item
                    for item in self._store.list_memberships(account.account_id)
                    if item.group_id == group_id
                ),
                None,
            )
        return Resolution(account=account, person=person, membership=membership, created=False)

    async def find_by_name(
        self,
        name: str,
        *,
        platform: str | None = None,
        platform_instance_id: str | None = None,
        group_id: str | None = None,
    ) -> list[MentionCandidate]:
        """Find aliases with current-group matches before platform-wide aliases."""

        def _work() -> list[MentionCandidate]:
            candidates: list[MentionCandidate] = []
            seen: set[str] = set()
            aliases = self._store.find_aliases_by_name(
                name,
                platform,
                platform_instance_id=platform_instance_id,
                group_id=group_id,
            )
            for alias in aliases:
                account = self._store.get_account(alias.account_id)
                if account is None or account.person_id is None:
                    continue
                person = self._store.get_person(account.person_id)
                if person is None or person.is_archived or person.person_id in seen:
                    continue
                seen.add(person.person_id)
                candidates.append(
                    MentionCandidate(
                        person=person,
                        account=account,
                        matched_name=alias.name,
                        in_group=group_id is not None and alias.group_id == group_id,
                    )
                )

            persons, _ = self._store.list_persons(query=name, limit=20)
            for person in persons:
                if person.person_id in seen or person.canonical_name != name:
                    continue
                account = next(
                    iter(
                        self._store.list_accounts(
                            person_id=person.person_id,
                            platform=platform,
                            platform_instance_id=platform_instance_id,
                            limit=1,
                        )
                    ),
                    None,
                )
                if account is None:
                    continue
                seen.add(person.person_id)
                candidates.append(
                    MentionCandidate(
                        person=person,
                        account=account,
                        matched_name=person.canonical_name,
                        in_group=False,
                    )
                )
            return candidates

        return await self._run(_work)

    # ------------------------------------------------------------------ #
    # management API
    # ------------------------------------------------------------------

    async def stats(self) -> dict[str, int]:
        return await self._run(self._store.stats)

    async def repair_unlinked_accounts(self) -> int:
        return await self._run(self._store.repair_unlinked_accounts)

    async def list_persons(
        self,
        query: str = "",
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Person], int]:
        return await self._run(
            self._store.list_persons,
            query=query,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )

    async def get_person_view(self, person_id: str) -> PersonView | None:
        return await self._run(self._store.get_person_view, person_id)

    async def list_person_identity_ids(self, person_id: str) -> tuple[str, ...]:
        return await self._run(self._store.list_person_identity_ids, person_id)

    async def create_person(
        self,
        canonical_name: str,
        notes: str = "",
        tags: Iterable[str] = (),
        is_bot: bool = False,
    ) -> Person:
        return await self._run(
            self._store.create_person,
            canonical_name,
            notes=notes,
            tags=tags,
            is_bot=is_bot,
        )

    async def update_person(self, person_id: str, **fields: Any) -> Person | None:
        return await self._run(self._store.update_person, person_id, **fields)

    async def delete_person(self, person_id: str) -> bool:
        return await self._run(self._store.delete_person, person_id)

    async def merge_persons(self, source_person_id: str, target_person_id: str) -> bool:
        return await self._run(self._store.merge_persons, source_person_id, target_person_id)

    async def merge_multiple_persons(self, source_person_ids: Iterable[str], target_person_id: str) -> int:
        return await self._run(
            self._store.merge_multiple_persons,
            source_person_ids,
            target_person_id,
        )

    async def list_accounts(
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
        return await self._run(
            self._store.list_accounts,
            person_id=person_id,
            unlinked=unlinked,
            platform=platform,
            platform_instance_id=platform_instance_id,
            query=query,
            limit=limit,
            offset=offset,
        )

    async def list_account_views(
        self,
        *,
        unlinked: bool = False,
        platform: str | None = None,
        platform_instance_id: str | None = None,
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AccountView], int]:
        return await self._run(
            self._store.list_account_views,
            unlinked=unlinked,
            platform=platform,
            platform_instance_id=platform_instance_id,
            query=query,
            limit=limit,
            offset=offset,
        )

    async def get_account(self, account_id: str) -> Account | None:
        return await self._run(self._store.get_account, account_id)

    async def link_account(self, account_id: str, person_id: str) -> bool:
        return await self._run(self._store.link_account, account_id, person_id)

    async def unlink_account(self, account_id: str) -> bool:
        return await self._run(self._store.unlink_account, account_id)

    async def delete_account(self, account_id: str) -> bool:
        return await self._run(self._store.delete_account, account_id)

    async def list_aliases(self, account_id: str) -> list[Alias]:
        return await self._run(self._store.list_aliases, account_id)

    async def add_alias(
        self,
        account_id: str,
        name: str,
        platform: str,
        group_id: str | None = None,
    ) -> Alias | None:
        return await self._run(
            self._store.record_alias,
            account_id,
            name,
            platform,
            group_id=group_id,
            source=AliasSource.MANUAL,
        )

    async def delete_alias(self, alias_id: str) -> bool:
        return await self._run(self._store.delete_alias, alias_id)

    async def update_membership_card(self, membership_id: str, card: str) -> bool:
        return await self._run(self._store.update_membership_card, membership_id, card)

    async def delete_membership(self, membership_id: str) -> bool:
        return await self._run(self._store.delete_membership, membership_id)

    async def person_of_account(self, account_id: str) -> Person | None:
        def _work() -> Person | None:
            account = self._store.get_account(account_id)
            if account is None or account.person_id is None:
                return None
            return self._store.get_person(account.person_id)

        return await self._run(_work)
