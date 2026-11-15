#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""The Mac companion (Kit Manager Milestone 3, docs/KIT_MANAGER_PLAN.md 5.1).

Serves the web page's own files from this repository and passes every other
request to the MPC, so the Kits page runs here with the page's latest code
and the MPC's data: a change to src/melodee/web/static is a reload away, no
firmware to build or install. The page the MPC carries itself is unchanged.

    python3 tools/companion/companion.py            # then open http://localhost:8800/kits
    python3 tools/companion/companion.py --mpc 192.168.155.1 --port 8800

Only this computer can reach it (127.0.0.1).
"""
import argparse
import html
import http.server
import re
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src/melodee/web/static"
# The pages built from the shell as tools/web_bundle.py builds them; the rest of the site comes from the MPC.
PAGES = {"/kits": ("Kits · Melodee", "kits", "kits.html"), "/files": ("Files · Melodee", "files", "files.html"),
         "/": ("Melodee", "device", "device.html")}
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".png": "image/png",
         ".svg": "image/svg+xml", ".html": "text/html; charset=utf-8", ".woff2": "font/woff2"}
# What is passed on to the MPC and back: not the hop-by-hop ones.
SKIP = {"connection", "keep-alive", "transfer-encoding", "host", "content-length", "accept-encoding"}


def page(title, active, main):
    shell = (STATIC / "shell.html").read_text()
    for name in ("device", "files", "kits", "quickstart", "manual"):
        shell = shell.replace("{{%s}}" % name, ' aria-current="page"' if name == active else "")
    return shell.replace("{{title}}", html.escape(title)).replace("{{main}}", (STATIC / main).read_text()).encode()


class Companion(http.server.BaseHTTPRequestHandler):
    mpc = "melodee.local"
    address = "melodee.local" # looked up once: a .local name can take seconds to look up each time

    def reply(self, status, ctype, body, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def local(self):
        """The page's own files, from the repository."""
        path = self.path.split("?")[0]
        if path in PAGES and (STATIC / PAGES[path][2]).is_file():
            return self.reply(200, TYPES[".html"], page(*PAGES[path]))
        name = path.lstrip("/")
        if re.fullmatch(r"[A-Za-z0-9_.-]+", name or "-") and (STATIC / name).is_file():
            return self.reply(200, TYPES.get(Path(name).suffix, "application/octet-stream"), (STATIC / name).read_bytes())
        return None

    def forward(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in SKIP}
        headers["Host"] = self.mpc # the MPC answers only to its own name or an address
        request = urllib.request.Request("http://%s%s" % (self.address, self.path), data=body, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(request, timeout=120) as r:
                status, rh, data = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            status, rh, data = e.code, e.headers, e.read()
        except (urllib.error.URLError, OSError) as e:
            return self.reply(502, "application/json", ('{"error":"The MPC does not answer at %s: %s"}' % (self.mpc, e)).encode())
        extra = [(k, v) for k, v in rh.items() if k.lower() not in SKIP | {"content-type", "cache-control"}]
        self.reply(status, rh.get("Content-Type", "application/octet-stream"), data, extra)

    def do_GET(self):
        if self.local() is None:
            self.forward()

    do_HEAD = do_GET

    def do_POST(self):
        self.forward()

    def log_message(self, fmt, *args):
        if args and str(args[1])[:1] in "45":
            sys.stderr.write("%s %s\n" % (self.requestline, args[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mpc", default="melodee.local", help="the MPC's address (melodee.local)")
    parser.add_argument("--port", type=int, default=8800)
    args = parser.parse_args()
    Companion.mpc = args.mpc
    try:
        Companion.address = socket.gethostbyname(args.mpc)
    except OSError:
        Companion.address = args.mpc # not found now: asked again with each request
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Companion)
    print("Melodee companion: http://localhost:%d/kits  (page from %s, data from the MPC at %s, %s)" % (args.port, STATIC, args.mpc, Companion.address))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
