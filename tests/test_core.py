from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.extractor import extract_snapshot
from core.models import SenderSnapshot
from core.service import DirectoryConfig, DirectoryService


def _service(tmp_path: str) -> DirectoryService:
    cfg = DirectoryConfig(
        {
            "observe_messages": True,
            "auto_track_display_names": True,
            "auto_stub_person": True,
            "capture_bots": False,
        }
    )
    return DirectoryService(Path(tmp_path) / "test.db", cfg)


class DirectoryConfigTests(unittest.TestCase):
    def test_umo_filter_defaults_to_empty_blacklist(self) -> None:
        config = DirectoryConfig({})
        assert config.umo_filter_mode == "blacklist"
        assert config.umo_filter_list == ()
        assert config.is_umo_allowed("aiocqhttp:GroupMessage:123")

        config.refresh({"umo_filter_mode": "whitelist"})
        assert config.umo_filter_list == ()
        assert not config.is_umo_allowed("aiocqhttp:GroupMessage:123")


class CoreServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_register_snapshot_creates_stub_person(self) -> None:
        svc = _service(self._tmp.name)
        snap = SenderSnapshot(
            platform="aiocqhttp",
            platform_user_id="100000001",
            display_name="测试用户A",
            group_id="100001",
        )
        res = await svc.register_snapshot(snap)
        assert res is not None
        assert res.created is True
        assert res.person is not None
        assert res.person.canonical_name == "测试用户A"
        assert res.membership is not None
        assert res.membership.current_card == "测试用户A"
        assert res.account.person_id == res.person.person_id
        views, total = await svc.list_account_views()
        assert total == 1
        assert views[0].person_name == "测试用户A"
        await svc.close()

    async def test_same_account_two_groups_two_cards(self) -> None:
        svc = _service(self._tmp.name)
        for group, card in (("g1", "名片A"), ("g2", "名片B")):
            await svc.register_snapshot(
                SenderSnapshot(
                    platform="aiocqhttp",
                    platform_user_id="111",
                    display_name=card,
                    group_id=group,
                )
            )
        res = await svc.resolve_sender("aiocqhttp", "111", "g2")
        assert res is not None and res.membership is not None
        assert res.membership.current_card == "名片B"
        res1 = await svc.resolve_sender("aiocqhttp", "111", "g1")
        assert res1 is not None and res1.membership is not None
        assert res1.membership.current_card == "名片A"
        # one account, one person, two memberships
        stats = await svc.stats()
        assert stats["accounts"] == 1
        assert stats["persons"] == 1
        assert stats["memberships"] == 2
        await svc.close()

    async def test_display_name_change_records_alias_keeps_identity(self) -> None:
        svc = _service(self._tmp.name)
        for card in ("旧名片", "新名片"):
            await svc.register_snapshot(
                SenderSnapshot(
                    platform="aiocqhttp",
                    platform_user_id="222",
                    display_name=card,
                    group_id="g1",
                )
            )
        res = await svc.resolve_sender("aiocqhttp", "222", "g1")
        assert res is not None
        assert res.membership is not None and res.membership.current_card == "新名片"
        aliases = await svc.list_aliases(res.account.account_id)
        names = {a.name for a in aliases}
        assert {"旧名片", "新名片"} <= names
        # identity unchanged: still one person
        assert (await svc.stats())["persons"] == 1
        await svc.close()

    async def test_cross_platform_merge(self) -> None:
        svc = _service(self._tmp.name)
        qq = await svc.register_snapshot(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="100000001", display_name="测试用户A")
        )
        rc = await svc.register_snapshot(
            SenderSnapshot(
                platform="rocket_chat",
                platform_user_id="rcABC",
                username="testuser",
                display_name="测试用户B",
            )
        )
        assert qq is not None and rc is not None
        assert qq.person is not None and rc.person is not None
        assert qq.person.person_id != rc.person.person_id

        merged = await svc.merge_persons(rc.person.person_id, qq.person.person_id)
        assert merged is True

        res_qq = await svc.resolve_sender("aiocqhttp", "100000001")
        res_rc = await svc.resolve_sender("rocket_chat", "rcABC")
        assert res_qq is not None and res_rc is not None
        assert res_qq.person is not None and res_rc.person is not None
        assert res_qq.person.person_id == res_rc.person.person_id

        stats = await svc.stats()
        assert stats["persons"] == 1
        assert stats["accounts"] == 2
        await svc.close()

    async def test_find_by_name_prefers_group_scope(self) -> None:
        svc = _service(self._tmp.name)
        # same display name used by two different accounts in two groups
        await svc.register_snapshot(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="u1", display_name="通用名", group_id="g1")
        )
        await svc.register_snapshot(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="u2", display_name="通用名", group_id="g2")
        )
        candidates = await svc.find_by_name("通用名", platform="aiocqhttp", group_id="g1")
        assert len(candidates) == 2
        assert candidates[0].in_group is True
        assert candidates[0].account.platform_user_id == "u1"
        await svc.close()

    async def test_search_treats_like_wildcards_as_literal_text(self) -> None:
        svc = _service(self._tmp.name)
        await svc.create_person("literal%name")
        await svc.create_person("literalXname")
        await svc.create_person("literal_name")

        percent_matches, _ = await svc.list_persons(query="%")
        underscore_matches, _ = await svc.list_persons(query="_")
        assert {person.canonical_name for person in percent_matches} == {"literal%name"}
        assert {person.canonical_name for person in underscore_matches} == {"literal_name"}

        await svc.register_snapshot(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="literal%user", display_name="百分号")
        )
        await svc.register_snapshot(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="literalXuser", display_name="普通字符")
        )
        account_matches = await svc.list_accounts(query="%")
        assert {account.platform_user_id for account in account_matches} == {"literal%user"}
        await svc.close()

    async def test_bot_skip_when_configured(self) -> None:
        cfg = DirectoryConfig({"capture_bots": False})
        svc = DirectoryService(Path(self._tmp.name) / "test.db", cfg)
        snap = SenderSnapshot(
            platform="aiocqhttp",
            platform_user_id="999",
            display_name="Bot",
            is_bot=True,
        )
        res = await svc.register_snapshot(snap)
        assert res is None
        stats = await svc.stats()
        assert stats["accounts"] == 0
        await svc.close()

    async def test_umo_filter_applies_to_event_resolution_and_refreshes(self) -> None:
        blocked_umo = "aiocqhttp:GroupMessage:blocked"
        allowed_umo = "aiocqhttp:GroupMessage:allowed"
        raw_config = {
            "umo_filter_mode": "blacklist",
            "umo_filter_list": [blocked_umo],
        }
        svc = DirectoryService(Path(self._tmp.name) / "umo-filter.db", DirectoryConfig(raw_config))
        blocked_event = ExtractorTests._Event(
            "aiocqhttp",
            ExtractorTests._Sender("blocked-user", "被拦截"),
            umo=blocked_umo,
        )
        allowed_event = ExtractorTests._Event(
            "aiocqhttp",
            ExtractorTests._Sender("allowed-user", "允许通过"),
            umo=allowed_umo,
        )

        assert await svc.resolve_event(blocked_event) is None
        allowed = await svc.resolve_event(allowed_event)
        assert allowed is not None

        raw_config["umo_filter_mode"] = "whitelist"
        raw_config["umo_filter_list"] = [allowed_umo]
        assert await svc.resolve_event(blocked_event) is None
        assert await svc.resolve_event(allowed_event) is not None
        assert (await svc.stats())["accounts"] == 1
        await svc.close()

    async def test_multi_merge_persons(self) -> None:
        svc = _service(self._tmp.name)
        # Create 3 separate persons via snapshots
        r_target = await svc.register_snapshot(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="100000001", display_name="主体")
        )
        r_s1 = await svc.register_snapshot(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="100000002", display_name="来源1")
        )
        r_s2 = await svc.register_snapshot(
            SenderSnapshot(platform="rocket_chat", platform_user_id="rc_s2", display_name="来源2")
        )

        assert r_target and r_s1 and r_s2
        assert r_target.person and r_s1.person and r_s2.person

        # Merge s1 and s2 INTO target
        count = await svc.merge_multiple_persons(
            [r_s1.person.person_id, r_s2.person.person_id], r_target.person.person_id
        )
        assert count == 2

        # The source ID remains resolvable through a permanent redirect.
        redirected = await svc.get_person_view(r_s1.person.person_id)
        assert redirected is not None
        assert redirected.person.person_id == r_target.person.person_id
        assert await svc.get_person_view(r_s2.person.person_id) is not None
        # Verify all accounts now belong to target
        view = await svc.get_person_view(r_target.person.person_id)
        assert view is not None
        assert len(view.accounts) == 3
        account_ids = {av.account.platform_user_id for av in view.accounts}
        assert account_ids == {"100000001", "100000002", "rc_s2"}
        await svc.close()


