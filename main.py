"""astrbot_plugin_identity_directory — 跨平台身份通讯录。"""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.agent.message import TextPart
from astrbot.core.star.filter.custom_filter import CustomFilter
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .core.extractor import extract_snapshot
from .core.hindsight import (
    PersonMemoryClient,
    PersonMemoryError,
    build_memory_content,
    build_memory_context,
    build_person_memory_scope,
    build_turn_document_id,
    load_or_create_salt,
)
from .core.prompt import build_identity_context
from .core.service import DirectoryConfig, DirectoryService
from .core.webapi import DirectoryWebApi

PLUGIN_NAME = "astrbot_plugin_identity_directory"


class PassiveIdentityCaptureFilter(CustomFilter):
    """Register senders without waking the message pipeline."""

    @staticmethod
    def _resolve_service() -> DirectoryService | None:
        from astrbot.core.star.star import star_map

        for metadata in star_map.values():
            candidate = getattr(metadata, "star_cls", metadata)
            service = getattr(candidate, "directory_service", None)
            if isinstance(service, DirectoryService):
                return service
        return None

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:  # noqa: ARG002
        service = self._resolve_service()
        if service is None:
            return False
        service.refresh_config(cfg)
        if not service.config.observe_messages:
            return False
        if not service.config.is_umo_allowed(getattr(event, "unified_msg_origin", "")):
            return False
        try:
            snapshot = extract_snapshot(event)
        except Exception:  # noqa: BLE001 — observation must never break delivery
            logger.exception("[identity-directory] failed to extract sender snapshot")
            return False
        if snapshot is not None:
            service.schedule_observation(snapshot)
        return False


