"""Lightweight fallback stubs for AstrBot dependencies in isolated test/CI environments."""

from __future__ import annotations

import logging
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any


class _StubModule(types.ModuleType):
    def __getattr__(self, name: str) -> Any:
        return super().__getattribute__(name)


def install_astrbot_stubs() -> None:
    if "astrbot" in sys.modules:
        return

    try:
        import astrbot  # noqa: F401

        return
    except ImportError:
        pass

    # Build stub module tree
    astrbot_mod = _StubModule("astrbot")
    api_mod = _StubModule("astrbot.api")
    event_mod = _StubModule("astrbot.api.event")
    star_mod = _StubModule("astrbot.api.star")
    web_mod = _StubModule("astrbot.api.web")
    core_mod = _StubModule("astrbot.core")
    core_agent_mod = _StubModule("astrbot.core.agent")
    core_agent_msg_mod = _StubModule("astrbot.core.agent.message")
    core_star_mod = _StubModule("astrbot.core.star")
    core_star_star_mod = _StubModule("astrbot.core.star.star")
    core_star_filter_mod = _StubModule("astrbot.core.star.filter")
    core_star_filter_cmd_mod = _StubModule("astrbot.core.star.filter.command")
    core_star_filter_custom_mod = _StubModule("astrbot.core.star.filter.custom_filter")
    core_utils_mod = _StubModule("astrbot.core.utils")
    core_utils_path_mod = _StubModule("astrbot.core.utils.astrbot_path")

    # astrbot.api
    class AstrBotConfig(dict[str, Any]):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.__dict__ = self

    api_mod.__dict__["AstrBotConfig"] = AstrBotConfig
    api_mod.__dict__["logger"] = logging.getLogger("astrbot")

    # astrbot.api.event
    class AstrMessageEvent:
        pass

    class PermissionType:
        ADMIN = "ADMIN"
        USER = "USER"

    class _FilterMeta(type):
        def __getattr__(cls, name: str) -> Any:
            if name == "PermissionType":
                return PermissionType
            return lambda *args, **kwargs: lambda fn: fn

    class _FilterModule(metaclass=_FilterMeta):
        PermissionType: Any = None

        def __getattr__(self, name: str) -> Any:
            if name == "PermissionType":
                return PermissionType
            return lambda *args, **kwargs: lambda fn: fn

        @staticmethod
        def command(*args: Any, **kwargs: Any) -> Callable[[Any], Any]:
            _ = (args, kwargs)
            return lambda fn: fn

        @staticmethod
        def permission_type(*args: Any, **kwargs: Any) -> Callable[[Any], Any]:
            _ = (args, kwargs)
            return lambda fn: fn

        @staticmethod
        def custom_filter(*args: Any, **kwargs: Any) -> Callable[[Any], Any]:
            _ = (args, kwargs)
            return lambda fn: fn

    _FilterModule.PermissionType = PermissionType
    event_mod.__dict__["AstrMessageEvent"] = AstrMessageEvent
    event_mod.__dict__["filter"] = _FilterModule

    # astrbot.api.star
    class Context:
        def __init__(self) -> None:
            self._web_apis: list[tuple[str, Any, list[str], str]] = []
            self._stars: dict[str, Any] = {}

        def register_web_api(self, path: str, handler: Any, methods: list[str], description: str) -> None:
            self._web_apis.append((path, handler, methods, description))

        def get_registered_star(self, name: str) -> Any:
            return self._stars.get(name)

    class Star:
        def __init__(self, context: Any, config: Any = None) -> None:
            self.context = context
            self.config = config

    def register(
        name: str, author: str, desc: str, version: str, repo: str | None = None
    ) -> Callable[[Any], Any]:
        _ = (name, author, desc, version, repo)
        return lambda cls: cls

    star_mod.__dict__["Context"] = Context
    star_mod.__dict__["Star"] = Star
    star_mod.__dict__["register"] = register

    # astrbot.api.web
    class _WebResponse:
        def __init__(self, data: Any, status: int = 200) -> None:
            self.data = data
            self.status = status

    def json_response(data: Any, status: int = 200) -> _WebResponse:
        return _WebResponse(data, status)

    def error_response(message: str, status: int = 400) -> _WebResponse:
        return _WebResponse({"error": message}, status)

    web_mod.__dict__["json_response"] = json_response
    web_mod.__dict__["error_response"] = error_response
    web_mod.__dict__["request"] = object()

    # astrbot.core.agent.message
    class TextPart:
        def __init__(self, text: str = "") -> None:
            self.text = text

        def mark_as_temp(self) -> TextPart:
            return self

    core_agent_msg_mod.__dict__["TextPart"] = TextPart

    # astrbot.core.star.filter.command
    class GreedyStr(str):
        pass

    class CommandFilter:
        def __init__(self, name: str) -> None:
            self.name = name

        def validate_and_convert_params(
            self, words: list[str], annotations: dict[str, Any]
        ) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for param_name, anno in annotations.items():
                if anno is GreedyStr or getattr(anno, "__name__", "") == "GreedyStr":
                    result[param_name] = " ".join(words)
            return result

    core_star_filter_cmd_mod.__dict__["GreedyStr"] = GreedyStr
    core_star_filter_cmd_mod.__dict__["CommandFilter"] = CommandFilter

    # astrbot.core.star.filter.custom_filter
    class CustomFilter:
        pass

    core_star_filter_custom_mod.__dict__["CustomFilter"] = CustomFilter

    # astrbot.core.star.star
    core_star_star_mod.__dict__["star_map"] = {}

    # astrbot.core.utils.astrbot_path
    def get_astrbot_plugin_data_path() -> Path:
        return Path("./data")

    core_utils_path_mod.__dict__["get_astrbot_plugin_data_path"] = get_astrbot_plugin_data_path

    # Register in sys.modules
    sys.modules["astrbot"] = astrbot_mod
    sys.modules["astrbot.api"] = api_mod
    sys.modules["astrbot.api.event"] = event_mod
    sys.modules["astrbot.api.star"] = star_mod
    sys.modules["astrbot.api.web"] = web_mod
    sys.modules["astrbot.core"] = core_mod
    sys.modules["astrbot.core.agent"] = core_agent_mod
    sys.modules["astrbot.core.agent.message"] = core_agent_msg_mod
    sys.modules["astrbot.core.star"] = core_star_mod
    sys.modules["astrbot.core.star.star"] = core_star_star_mod
    sys.modules["astrbot.core.star.filter"] = core_star_filter_mod
    sys.modules["astrbot.core.star.filter.command"] = core_star_filter_cmd_mod
    sys.modules["astrbot.core.star.filter.custom_filter"] = core_star_filter_custom_mod
    sys.modules["astrbot.core.utils"] = core_utils_mod
    sys.modules["astrbot.core.utils.astrbot_path"] = core_utils_path_mod


install_astrbot_stubs()
