"""Domain models for the identity directory.

All dataclasses are immutable snapshots; mutations go through the store.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class AliasSource(StrEnum):
    """How an alias was recorded."""

    OBSERVED = "observed"  # seen in a message event
    MANUAL = "manual"  # entered by an operator in the UI


class MergeStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class Person:
    """A real-world human (or bot persona) — the stable identity anchor."""

    person_id: str  # uuid4 hex
    canonical_name: str
    notes: str = ""
    tags: tuple[str, ...] = ()
    is_bot: bool = False
    is_archived: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class Account:
    """One account on one platform. Identity key is (platform, platform_user_id)."""

    account_id: str  # uuid4 hex
    platform: str  # e.g. "aiocqhttp", "rocket_chat", "telegram"
    platform_user_id: str  # immutable platform id: QQ number, RC _id, TG user id
    username: str = ""  # platform handle (mutable on some platforms); "" if none
    person_id: str | None = None  # None => unlinked account
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class Membership:
    """An account's membership in one group/chat. Group card lives here."""

    membership_id: str  # uuid4 hex
    account_id: str
    group_id: str  # platform-scoped group id
    current_card: str = ""  # current group card (mutable display name)
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class Alias:
    """A display name observed (or manually recorded) for an account.

    Scoped by platform and optionally by group: the same account may carry
    different cards in different groups.
    """

    alias_id: str  # uuid4 hex
    account_id: str
    name: str
    platform: str
    group_id: str | None = None  # None => platform-wide (e.g. QQ global nickname)
    source: AliasSource = AliasSource.OBSERVED
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AccountView:
    """Joined read model: account + its memberships + alias count."""

    account: Account
    memberships: tuple[Membership, ...] = ()
    alias_count: int = 0


@dataclass(frozen=True, slots=True)
class PersonView:
    """Joined read model: person + all linked accounts."""

    person: Person
    accounts: tuple[AccountView, ...] = ()


@dataclass(frozen=True, slots=True)
class MentionCandidate:
    """A person matched by display name within a scope."""

    person: Person
    account: Account
    matched_name: str
    in_group: bool  # whether the match is scoped to the current group


@dataclass(frozen=True, slots=True)
class Resolution:
    """Result of resolving an event's sender."""

    account: Account
    person: Person | None  # None if auto_stub_person disabled and unlinked
    membership: Membership | None
    created: bool  # whether the account was newly registered


@dataclass(frozen=True, slots=True)
class SenderSnapshot:
    """Normalized sender identity extracted from a platform event."""

    platform: str
    platform_user_id: str
    display_name: str  # group card if group else nickname/username
    username: str = ""
    group_id: str | None = None
    is_bot: bool = False