class IdentityDirectory(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config if config is not None else {}
        db_dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        self.directory_service = DirectoryService(db_dir / "directory.db", DirectoryConfig(self.config))
        self._memory_salt = load_or_create_salt(db_dir / "hindsight_scope_salt.txt")
        self._memory_clients: dict[tuple[str, str, str, int, int, int], PersonMemoryClient] = {}
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
        if self._memory_clients:
            await asyncio.gather(*(client.aclose() for client in self._memory_clients.values()))
        await self.directory_service.close()

    # ------------------------------------------------------------- #
    # passive observation (never wakes the pipeline)
    # ------------------------------------------------------------- #

    @filter.custom_filter(PassiveIdentityCaptureFilter, False)
    async def _passive_capture_hook(self, event: AstrMessageEvent) -> None:
        """Placeholder handler; the custom filter performs the observation."""
        return

    # ------------------------------------------------------------- #
    # identity context for the current LLM request
    # ------------------------------------------------------------- #

    @filter.on_llm_request()
    async def _inject_identity_context(self, event: AstrMessageEvent, req: object) -> None:
        config = self._refresh_config()
        if not config.is_umo_allowed(getattr(event, "unified_msg_origin", "")):
            return
        if not config.inject_identity_context and not self._memory_recall_enabled():
            return
        try:
            snapshot = extract_snapshot(event)
            if snapshot is None:
                return
            resolution = await self.directory_service.resolve_event(
                event,
                register=config.observe_messages
                and (config.inject_identity_context or self._memory_recall_enabled()),
            )
            if resolution is None:
                return
            parts = getattr(req, "extra_user_content_parts", None)
            if not isinstance(parts, list):
                return

            if config.inject_identity_context:
                context_text = build_identity_context(snapshot, resolution)
                if context_text:
                    parts.append(_temporary_text_part(context_text))

            if not self._memory_recall_enabled():
                return
            person_ids = (
                await self.directory_service.list_person_identity_ids(resolution.person.person_id)
                if resolution.person
                else ()
            )
            scope = build_person_memory_scope(
                snapshot,
                resolution,
                salt=self._memory_salt,
                person_ids=person_ids,
                cross_group_memory=config.hindsight_cross_group_memory,
            )
            query = str(getattr(event, "message_str", "") or "").strip()
            if scope is None or not query:
                return
            recalled = await self._person_memory_client().recall(query, scope)
            if recalled:
                parts.append(_temporary_text_part(recalled))
        except PersonMemoryError as exc:
            logger.warning("[identity-directory] Person memory recall skipped: %s", exc)
        except Exception:  # noqa: BLE001 — identity enhancement must not break delivery
            logger.exception("[identity-directory] failed to inject identity context")

    @filter.on_llm_response()
    async def _retain_person_memory(self, event: AstrMessageEvent, resp: object) -> None:
        config = self._refresh_config()
        if not config.is_umo_allowed(getattr(event, "unified_msg_origin", "")):
            return
        if not self._memory_retain_enabled():
            return
        try:
            snapshot = extract_snapshot(event)
            if snapshot is None:
                return
            resolution = await self.directory_service.resolve_event(
                event,
                register=config.observe_messages,
            )
            person_ids = (
                await self.directory_service.list_person_identity_ids(resolution.person.person_id)
                if resolution and resolution.person
                else ()
            )
            scope = build_person_memory_scope(
                snapshot,
                resolution,
                salt=self._memory_salt,
                person_ids=person_ids,
                cross_group_memory=config.hindsight_cross_group_memory,
            )
            if scope is None:
                return
            content = build_memory_content(
                str(getattr(event, "message_str", "") or ""),
                str(getattr(resp, "completion_text", "") or ""),
                min_chars=config.hindsight_retain_min_chars,
            )
            if content and resolution and resolution.person:
                document_id = build_turn_document_id(
                    scope,
                    source_message_id=_event_message_id(event),
                    content=content,
                )
                await self._person_memory_client().retain(
                    content,
                    scope,
                    document_id=document_id,
                    context=build_memory_context(snapshot, resolution),
                    timestamp=_event_timestamp(event),
                    entity_name=resolution.person.canonical_name,
                )
        except PersonMemoryError as exc:
            logger.warning("[identity-directory] Person memory retain skipped: %s", exc)
        except Exception:  # noqa: BLE001 — retention must not break delivery
            logger.exception("[identity-directory] failed to retain Person memory")

    def _refresh_config(self) -> DirectoryConfig:
        return self.directory_service.refresh_config(self.config)

    def _memory_recall_enabled(self) -> bool:
        config = self._refresh_config()
        return (
            config.hindsight_enabled
            and config.hindsight_recall_enabled
            and bool(config.hindsight_api_base and config.hindsight_bank_id)
        )

    def _memory_retain_enabled(self) -> bool:
        config = self._refresh_config()
        return (
            config.hindsight_enabled
            and config.hindsight_retain_enabled
            and bool(config.hindsight_api_base and config.hindsight_bank_id)
        )

    def _person_memory_client(self) -> PersonMemoryClient:
        config = self._refresh_config()
        key = (
            config.hindsight_api_base,
            config.hindsight_bank_id,
            config.hindsight_api_key,
            config.hindsight_recall_limit,
            config.hindsight_timeout_seconds,
            config.hindsight_item_max_chars,
        )
        client = self._memory_clients.get(key)
        if client is None:
            client = PersonMemoryClient(
                config.hindsight_api_base,
                config.hindsight_bank_id,
                api_key=config.hindsight_api_key,
                recall_limit=config.hindsight_recall_limit,
                timeout_seconds=config.hindsight_timeout_seconds,
                item_max_chars=config.hindsight_item_max_chars,
            )
            self._memory_clients[key] = client
        return client

    # ------------------------------------------------------------- #
    # commands
    # ------------------------------------------------------------- #

    @filter.command("whoami", alias={"我是谁"})
    async def whoami(self, event: AstrMessageEvent):
        """显示当前账号在通讯录中的身份。"""
        config = self._refresh_config()
        if not config.is_umo_allowed(getattr(event, "unified_msg_origin", "")):
            return
        snapshot = extract_snapshot(event)
        if snapshot is None:
            yield event.plain_result("无法识别当前账号。")
            return
        resolution = await self.directory_service.resolve_event(
            event,
            register=config.observe_messages,
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

    @filter.command("directory", alias={"通讯录", "通讯录状态", "通讯录统计"})
    async def directory_stats(self, event: AstrMessageEvent, sub_cmd: str = ""):  # noqa: ARG002
        """查看通讯录统计信息。用法: /directory"""
        config = self._refresh_config()
        if not config.is_umo_allowed(getattr(event, "unified_msg_origin", "")):
            return
        stats = await self.directory_service.stats()
        yield event.plain_result(
            "📊 通讯录统计数据：\n"
            f"• 联系人总数：{stats.get('persons', 0)} 人\n"
            f"• 关联账号数：{stats.get('accounts', 0)} 个（未归并：{stats.get('unlinked_accounts', 0)}）\n"
            f"• 历史别名数：{stats.get('aliases', 0)} 条\n"
            f"• 群名片记录：{stats.get('memberships', 0)} 张"
        )

    @filter.command("lookup", alias={"查人", "查找联系人"})
    async def lookup_person(self, event: AstrMessageEvent, name: str = ""):
        """按显示名或群名片查找联系人。用法: /lookup <名字>"""
        config = self._refresh_config()
        if not config.is_umo_allowed(getattr(event, "unified_msg_origin", "")):
            return
        query_name = name.strip()
        if not query_name:
            yield event.plain_result("请提供要查询的名字或群名片。用法: /lookup <名字>")
            return

        snapshot = extract_snapshot(event)
        platform = snapshot.platform if snapshot else ""
        group_id = snapshot.group_id if snapshot else None

        candidates = await self.directory_service.find_by_name(
            query_name,
            platform=platform,
            group_id=group_id,
        )
        if not candidates:
            yield event.plain_result(f"未在通讯录中找到与“{query_name}”相关的联系人。")
            return

        lines = [f"🔍 找到 {len(candidates)} 位相关联系人："]
        for i, cand in enumerate(candidates[:5], 1):
            person = cand.person
            account = cand.account
            scope_text = "本群成员" if cand.in_group else "全局匹配"
            lines.append(
                f"{i}. 【{person.canonical_name}】（{scope_text}，匹配名: {cand.matched_name}）\n"
                f"   账号: {account.platform}:{account.platform_user_id}"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("link", alias={"bind", "绑定", "关联账号"})
    async def link_account_cmd(self, event: AstrMessageEvent, code: str = ""):
        """跨平台自助关联绑定账号。用法: /link (申请) 或 /link <6位绑定码>"""
        config = self._refresh_config()
        if not config.is_umo_allowed(getattr(event, "unified_msg_origin", "")):
            return
        snapshot = extract_snapshot(event)
        if snapshot is None:
            yield event.plain_result("无法识别当前账号。")
            return

        action_arg = code.strip().upper()
        # Case 1: 申请生成绑定码
        if not action_arg or action_arg in {"CODE", "NEW", "申请", "GET"}:
            resolution = await self.directory_service.resolve_event(
                event,
                register=True,
            )
            if resolution is None or resolution.person is None:
                yield event.plain_result("无法为当前账号创建联系人主体，请先发送一条普通消息。")
                return
            person = resolution.person
            ticket = self.directory_service.create_binding_ticket(
                person_id=person.person_id,
                person_name=person.canonical_name,
                creator_platform=snapshot.platform,
                creator_user_id=snapshot.platform_user_id,
                ttl_seconds=600,
            )
            yield event.plain_result(
                f"🔑 跨平台绑定码已生成：【{ticket.code}】\n"
                "• 有效时间：10 分钟\n"
                f"• 绑定主体：【{person.canonical_name}】\n"
                f"• 发起账号：{snapshot.platform}:{snapshot.platform_user_id}\n\n"
                f"👉 请在另一个平台（如 QQ 或 Rocket.Chat）中向机器人发送：/link {ticket.code}\n"
                "即可将两个账号合并为同一个人，共享跨平台身份与记忆！"
            )
            return

        # Case 2: 输入绑定码完成核销
        success, message, merged_person = await self.directory_service.redeem_binding_ticket(
            code=action_arg,
            target_snapshot=snapshot,
        )
        if not success:
            yield event.plain_result(f"❌ 绑定失败：{message}")
            return

        p_name = merged_person.canonical_name if merged_person else "统一联系人"
        yield event.plain_result(
            f"🎉 跨平台账号绑定成功！\n"
            f"当前账号（{snapshot.platform}:{snapshot.platform_user_id}）已成功归并至【{p_name}】名下。\n"
            "现在你在不同平台上的身份、名片与记忆已完全互通共享！"
        )

    # ------------------------------------------------------------- #
    # web api registration
    # ------------------------------------------------------------- #

    def _register_web_apis(self, context: Context) -> None:
        routes: list[tuple[str, Any, list[str], str]] = [
            ("/stats", self._web_api.stats, ["GET"], "Directory stats"),
            ("/repair", self._web_api.repair_unlinked, ["POST"], "Link eligible unlinked accounts"),
            ("/persons", self._web_api.list_persons, ["GET"], "List persons"),
            ("/persons/create", self._web_api.create_person, ["POST"], "Create person"),
            ("/persons/<person_id>", self._web_api.get_person, ["GET"], "Get person detail"),
            ("/persons/<person_id>/update", self._web_api.update_person, ["POST"], "Update person"),
            ("/persons/<person_id>/delete", self._web_api.delete_person, ["POST"], "Delete person"),
            ("/persons/merge", self._web_api.merge_persons, ["POST"], "Merge persons"),
            ("/accounts", self._web_api.list_accounts, ["GET"], "List accounts"),
            ("/accounts/<account_id>/link", self._web_api.link_account, ["POST"], "Link account to person"),
            ("/accounts/<account_id>/unlink", self._web_api.unlink_account, ["POST"], "Unlink account"),
            ("/accounts/<account_id>/delete", self._web_api.delete_account, ["POST"], "Delete account"),
            ("/accounts/<account_id>/aliases", self._web_api.list_aliases, ["GET"], "List account aliases"),
            ("/accounts/<account_id>/aliases/add", self._web_api.add_alias, ["POST"], "Add account alias"),
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
        for path, handler, methods, description in routes:
            context.register_web_api(f"/{PLUGIN_NAME}{path}", handler, methods, description)


def _event_message_id(event: AstrMessageEvent) -> str:
    getter = getattr(event, "get_message_id", None)
    if callable(getter):
        try:
            value = getter()
        except (AttributeError, TypeError):
            value = None
        if value not in (None, ""):
            return str(value)
    message_obj = getattr(event, "message_obj", None)
    return str(getattr(message_obj, "message_id", "") or "")


def _event_timestamp(event: AstrMessageEvent) -> str | None:
    message_obj = getattr(event, "message_obj", None)
    raw = getattr(message_obj, "timestamp", None)
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(raw).strip()
    return text or None


def _temporary_text_part(text: str) -> TextPart:
    """Construct a temporary part across supported AstrBot TextPart signatures."""
    parameters = inspect.signature(TextPart).parameters
    if "text" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    ):
        part = TextPart(text=text)
    elif any(
        parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        }
        for parameter in parameters.values()
    ):
        part = TextPart(text)  # pyright: ignore[reportCallIssue]
    else:
        raise TypeError("TextPart constructor does not accept a text value")

    mark_as_temp = getattr(part, "mark_as_temp", None)
    if not callable(mark_as_temp):
        raise TypeError("TextPart does not support mark_as_temp()")
    marked = mark_as_temp()
    if isinstance(marked, TextPart):
        return marked
    return part
