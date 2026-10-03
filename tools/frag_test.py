#!/usr/bin/env python3
"""
frag_test.py - Stage 0 network diagnosis (standalone, stdlib only, Python 3.8+)

Cho một hostname, thử lần lượt (trên IPv4 và/hoặc IPv6):

  normal            TLS bình thường (baseline)
  write-frag@1      ClientHello bị chia thành 2 lần send(), cắt ở byte thứ 1
  write-frag@sni    ... cắt giữa tên SNI
  record-frag@1     ClientHello bị chia thành 2 TLS record (1 lần send), cắt ở byte 1
  record-frag@sni   ... cắt giữa tên SNI
  record+write@sni  2 TLS record, gửi bằng 2 lần send() riêng
  no-sni            ClientHello không có SNI (chỉ chẩn đoán, không xác thực cert)
  alt-sni           (tùy chọn --alt-sni) SNI khác, cùng IP (chỉ chẩn đoán)

Mỗi test ghi: TCP connect, loại byte đầu tiên server trả về, TLS handshake,
phiên bản/cipher, issuer của cert, HTTP status (HEAD /), lỗi (RST/timeout/EOF/alert).

LƯU Ý khi đọc kết quả:
  * "write-frag" chỉ kiểm soát số lần send(); TCP stack của OS vẫn có thể gộp/chia lại.
    Muốn chắc chắn, bắt gói bằng Wireshark/tcpdump (xem số segment của ClientHello).
  * TLS handshake thành công != HTTP request hợp lệ. Hai tầng này được báo riêng.
  * Test no-sni/alt-sni chỉ để chẩn đoán cơ chế chặn, không phải kỹ thuật dùng thật.
  * Kết quả có thể thay đổi giữa các lần chạy: dùng --repeat 3.

Ví dụ:
  python frag_test.py example.com
  python frag_test.py example.com --family 4 --repeat 3 --json out.json
  python frag_test.py example.com --ip 1.2.3.4          # bỏ DNS khỏi phương trình
  python frag_test.py example.com --alt-sni www.example.org
"""
import argparse
import json
import socket
import ssl
import sys
import time

ALERTS = {
    10: "unexpected_message", 40: "handshake_failure", 42: "bad_certificate",
    47: "illegal_parameter", 50: "decode_error", 70: "protocol_version",
    80: "internal_error", 112: "unrecognized_name",
}


