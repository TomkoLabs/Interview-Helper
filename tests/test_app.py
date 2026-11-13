import hashlib
import re
import shutil

from fastapi.testclient import TestClient
from interview_helper import app as app_module
from interview_helper.app import create_app
from interview_helper.config import Config


def test_local_security_refresh_and_archive(tmp_path):
    config = Config.load(tmp_path / "config.local.toml")
    app = create_app(config)
    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        assert client.get("/api/state").status_code == 401
        index = client.get("/")
        assert index.status_code == 200
        assert "frame-ancestors 'none'" in index.headers["Content-Security-Policy"]
        assert "HttpOnly" in index.headers["set-cookie"]
        state = client.get("/api/state").json()
        token = state["csrf"]
        assert client.post("/api/start").status_code == 403
        assert (
            client.post(
                "/api/start", headers={"Origin": "https://evil.invalid", "X-Interview-CSRF": token}
            ).status_code
            == 403
        )
        assert client.get("/api/state", headers={"Host": "evil.invalid:8787"}).status_code == 403
        assert client.get("/api/state", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        client.get("/")  # Browser refresh reuses backend state and valid cookie.
        assert client.get("/api/state").json()["csrf"] == token
        assert client.get("/api/sessions").json() == []
        assert client.get("/api/sessions/not-a-session").status_code == 404
        assert client.get("/static/theme.js").status_code == 200
        assert client.get("/static/unknown").status_code == 404


def asset_urls(html):
    return dict(re.findall(r'(?:src|href)="(/static/([^?\"]+)\?v=[a-f0-9]{64})"', html))


def test_content_fingerprints_and_uncached_html_cover_live_and_archive_ui(tmp_path, monkeypatch):
    static = tmp_path / "static"
    shutil.copytree(app_module.STATIC, static)
    monkeypatch.setattr(app_module, "STATIC", static)
    config = Config.load(tmp_path / "config.local.toml")
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        index = client.get("/")
        assert index.headers["cache-control"] == "no-store"
        urls = asset_urls(index.text)
        assert set(urls.values()) == {"app.js", "app.css", "theme.js"}
        for url, name in urls.items():
            expected = (static / name).read_bytes()
            assert url.endswith("?v=" + hashlib.sha256(expected).hexdigest())
            response = client.get(url)
            assert response.content == expected
            assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
            assert response.headers["etag"] == '"' + hashlib.sha256(expected).hexdigest() + '"'
            assert client.get("/static/" + name).headers["cache-control"] == "no-store"
        assert asset_urls(client.get("/").text) == urls
        # Archives render in the same page via this very app.js, with private JSON.
        assert 'id="savedDialog"' in index.text
        assert client.get("/api/sessions").headers["cache-control"] == "no-store"
        assert client.get("/api/state").headers["cache-control"] == "no-store"
        for name in urls.values():
            (static / name).write_bytes((static / name).read_bytes() + b"\n/* upgraded */\n")
        # An already-running backend keeps its matching bytes until a stopped upgrade.
        assert asset_urls(client.get("/").text) == urls
        for url in urls:
            assert hashlib.sha256(client.get(url).content).hexdigest() == url.split("=", 1)[1]

    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        refreshed = client.get(
            "/",
            headers={
                "If-None-Match": '"old"',
                "If-Modified-Since": "Wed, 31 Dec 2099 23:59:59 GMT",
            },
        )
        assert refreshed.status_code == 200 and refreshed.headers["cache-control"] == "no-store"
        changed = asset_urls(refreshed.text)
        assert set(changed.values()) == set(urls.values())
        assert not set(changed).intersection(urls)
        for url, name in changed.items():
            assert client.get(url).content == (static / name).read_bytes()
        for old in urls:
            response = client.get(old)
            assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
    # Fresh processes with unchanged content issue exactly the same URLs.
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        assert asset_urls(client.get("/").text) == changed
