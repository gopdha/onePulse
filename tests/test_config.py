import pytest

from onepulse_common.config import MissingConfigError, Settings


def test_load_raises_on_missing_required_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONEPULSE_ENVIRONMENT", raising=False)
    with pytest.raises(MissingConfigError):
        Settings.load()


def test_load_reads_all_fields_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEPULSE_ENVIRONMENT", "dev")
    monkeypatch.setenv("ONEPULSE_PG_HOST", "onepulse-pg-dev.postgres.database.azure.com")
    monkeypatch.setenv("ONEPULSE_PG_DATABASE", "onepulse")
    monkeypatch.setenv("ONEPULSE_PG_ROLE", "app_role")
    monkeypatch.setenv("ONEPULSE_FOUNDRY_BASE_URL", "https://example.services.ai.azure.com/anthropic")
    monkeypatch.setenv("ONEPULSE_FOUNDRY_DEPLOYMENT_NAME", "claude-sonnet-5")

    settings = Settings.load()

    assert settings.environment == "dev"
    assert settings.postgres.host == "onepulse-pg-dev.postgres.database.azure.com"
    assert settings.postgres.role_name == "app_role"
    assert settings.postgres.port == 5432
    assert settings.foundry.deployment_name == "claude-sonnet-5"


def test_load_reads_optional_pg_port_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEPULSE_ENVIRONMENT", "dev")
    monkeypatch.setenv("ONEPULSE_PG_HOST", "host")
    monkeypatch.setenv("ONEPULSE_PG_DATABASE", "db")
    monkeypatch.setenv("ONEPULSE_PG_ROLE", "app_role")
    monkeypatch.setenv("ONEPULSE_PG_PORT", "6432")
    monkeypatch.setenv("ONEPULSE_FOUNDRY_BASE_URL", "https://example.services.ai.azure.com/anthropic")
    monkeypatch.setenv("ONEPULSE_FOUNDRY_DEPLOYMENT_NAME", "claude-sonnet-5")

    settings = Settings.load()

    assert settings.postgres.port == 6432
