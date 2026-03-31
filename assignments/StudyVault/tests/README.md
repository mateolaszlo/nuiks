# Automated Tests

Top-level test suites are split by confidence level and scope:

- `unit/` shared-library and pure-logic tests
- `services/` service-specific API and behavior tests
- `integration/` multi-service workflow tests
- `smoke/` compose-based MVP health checks
- `fixtures/` reusable files and payloads

Service-local tests can also live under each backend app in `apps/*/tests/`.

