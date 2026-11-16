"""배포 서버 Secrets → 환경변수 연결(app/state.load_secrets_into_env)."""

from __future__ import annotations

import streamlit as st

from app import state


class FakeSecrets(dict):
    pass


def test_secrets_copied_without_overwriting(monkeypatch):
    monkeypatch.delenv("TEST_BRIDGE_A", raising=False)
    monkeypatch.setenv("TEST_BRIDGE_B", "local")
    monkeypatch.setattr(st, "secrets", FakeSecrets(TEST_BRIDGE_A="from-secrets", TEST_BRIDGE_B="server", nested={"x": 1}))
    state.load_secrets_into_env()
    import os

    assert os.environ["TEST_BRIDGE_A"] == "from-secrets"
    assert os.environ["TEST_BRIDGE_B"] == "local"  # 이미 있는 값은 그대로
    assert "nested" not in os.environ
    monkeypatch.delenv("TEST_BRIDGE_A")


def test_no_secrets_file_is_noop(monkeypatch):
    class Broken:
        def __iter__(self):
            raise FileNotFoundError("no secrets.toml")

        def keys(self):
            raise FileNotFoundError("no secrets.toml")

    monkeypatch.setattr(st, "secrets", Broken())
    state.load_secrets_into_env()  # 예외 없이 끝나야 한다
