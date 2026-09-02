"""Pytest configuration and test environment bootstrap."""

from __future__ import annotations

from tests._stubs import install_astrbot_stubs

# Automatically ensure AstrBot mocks are available in isolated test environments (such as CI)
install_astrbot_stubs()
