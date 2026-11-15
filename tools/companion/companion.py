#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""The Mac companion (Kit Manager Milestone 3, docs/KIT_MANAGER_PLAN.md 5.1).

Serves the web page's own files from this repository and passes every other
request to the MPC, so the Kits page runs here with the page's latest code
and the MPC's data: a change to src/melodee/web/static is a reload away, no
firmware to build or install. The page the MPC carries itself is unchanged.

    python3 tools/companion/companion.py            # then open http://localhost:8800/kits
    python3 tools/companion/companion.py --mpc 192.168.155.1 --port 8800 --splice ~/Splice/sounds/packs

It also offers the Splice sounds on this Mac (tools/companion/splice_library.py)
as a source in Sounds, copied to the card when they go on a pad.

Only this computer can reach it (127.0.0.1), by localhost or 127.0.0.1.
"""
import argparse
import html
import http.server
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from splice_library import TYPES as AUDIO_TYPES, SpliceLibrary, default_root  # noqa: E402
from splice_mcp import SpliceMcp  # noqa: E402
from splice_kits import DOWNLOADS, SpliceKits  # noqa: E402
from splice_library import copy_to_card  # noqa: E402

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
    splice = None
    mcp = None      # the official Splice MCP (splice_mcp.py): sign-in kept in the Keychain
    kits = None     # Describe a kit through it, and get for a credit (splice_kits.py)

    def reply(self, status, ctype, body, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass # the browser stopped waiting (a page moved on): nothing to tell it

    def local(self):
        """The page's own files, from the repository."""
        path = self.path.split("?")[0]
        if path in PAGES and (STATIC / PAGES[path][2]).is_file():
            return self.reply(200, TYPES[".html"], page(*PAGES[path]))
        name = path.lstrip("/")
        if re.fullmatch(r"[A-Za-z0-9_.-]+", name or "-") and (STATIC / name).is_file():
            return self.reply(200, TYPES.get(Path(name).suffix, "application/octet-stream"), (STATIC / name).read_bytes())
        return None

    def mpc_call(self, method, path, query, body=None):
        """(status, bytes) of a request to the MPC, as its own page would make it."""
        url = "http://%s%s?%s" % (self.address, path, urllib.parse.urlencode(query))
        headers = {"Host": self.mpc, "X-Melodee": "1"}
        request = urllib.request.Request(url, data=body if body is not None else (b"" if method == "POST" else None),
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def json_reply(self, status, value):
        self.reply(status, "application/json; charset=utf-8", json.dumps(value).encode())

    def companion(self):
        """/companion/...: what only the Mac has. Refused unless asked by this computer's own name (no DNS rebinding);
        writes need X-Melodee, which another site's page cannot send without asking first."""
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host not in ("localhost", "127.0.0.1"):
            return self.json_reply(421, {"error": "Open the companion at localhost"})
        url = urllib.parse.urlparse(self.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        lib = self.splice
        if url.path == "/companion/hello" and self.command in ("GET", "HEAD"):
            signed = self.mcp.signed_in() if self.mcp else False
            return self.json_reply(200, {"companion": True, "signedIn": signed, **(lib.hello() if lib else {"splice": False}),
                                         **({"credits": self.kits.left, "creditsAt": None, "creditsFrom": "download"} if self.kits and self.kits.left is not None else {})})
        # Signing in to Splice: the browser goes to Splice and comes back here.
        if url.path == "/companion/splice/login" and self.command == "GET":
            try:
                where = self.mcp.login_url()
            except OSError as e:
                return self.json_reply(502, {"error": str(e)})
            self.send_response(302)
            self.send_header("Location", where)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if url.path == "/companion/splice/callback" and self.command == "GET":
            try:
                self.mcp.finish(query)
                words, ok = "Signed in to Splice. You can close this tab.", True
            except (PermissionError, OSError) as e:
                words, ok = "Splice sign-in failed: %s" % e, False
            body = ("<!doctype html><meta charset=utf-8><title>Splice</title><body style='font:16px system-ui;padding:40px;"
                    "background:#17141F;color:#eee'><p>%s</p><script>%s</script>" % (html.escape(words),
                    "window.opener&&window.opener.postMessage('splice-signed-in','*');setTimeout(()=>window.close(),800)" if ok else "")).encode()
            return self.reply(200 if ok else 400, "text/html; charset=utf-8", body)
        # Describe a kit: a search per pad, to a draft (no credits); then get, a sound at a time (asked first).
        if url.path == "/companion/splice/describe" and self.command == "GET" and query.get("stream"):
            # One JSON object a line, as each search is done (the page shows the work), the draft last.
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for step in self.kits.steps(query.get("text", ""), self.mark):
                    self.wfile.write((json.dumps(step) + "\n").encode())
                    self.wfile.flush()
            except PermissionError as e:
                self.wfile.write((json.dumps({"error": str(e), "signedOut": True}) + "\n").encode())
            except (OSError, ValueError) as e:
                try:
                    self.wfile.write((json.dumps({"error": str(e)}) + "\n").encode())
                except OSError:
                    pass # the page went away
            self.close_connection = True
            return None
        if url.path == "/companion/splice/describe" and self.command == "GET":
            try:
                return self.json_reply(200, self.kits.draft(query.get("text", ""), self.mark))
            except PermissionError as e:
                return self.json_reply(401, {"error": str(e), "signedOut": True})
            except (OSError, ValueError) as e:
                return self.json_reply(502, {"error": str(e)})
        if url.path == "/companion/splice/get" and self.command == "POST":
            if "X-Melodee" not in self.headers:
                return self.json_reply(403, {"error": "Not from Melodee's page"})
            try:
                path, fresh = self.kits.get(query.get("uuid", ""), query.get("name", ""), query.get("label", ""))
                card = copy_to_card(path, query.get("label", "") or "Splice", self.mpc_call)
                lib.forget() # the Splice source lists it now, under Got with Melodee
            except LookupError as e:
                return self.json_reply(404, {"error": str(e)})
            except PermissionError as e:
                return self.json_reply(403, {"error": str(e)})
            except (OSError, ValueError) as e:
                return self.json_reply(502, {"error": str(e) or "Could not get it"})
            return self.json_reply(200, {"id": card, "fresh": fresh, "gets": self.kits.spent, "limit": self.kits.limit, "left": self.kits.left})
        if url.path == "/companion/splice/logout" and self.command == "POST":
            if "X-Melodee" not in self.headers:
                return self.json_reply(403, {"error": "Not from Melodee's page"})
            self.mcp.sign_out()
            return self.json_reply(200, {})
        if not lib or not lib.available():
            return self.json_reply(404, {"error": "No Splice folder on this Mac"})
        if url.path == "/companion/splice/icon" and self.command in ("GET", "HEAD"):
            png = lib.icon()
            return self.reply(200, "image/png", png) if png else self.json_reply(404, {"error": "No Splice app here"})
        # A cover one put in a pack's folder; the page makes one else.
        if url.path == "/companion/splice/cover" and self.command in ("GET", "HEAD"):
            data, kind = lib.cover(query.get("pack", ""))
            return self.reply(200, kind, data) if data else self.json_reply(404, {"error": "No cover"})
        if url.path == "/companion/splice/sounds" and self.command in ("GET", "HEAD"):
            return self.json_reply(200, lib.sounds())
        if url.path == "/companion/splice/sample" and self.command in ("GET", "HEAD"):
            path = lib.place(query.get("path", ""))
            if path is None:
                return self.json_reply(404, {"error": "No such sound in the Splice folder"})
            return self.reply(200, AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream"), path.read_bytes())
        if url.path == "/companion/splice/import" and self.command == "POST":
            if "X-Melodee" not in self.headers:
                return self.json_reply(403, {"error": "Not from Melodee's page"})
            try:
                return self.json_reply(200, {"id": lib.import_to_card(query.get("path", ""), self.mpc_call)})
            except LookupError as e:
                return self.json_reply(404, {"error": str(e)})
            except (OSError, ValueError) as e:
                return self.json_reply(502, {"error": str(e) or "Could not copy it to the card"})
        return self.json_reply(404, {"error": "Not found"})

    def mark(self, sounds):
        """Sounds one has already: in the Splice folder (played from there), or got here before (free again)."""
        mine = {}
        if self.splice and self.splice.available():
            for rel in self.splice.sounds()["files"]:
                mine.setdefault(rel.rsplit("/", 1)[-1].lower(), rel)
        for s in sounds:
            s["mine"] = mine.get(s["name"].lower(), "")
            s["kept"] = bool(self.kits.local(s["name"], s["label"]))

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
        if self.path.startswith("/companion/"):
            return self.companion()
        if self.local() is None:
            self.forward()

    do_HEAD = do_GET

    def do_POST(self):
        if self.path.startswith("/companion/"):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            return self.companion()
        self.forward()

    def log_message(self, fmt, *args):
        if args and str(args[1])[:1] in "45":
            sys.stderr.write("%s %s\n" % (self.requestline, args[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mpc", default="melodee.local", help="the MPC's address (melodee.local)")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--splice", default=str(default_root()), help="the Splice sounds folder (%(default)s)")
    parser.add_argument("--credit-limit", type=int, default=20, help="Splice sounds a session may get (%(default)s): each new one is a credit")
    args = parser.parse_args()
    Companion.mpc = args.mpc
    Companion.splice = SpliceLibrary(args.splice, DOWNLOADS)
    Companion.mcp = SpliceMcp("http://localhost:%d/companion/splice/callback" % args.port)
    Companion.kits = SpliceKits(Companion.mcp, args.credit_limit)
    try:
        Companion.address = socket.gethostbyname(args.mpc)
    except OSError:
        Companion.address = args.mpc # not found now: asked again with each request
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Companion)
    print("Melodee companion: http://localhost:%d/kits  (page from %s, data from the MPC at %s, %s)" % (args.port, STATIC, args.mpc, Companion.address))
    hello = Companion.splice.hello()
    print("Splice: %s" % ("%d packs in %s" % (hello["packs"], hello["root"]) if hello["splice"] else "no folder at %s (--splice)" % hello["root"]))
    print("Splice MCP: %s" % ("signed in (Keychain)" if Companion.mcp.signed_in() else "not signed in: Sign in on the Kits page's Splice source"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