# --------------------------------------------------------------------------
# Fragmentation
# --------------------------------------------------------------------------
def fragment(data, mode, pos, sni):
    """Trả về list các chunk sẽ được send() lần lượt cho flight đầu (ClientHello)."""
    if mode == "normal" or len(data) < 6 or data[0] != 0x16:
        return [data]
    rec_len = int.from_bytes(data[3:5], "big")
    rec = data[:5 + rec_len]
    tail = data[5 + rec_len:]
    payload = rec[5:]
    hdr3 = rec[:3]  # type + record version

    if pos == "early":
        cut = 1
    else:
        off = payload.find(sni.encode()) if sni else -1
        cut = off + max(1, len(sni) // 2) if off >= 0 else len(payload) // 2
    cut = max(1, min(cut, len(payload) - 1))

    if mode == "write":
        idx = 1 if pos == "early" else 5 + cut
        pieces = [rec[:idx], rec[idx:]]
    else:  # record / record_write: chia thành 2 TLS record hợp lệ
        r1 = hdr3 + cut.to_bytes(2, "big") + payload[:cut]
        r2 = hdr3 + (len(payload) - cut).to_bytes(2, "big") + payload[cut:]
        pieces = [r1, r2] if mode == "record_write" else [r1 + r2]
    if tail:
        pieces[-1] += tail
    return pieces


def send_pieces(sock, pieces, delay):
    for i, p in enumerate(pieces):
        sock.sendall(p)
        if i < len(pieces) - 1 and delay > 0:
            time.sleep(delay)


def classify_first(chunk):
    b0 = chunk[0]
    if b0 == 0x16:
        return "tls_handshake(0x16)"
    if b0 == 0x15:
        desc = chunk[6] if len(chunk) > 6 else None
        return f"tls_alert(0x15,{ALERTS.get(desc, desc)})"
    if b0 == 0x14:
        return "tls_ccs(0x14)"
    if b0 == 0x17:
        return "tls_appdata(0x17)"
    if chunk[:5] == b"HTTP/":
        return "PLAINTEXT_HTTP(block page?)"
    return f"other(0x{b0:02x})"


# --------------------------------------------------------------------------
# One test
# --------------------------------------------------------------------------
def run_one(ip, family, port, host, test, args):
    r = {"test": test["name"], "ip": ip, "stage": "start", "ok": False}
    sni = test["sni"]
    verify = test.get("verify", True) and not args.insecure

    ctx = ssl.create_default_context()
    if args.tls12:
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(args.timeout)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)

    def flush(out):
        d = out.read()
        if d:
            s.sendall(d)

    try:
        s.connect((ip, port))
        r["tcp_ms"] = ms()
        r["stage"] = "tls"

        inc, out = ssl.MemoryBIO(), ssl.MemoryBIO()
        obj = ctx.wrap_bio(inc, out, server_hostname=sni)
        sent_first = got_first = False
        t_hello = None

        while True:
            try:
                obj.do_handshake()
                flush(out)
                break
            except ssl.SSLWantReadError:
                data = out.read()
                if data:
                    if not sent_first:
                        pieces = fragment(data, test["mode"], test.get("pos"), sni)
                        r["hello_bytes"] = len(data)
                        r["writes"] = [len(p) for p in pieces]
                        send_pieces(s, pieces, args.delay)
                        sent_first = True
                        t_hello = ms()
                        r["stage"] = "hello_sent"
                    else:
                        s.sendall(data)
                chunk = s.recv(65536)
                if not got_first:
                    got_first = True
                    r["first_ms"] = ms() - (t_hello or 0)
                    if chunk:
                        r["first"] = classify_first(chunk)
                        r["first_hex"] = chunk[:12].hex()
                if not chunk:
                    raise EOFError("peer closed")
                r["stage"] = "handshake"
                inc.write(chunk)

        r["handshake_ok"] = True
        r["handshake_ms"] = ms()
        r["tls"] = obj.version()
        r["cipher"] = (obj.cipher() or ("?",))[0]
        try:
            cert = obj.getpeercert()
            if cert:
                iss = {k: v for tup in cert.get("issuer", ()) for k, v in tup}
                r["issuer"] = iss.get("organizationName") or iss.get("commonName")
        except Exception:
            pass

        if test.get("http"):
            r["stage"] = "http"
            req = (f"HEAD / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: frag_test/1.0\r\n"
                   f"Accept: */*\r\nConnection: close\r\n\r\n")
            obj.write(req.encode())
            flush(out)
            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 16384:
                try:
                    d = obj.read(4096)
                except ssl.SSLWantReadError:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    inc.write(chunk)
                    continue
                except ssl.SSLZeroReturnError:
                    break
                if not d:
                    break
                buf += d
            head = buf.decode("latin-1", "replace").split("\r\n")
            r["http"] = head[0] if head and head[0] else None
            for line in head[1:]:
                if line.lower().startswith("server:"):
                    r["server"] = line.split(":", 1)[1].strip()
            if not r["http"]:
                r["error"] = "no HTTP response after handshake"
            else:
                r["ok"] = True
        else:
            r["ok"] = True
        r["stage"] = "done"
    except ssl.SSLCertVerificationError as e:
        r["error"] = f"cert_verify_failed: {e.verify_message}"
    except ssl.SSLError as e:
        r["error"] = f"tls_error: {e.reason or e}"
    except socket.timeout:
        r["error"] = "timeout"
    except ConnectionResetError:
        r["error"] = "RST (connection reset)"
    except EOFError as e:
        r["error"] = f"eof: {e}"
    except OSError as e:
        r["error"] = f"os_error: {e}"
    finally:
        r["elapsed_ms"] = ms()
        try:
            s.close()
        except OSError:
            pass
    return r


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def build_tests(host, alt_sni):
    t = [
        dict(name="normal", mode="normal", sni=host, http=True),
        dict(name="write-frag@1", mode="write", pos="early", sni=host, http=True),
        dict(name="write-frag@sni", mode="write", pos="sni", sni=host, http=True),
        dict(name="record-frag@1", mode="record", pos="early", sni=host, http=True),
        dict(name="record-frag@sni", mode="record", pos="sni", sni=host, http=True),
        dict(name="record+write@sni", mode="record_write", pos="sni", sni=host, http=True),
        dict(name="no-sni", mode="normal", sni=None, http=False, verify=False),
    ]
    if alt_sni:
        t.append(dict(name="alt-sni", mode="normal", sni=alt_sni, http=False, verify=False))
    return t


