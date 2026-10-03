"""Tests for the persistent, expiring route table."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from core.network.routing import FRAG, Route, Routing


def test_remember_is_persisted_and_reloaded(tmp_path):
    path = tmp_path / "network.json"
    routing = Routing(path)
    routing.remember("blocked.example", FRAG, "record_sni_mid", "first_byte_timeout")

    reloaded = Routing(path)
    route = reloaded.get("blocked.example")
    assert route is not None
    assert route.transport == FRAG
    assert route.strategy == "record_sni_mid"
    assert route.reason == "first_byte_timeout"
    assert route.expires_at


def test_hostname_lookup_is_case_and_dot_insensitive(tmp_path):
    routing = Routing(tmp_path / "network.json")
    routing.remember("Blocked.Example.", FRAG, "record_sni_mid")
    assert routing.get("blocked.example") is not None


def test_expired_route_is_dropped_and_removed_from_file(tmp_path):
    path = tmp_path / "network.json"
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    path.write_text(
        json.dumps({
            "version": 1,
            "hosts": {
                "old.example": {
                    "transport": FRAG,
                    "strategy": "record_sni_mid",
                    "expires_at": past,
                }
            },
        }),
        encoding="utf-8",
    )

    routing = Routing(path)
    assert routing.get("old.example") is None
    # the expired entry must have been flushed back to disk
    assert json.loads(path.read_text(encoding="utf-8"))["hosts"] == {}


def test_touch_extends_expiry(tmp_path):
    routing = Routing(tmp_path / "network.json")
    route = routing.remember("blocked.example", FRAG, "record_sni_mid")
    before = route.expires_at

    routing.touch("blocked.example")
    after = routing.get("blocked.example").expires_at
    assert after >= before


def test_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "network.json"
    path.write_text("{ not json", encoding="utf-8")

    routing = Routing(path)  # must not raise
    routing.remember("blocked.example", FRAG, "record_sni_mid")
    assert routing.get("blocked.example") is not None


def test_forget_and_clear_all(tmp_path):
    path = tmp_path / "network.json"
    routing = Routing(path)
    routing.remember("a.example", FRAG, "record_sni_mid")
    routing.remember("b.example", FRAG, "record_sni_mid")

    routing.forget("a.example")
    assert routing.get("a.example") is None
    assert routing.get("b.example") is not None

    routing.clear_all()
    assert list(Routing(path).snapshot()) == []


def test_route_expiry_helper():
    assert Route(FRAG, expires_at="").is_expired() is False
    assert Route(FRAG, expires_at="1970-01-01T00:00:00+00:00").is_expired() is True
