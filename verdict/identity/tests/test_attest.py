from verdict.identity.attest import (
    _scrub, build_attestation, canonical_hash, onchain_value,
)

SAMPLE = {
    "verdict": "NO_TRADE",
    "created_at": "2026-06-20T17:00:00Z",  # volatile — must not affect the hash
    "candidates": [{"id": "a", "ts": 123}, {"id": "b"}],
    "criteria": {"min_sharpe": 1.0, "max_drawdown_pct": 25.0},
    "summary": "NO_TRADE across the majors",
}


def test_scrub_drops_volatile_fields_only():
    s = _scrub(SAMPLE)
    assert "created_at" not in s
    assert "ts" not in s["candidates"][0]
    assert s["verdict"] == "NO_TRADE"
    assert s["criteria"]["min_sharpe"] == 1.0


def test_hash_is_timestamp_independent():
    a = dict(SAMPLE, created_at="2026-06-20T17:00:00Z")
    b = dict(SAMPLE, created_at="1999-01-01T00:00:00Z")
    assert canonical_hash(a) == canonical_hash(b)
    h = canonical_hash(a)
    assert h.startswith("0x") and len(h) >= 42  # keccak/sha256 hex


def test_changing_the_decision_changes_the_hash():
    assert canonical_hash(SAMPLE) != canonical_hash(dict(SAMPLE, verdict="TRADE"))


def test_onchain_value_is_compact_and_parseable():
    att = build_attestation(SAMPLE, now_iso="2026-06-20T17:00:00+00:00")
    v = onchain_value(att)
    parts = v.split("|")
    assert parts[0] == "verdict-attestation/v1"
    assert parts[1] == "NO_TRADE"
    assert parts[2].startswith("0x")
    assert "@4h" in v
    assert att["candidates"] == 2
