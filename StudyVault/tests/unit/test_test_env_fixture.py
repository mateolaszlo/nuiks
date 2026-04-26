from __future__ import annotations

from tests.conftest import load_test_env_values


def test_test_env_fixture_loads_values_from_dot_env_test() -> None:
    env_values = load_test_env_values()

    assert env_values["KEYCLOAK_ISSUER_URL"] == "http://keycloak.test/realms/studyvault"
    assert env_values["CATALOG_INTERNAL_URL"] == "http://catalog.test"
    assert env_values["FILE_INTERNAL_URL"] == "http://file.test"
    assert env_values["FILE_S3_BUCKET"] == "studyvault-files-test"
    assert env_values["STUDYVAULT_SKIP_APP_BOOTSTRAP"] == "true"
