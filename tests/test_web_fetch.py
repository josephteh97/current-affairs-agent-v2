"""Exercise 1 — web_fetch network policy (SECURITY.md §3). Needs internet for the last check."""
import http.server
import ipaddress
import threading

from _check import check, finish, section
import tools
from tools import web_fetch

section("blocked URLs")
for url in [
    "file:///etc/hostname", "FILE:///etc/hostname", "ftp://example.com", "data:text/plain,hi",
    "http://127.0.0.1:11434/api/tags", "http://example.com:22/", "http://example.com:abc/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
    "http://0x7f000001/", "http://2130706433/", "http://127.1/", "http://0.0.0.0/",
    "http://localhost/", "http://10.0.0.1/", "http://192.168.1.1/",
]:
    out = web_fetch(url)
    check(url, "blocked" in out.lower(), out)

section("redirects are checked on every hop")
TARGETS = {"/to-loopback": "http://127.0.0.2:{p}/secret",
           "/to-file": "file:///etc/hostname",
           "/to-badport": "http://example.com:11434/"}


class Redirector(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        target = TARGETS.get(self.path)
        if target:
            self.send_response(302)
            self.send_header("Location", target.format(p=PORT))
        else:
            self.send_response(200)
        self.end_headers()
        if not target:
            self.wfile.write(b"<title>ok</title>hello")

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# Test-only relaxation: allow this server's port, and treat ONLY 127.0.0.1 as public.
orig_ports, orig_public = set(tools._ALLOWED_PORTS), tools._is_public
tools._ALLOWED_PORTS.add(PORT)
tools._is_public = lambda ip: ip == ipaddress.ip_address("127.0.0.1") or orig_public(ip)
try:
    base = f"http://127.0.0.1:{PORT}"
    check("sanity: first hop reachable in test mode", "hello" in web_fetch(base + "/ok"))
    for path in TARGETS:
        out = web_fetch(base + path)
        check(f"redirect {path}", "blocked" in out.lower(), out)
finally:
    tools._ALLOWED_PORTS.clear()
    tools._ALLOWED_PORTS.update(orig_ports)
    tools._is_public = orig_public
    srv.shutdown()

section("public pages still work (needs internet)")
out = web_fetch("https://example.com")
check("https://example.com", "Example Domain" in out, out)

finish()
