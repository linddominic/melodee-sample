# SPDX-License-Identifier: AGPL-3.0-only
"""The official Splice MCP server (https://mcp.splice.com/mcp) for the companion.

Signs in as Splice documents for MCP clients (docs/KIT_MANAGER_SPLICE.md):
OAuth 2.1 with dynamic client registration and PKCE, the login in the
browser, the code back on the companion's own /companion/splice/callback.
The refresh token and the client's id are kept in the Mac's login Keychain
(service "Melodee companion: Splice MCP"), never on the card, in the
repository or in the browser; the access token lives in memory only.
"""
import base64
import hashlib
import json
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SERVER = "https://mcp.splice.com"
RESOURCE = SERVER + "/mcp"
AGENT = "melodee-kit-manager/0.1"
KEYCHAIN_SERVICE = "Melodee companion: Splice MCP"
KEYCHAIN_ACCOUNT = "splice"


def http(url, data=None, headers=None, form=False, timeout=30):
    """(status, headers, bytes) of a GET, or of a POST of JSON or a form."""
    head = {"User-Agent": AGENT, **(headers or {})}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
        head["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    request = urllib.request.Request(url, data=body, headers=head, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class Keychain:
    """One secret in the login Keychain, through macOS's own `security` tool."""

    @staticmethod
    def read():
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
                           capture_output=True, text=True)
        if r.returncode:
            return {}
        try:
            return json.loads(r.stdout.strip())
        except ValueError:
            return {}

    @staticmethod
    def write(value):
        subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT,
                        "-l", KEYCHAIN_SERVICE, "-w", json.dumps(value)], capture_output=True, check=True)

    @staticmethod
    def forget():
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT], capture_output=True)


class SpliceMcp:
    def __init__(self, redirect):
        self.redirect = redirect          # http://localhost:<port>/companion/splice/callback
        self.lock = threading.RLock()
        self.access, self.expires = None, 0.0
        self.session = None
        self.pending = {}                 # state -> (verifier, client id) of a login under way
        self.meta = None

    def metadata(self):
        if self.meta is None:
            status, _, body = http(SERVER + "/.well-known/oauth-authorization-server")
            if status != 200:
                raise OSError("Splice's sign-in server does not answer (%d)" % status)
            self.meta = json.loads(body)
        return self.meta

    def signed_in(self):
        return bool(Keychain.read().get("refresh_token"))

    def client(self):
        """Our client's id, registered with Splice once for this redirect."""
        saved = Keychain.read()
        if saved.get("client_id") and saved.get("redirect") == self.redirect:
            return saved["client_id"]
        status, _, body = http(self.metadata()["registration_endpoint"], {
            "client_name": "Melodee Kit Manager (Mac companion)", "redirect_uris": [self.redirect],
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "token_endpoint_auth_method": "none"})
        if status >= 300:
            raise OSError("Splice refused to register the companion (%d)" % status)
        client = json.loads(body)["client_id"]
        Keychain.write({"client_id": client, "redirect": self.redirect})
        return client

    def login_url(self):
        """Where the browser goes to sign in; the answer comes back to finish()."""
        client = self.client()
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        with self.lock:
            self.pending = {state: (verifier, client)}
        return self.metadata()["authorization_endpoint"] + "?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": client, "redirect_uri": self.redirect, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "scope": "openid profile email offline_access", "resource": RESOURCE})

    def finish(self, query):
        with self.lock:
            verifier, client = self.pending.pop(query.get("state", ""), (None, None))
        if not verifier or "code" not in query:
            raise PermissionError(query.get("error_description") or query.get("error") or "The sign-in did not come back")
        self.token({"grant_type": "authorization_code", "code": query["code"], "redirect_uri": self.redirect,
                    "client_id": client, "code_verifier": verifier, "resource": RESOURCE}, client)

    def token(self, form, client):
        status, _, body = http(self.metadata()["token_endpoint"], form, form=True)
        if status >= 300:
            raise PermissionError("Splice refused the sign-in (%d)" % status)
        got = json.loads(body)
        with self.lock:
            self.access = got["access_token"]
            self.expires = time.time() + int(got.get("expires_in", 3600)) - 60
            self.session = None
        saved = Keychain.read()
        saved.update({"client_id": client, "redirect": self.redirect})
        if got.get("refresh_token"):
            saved["refresh_token"] = got["refresh_token"]
        Keychain.write(saved)

    def sign_out(self):
        with self.lock:
            self.access, self.session = None, None
        saved = Keychain.read()
        saved.pop("refresh_token", None)
        Keychain.write(saved) if saved else Keychain.forget()

    def bearer(self):
        with self.lock:
            if self.access and time.time() < self.expires:
                return self.access
        saved = Keychain.read()
        if not saved.get("refresh_token"):
            raise PermissionError("Not signed in to Splice")
        self.token({"grant_type": "refresh_token", "refresh_token": saved["refresh_token"], "client_id": saved["client_id"],
                    "resource": RESOURCE}, saved["client_id"])
        return self.access

    def rpc(self, method, params=None, notify=False):
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            message["id"] = secrets.randbelow(1 << 30)
        headers = {"Authorization": "Bearer " + self.bearer(), "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2025-06-18"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        status, head, body = http(RESOURCE, message, headers, timeout=60)
        lower = {k.lower(): v for k, v in head.items()}
        self.session = lower.get("mcp-session-id") or self.session
        if status == 401:
            with self.lock:
                self.access = None
            raise PermissionError("Splice asked to sign in again")
        if notify:
            return None
        text = body.decode(errors="replace")
        if "text/event-stream" in lower.get("content-type", ""):
            datas = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            text = datas[-1] if datas else ""
        if status >= 300:
            raise OSError("Splice MCP answered %d" % status)
        reply = json.loads(text) if text else {}
        if "error" in reply:
            raise OSError(reply["error"].get("message", "Splice MCP error"))
        return reply.get("result", {})

    def call(self, tool, arguments):
        """A tool's text (the server answers Markdown)."""
        with self.lock:
            if not self.session:
                self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "melodee-companion", "version": "0.1"}})
                self.rpc("notifications/initialized", notify=True)
        result = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        return "\n".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")
