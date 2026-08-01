"""The .env loader that makes `python -m cisco_sdwan_mcp.server` work from a checkout."""

import os

from cisco_sdwan_mcp.env import load_env_file


def test_loads_variables_from_the_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SDWAN_VMANAGE_URL=https://vmanage.test:8443\nSDWAN_USERNAME=reader\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SDWAN_ENV_FILE", str(env_file))

    assert load_env_file() == env_file
    assert os.environ["SDWAN_VMANAGE_URL"] == "https://vmanage.test:8443"
    assert os.environ["SDWAN_USERNAME"] == "reader"


def test_environment_wins_over_the_file(tmp_path, monkeypatch):
    """Compose/Kubernetes inject the real secrets — the file must not clobber."""
    env_file = tmp_path / ".env"
    env_file.write_text("SDWAN_VMANAGE_URL=https://from-file:8443\n", encoding="utf-8")
    monkeypatch.setenv("SDWAN_ENV_FILE", str(env_file))
    monkeypatch.setenv("SDWAN_VMANAGE_URL", "https://from-environment:8443")

    load_env_file()

    assert os.environ["SDWAN_VMANAGE_URL"] == "https://from-environment:8443"


def test_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SDWAN_ENV_FILE", str(tmp_path / "absent.env"))

    assert load_env_file() is None
