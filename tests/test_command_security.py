"""Regression contracts for security-sensitive chat command registration."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from astrbot.core.star.filter.command import CommandFilter, GreedyStr

ROOT_DIR = Path(__file__).resolve().parent.parent


class CommandParsingTests(unittest.TestCase):
    def test_greedy_string_keeps_all_command_words(self) -> None:
        command = CommandFilter("self_persona")
        parsed = command.validate_and_convert_params(["喜欢", "软路由", "与", "AI"], {"content": GreedyStr})
        assert parsed == {"content": "喜欢 软路由 与 AI"}

    def test_sensitive_commands_register_greedy_arguments(self) -> None:
        module = ast.parse((ROOT_DIR / "main.py").read_text(encoding="utf-8"))
        expected_parameters = {
            "lookup_person": "name",
            "link_account_cmd": "action",
            "persona_cmd": "target",
            "self_persona_cmd": "content",
        }
        functions = {
            node.name: node
            for node in ast.walk(module)
            if isinstance(node, ast.AsyncFunctionDef) and node.name in expected_parameters
        }
        assert functions.keys() == expected_parameters.keys()
        for function_name, parameter_name in expected_parameters.items():
            parameter = next(
                argument for argument in functions[function_name].args.args if argument.arg == parameter_name
            )
            assert isinstance(parameter.annotation, ast.Name)
            assert parameter.annotation.id == "GreedyStr"


class PluginConfigurationSchemaTests(unittest.TestCase):
    def test_command_safety_controls_are_exposed_and_localized(self) -> None:
        schema = json.loads((ROOT_DIR / "_conf_schema.json").read_text(encoding="utf-8"))
        assert schema["allow_self_persona"]["default"] is True
        assert schema["allow_member_lookup"]["default"] is False

        for locale in ("zh-CN", "en-US"):
            messages = json.loads(
                (ROOT_DIR / ".astrbot-plugin" / "i18n" / f"{locale}.json").read_text(encoding="utf-8")
            )
            assert {"allow_self_persona", "allow_member_lookup"} <= messages["config"].keys()


if __name__ == "__main__":
    unittest.main()
