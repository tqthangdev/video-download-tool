"""Test bootstrap: project importability + shared fixtures for the proxy tests."""

from __future__ import annotations

import asyncio
import pathlib
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Self-signed cert/key for CN=localhost (SAN: DNS:localhost, IP:127.0.0.1), so
# the local TLS origin needs neither openssl nor the network at run time.
CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIDJTCCAg2gAwIBAgIUfA5S6HPNYkECZ3WwUwm5eUzeXN8wDQYJKoZIhvcNAQEL
BQAwFDESMBAGA1UEAwwJbG9jYWxob3N0MB4XDTI2MTAwMjEwNTMzMVoXDTM2MDky
OTEwNTMzMVowFDESMBAGA1UEAwwJbG9jYWxob3N0MIIBIjANBgkqhkiG9w0BAQEF
AAOCAQ8AMIIBCgKCAQEA0k7hYagj4m3GGnVZwL5dszl5vrRdTooGQJFerjWFjinH
tgDJTuGKaIAOJAkv3ixqF3ucWiDEZlIjZtcg7rrJ0uDX5m8yRbV8Afs/YduuMKn+
Lo5b8RA/d1QxPUhm+kj5TsFWEzFlzOUQkSk6Hp6popV6Osx7Vh/3rX09IQe5/36q
SUFs7npP2D0pyBHWDwFS3ZhMlHEVZrbeseDS8KKGZcJdIxUb7/Kc/vk0JI3vjs8Z
Ep5sKOHUZRpxtn1QcyThxg8f2aDFnKWSXt5+EudO8j0RdHM2lN5BvtzI8PRPo2rT
RHG1eWnWyD8A0bgvRQ5vFX8NXaCIukrUC9LJJXXSXQIDAQABo28wbTAdBgNVHQ4E
FgQUNuqxZTY8Vr0AIGGSa8auWUrZAgUwHwYDVR0jBBgwFoAUNuqxZTY8Vr0AIGGS
a8auWUrZAgUwDwYDVR0TAQH/BAUwAwEB/zAaBgNVHREEEzARgglsb2NhbGhvc3SH
BH8AAAEwDQYJKoZIhvcNAQELBQADggEBAJy3TvumkaP3RcNicvM801F+3OkzsRUZ
FLPB2FRovYsNXsgn/RfARXYE/evN9zg2yjIu1MIYV5vHlb3Fu6DuibloWaiBibm0
ejWfb8Qc810ZGPSLn5hoMGbWy03aF10vs0dmaqTxUN0lXkQ3FareI7M1P6mvzZHq
jj/qVPCc+PhpRUlzCtNVUDF8HGpej4UUfUMgwwe6VYx8e4rh7qGs1wTLHzr2lQVV
h18a5djc6mWLhRKlikf7ZZC0RmquY1A3FFi39P+365Wh9ZNqoYjKw4nuNTVptlu8
kSKEU2oTb/llijpbaNw4dLTCDcyjzpB+suXeld4oQo73mLFTunzFAHs=
-----END CERTIFICATE-----
"""

KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDSTuFhqCPibcYa
dVnAvl2zOXm+tF1OigZAkV6uNYWOKce2AMlO4YpogA4kCS/eLGoXe5xaIMRmUiNm
1yDuusnS4NfmbzJFtXwB+z9h264wqf4ujlvxED93VDE9SGb6SPlOwVYTMWXM5RCR
KToenqmilXo6zHtWH/etfT0hB7n/fqpJQWzuek/YPSnIEdYPAVLdmEyUcRVmtt6x
4NLwooZlwl0jFRvv8pz++TQkje+OzxkSnmwo4dRlGnG2fVBzJOHGDx/ZoMWcpZJe
3n4S507yPRF0czaU3kG+3Mjw9E+jatNEcbV5adbIPwDRuC9FDm8Vfw1doIi6StQL
0sklddJdAgMBAAECggEAGE9M5yRv7XMB9Ln+43Q90YNByuT/ah4zRdBn8Nw38Wxr
7OJfYrJYdObke47iTRy2MLu1oYdrHGa/N9qDMIU/4hPicP0Ggx9M08/Ojkm981sb
ChejkhRuOaVuQaa2XJUF2HApunM50LrjtNven354nlYH+Hb9hMGSOCgjYkeJ3Pn6
BVBr42os72C3o6LxUQu5pL1ZYISDe0/598yHsFeJwYCXWFpQY2gUhBN5O/PmF2mK
sgVQMplh2buJE/2apmcYA94E0pX0xDcrVP1xZ4UC8odtt5J6tM5pEy+Vnr7jjiW1
58DUbC3kddSmgARHz8N4Q7hniyR3UqrGbGIEanZDwQKBgQD3aWlOR1fkNzLiMTrA
4CJmbd9XWV+0Phwgb5y/dhbb3NGygwIXrv7JdAjbyc4ZWt4KKIgyhn1JQ703u0yP
IcufAi6l5ATBmndnDx0JSkxDfpoE9LGCl/u44gOm7xBR/M6egccduQ5fRZNqDkuh
eDGArhclayy8e6hOUCk2MDH1/QKBgQDZm8DDBz1xcI8JE6tWz01nZNu10ohQhXgu
I39Q3kdD+KpZHjxSEmdIgy8FXGrpveF52cgFOWC5/19CrpvokXrWSlsFVfG8qlZU
q0IcOtz1mmKL2TemDi7cRx9LQfZL6h6yUfD+r12XUbNEA+RSl9lU0xUApfYSU8CU
DlbfQ4HL4QKBgECT4QqvkH9e8QcdNmq1lgUKVKtmBpbzR0AoIc/PsPO+VXW0wE0S
PiqzAMTtjcAMebxJDBO0CuuepLrxRnBtr8pXNXnTZHJsMRJTXY7ZN8K+PtFgVRzz
Mp71T2K5L5dW10+ELEbT0K6JaIrcJF2HE9S0nBIGQW0JEcsvHTKprcC5AoGACeoo
zDoGOKbyPW2h/uCPHEjiIdSn1VNfeGqxoFOgV5561HimMu8XuZwQhmQBkwjNvymH
DYXhvFfAVV9zRxNpz12v6/xQeVIhgNYUuwiLjL0uBEUvXeeDhxHOgTVOLYNLRsCp
BFGlKAHW8yBiRMkaY90CNfdZ0Nf0DEri9mUzAsECgYEAwgkXrLuvve32S5Neu90N
KOQlvtojuKThyzMUYnBKzcWYD4ON1EBANtDOt+dA9Vb1o4LdO120xJXVOBiphZfW
zXNwQgUQXFb57knSvjqkCyOSPmy70v30LCuRCMYcWaI78JaS8dgchAT6hEN26aHa
tNsPkt83D5tfZeD8KWYi2Hg=
-----END PRIVATE KEY-----
"""


@pytest.fixture(scope="session")
def tls_material(tmp_path_factory):
    """Paths to the local TLS origin's cert and key."""
    directory = tmp_path_factory.mktemp("tls")
    cert = directory / "cert.pem"
    key = directory / "key.pem"
    cert.write_text(CERT_PEM, encoding="utf-8")
    key.write_text(KEY_PEM, encoding="utf-8")
    return cert, key


class LoopRunner:
    """Runs an asyncio loop in a background thread; the test client is blocking."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def run(self, coro, timeout: float = 15.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def spawn(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


@pytest.fixture
def loop_runner():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield LoopRunner(loop)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()
