from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from core.hindsight import (
    MAX_TIMEOUT_SECONDS,
    PersonMemoryClient,
    PersonMemoryError,
    build_memory_content,
    build_memory_context,
    build_person_memory_scope,
    build_turn_document_id,
)
from core.models import Account, Person, Resolution, SenderSnapshot


def _resolution(person_id: str = "person-main") -> Resolution:
    person = Person(person_id=person_id, canonical_name="测试用户")
    account = Account(
        account_id="account-1",
        platform="aiocqhttp",
        platform_user_id="user-secret-id",
        person_id=person_id,
        platform_instance_id="qq-instance-secret",
    )
    return Resolution(account=account, person=person, membership=None, created=False)


class PersonMemoryScopeTests(unittest.TestCase):
    def test_private_scope_follows_person_across_platforms(self) -> None:
        resolution = _resolution()
        qq = build_person_memory_scope(
            SenderSnapshot(
                platform="aiocqhttp",
                platform_user_id="qq-user",
                display_name="QQ 名片",
                platform_instance_id="qq-instance",
            ),
            resolution,
            salt="salt",
        )
        rc = build_person_memory_scope(
            SenderSnapshot(
                platform="rocket_chat",
                platform_user_id="rc-user",
                display_name="RC 名片",
                platform_instance_id="rc-instance",
            ),
            resolution,
            salt="salt",
        )

        assert qq is not None and rc is not None
        assert qq.tags == rc.tags
        assert qq.tags == ("identity:person:person-main", "identity:scope:person")
        assert "qq-user" not in " ".join(qq.tags)
        assert "rc-user" not in " ".join(rc.tags)

    def test_group_scope_isolates_person_group_and_instance(self) -> None:
        first = build_person_memory_scope(
            SenderSnapshot(
                platform="aiocqhttp",
                platform_user_id="user-secret-id",
                display_name="群名片",
                group_id="group-secret-id",
                platform_instance_id="instance-secret-id",
            ),
            _resolution("person-a"),
            salt="salt",
        )
        other_group = build_person_memory_scope(
            SenderSnapshot(
                platform="aiocqhttp",
                platform_user_id="user-secret-id",
                display_name="群名片",
                group_id="other-group-secret-id",
                platform_instance_id="instance-secret-id",
            ),
            _resolution("person-a"),
            salt="salt",
        )
        other_person = build_person_memory_scope(
            SenderSnapshot(
                platform="aiocqhttp",
                platform_user_id="other-user-secret-id",
                display_name="同名片",
                group_id="group-secret-id",
                platform_instance_id="instance-secret-id",
            ),
            _resolution("person-b"),
            salt="salt",
        )

        assert first is not None and other_group is not None and other_person is not None
        assert first.audience_tags != other_group.audience_tags
        assert first.audience_tags == other_person.audience_tags
        assert first.person_tags != other_person.person_tags
        rendered = " ".join(first.tags)
        assert "user-secret-id" not in rendered
        assert "group-secret-id" not in rendered
        assert "instance-secret-id" not in rendered

    def test_cross_group_memory_requires_explicit_opt_in(self) -> None:
        group_snapshot = SenderSnapshot(
            platform="aiocqhttp",
            platform_instance_id="bot-a",
            platform_user_id="user-a",
            display_name="测试用户",
            group_id="group-a",
        )
        isolated = build_person_memory_scope(group_snapshot, _resolution(), salt="salt")
        shared = build_person_memory_scope(
            group_snapshot,
            _resolution(),
            salt="salt",
            cross_group_memory=True,
        )

        assert isolated is not None and shared is not None
        assert isolated.scope_type == "group_member"
        assert shared.tags == ("identity:person:person-main", "identity:scope:person")

    def test_merge_redirect_ids_are_recalled_but_new_writes_use_canonical_id(self) -> None:
        scope = build_person_memory_scope(
            SenderSnapshot(
                platform="rocket_chat",
                platform_user_id="rc-user",
                display_name="测试用户",
            ),
            _resolution("person-main"),
            salt="salt",
            person_ids=("person-main", "person-old-a", "person-old-b"),
        )

        assert scope is not None
        assert scope.person_tags == (
            "identity:person:person-main",
            "identity:person:person-old-a",
            "identity:person:person-old-b",
        )
        assert scope.tags == ("identity:person:person-main", "identity:scope:person")

    def test_retention_rejects_commands_and_obvious_credentials(self) -> None:
        assert build_memory_content("/status", "正常运行") is None
        assert build_memory_content("API_KEY=sk-secret-value", "收到") is None
        content = build_memory_content("我今天完成了跨平台身份合并", "我会记住这件事")
        assert content is not None
        assert json.loads(content) == [
            {"role": "user", "content": "我今天完成了跨平台身份合并"},
            {"role": "assistant", "content": "我会记住这件事"},
        ]


class PersonMemoryClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_is_capped(self) -> None:
        client = PersonMemoryClient("http://hindsight.test", "bank", timeout_seconds=999)
        assert client.timeout_seconds == MAX_TIMEOUT_SECONDS

    async def test_request_timeout_aborts_slow_transport(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(2)
            return httpx.Response(200, json={"results": []})

        client = PersonMemoryClient(
            "http://hindsight.test",
            "bank",
            timeout_seconds=1,
            transport=httpx.MockTransport(handler),
        )
        scope = build_person_memory_scope(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="u", display_name="n"),
            _resolution(),
            salt="salt",
        )
        assert scope is not None
        try:
            with self.assertRaisesRegex(PersonMemoryError, "timed out"):
                await client.recall("慢请求", scope)
        finally:
            await client.aclose()

    async def test_recall_uses_or_group_for_merged_ids_and_escapes_memory(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"text": "<script>untrusted()</script>"},
                        {"text": "<script>untrusted()</script>"},
                    ]
                },
            )

        client = PersonMemoryClient(
            "http://hindsight.test",
            "bank",
            transport=httpx.MockTransport(handler),
        )
        scope = build_person_memory_scope(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="u", display_name="n"),
            _resolution(),
            salt="salt",
            person_ids=("person-main", "person-old"),
        )
        assert scope is not None

        formatted = await client.recall("做过什么", scope)
        await client.aclose()

        assert "tag_groups" in captured
        assert "tags" not in captured
        assert captured["tag_groups"] == [
            {"tags": ["identity:scope:person"], "match": "all_strict"},
            {
                "tags": ["identity:person:person-main", "identity:person:person-old"],
                "match": "any_strict",
            },
        ]
        assert formatted.count("- ") == 1
        assert "<script>" not in formatted
        assert "&lt;script&gt;" in formatted

    async def test_retain_writes_only_canonical_person_tag(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"success": True})

        client = PersonMemoryClient(
            "http://hindsight.test",
            "bank",
            transport=httpx.MockTransport(handler),
        )
        scope = build_person_memory_scope(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="u", display_name="n"),
            _resolution(),
            salt="salt",
            person_ids=("person-main", "person-old"),
        )
        assert scope is not None

        content = build_memory_content("我完成了任务", "已经记住")
        assert content is not None
        document_id = build_turn_document_id(
            scope,
            source_message_id="message-1",
            content=content,
        )
        await client.retain(
            content,
            scope,
            document_id=document_id,
            context=build_memory_context(
                SenderSnapshot(platform="aiocqhttp", platform_user_id="u", display_name="n"),
                _resolution(),
            ),
            timestamp="2026-08-30T12:00:00+00:00",
            entity_name="测试用户",
        )
        await client.aclose()

        items = captured["items"]
        assert isinstance(items, list)
        item = items[0]
        assert item["tags"] == ["identity:person:person-main", "identity:scope:person"]
        assert "person-old" not in " ".join(item["tags"])
        assert item["document_id"] == document_id
        assert item["context"] == "AstrBot private conversation with 测试用户 via aiocqhttp"
        assert item["timestamp"] == "2026-08-30T12:00:00+00:00"
        assert item["entities"] == [{"text": "测试用户", "type": "PERSON"}]
        assert isinstance(captured["operation_id"], str)


if __name__ == "__main__":
    unittest.main()