def resolve(host, port, ip, family):
    targets = []
    if ip:
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(fam, ip)], [ip]
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    all_ips = sorted({i[4][0] for i in infos})
    v4 = next((i[4][0] for i in infos if i[0] == socket.AF_INET), None)
    v6 = next((i[4][0] for i in infos if i[0] == socket.AF_INET6), None)
    if family in ("4", "both") and v4:
        targets.append((socket.AF_INET, v4))
    if family in ("6", "both") and v6:
        targets.append((socket.AF_INET6, v6))
    return targets, all_ips


def summarize(r):
    parts = [f"tcp={r.get('tcp_ms', '-')}ms"]
    if "writes" in r:
        parts.append(f"writes={r['writes']}")
    if "first" in r:
        parts.append(f"first={r['first']}@{r.get('first_ms')}ms")
    if r.get("handshake_ok"):
        parts.append(f"{r.get('tls')}/{r.get('cipher')}")
        if r.get("issuer"):
            parts.append(f"issuer={r['issuer']}")
    if r.get("http"):
        parts.append(f"http='{r['http']}'")
    if r.get("server"):
        parts.append(f"server={r['server']}")
    if r.get("error"):
        parts.append(f"ERROR[{r['stage']}]={r['error']}")
    return "  ".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--ip", help="bỏ qua DNS, dùng IP này")
    ap.add_argument("--family", choices=["4", "6", "both"], default="both")
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--delay", type=float, default=0.05, help="giây nghỉ giữa các lần send() của ClientHello")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--alt-sni", help="thêm test SNI khác trên cùng IP (chỉ chẩn đoán)")
    ap.add_argument("--tls12", action="store_true", help="giới hạn TLS 1.2")
    ap.add_argument("--insecure", action="store_true", help="không xác thực cert")
    ap.add_argument("--only", help="chỉ chạy các test có tên chứa chuỗi này")
    ap.add_argument("--json", help="ghi kết quả ra file JSON")
    args = ap.parse_args()

    print(f"== frag_test: {args.host}:{args.port}  python={sys.version.split()[0]}  {ssl.OPENSSL_VERSION}")
    t0 = time.monotonic()
    try:
        targets, all_ips = resolve(args.host, args.port, args.ip, args.family)
    except socket.gaierror as e:
        print(f"DNS FAIL: {e}")
        return 2
    print(f"DNS: {all_ips}  ({int((time.monotonic()-t0)*1000)}ms)")
    if not targets:
        print("Không có IP phù hợp với --family.")
        return 2

    tests = build_tests(args.host, args.alt_sni)
    if args.only:
        tests = [t for t in tests if args.only in t["name"]]

    results = []
    for fam, ip in targets:
        print(f"\n-- {'IPv6' if fam == socket.AF_INET6 else 'IPv4'} {ip}")
        for t in tests:
            for n in range(args.repeat):
                r = run_one(ip, fam, args.port, args.host, t, args)
                r["run"] = n + 1
                results.append(r)
                tag = "PASS" if r["ok"] else "FAIL"
                suffix = f" #{n+1}" if args.repeat > 1 else ""
                print(f"[{tag}] {t['name']}{suffix:<4}  {summarize(r)}")

    print("\n== Tóm tắt (test x IP) ==")
    names = []
    for r in results:
        k = (r["test"], r["ip"])
        if k not in names:
            names.append(k)
    for k in names:
        rs = [r for r in results if (r["test"], r["ip"]) == k]
        p = sum(1 for r in rs if r["ok"])
        print(f"  {k[0]:<18} {k[1]:<40} {p}/{len(rs)} pass")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nĐã ghi {args.json}")
    print("\nDán toàn bộ output này lại để đọc kết quả.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
