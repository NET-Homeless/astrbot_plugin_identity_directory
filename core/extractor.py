"""Extract a normalized SenderSnapshot from an AstrBot message event.

Adapter-specific quirks live here and nowhere else:
- aiocqhttp: user_id is the QQ number (immutable); nickname field carries the
  group card in group chats (mutable display name).
- rocket_chat (custom adapter): user_id is the RC internal _id (immutable);
  nickname is the RC display name; username is the RC handle.
- Everything else: best-effort generic fallback over the AstrBotMessage shape.
"""

from __future__ import annotations

from typing import Any

from .models import SenderSnapshot

_GENERIC_BOT_HINTS = ("bot", "botapp", "webhook")


def extract_snapshot(event: Any) -> SenderSnapshot | None:
    """Best-effort extraction; returns None when no stable id is available."""
    platform = _platform_name(event)
    message_obj = getattr(event, "message_obj", None)
    if message_obj is None:
        return None

    sender = getattr(message_obj, "sender", None)
    if sender is None:
        return None

    user_id = str(getattr(sender, "user_id", "") or "").strip()
    if not user_id:
        return None

    group_id = _group_id(event, message_obj)
    username = _username(event, message_obj, platform)
    display_name = _display_name(event, sender, group_id)
    is_bot = _is_bot(event, message_obj, platform, username)

    return SenderSnapshot(
        platform=platform,
        platform_user_id=user_id,
        display_name=display_name,
        username=username,
        group_id=group_id,
        is_bot=is_bot,
    )


def _platform_name(event: Any) -> str:
    getter = getattr(event, "get_platform_name", None)
    if callable(getter):
        try:
            name = str(getter() or "").strip()
            if name:
                return name
        except Exception:  # noqa: BLE001 — adapters may raise on half-built events
            pass
    return "unknown"


def _group_id(event: Any, message_obj: Any) -> str | None:
    getter = getattr(event, "get_group_id", None)
    if callable(getter):
        try:
            gid = str(getter() or "").strip()
            if gid:
                return gid
        except Exception:  # noqa: BLE001
            pass
    gid = str(getattr(message_obj, "group_id", "") or "").strip()
    return gid or None


def _username(event: Any, message_obj: Any, platform: str) -> str:
    raw = getattr(message_obj, "raw_message", None)
    if platform == "rocket_chat" and isinstance(raw, dict):
        sender = raw.get("u", {}) if isinstance(raw.get("u"), dict) else {}
        return str(sender.get("username") or "").strip()
    return ""


def _display_name(event: Any, sender: Any, group_id: str | None) -> str:
    nickname = str(getattr(sender, "nickname", "") or "").strip()
    user_id = str(getattr(sender, "user_id", "") or "").strip()
    # Adapters fall back to the raw user id when no display name is available
    # (e.g. aiocqhttp on system/notice events). Treat that as "no name": an
    # account id must never be recorded as an alias.
    if not nickname or nickname == user_id:
        return ""
    return nickname


def _is_bot(event: Any, message_obj: Any, platform: str, username: str) -> bool:
    raw = getattr(message_obj, "raw_message", None)
    if isinstance(raw, dict):
        if platform == "rocket_chat":
            sender = raw.get("u", {}) if isinstance(raw.get("u"), dict) else {}
            if sender.get("bot") is True:
                return True
        if raw.get("is_bot") is True:
            return True
    lowered = username.lower()
    return any(hint in lowered for hint in _GENERIC_BOT_HINTS) if lowered else False
