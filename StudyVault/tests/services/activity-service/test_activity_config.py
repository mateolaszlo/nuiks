from tests.conftest import load_service_module


def test_activity_settings_prefer_dedicated_keycloak_admin_credentials(monkeypatch) -> None:
    config = load_service_module("activity", "app.core.config")
    monkeypatch.setenv("KEYCLOAK_ADMIN_USERNAME", "explicit-admin")
    monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "explicit-password")
    monkeypatch.setenv("KC_BOOTSTRAP_ADMIN_USERNAME", "bootstrap-admin")
    monkeypatch.setenv("KC_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-password")
    config.get_settings.cache_clear()

    settings = config.get_settings()

    assert settings.keycloak_admin_username == "explicit-admin"
    assert settings.keycloak_admin_password == "explicit-password"
    config.get_settings.cache_clear()


def test_activity_settings_fall_back_to_bootstrap_admin_credentials(monkeypatch) -> None:
    config = load_service_module("activity", "app.core.config")
    monkeypatch.delenv("KEYCLOAK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("KEYCLOAK_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("KC_BOOTSTRAP_ADMIN_USERNAME", "bootstrap-admin")
    monkeypatch.setenv("KC_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-password")
    config.get_settings.cache_clear()

    settings = config.get_settings()

    assert settings.keycloak_admin_username == "bootstrap-admin"
    assert settings.keycloak_admin_password == "bootstrap-password"
    config.get_settings.cache_clear()


def test_activity_settings_default_admin_credentials_when_no_env_is_set(monkeypatch) -> None:
    config = load_service_module("activity", "app.core.config")
    monkeypatch.delenv("KEYCLOAK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("KEYCLOAK_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("KC_BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("KC_BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    config.get_settings.cache_clear()

    settings = config.get_settings()

    assert settings.keycloak_admin_username == "admin"
    assert settings.keycloak_admin_password == "admin"
    assert settings.keycloak_auth_sync_enabled is True
    assert settings.keycloak_auth_sync_interval_seconds == 300.0
    assert settings.keycloak_auth_sync_batch_size == 200
    config.get_settings.cache_clear()
