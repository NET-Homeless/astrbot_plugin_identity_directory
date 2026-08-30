"""astrbot_plugin_identity_directory — 跨平台身份通讯录.

Passively observes every message (without waking the pipeline), registers
platform accounts into a SQLite-backed directory, and exposes a WebUI
management page plus a Python API for other plugins to resolve senders to
stable persons.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config import AstrBotConfig
from astrbot.core.star.filter.custom_filter import CustomFilter
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .core.extractor import extract_snapshot
from .core.models import SenderSnapshot
from .core.service import DirectoryConfig, DirectoryService
from .core.webapi import DirectoryWebApi

PLUGIN_NAME = "astrbot_plugin_identity_directory"


class PassiveIdentityCaptureFilter(CustomFilter):
    """Register senders without waking the pipeline.

    Returning False keeps the event unwoken: the associated handler is never
    invoked and the message flow is untouched. The actual registration is a
    fire-and-forget asyncio task so this synchronous filter stays fast.

    AstrBot's custom-filter decorator instantiates filters with only the
    ``raise_error`` argument, so the directory service is resolved lazily from
    the star registry on each event instead of being injected.
    """

    @staticmethod
    def _resolve_service() -> DirectoryService | None:
        from astrbot.core.star.star import star_map

        for module_path, metadata in star_map.items():
            if module_path.endswith(f"{PLUGIN_NAME}.main"):
                star_cls = getattr(metadata, "star_cls", None)
                if star_cls is not None:
                    return getattr(star_cls, "directory_service", None)
        return None

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:  # noqa: ARG002
        service = self._resolve_service()
        if service is None or not service.config.observe_messages:
            return False
        try:
            snapshot = extract_snapshot(event)
        except Exception:  # noqa: BLE001 — observation must never break delivery
            logger.exception("[identity-directory] failed to extract sender snapshot")
            return False
        if snapshot is None:
            return False
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._safe_register(service, snapshot))
        except RuntimeError:
            # No running loop (e.g. during tests); drop silently.
            pass
        return False

    @staticmethod
    async def _safe_register(service: DirectoryService, snapshot: SenderSnapshot) -> None:
        try:
            await service.register_snapshot(snapshot)
        except Exception:  # noqa: BLE001
            logger.exception("[identity-directory] failed to register sender")


class IdentityDirectory(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self._raw_config = config or {}
        db_path = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME / "directory.db"
        self.directory_service = DirectoryService(db_path, DirectoryConfig(self._raw_config))
        self._web_api = DirectoryWebApi(self.directory_service)
        self._register_web_apis(context)

    # ------------------------------------------------------------- #
    # lifecycle
    # ------------------------------------------------------------- #

    async def initialize(self) -> None:
        stats = await self.directory_service.stats()
        logger.info(
            "[identity-directory] loaded: %s persons, %s accounts (%s unlinked)",
            stats["persons"],
            stats["accounts"],
            stats["unlinked_accounts"],
        )

    async def terminate(self) -> None:
        await self.directory_service.close()

    # ------------------------------------------------------------- #
    # passive observation (never wakes the pipeline)
    # ------------------------------------------------------------- #

    @filter.custom_filter(PassiveIdentityCaptureFilter, False)
    async def _passive_capture_hook(self, event: AstrMessageEvent) -> None:
        """Placeholder handler — the filter does the work and returns False,
        so this is never invoked. Exists only to carry the filter."""
        return

    # ------------------------------------------------------------- #
    # commands
    # ------------------------------------------------------------- #

    @filter.command("whoami", alias={"我是谁"})
    async def whoami(self, event: AstrMessageEvent):
        """显示当前账号在通讯录中的身份。"""
        snapshot = extract_snapshot(event)
        if snapshot is None:
            yield event.plain_result("无法识别当前账号。")
            return
        resolution = await self.directory_service.resolve_sender(
            snapshot.platform, snapshot.platform_user_id, snapshot.group_id
        )
        if resolution is None or resolution.person is None:
            yield event.plain_result(f"通讯录里还没有你（{snapshot.platform}:{snapshot.platform_user_id}）。")
            return
        person = resolution.person
        view = await self.directory_service.get_person_view(person.person_id)
        account_count = len(view.accounts) if view else 0
        yield event.plain_result(
            f"你是【{person.canonical_name}】"
            f"（{snapshot.platform}:{snapshot.platform_user_id}，共绑定 {account_count} 个账号）。"
        )

    # ------------------------------------------------------------- #
    # web api registration
    # ------------------------------------------------------------- #

    def _register_web_apis(self, context: Context) -> None:
        routes: list[tuple[str, object, list[str], str]] = [
            ("/stats", self._web_api.stats, ["GET"], "Directory stats"),
            ("/repair", self._web_api.repair_unlinked, ["POST"], "Link stub persons to unlinked accounts"),
            ("/persons", self._web_api.list_persons, ["GET"], "List persons"),
            ("/persons/create", self._web_api.create_person, ["POST"], "Create person"),
            ("/persons/<person_id>", self._web_api.get_person, ["GET"], "Get person detail"),
            ("/persons/<person_id>/update", self._web_api.update_person, ["POST"], "Update person"),
            ("/persons/<person_id>/delete", self._web_api.delete_person, ["POST"], "Delete person"),
            ("/persons/merge", self._web_api.merge_persons, ["POST"], "Merge two persons"),
            ("/accounts", self._web_api.list_accounts, ["GET"], "List accounts"),
            ("/accounts/<account_id>/link", self._web_api.link_account, ["POST"], "Link account to person"),
            ("/accounts/<account_id>/unlink", self._web_api.unlink_account, ["POST"], "Unlink account"),
            ("/accounts/<account_id>/delete", self._web_api.delete_account, ["POST"], "Delete account"),
            ("/accounts/<account_id>/aliases", self._web_api.list_aliases, ["GET"], "List account aliases"),
            ("/accounts/<account_id>/aliases/add", self._web_api.add_alias, ["POST"], "Add alias"),
            ("/aliases/<alias_id>/delete", self._web_api.delete_alias, ["POST"], "Delete alias"),
            (
                "/memberships/<membership_id>/update",
                self._web_api.update_membership,
                ["POST"],
                "Update membership card",
            ),
            (
                "/memberships/<membership_id>/delete",
                self._web_api.delete_membership,
                ["POST"],
                "Delete membership",
            ),
            ("/resolve", self._web_api.resolve, ["GET"], "Resolve platform account"),
            ("/lookup", self._web_api.find_by_name, ["GET"], "Find persons by display name"),
        ]
        for path, handler, methods, desc in routes:
            context.register_web_api(f"/{PLUGIN_NAME}{path}", handler, methods, desc)
