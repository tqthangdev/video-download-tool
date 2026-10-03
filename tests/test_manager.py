"""Tests for the NetworkManager lifecycle and the yt-dlp proxy option."""

from __future__ import annotations

from core.network.manager import NetworkManager
from core.ytdlp import YtdlpClient


def test_disabled_manager_does_not_start(tmp_path):
    manager = NetworkManager(enabled=False, routing_path=tmp_path / "network.json")
    assert manager.start() is False
    assert manager.running is False
    assert manager.proxy_url is None
    manager.stop()


def test_manager_starts_and_stops(tmp_path):
    manager = NetworkManager(enabled=True, routing_path=tmp_path / "network.json")
    try:
        assert manager.start(timeout=8) is True
        assert manager.running
        assert manager.proxy_url.startswith("http://")
        assert "@" in manager.proxy_url  # per-run credentials are embedded
    finally:
        manager.stop()
    assert not manager.running
    assert manager.proxy_url is None


def test_manager_toggle_and_learned_hosts(tmp_path):
    manager = NetworkManager(enabled=False, routing_path=tmp_path / "network.json")
    try:
        assert manager.set_enabled(True) is True
        assert manager.running

        manager.routing.remember("blocked.example", "frag", "record_sni_mid")
        assert "blocked.example" in manager.learned_hosts()

        manager.clear_learned()
        assert manager.learned_hosts() == {}
    finally:
        manager.set_enabled(False)
    assert not manager.running


def test_ytdlp_client_includes_proxy_option():
    client = YtdlpClient({}, proxy_url="http://user:pass@127.0.0.1:1234")
    assert client._base_opts()["proxy"] == "http://user:pass@127.0.0.1:1234"
    assert client._requests_proxies()["https"] == "http://user:pass@127.0.0.1:1234"

    client.set_proxy(None)
    assert "proxy" not in client._base_opts()
    assert client._requests_proxies() is None
