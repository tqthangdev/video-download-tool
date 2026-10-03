"""Bidirectional byte relay between two asyncio stream pairs.

Streams with backpressure (never buffers a whole transfer in RAM), propagates
half-close (one side EOF -> the other side gets EOF and keeps draining), and
closes both writers when either direction fails or goes idle.
"""

from __future__ import annotations

import asyncio

DEFAULT_BUFFER_SIZE = 64 * 1024
# A tunnelled connection with no traffic for this long is considered dead.
DEFAULT_IDLE_TIMEOUT = 120.0


def _write_eof(writer) -> None:
    """Half-close the write side when the transport supports it."""
    try:
        if writer.can_write_eof():
            writer.write_eof()
    except (OSError, RuntimeError):
        pass


async def _close(writer) -> None:
    try:
        writer.close()
    except Exception:  # noqa: BLE001 - best effort
        pass
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 - best effort
        pass


async def _pump(reader, writer, buffer_size: int, idle_timeout: float) -> None:
    while True:
        data = await asyncio.wait_for(reader.read(buffer_size), timeout=idle_timeout)
        if not data:
            _write_eof(writer)
            return
        writer.write(data)
        await writer.drain()


async def relay(
    reader_a,
    writer_a,
    reader_b,
    writer_b,
    *,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
) -> None:
    """Relay bytes both ways until both sides close.

    `(reader_a, writer_a)` and `(reader_b, writer_b)` are opposite ends: data
    read from `reader_a` is written to `writer_b` and vice versa. Raises
    `asyncio.TimeoutError` if a direction stays idle for `idle_timeout`.
    """
    tasks = [
        asyncio.create_task(_pump(reader_a, writer_b, buffer_size, idle_timeout)),
        asyncio.create_task(_pump(reader_b, writer_a, buffer_size, idle_timeout)),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _close(writer_a)
        await _close(writer_b)