class ExtractorTests(unittest.TestCase):
    class _Sender:
        def __init__(self, user_id: str, nickname: str) -> None:
            self.user_id = user_id
            self.nickname = nickname

    class _MessageObj:
        def __init__(
            self, sender: ExtractorTests._Sender, group_id: str = "", raw: dict | None = None
        ) -> None:
            self.sender = sender
            self.group_id = group_id
            self.raw_message = raw or {}

    class _Event:
        def __init__(
            self,
            platform: str,
            sender: ExtractorTests._Sender,
            group_id: str = "",
            raw: dict | None = None,
            umo: str = "",
        ) -> None:
            self._platform = platform
            self.message_obj = ExtractorTests._MessageObj(sender, group_id, raw)
            self.unified_msg_origin = umo

        def get_platform_name(self) -> str:
            return self._platform

        def get_group_id(self) -> str:
            return self.message_obj.group_id

    def test_aiocqhttp_group_card(self) -> None:
        event = self._Event(
            "aiocqhttp",
            self._Sender("100000001", "测试卡片名"),
            group_id="100001",
        )
        snap = extract_snapshot(event)
        assert snap is not None
        assert snap.platform == "aiocqhttp"
        assert snap.platform_user_id == "100000001"
        assert snap.display_name == "测试卡片名"
        assert snap.group_id == "100001"

    def test_rocket_chat_username_from_raw(self) -> None:
        raw = {"u": {"_id": "rcABC", "username": "testuser", "name": "测试用户"}}
        event = self._Event(
            "rocket_chat",
            self._Sender("rcABC", "测试用户"),
            group_id="GENERAL",
            raw=raw,
        )
        snap = extract_snapshot(event)
        assert snap is not None
        assert snap.platform_user_id == "rcABC"
        assert snap.username == "testuser"

    def test_username_bot_hint_requires_token_boundary(self) -> None:
        for index, username in enumerate(("robot", "both", "bottom")):
            event = self._Event(
                "rocket_chat",
                self._Sender(f"rc-{index}", "普通用户"),
                raw={"u": {"username": username}},
            )
            snapshot = extract_snapshot(event)
            assert snapshot is not None and snapshot.is_bot is False

        bot_event = self._Event(
            "rocket_chat",
            self._Sender("rc-bot", "机器人"),
            raw={"u": {"username": "helper-bot"}},
        )
        bot_snapshot = extract_snapshot(bot_event)
        assert bot_snapshot is not None and bot_snapshot.is_bot is True

    def test_missing_user_id_returns_none(self) -> None:
        event = self._Event("aiocqhttp", self._Sender("", ""))
        assert extract_snapshot(event) is None


if __name__ == "__main__":
    unittest.main()
