"""Pure TLS ClientHello fragmentation.

No I/O here: given the bytes the client already sent (at least the first TLS
record), decide how to split the ClientHello into two TLS records and in what
writes to send them.

Only splitting the *record structure* works — Stage 0 showed that splitting
just the `send()` calls does not. The ClientHello content is never modified
(no SNI change, no added/removed extension), so the client's TLS fingerprint is
preserved.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

# Splitting into two TLS records (`record_*`) is the technique proven in
# Stage 0. `record_sni_mid` is the default; the others are fallbacks kept for
# when a filter changes behaviour.
FRAG_STRATEGIES: Tuple[str, ...] = (
    "record_sni_mid",
    "record_early",
    "record_sni_mid_split_write",
)

RECORD_HEADER_LEN = 5
TLS_HANDSHAKE = 0x16
HANDSHAKE_CLIENT_HELLO = 0x01


def is_tls_client_hello(data: bytes) -> bool:
    """True for the start of a TLS handshake record (0x16, protocol 0x03xx)."""
    return len(data) >= 3 and data[0] == TLS_HANDSHAKE and data[1] == 0x03


def first_record_length(data: bytes) -> Optional[int]:
    """Payload length declared by the first record's header, or None if short."""
    if len(data) < RECORD_HEADER_LEN:
        return None
    return int.from_bytes(data[3:5], "big")


def has_full_first_record(data: bytes) -> bool:
    """True when `data` holds at least the whole first TLS record."""
    length = first_record_length(data)
    return length is not None and len(data) >= RECORD_HEADER_LEN + length


def handshake_spans_records(data: bytes) -> bool:
    """True when the ClientHello handshake message crosses the first record.

    The client already fragmented it, so forwarding it as-is is both correct
    and enough (it was not stopped); splitting again is meaningless.
    """
    length = first_record_length(data)
    if length is None or len(data) < RECORD_HEADER_LEN + 4:
        return False

    payload = data[RECORD_HEADER_LEN:RECORD_HEADER_LEN + length]
    if not payload or payload[0] != HANDSHAKE_CLIENT_HELLO:
        return False

    handshake_len = int.from_bytes(payload[1:4], "big")
    return 4 + handshake_len > length


def cut_position(payload: bytes, sni: Optional[str]) -> int:
    """Where to cut the payload: middle of the SNI, else the middle of it."""
    if sni:
        offset = payload.find(sni.encode("ascii", "ignore"))
        if offset >= 0:
            return offset + max(1, len(sni) // 2)
    return len(payload) // 2


def build_records(header: bytes, payload: bytes, cut: int) -> Tuple[bytes, bytes]:
    """Split `payload` into two records that reuse the 3-byte `header`."""
    first = header + cut.to_bytes(2, "big") + payload[:cut]
    second = header + (len(payload) - cut).to_bytes(2, "big") + payload[cut:]
    return first, second


def _split_first_record(
    data: bytes, strategy: str, sni: Optional[str]
) -> Optional[Tuple[bytes, bytes, bytes]]:
    """(record1, record2, tail) for a splittable ClientHello, else None."""
    if not is_tls_client_hello(data):
        return None

    length = first_record_length(data)
    if length is None:
        return None

    record = data[:RECORD_HEADER_LEN + length]
    tail = data[RECORD_HEADER_LEN + length:]
    payload = record[RECORD_HEADER_LEN:]
    if len(payload) < 2:
        return None

    if strategy == "record_early":
        cut = 1
    else:
        cut = cut_position(payload, sni)
    cut = max(1, min(cut, len(payload) - 1))

    first, second = build_records(record[:3], payload, cut)
    return first, second, tail


def split_records(
    data: bytes, strategy: str = "record_sni_mid", sni: Optional[str] = None
) -> Sequence[bytes]:
    """The two TLS records the ClientHello becomes (`[data]` when not split)."""
    if strategy not in FRAG_STRATEGIES or handshake_spans_records(data):
        return [data]

    parts = _split_first_record(data, strategy, sni)
    if parts is None:
        return [data]

    first, second, _tail = parts
    return [first, second]


def fragment(
    data: bytes, strategy: str = "record_sni_mid", sni: Optional[str] = None
) -> Sequence[bytes]:
    """Writes to send the first flight, in order.

    One write for the `record_*` strategies, two writes for `*_split_write`.
    Returns `[data]` unchanged when the input is not a splittable ClientHello.
    """
    if strategy not in FRAG_STRATEGIES or handshake_spans_records(data):
        return [data]

    parts = _split_first_record(data, strategy, sni)
    if parts is None:
        return [data]

    first, second, tail = parts
    if strategy.endswith("_split_write"):
        return [first, second + tail]
    return [first + second + tail]
