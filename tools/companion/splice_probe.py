#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Splice MCP probe (Kit Manager Milestone 4, docs/KIT_MANAGER_PLAN.md 5.4).

Signs in to the official Splice MCP server (https://mcp.splice.com/mcp) the
way the Mac companion would: OAuth 2.1 with dynamic client registration and
PKCE, the browser opened for the login, the code taken on a local port. Then
it asks the server what it offers (tools, resources, prompts) and prints it.

It calls no tool unless --search is given, and never download_asset: nothing
is downloaded and no credits are used.
The token is kept in memory only and never written anywhere (the plan: tokens
stay on the Mac companion, never in firmware or the browser).

    python3 tools/companion/splice_probe.py [--out .local/splice-mcp.json] [--search "punchy kick"]

--search also runs describe_a_sound (read only: a catalog search, no credits)
for one query and saves what a result holds, to see whether results carry an
audio preview to audition before anything is downloaded.
"""
import argparse
import base64
import hashlib
import http.server
import json
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

SERVER = "https://mcp.splice.com"
RESOURCE = SERVER + "/mcp"
AGENT = "melodee-kit-manager-probe/0.1"


def fetch(url, data=None, headers=None, form=False):
    """(status, headers, body bytes) for a GET, or a POST of JSON or a form."""
    body = None
    head = {"User-Agent": AGENT, **(headers or {})}
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            head["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            head["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=head, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def sign_in():
    """An access token for the MCP server, from a login in the browser."""
    _, _, meta = fetch(SERVER + "/.well-known/oauth-authorization-server")
    meta = json.loads(meta)
    # The local port that takes the login's answer.
    got = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p>Signed in. You can close this tab and go back to the terminal.</p>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Callback)
    redirect = "http://127.0.0.1:%d/callback" % server.server_port
    status, _, reg = fetch(meta["registration_endpoint"], {
        "client_name": "Melodee Kit Manager (probe)",
        "redirect_uris": [redirect],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })
    if status >= 300:
        raise SystemExit("Client registration refused (%d): %s" % (status, reg.decode(errors="replace")[:400]))
    client = json.loads(reg)["client_id"]
    print("Registered client:", client)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = meta["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client, "redirect_uri": redirect, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "scope": "openid profile email offline_access", "resource": RESOURCE,
    })
    print("Opening the browser to sign in to Splice. If it does not open, go to:\n" + url)
    webbrowser.open(url)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    thread.join(timeout=300)
    server.server_close()
    if got.get("state") != state or "code" not in got:
        raise SystemExit("No login came back: %s" % {k: v for k, v in got.items() if k != "code"})
    status, _, token = fetch(meta["token_endpoint"], {
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": redirect,
        "client_id": client, "code_verifier": verifier, "resource": RESOURCE,
    }, form=True)
    if status >= 300:
        raise SystemExit("Token refused (%d): %s" % (status, token.decode(errors="replace")[:400]))
    token = json.loads(token)
    print("Signed in. Token type %s, expires in %s s, refresh token: %s" % (
        token.get("token_type"), token.get("expires_in"), "yes" if token.get("refresh_token") else "no"))
    return token["access_token"]


class Mcp:
    """The streamable HTTP transport: JSON-RPC posts, answers as JSON or server-sent events."""

    def __init__(self, token):
        self.token, self.session, self.next = token, None, 1

    def call(self, method, params=None, notify=False):
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            message["id"] = self.next
            self.next += 1
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2025-06-18"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        status, head, body = fetch(RESOURCE, message, headers)
        self.session = head.get("Mcp-Session-Id") or head.get("mcp-session-id") or self.session
        if notify:
            return None
        text = body.decode(errors="replace")
        if "text/event-stream" in (head.get("Content-Type") or head.get("content-type") or ""):
            datas = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            text = datas[-1] if datas else ""
        if status >= 300:
            return {"error": {"status": status, "body": text[:600]}}
        return json.loads(text) if text else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=".local/splice-mcp.json", help="where to save what the server offers (no token)")
    parser.add_argument("--search", help="also run describe_a_sound (read only, no credits) for this query")
    args = parser.parse_args()
    mcp = Mcp(sign_in())
    init = mcp.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "melodee-kit-manager-probe", "version": "0.1"}})
    mcp.call("notifications/initialized", notify=True)
    found = {"initialize": init.get("result", init)}
    for method, key in (("tools/list", "tools"), ("resources/list", "resources"),
                        ("resources/templates/list", "resourceTemplates"), ("prompts/list", "prompts")):
        reply = mcp.call(method)
        found[key] = reply.get("result", {}).get(key, reply.get("error"))
    info = found["initialize"].get("serverInfo", {}) if isinstance(found["initialize"], dict) else {}
    print("\nServer: %s %s" % (info.get("name"), info.get("version")))
    tools = found["tools"] if isinstance(found["tools"], list) else []
    print("Tools (%d):" % len(tools))
    for t in tools:
        params = ", ".join(sorted((t.get("inputSchema") or {}).get("properties", {})))
        print("  - %s(%s)\n      %s" % (t.get("name"), params, " ".join((t.get("description") or "").split())[:300]))
    for key in ("resources", "resourceTemplates", "prompts"):
        value = found[key]
        print("%s: %s" % (key, len(value) if isinstance(value, list) else value))
    if args.search:
        reply = mcp.call("tools/call", {"name": "describe_a_sound", "arguments": {"query": args.search, "type": "oneshot"}})
        found["search"] = {"query": args.search, "reply": reply.get("result", reply)}
        result = reply.get("result", {})
        print("\nSearch %r:" % args.search)
        for part in result.get("content", [])[:3]:
            print(" ", (part.get("text") or json.dumps(part))[:1500])
        if result.get("structuredContent"):
            print("  structured:", json.dumps(result["structuredContent"])[:1500])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(found, indent=2))
    print("\nSaved to %s (no token in it)." % out)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
