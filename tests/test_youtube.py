"""YouTube client, offline: a fake opener stands in for Google's servers."""
import io
import json
import time

import pytest

from bpu.youtube import YouTube, snapshot


class FakeGoogle:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, req):
        self.calls.append(req)
        for prefix, body in self.routes.items():
            if req.full_url.startswith(prefix):
                return io.BytesIO(json.dumps(body).encode())
        raise AssertionError(f"unexpected request {req.full_url}")


@pytest.fixture
def secrets(tmp_path):
    (tmp_path / "client_secret.json").write_text(json.dumps({"installed": {
        "client_id": "cid", "client_secret": "csec",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token"}}))
    return tmp_path


def test_auth_url_requests_offline_access(secrets):
    url = YouTube(secrets).auth_url()
    assert "access_type=offline" in url and "client_id=cid" in url and "youtube.force-ssl" in url


def test_exchange_then_refresh_when_expired(secrets):
    google = FakeGoogle({"https://oauth2.googleapis.com/token":
                         {"access_token": "A1", "refresh_token": "R", "expires_in": 3600}})
    yt = YouTube(secrets, opener=google)
    yt.exchange("http://localhost/?iss=x&code=4/abc&scope=s")
    assert b"code=4%2Fabc" in google.calls[0].data
    assert (secrets / "token.json").stat().st_mode & 0o777 == 0o600

    assert yt.access_token() == "A1" and len(google.calls) == 1  # still fresh: no refresh
    tok = json.loads((secrets / "token.json").read_text())
    tok["expires_at"] = time.time() - 1
    (secrets / "token.json").write_text(json.dumps(tok))
    yt.access_token()
    assert b"grant_type=refresh_token" in google.calls[1].data


def test_snapshot_stores_channel_and_video_stats(secrets, conn):
    (secrets / "token.json").write_text(json.dumps(
        {"access_token": "A", "refresh_token": "R", "expires_at": time.time() + 3600}))
    api = "https://www.googleapis.com/youtube/v3/"
    google = FakeGoogle({
        api + "channels": {"items": [{"id": "UC1", "statistics": {"subscriberCount": "2"},
                                      "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]},
        api + "playlistItems": {"items": [{"contentDetails": {"videoId": "v1"}}]},
        api + "videos": {"items": [{"id": "v1", "statistics": {"viewCount": "1452"}}]},
    })
    assert snapshot(conn, YouTube(secrets, opener=google)) == {"subscriberCount": "2"}
    rows = conn.execute("SELECT scope, ref FROM analytics_snapshots ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("channel", "UC1"), ("video", "v1")]
    assert google.calls[0].headers["Authorization"] == "Bearer A"
