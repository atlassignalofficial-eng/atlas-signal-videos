"""YouTube Data API v3 over OAuth (installed-app flow), stdlib only.

Secrets live in cfg paths.secrets (gitignored, mode 600):
  client_secret.json  - downloaded from Google Cloud Console (Desktop app)
  token.json          - written by `exchange()`, refreshed automatically
"""
import json
import time
import urllib.error
import urllib.parse as up
import urllib.request as ur
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3/"
SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
REDIRECT = "http://localhost"


class YouTube:
    def __init__(self, secrets_dir, opener=ur.urlopen):
        self.dir = Path(secrets_dir)
        self.client = json.loads((self.dir / "client_secret.json").read_text())["installed"]
        self.token_file = self.dir / "token.json"
        self._open = opener

    def auth_url(self) -> str:
        return self.client["auth_uri"] + "?" + up.urlencode({
            "client_id": self.client["client_id"], "redirect_uri": REDIRECT,
            "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent"})

    def exchange(self, redirected_url: str) -> None:
        """Trade the ?code= from the redirected localhost URL for tokens."""
        code = up.parse_qs(up.urlparse(redirected_url).query)["code"][0]
        self._save(self._post(self.client["token_uri"], {
            "code": code, "client_id": self.client["client_id"],
            "client_secret": self.client["client_secret"],
            "redirect_uri": REDIRECT, "grant_type": "authorization_code"}))

    def access_token(self) -> str:
        tok = json.loads(self.token_file.read_text())
        if tok["expires_at"] - 60 < time.time():
            tok.update(self._post(self.client["token_uri"], {
                "client_id": self.client["client_id"],
                "client_secret": self.client["client_secret"],
                "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}))
            self._save(tok)
        return tok["access_token"]

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = ur.Request(API + path, json.dumps(body).encode() if body is not None else None,
                         method=method, headers={"Authorization": "Bearer " + self.access_token(),
                                                 "Content-Type": "application/json"})
        try:
            with self._open(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"YouTube API {e.code} on {method} {path}: {e.read().decode()[:500]}")

    def _post(self, url, data) -> dict:
        with self._open(ur.Request(url, up.urlencode(data).encode())) as r:
            return json.load(r)

    def _save(self, tok) -> None:
        tok["expires_at"] = time.time() + tok["expires_in"]
        self.token_file.write_text(json.dumps(tok))
        self.token_file.chmod(0o600)


def snapshot(conn, yt: YouTube) -> dict:
    """Store public channel + per-video statistics. Returns the channel stats."""
    ch = yt.call("GET", "channels?part=statistics,contentDetails&mine=true")["items"][0]
    stats = ch["statistics"]
    conn.execute("INSERT INTO analytics_snapshots (scope, ref, metrics) VALUES ('channel', ?, ?)",
                 (ch["id"], json.dumps(stats)))
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    items = yt.call("GET", f"playlistItems?part=contentDetails&maxResults=50&playlistId={uploads}")
    ids = ",".join(i["contentDetails"]["videoId"] for i in items.get("items", []))
    if ids:
        for v in yt.call("GET", f"videos?part=statistics&id={ids}")["items"]:
            conn.execute("INSERT INTO analytics_snapshots (scope, ref, metrics) VALUES ('video', ?, ?)",
                         (v["id"], json.dumps(v["statistics"])))
    return stats
