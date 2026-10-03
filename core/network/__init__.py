"""
core.network

Local network fallback for hosts whose TLS handshake is filtered: a small
CONNECT proxy managed by the app picks per hostname between a plain `direct`
connection and `frag` (splitting the ClientHello into two TLS records).
"""
