#!/usr/bin/env python3
"""Run the Stage 1 smart CONNECT proxy standalone and print its proxy URL.

Not integrated into the app yet: this is the manual test harness.

    python tools/run_proxy.py
    curl --proxy http://USER:PASS@127.0.0.1:PORT https://example.com/ -I
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.network.proxy import (  # noqa: E402  (after sys.path tweak)
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HOST,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_T1,
    SmartProxy,
)
from core.network.relay import DEFAULT_IDLE_TIMEOUT  # noqa: E402


async def _run(args: argparse.Namespace) -> None:
    proxy = SmartProxy(
        host=args.host,
        t1=args.t1,
        connect_timeout=args.connect_timeout,
        idle_timeout=args.idle_timeout,
        max_connections=args.max_connections,
        allow_local_targets=args.allow_local_targets,
    )
    await proxy.start()

    print("Proxy ready.", flush=True)
    print(f"  curl --proxy {proxy.proxy_url} -I https://example.com/", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await proxy.stop()
        print("Proxy stopped.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--t1", type=float, default=DEFAULT_T1,
                        help="seconds to wait for the origin's first TLS byte")
    parser.add_argument("--connect-timeout", type=float, default=DEFAULT_CONNECT_TIMEOUT)
    parser.add_argument("--idle-timeout", type=float, default=DEFAULT_IDLE_TIMEOUT)
    parser.add_argument("--max-connections", type=int, default=DEFAULT_MAX_CONNECTIONS)
    parser.add_argument("--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT)
    parser.add_argument("--allow-local-targets", action="store_true",
                        help="allow CONNECT to loopback (testing only)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
