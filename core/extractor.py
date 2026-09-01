"""Extract a normalized :class:`SenderSnapshot` from an AstrBot event.

Adapter-specific quirks live here and nowhere else:
- aiocqhttp: ``user_id`` is the QQ number; ``nickname`` carries the group card.
- rocket_chat: ``user_id`` is the RC internal ``_id``; raw ``u.username`` is
  the mutable handle and ``nickname`` is the display name.
- other adapters: use the common AstrBot event/message shape as a fallback.
"""

from __future__ import annotations

import re
from typing import Any

from .models import SenderSnapshot

_GENERIC_BOT_HINTS = ("bot", "botapp", "webhook")


def extract_snapshot(event: Any) -> SenderSnapshot | None:
    """Best-effort extraction; return ``None`` without a stable sender ID."""
    platform = _platform_name(event)
    message_obj = getattr(event, "message_obj", None)
    if message_obj is None:
        return None

    sender = getattr(message_obj, "sender", None)
    if sender is None:
        return None

    user_id = _text(getattr(sender, "user_id", None))
    if not user_id:
        return None

    group_id = _group_id(event, message_obj)
    username = _username(message_obj, platform)
    display_name = _display_name(sender)
    platform_instance_id = _platform_instance_id(event, message_obj, platform)

    return SenderSnapshot(
        platform=platform,
        platform_user_id=user_id,
        display_name=display_name,
        username=username,
        group_id=group_id,
        is_bot=_is_bot(message_obj, platform, username),
        platform_instance_id=platform_instance_id,
    )


def _platform_name(event: Any) -> str:
    value = _call_event_value(event, "get_platform_name")
    return value or "unknown"


def _platform_instance_id(event: Any, message_obj: Any, platform: str) -> str:
    """Return the stable adapter/bot instance ID, never a sender ID."""
    for obj in (event, message_obj):
        value = _call_event_value(obj, "get_platform_id") or _text(getattr(obj, "platform_id", None))
        if value:
            return value

        metadata = getattr(obj, "platform_meta", None)
        value = _text(getattr(metadata, "id", None))
        if value:
            return value

    return platform


def _group_id(event: Any, message_obj: Any) -> str | None:
    group_id = _call_event_value(event, "get_group_id")
    if group_id:
        return group_id
    return _text(getattr(message_obj, "group_id", None)) or None


def _username(message_obj: Any, platform: str) -> str:
    raw = getattr(message_obj, "raw_message", None)
    if platform.casefold() == "rocket_chat" and isinstance(raw, dict):
        raw_u = raw.get("u")
        sender = raw_u if isinstance(raw_u, dict) else {}
        return _text(sender.get("username"))
    return ""


def _display_name(sender: Any) -> str:
    nickname = _text(getattr(sender, "nickname", None))
    user_id = _text(getattr(sender, "user_id", None))
    # Some adapters use the raw user ID as a placeholder nickname. It is not
    # a display alias and must never be written into alias history.
    if not nickname or nickname == user_id:
        return ""
    return nickname


def _is_bot(message_obj: Any, platform: str, username: str) -> bool:
    raw = getattr(message_obj, "raw_message", None)
    if isinstance(raw, dict):
        if platform.casefold() == "rocket_chat":
            raw_u = raw.get("u")
            sender = raw_u if isinstance(raw_u, dict) else {}
            if sender.get("bot") is True:
                return True
        if raw.get("is_bot") is True:
            return True

    lowered = username.casefold()
    tokens = {token for token in re.split(r"[^a-z0-9]+", lowered) if token}
    return bool(tokens.intersection(_GENERIC_BOT_HINTS))


def _call_event_value(obj: Any, method_name: str) -> str:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return ""
    try:
        return _text(method())
    except Exception:  # noqa: BLE001 — half-built adapter events are observable
        return ""


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""
