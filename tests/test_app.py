from fastapi.testclient import TestClient
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
