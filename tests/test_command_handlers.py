"""Behavioral checks for chat-command privacy boundaries."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import tempfile
import types
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import tests._stubs  # noqa: F401

ROOT_DIR = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "identity_directory_command_test"


def _load_plugin_module() -> ModuleType:
    existing = sys.modules.get(f"{PACKAGE_NAME}.main")
    if isinstance(existing, ModuleType):
        return existing

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT_DIR)]
    sys.modules[PACKAGE_NAME] = package
    spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.main", ROOT_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PLUGIN = _load_plugin_module()
MODELS = importlib.import_module(f"{PACKAGE_NAME}.core.models")


class _Sender:
    def __init__(self, user_id: str, nickname: str) -> None:
        self.user_id = user_id
        self.nickname = nickname


class _Message:
    def __init__(self, user_id: str, nickname: str, group_id: str) -> None:
        self.sender = _Sender(user_id, nickname)
        self.group_id = group_id
        self.raw_message: dict[str, object] = {}


class _Event:
    def __init__(
        self,
        *,
        user_id: str,
        nickname: str,
        group_id: str = "",
        platform: str = "aiocqhttp",
        platform_instance_id: str = "bot-a",
        is_admin: bool = False,
    ) -> None:
        self.message_obj = _Message(user_id, nickname, group_id)
        self.unified_msg_origin = "test:session"
        self._platform = platform
        self._platform_instance_id = platform_instance_id
        self._is_admin = is_admin

    def get_platform_name(self) -> str:
        return self._platform

    def get_platform_id(self) -> str:
        return self._platform_instance_id

    def get_group_id(self) -> str:
        return self.message_obj.group_id

    def is_admin(self) -> bool:
        return self._is_admin

    @staticmethod
    def plain_result(text: str) -> str:
        return text


class CommandPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.config: dict[str, object] = {}
        self.plugin = PLUGIN.IdentityDirectory.__new__(PLUGIN.IdentityDirectory)
        self.plugin.config = self.config
        self.plugin.directory_service = PLUGIN.DirectoryService(
            Path(self._tmp.name) / "directory.db", PLUGIN.DirectoryConfig(self.config)
        )
        self.plugin._memory_salt = "test-salt"
        self.plugin._memory_clients = {}

    async def asyncTearDown(self) -> None:
        await self.plugin.directory_service.close()
        self._tmp.cleanup()

    @staticmethod
    async def _responses(generator: AsyncIterator[str]) -> list[str]:
        return [item async for item in generator]

    async def test_sensitive_commands_reject_group_use_except_self_portrait_and_link(self) -> None:
        event = _Event(user_id="member", nickname="成员", group_id="group-1")

        directory = await self._responses(self.plugin.directory_stats(event))
        persona = await self._responses(self.plugin.persona_cmd(event, "任何人"))
        self_persona = await self._responses(self.plugin.self_persona_cmd(event, "我的设定"))
        link = await self._responses(self.plugin.link_account_cmd(event, ""))

        assert "私聊" in directory[0]
        assert "私聊" in persona[0]
        assert "已成功更新" in self_persona[0]
        assert "私聊" not in self_persona[0]
        assert "绑定码已生成" in link[0]
        assert "私聊" not in link[0]

    async def test_link_allows_group_binding_with_creator_confirmation(self) -> None:
        creator = _Event(user_id="creator", nickname="发起账号", group_id="group-1")
        created = await self._responses(self.plugin.link_account_cmd(creator, ""))
        code = created[0].split("【", 1)[1].split("】", 1)[0]
        assert "/link approve" not in created[0]

        target = _Event(user_id="target", nickname="目标账号", group_id="group-2")
        submitted = await self._responses(self.plugin.link_account_cmd(target, code))
        assert "已提交" in submitted[0]

        obsolete = await self._responses(self.plugin.link_account_cmd(creator, f"approve {code}"))
        assert "用法" in obsolete[0]

        confirmed = await self._responses(self.plugin.link_account_cmd(creator, f"confirm {code}"))
        assert "绑定成功" in confirmed[0]

    async def test_link_logs_lifecycle_without_sensitive_values(self) -> None:
        creator = _Event(user_id="raw-creator-id", nickname="发起账号", group_id="group-1")
        target = _Event(user_id="raw-target-id", nickname="目标账号", group_id="group-2")

        with patch.object(PLUGIN.logger, "info") as info, patch.object(PLUGIN.logger, "warning") as warning:
            created = await self._responses(self.plugin.link_account_cmd(creator, ""))
            code = created[0].split("【", 1)[1].split("】", 1)[0]
            await self._responses(self.plugin.link_account_cmd(target, code))
            await self._responses(self.plugin.link_account_cmd(creator, f"confirm {code}"))

        log_text = "\n".join(" ".join(str(value) for value in call.args) for call in info.call_args_list)
        assert "[identity-directory] binding ticket created" in log_text
        assert "[identity-directory] binding target submitted" in log_text
        assert "[identity-directory] binding confirmed" in log_text
        assert code not in log_text
        assert "raw-creator-id" not in log_text
        assert "raw-target-id" not in log_text
        warning.assert_not_called()

    async def test_link_logs_rejections_without_sensitive_values(self) -> None:
        creator = _Event(user_id="raw-creator-id", nickname="发起账号", group_id="group-1")
        other = _Event(user_id="raw-other-id", nickname="其他账号", group_id="group-2")

        with patch.object(PLUGIN.logger, "info"), patch.object(PLUGIN.logger, "warning") as warning:
            created = await self._responses(self.plugin.link_account_cmd(creator, ""))
            code = created[0].split("【", 1)[1].split("】", 1)[0]
            await self._responses(self.plugin.link_account_cmd(other, "INVALID-CODE"))
            await self._responses(self.plugin.link_account_cmd(other, f"confirm {code}"))

        warning_text = "\n".join(
            " ".join(str(value) for value in call.args) for call in warning.call_args_list
        )
        assert "[identity-directory] binding target submission rejected" in warning_text
        assert "[identity-directory] binding confirmation rejected" in warning_text
        assert "INVALID-CODE" not in warning_text
        assert code not in warning_text
        assert "raw-other-id" not in warning_text

    async def test_member_lookup_defaults_closed_then_masks_group_result(self) -> None:
        event = _Event(user_id="requester", nickname="查询者", group_id="group-1")
        denied = await self._responses(self.plugin.lookup_person(event, "同名成员"))
        assert "未启用" in denied[0]

        self.config["allow_member_lookup"] = True
        await self.plugin.directory_service.register_snapshot(
            MODELS.SenderSnapshot(
                "aiocqhttp",
                "visible-account",
                "同名成员",
                group_id="group-1",
                platform_instance_id="bot-a",
            )
        )
        await self.plugin.directory_service.register_snapshot(
            MODELS.SenderSnapshot(
                "aiocqhttp",
                "other-instance-account",
                "同名成员",
                group_id="group-1",
                platform_instance_id="bot-b",
            )
        )

        result = await self._responses(self.plugin.lookup_person(event, "同名成员"))
        assert "找到 1 位" in result[0]
        assert "visible-account" not in result[0]
        assert "other-instance-account" not in result[0]
        assert "Person ID" not in result[0]

    async def test_private_admin_lookup_includes_disambiguation_identifiers(self) -> None:
        event = _Event(user_id="admin", nickname="管理员", is_admin=True)
        await self.plugin.directory_service.register_snapshot(
            MODELS.SenderSnapshot(
                "aiocqhttp",
                "visible-account",
                "同名成员",
                platform_instance_id="bot-a",
            )
        )

        result = await self._responses(self.plugin.lookup_person(event, "同名成员"))
        assert "Person ID:" in result[0]
        assert "账号: aiocqhttp:visible-account" in result[0]

    async def test_self_persona_bounds_private_input(self) -> None:
        event = _Event(user_id="member", nickname="成员")
        result = await self._responses(self.plugin.self_persona_cmd(event, "x" * 501))
        assert "最多 500 个字符" in result[0]

    async def test_self_persona_write_read_and_clear_updates_notes(self) -> None:
        event = _Event(user_id="member-persona", nickname="成员画像测试")
        write_res = await self._responses(self.plugin.self_persona_cmd(event, "喜欢自动化测试与开源"))
        assert "已成功更新" in write_res[0]
        assert "喜欢自动化测试与开源" in write_res[0]

        resolution = await self.plugin.directory_service.resolve_sender(
            "aiocqhttp", "member-persona", platform_instance_id="bot-a"
        )
        assert resolution is not None and resolution.person is not None
        assert resolution.person.notes == "喜欢自动化测试与开源"

        read_res = await self._responses(self.plugin.self_persona_cmd(event, ""))
        assert "喜欢自动化测试与开源" in read_res[0]

        clear_res = await self._responses(self.plugin.self_persona_cmd(event, "清空"))
        assert "已成功清空" in clear_res[0]

        cleared = await self.plugin.directory_service.resolve_sender(
            "aiocqhttp", "member-persona", platform_instance_id="bot-a"
        )
        assert cleared is not None and cleared.person is not None
        assert cleared.person.notes == ""

    async def test_self_persona_group_read_hides_private_details_and_respects_switch(self) -> None:
        event = _Event(user_id="group-member", nickname="群成员", group_id="group-1")
        await self._responses(self.plugin.self_persona_cmd(event, "公开画像"))

        read_res = await self._responses(self.plugin.self_persona_cmd(event, ""))
        assert "公开画像" in read_res[0]
        assert "aiocqhttp:group-member" not in read_res[0]

        self.plugin.config = {"allow_self_persona": False}
        disabled_res = await self._responses(self.plugin.self_persona_cmd(event, "新画像"))
        assert "已被管理员关闭" in disabled_res[0]
        resolution = await self.plugin.directory_service.resolve_sender(
            "aiocqhttp", "group-member", "group-1", platform_instance_id="bot-a"
        )
        assert resolution is not None and resolution.person is not None
        assert resolution.person.notes == "公开画像"


if __name__ == "__main__":
    unittest.main()
