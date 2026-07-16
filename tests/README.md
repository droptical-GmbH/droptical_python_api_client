# Tests

These are integration tests intended for droptical's own CI. They run against a
droptical device or test backend.

Point them at a target with the `DROPTICAL_TEST_HOST` / `DROPTICAL_TEST_PORT`
environment variables (default `127.0.0.1:80`). The integration suite skips
automatically if no backend is reachable.

WARNING: the suite establishes its baseline via factory-reset, which wipes
measurement data and resets settings. Only ever point it at a test backend,
never a production device.

The backend-free unit tests run anywhere, with no device or backend required:

- `tests/test_models.py` — model parsing / serialization.
- The stream protocol and JSON-parsing tests.

Run everything with `pytest` from the repository root.
