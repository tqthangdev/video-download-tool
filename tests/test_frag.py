"""Unit tests for core.network.frag (pure, no network)."""

from core.network import frag
from core.network.frag import (
    build_records,
    cut_position,
    first_record_length,
    fragment,
    handshake_spans_records,
    has_full_first_record,
    is_tls_client_hello,
    split_records,
)


def make_client_hello(sni: str = "example.com", pad: int = 48) -> bytes:
    body = b"\x03\x03" + b"\x00" * pad + sni.encode() + b"\x00" * pad
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x01" + len(handshake).to_bytes(2, "big") + handshake


# --------------------------------------------------------------------------
# build_records: invariants hold for every valid cut
# --------------------------------------------------------------------------
def test_build_records_invariants_for_every_cut():
    header = b"\x16\x03\x01"
    payload = bytes(range(256)) * 3  # 768 bytes
    for cut in range(1, len(payload)):
        first, second = build_records(header, payload, cut)
        assert first[:3] == header and second[:3] == header
        assert int.from_bytes(first[3:5], "big") == cut
        assert int.from_bytes(second[3:5], "big") == len(payload) - cut
        assert first[5:] + second[5:] == payload
        # two records add 5 extra header bytes over the original one
        assert len(first) + len(second) == len(payload) + 10


# --------------------------------------------------------------------------
# cut position
# --------------------------------------------------------------------------
def test_cut_position_uses_middle_of_sni():
    hello = make_client_hello("blocked.example")
    payload = hello[5:]
    offset = payload.find(b"blocked.example")
    assert offset >= 0
    assert cut_position(payload, "blocked.example") == offset + len("blocked.example") // 2


def test_cut_position_falls_back_to_middle_without_sni():
    payload = b"\x00" * 101
    assert cut_position(payload, "absent.example") == len(payload) // 2
    assert cut_position(payload, None) == len(payload) // 2


# --------------------------------------------------------------------------
# fragment / split_records
# --------------------------------------------------------------------------
def test_record_sni_mid_splits_and_preserves_payload():
    hello = make_client_hello("blocked.example")
    writes = fragment(hello, "record_sni_mid", "blocked.example")
    assert len(writes) == 1  # one write, two records inside
    blob = writes[0]
    assert len(blob) == len(hello) + 5
    assert blob[:3] == hello[:3]

    records = split_records(hello, "record_sni_mid", "blocked.example")
    assert len(records) == 2
    r1, r2 = records
    assert r1[3:5] + r2[3:5]  # both lengths present
    assert r1[5:] + r2[5:] == hello[5:]
    assert b"".join(records) == blob


def test_record_early_cuts_at_one():
    hello = make_client_hello("example.com")
    r1, r2 = split_records(hello, "record_early")
    assert int.from_bytes(r1[3:5], "big") == 1
    assert r1[5:] + r2[5:] == hello[5:]


def test_split_write_returns_two_writes():
    hello = make_client_hello("example.com")
    writes = fragment(hello, "record_sni_mid_split_write", "example.com")
    assert len(writes) == 2
    r1, r2 = split_records(hello, "record_sni_mid_split_write", "example.com")
    assert writes == [r1, r2]


def test_sni_mid_actually_cuts_inside_sni():
    hello = make_client_hello("blocked.example")
    r1, r2 = split_records(hello, "record_sni_mid", "blocked.example")
    # the SNI must not survive intact in either record (the cut is inside it)
    assert b"blocked.example" not in r1
    assert b"blocked.example" not in r2
    assert r1[5:] + r2[5:] == hello[5:]


# --------------------------------------------------------------------------
# not-splittable inputs are forwarded unchanged
# --------------------------------------------------------------------------
def test_non_tls_is_passed_through():
    data = b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"
    assert fragment(data) == [data]
    assert split_records(data) == [data]


def test_client_hello_already_spanning_records_is_unchanged():
    hello = make_client_hello("example.com")
    payload = hello[5:]
    half = len(payload) // 2
    spanning = b"\x16\x03\x01" + half.to_bytes(2, "big") + payload[:half]
    assert handshake_spans_records(spanning) is True
    assert fragment(spanning, "record_sni_mid", "example.com") == [spanning]
    assert split_records(spanning) == [spanning]


def test_tiny_and_unknown_strategy_are_unchanged():
    tiny = b"\x16\x03\x01\x00\x01\x01"
    assert fragment(tiny, "record_early") == [tiny]
    hello = make_client_hello()
    assert fragment(hello, "nope") == [hello]


def test_helpers():
    hello = make_client_hello("example.com")
    assert is_tls_client_hello(hello)
    assert not is_tls_client_hello(b"\x17\x03\x03")
    assert first_record_length(hello) == len(hello) - 5
    assert has_full_first_record(hello)
    assert not has_full_first_record(hello[:-1])


def test_strategy_list_is_exported():
    assert frag.FRAG_STRATEGIES[0] == "record_sni_mid"
    assert "record_sni_mid_split_write" in frag.FRAG_STRATEGIES
