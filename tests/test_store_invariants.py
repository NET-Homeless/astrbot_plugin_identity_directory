from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.models import SenderSnapshot
from core.service import DirectoryConfig, DirectoryService
from core.store import _SCHEMA_V1, DirectoryStore


class StoreMigrationTests(unittest.TestCase):
    def test_v1_database_migrates_without_losing_relations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "directory.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(_SCHEMA_V1)
            conn.execute(
                "INSERT INTO persons VALUES(?,?,?,?,?,?,?,?)",
                ("person-1", "测试用户", "备注", "标签", 0, 0, 1.0, 2.0),
            )
            conn.execute(
                "INSERT INTO accounts VALUES(?,?,?,?,?,?,?)",
                ("account-1", "aiocqhttp", "user-1", "", "person-1", 1.0, 2.0),
            )
            conn.execute(
                "INSERT INTO memberships VALUES(?,?,?,?,?,?)",
                ("membership-1", "account-1", "group-1", "群名片", 1.0, 2.0),
            )
            conn.execute(
                "INSERT INTO aliases VALUES(?,?,?,?,?,?,?,?)",
                ("alias-1", "account-1", "群名片", "aiocqhttp", "group-1", "observed", 1.0, 2.0),
            )
            conn.execute("PRAGMA user_version=1")
            conn.commit()
            conn.close()

            store = DirectoryStore(db_path)
            account = store.get_account("account-1")
            assert account is not None
            assert account.platform_instance_id == "aiocqhttp"
            assert account.person_id == "person-1"
            assert store.list_memberships("account-1")[0].current_card == "群名片"
            assert store.list_aliases("account-1")[0].name == "群名片"
            assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 5
            assert store._conn.execute("PRAGMA foreign_key_check").fetchall() == []
            store.close()

    def test_v2_fallback_instance_merges_into_single_real_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "directory.db"
            DirectoryStore(db_path).close()
            conn = sqlite3.connect(db_path)
            conn.executemany(
                "INSERT INTO persons(person_id, canonical_name, notes, tags, is_bot, is_archived, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                [
                    ("person-legacy", "人工整理姓名", "保留备注", "", 0, 0, 1.0, 2.0),
                    ("person-stub", "新群名片", "", "", 0, 0, 5.0, 6.0),
                ],
            )
            conn.executemany(
                "INSERT INTO accounts VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    (
                        "account-legacy",
                        "aiocqhttp",
                        "aiocqhttp",
                        "user-1",
                        "",
                        "person-legacy",
                        1.0,
                        7.0,
                        0,
                    ),
                    (
                        "account-current",
                        "aiocqhttp",
                        "萌依",
                        "user-1",
                        "current-user",
                        "person-stub",
                        5.0,
                        9.0,
                        0,
                    ),
                    ("ambiguous-legacy", "rocket_chat", "rocket_chat", "user-2", "", None, 1.0, 2.0, 0),
                    ("ambiguous-a", "rocket_chat", "workspace-a", "user-2", "", None, 1.0, 2.0, 0),
                    ("ambiguous-b", "rocket_chat", "workspace-b", "user-2", "", None, 1.0, 2.0, 0),
                ],
            )
            conn.executemany(
                "INSERT INTO memberships VALUES(?,?,?,?,?,?)",
                [
                    ("membership-legacy", "account-legacy", "group-1", "旧名片", 1.0, 7.0),
                    ("membership-current", "account-current", "group-1", "新名片", 5.0, 9.0),
                ],
            )
            conn.executemany(
                "INSERT INTO aliases VALUES(?,?,?,?,?,?,?,?)",
                [
                    (
                        "alias-legacy",
                        "account-legacy",
                        "共同别名",
                        "aiocqhttp",
                        "group-1",
                        "manual",
                        1.0,
                        7.0,
                    ),
                    (
                        "alias-current",
                        "account-current",
                        "共同别名",
                        "aiocqhttp",
                        "group-1",
                        "observed",
                        5.0,
                        9.0,
                    ),
                    (
                        "alias-only-legacy",
                        "account-legacy",
                        "历史别名",
                        "aiocqhttp",
                        None,
                        "manual",
                        1.0,
                        4.0,
                    ),
                ],
            )
            conn.execute("PRAGMA user_version=2")
            conn.commit()
            conn.close()

            store = DirectoryStore(db_path)
            merged = store.get_account_by_platform("aiocqhttp", "user-1", "萌依")
            assert merged is not None
            assert merged.account_id == "account-current"
            assert merged.person_id == "person-legacy"
            assert (merged.first_seen, merged.last_seen) == (1.0, 9.0)
            assert store.get_account("account-legacy") is None
            assert store.get_person("person-stub") is not None
            assert store.resolve_person_id("person-stub") == "person-legacy"

            memberships = store.list_memberships("account-current")
            assert len(memberships) == 1
            assert memberships[0].current_card == "新名片"
            assert (memberships[0].first_seen, memberships[0].last_seen) == (1.0, 9.0)
            aliases = {alias.name: alias for alias in store.list_aliases("account-current")}
            assert set(aliases) == {"共同别名", "历史别名"}
            assert aliases["共同别名"].source.value == "manual"
            assert (aliases["共同别名"].first_seen, aliases["共同别名"].last_seen) == (1.0, 9.0)

            ambiguous, total = store.list_account_views(platform="rocket_chat")
            assert total == 3
            assert {view.account.platform_instance_id for view in ambiguous} == {
                "rocket_chat",
                "workspace-a",
                "workspace-b",
            }
            assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 5
            assert store._conn.execute("PRAGMA foreign_key_check").fetchall() == []
            store.close()

    def test_v4_migrates_legacy_self_persona_into_notes_and_drops_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "directory.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE persons (
                    person_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '',
                    is_bot INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    self_persona TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.executemany(
                "INSERT INTO persons VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    ("person-self", "测试用户", "", "", 0, 0, 1.0, 2.0, "全栈开发者"),
                    ("person-notes", "已有画像", "原画像", "", 0, 0, 1.0, 2.0, "旧副本"),
                ],
            )
            conn.execute("PRAGMA user_version=4")
            conn.commit()
            conn.close()

            store = DirectoryStore(db_path)
            self_portrait = store.get_person("person-self")
            existing_portrait = store.get_person("person-notes")
            assert self_portrait is not None and self_portrait.notes == "全栈开发者"
            assert existing_portrait is not None and existing_portrait.notes == "原画像"
            columns = {row[1] for row in store._conn.execute("PRAGMA table_info(persons)")}
            assert "self_persona" not in columns
            assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 5
            store.close()


class ServiceInvariantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    def _service(self) -> DirectoryService:
        return DirectoryService(
            Path(self._tmp.name) / "directory.db",
            DirectoryConfig({"auto_stub_person": True}),
        )

    async def test_platform_instance_is_part_of_account_identity(self) -> None:
        service = self._service()
        first = await service.register_snapshot(
            SenderSnapshot(
                platform="rocket_chat",
                platform_user_id="same-user-id",
                display_name="Workspace A",
                platform_instance_id="workspace-a",
            )
        )
        second = await service.register_snapshot(
            SenderSnapshot(
                platform="rocket_chat",
                platform_user_id="same-user-id",
                display_name="Workspace B",
                platform_instance_id="workspace-b",
            )
        )

        assert first is not None and second is not None
        assert first.account.account_id != second.account.account_id
        assert (await service.stats())["accounts"] == 2
        await service.close()

    async def test_manual_unlink_is_not_undone_by_next_observation(self) -> None:
        service = self._service()
        snapshot = SenderSnapshot(
            platform="aiocqhttp",
            platform_user_id="user-1",
            display_name="测试用户",
            platform_instance_id="qq-instance",
        )
        first = await service.register_snapshot(snapshot)
        assert first is not None and first.person is not None
        assert await service.unlink_account(first.account.account_id)

        second = await service.register_snapshot(snapshot)
        assert second is not None
        assert second.person is None
        assert second.account.person_id is None
        assert second.account.suppress_auto_stub is True
        await service.close()

    async def test_deleted_person_does_not_recreate_on_next_observation(self) -> None:
        service = self._service()
        snapshot = SenderSnapshot(
            platform="aiocqhttp",
            platform_user_id="deleted-user",
            display_name="已删除联系人",
            platform_instance_id="qq-instance",
        )
        first = await service.register_snapshot(snapshot)
        assert first is not None and first.person is not None
        assert await service.delete_person(first.person.person_id)

        second = await service.register_snapshot(snapshot)
        assert second is not None
        assert second.person is None
        assert second.account.person_id is None
        assert second.account.suppress_auto_stub is True
        stats = await service.stats()
        assert stats["unlinked_accounts"] == 1
        assert stats["repairable_unlinked_accounts"] == 0
        await service.close()

    async def test_runtime_config_changes_are_applied_to_registration(self) -> None:
        raw_config = {"auto_stub_person": False}
        service = DirectoryService(
            Path(self._tmp.name) / "directory.db",
            DirectoryConfig(raw_config),
        )
        assert service.config.hindsight_timeout_seconds == 3
        first = await service.register_snapshot(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="config-user-1", display_name="未建档")
        )
        assert first is not None and first.person is None

        raw_config["auto_stub_person"] = True
        second = await service.register_snapshot(
            SenderSnapshot(platform="aiocqhttp", platform_user_id="config-user-2", display_name="应建档")
        )
        assert second is not None and second.person is not None
        await service.close()

    async def test_concurrent_observations_are_serialized_to_one_account(self) -> None:
        service = self._service()
        snapshots = [
            SenderSnapshot(
                platform="aiocqhttp",
                platform_user_id="same-user",
                display_name=f"群名片 {index}",
                group_id="group-1",
                platform_instance_id="qq-instance",
            )
            for index in range(20)
        ]

        await asyncio.gather(*(service.register_snapshot(snapshot) for snapshot in snapshots))
        stats = await service.stats()
        assert stats["accounts"] == 1
        assert stats["persons"] == 1
        assert stats["memberships"] == 1
        assert stats["aliases"] == 20
        await service.close()

    async def test_close_drains_scheduled_observations(self) -> None:
        service = self._service()
        assert service.schedule_observation(
            SenderSnapshot(
                platform="aiocqhttp",
                platform_user_id="scheduled-user",
                display_name="异步登记",
            )
        )
        await service.close()

        store = DirectoryStore(Path(self._tmp.name) / "directory.db")
        assert store.stats()["accounts"] == 1
        store.close()

    async def test_merge_identity_ids_include_all_sources(self) -> None:
        service = self._service()
        results = [
            await service.register_snapshot(
                SenderSnapshot(
                    platform="aiocqhttp",
                    platform_user_id=f"user-{index}",
                    display_name=f"联系人 {index}",
                )
            )
            for index in range(3)
        ]
        assert all(result is not None and result.person is not None for result in results)
        target = results[0].person.person_id  # type: ignore[union-attr]
        sources = [result.person.person_id for result in results[1:]]  # type: ignore[union-attr]
        await service.merge_multiple_persons(sources, target)

        assert set(await service.list_person_identity_ids(target)) == {target, *sources}
        await service.close()


if __name__ == "__main__":
    unittest.main()
