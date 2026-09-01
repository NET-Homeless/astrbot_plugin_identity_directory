from __future__ import annotations

import unittest

from scripts.privacy_check import scan_line


class PrivacyScannerTests(unittest.TestCase):
    def test_public_fixture_allowlist_is_explicit(self) -> None:
        safe_lines = (
            'platform_user_id="100000001"',
            "contact@example.org",
            'path="/Users/username/project"',
            'api_key="test-placeholder"',
        )

        for line in safe_lines:
            with self.subTest(line=line):
                assert scan_line("fixture.py", line, line_no=3) == []

    def test_diagnostics_redact_account_email_path_and_secret_values(self) -> None:
        account_id = "987" + "654321"
        email = "person@" + "private." + "example"
        local_path = "/Users/" + "alice" + "/private-project"
        secret_value = "sk-" + ("A" * 48)
        secret_field = "api" + "_key"
        cases = (
            ("user_id=" + repr(account_id), account_id, "账号 ID"),
            (email, email, "邮箱地址"),
            ("path=" + repr(local_path), local_path, "本机绝对路径"),
            (secret_field + "=" + repr(secret_value), secret_value, "敏感字段"),
        )

        for line, sensitive_value, message in cases:
            with self.subTest(message=message):
                diagnostics = "\n".join(scan_line("fixture.py", line, line_no=8))
                assert message in diagnostics
                assert sensitive_value not in diagnostics

    def test_known_token_format_is_detected_without_echoing_token(self) -> None:
        token = "ghp_" + ("B" * 40)
        diagnostics = "\n".join(scan_line("fixture.py", "token=" + token, line_no=12))

        assert "GitHub Token" in diagnostics
        assert token not in diagnostics


if __name__ == "__main__":
    unittest.main()
