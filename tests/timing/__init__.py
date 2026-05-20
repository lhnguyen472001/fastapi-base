"""Statistical-timing test fixtures and helpers (SC-005, SC-006).

These tests probe the wall-clock distribution of endpoints to detect
information-leak side channels. They live in their own package so the
fixtures (large sample sizes, no shared state with other tests) can be
opt-in via ``pytest tests/timing/``.
"""
