"""Serialization helpers: dataclass → JSON-safe dict for the web API."""

from __future__ import annotations

from .models import Account, AccountView, Alias, Membership, Person, PersonView, Resolution


def person_to_dict(p: Person) -> dict:
    return {
        "person_id": p.person_id,
        "canonical_name": p.canonical_name,
        "notes": p.notes,
        "tags": list(p.tags),
        "is_bot": p.is_bot,
        "is_archived": p.is_archived,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def account_to_dict(a: Account) -> dict:
    return {
        "account_id": a.account_id,
        "platform": a.platform,
        "platform_instance_id": a.platform_instance_id,
        "platform_user_id": a.platform_user_id,
        "username": a.username,
        "person_id": a.person_id,
        "suppress_auto_stub": a.suppress_auto_stub,
        "first_seen": a.first_seen,
        "last_seen": a.last_seen,
    }


def membership_to_dict(m: Membership) -> dict:
    return {
        "membership_id": m.membership_id,
        "account_id": m.account_id,
        "group_id": m.group_id,
        "current_card": m.current_card,
        "first_seen": m.first_seen,
        "last_seen": m.last_seen,
    }


def alias_to_dict(a: Alias) -> dict:
    return {
        "alias_id": a.alias_id,
        "account_id": a.account_id,
        "name": a.name,
        "platform": a.platform,
        "group_id": a.group_id,
        "source": str(a.source),
        "first_seen": a.first_seen,
        "last_seen": a.last_seen,
    }


def account_view_to_dict(v: AccountView) -> dict:
    data = account_to_dict(v.account)
    data["memberships"] = [membership_to_dict(m) for m in v.memberships]
    data["alias_count"] = v.alias_count
    return data


def person_view_to_dict(v: PersonView) -> dict:
    data = person_to_dict(v.person)
    data["accounts"] = [account_view_to_dict(a) for a in v.accounts]
    return data


def resolution_to_dict(r: Resolution) -> dict:
    return {
        "account": account_to_dict(r.account),
        "person": person_to_dict(r.person) if r.person else None,
        "membership": membership_to_dict(r.membership) if r.membership else None,
        "created": r.created,
    }
