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


def test_derive_public_origin_and_hosts_falls_back_to_local_test_hosts() -> None:
    origin, allowed_hosts = derive_public_origin_and_hosts("not-a-url")

    assert origin is None
    assert allowed_hosts == ["localhost", "127.0.0.1", "testserver"]
