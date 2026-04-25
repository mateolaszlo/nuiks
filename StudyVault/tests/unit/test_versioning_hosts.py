from __future__ import annotations

from studyvault_backend_common.versioning import derive_public_origin_and_hosts


def test_derive_public_origin_and_hosts_includes_loopback_hosts() -> None:
    origin, allowed_hosts = derive_public_origin_and_hosts(
        "http://keycloak.test/realms/studyvault"
    )

    assert origin == "http://keycloak.test"
    assert "keycloak.test" in allowed_hosts
    assert "localhost" in allowed_hosts
    assert "127.0.0.1" in allowed_hosts
    assert "testserver" in allowed_hosts


def test_derive_public_origin_and_hosts_includes_internal_compose_hosts() -> None:
    _, allowed_hosts = derive_public_origin_and_hosts(
        "http://localhost:8080/realms/studyvault"
    )

    assert "catalog-service" in allowed_hosts
    assert "catalog-service:8000" in allowed_hosts
    assert "search-service" in allowed_hosts
    assert "search-service:8000" in allowed_hosts
    assert "file-service" in allowed_hosts
    assert "file-service:8000" in allowed_hosts
    assert "activity-service" in allowed_hosts
    assert "activity-service:8000" in allowed_hosts
    assert "keycloak" in allowed_hosts
    assert "keycloak:8080" in allowed_hosts


def test_derive_public_origin_and_hosts_falls_back_to_local_test_hosts() -> None:
    origin, allowed_hosts = derive_public_origin_and_hosts("not-a-url")

    assert origin is None
    assert "localhost" in allowed_hosts
    assert "127.0.0.1" in allowed_hosts
    assert "testserver" in allowed_hosts
    assert "catalog-service:8000" in allowed_hosts
    assert "activity-service:8000" in allowed_hosts
