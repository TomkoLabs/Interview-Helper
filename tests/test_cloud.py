import asyncio
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from interview_helper.app import create_app
from interview_helper.cloud_auth import ChatGPTAuth, ISSUER, SCOPES, access_token, account_path
from interview_helper.config import Config, Endpoint
from interview_helper.gateway import Gateway
from interview_helper.storage import atomic_json


def cloud(**kwargs):
    return Endpoint(
        "cloud",
        "https://api.openai.com/v1",
        "test-model",
        backend="openai_api",
        api_key="private-test-key",
        **kwargs,
    )


def test_preview_rejects_incompatible_fields():
    for key in [
        "max_output_tokens",
        "max_tokens",
        "temperature",
        "top_p",
        "background",
        "previous_response_id",
    ]:
        with pytest.raises(ValueError):
            Endpoint(
                "plan",
                "https://api.openai.com/v1",
                "model",
                backend="chatgpt",
                oauth_file="ignored",
                parameters={key: 1},
            )
    with pytest.raises(ValueError):
        Endpoint(
            "plan", "http://elsewhere.invalid", "model", backend="chatgpt", oauth_file="ignored"
        )
    with pytest.raises(ValueError):
        cloud(parameters={"reasoning_effort": "xhigh"})


@pytest.mark.parametrize(
    "terminal,error",
    [
        ("response.completed", False),
        ("response.incomplete", True),
        ("response.failed", True),
        ("error", True),
        (None, True),
        ("[DONE]", True),
    ],
)
async def test_responses_terminal_and_payload(terminal, error):
    endpoint = cloud(parameters={"reasoning_effort": "none"})
    gateway = Gateway([endpoint])
    records = '{"action":"NEW","question":"Explain a queue?","developing":false}\n{"text":"A useful sentence."}\n{"done":true}\n'

    async def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert body["store"] is False and body["stream"] is True
        assert body["instructions"] == "system instruction"
        assert body["input"] == [{"role": "user", "content": "Explain a queue?"}]
        assert body["reasoning"] == {"effort": "none"}
        assert "max_output_tokens" not in body and "temperature" not in body
        events = [
            {"type": "response.reasoning_summary_text.delta", "delta": "secret reasoning"},
            {"type": "response.output_text.delta", "delta": records},
        ]
        if terminal and terminal != "[DONE]":
            events.append(
                {
                    "type": terminal,
                    "response": {
                        "status": "completed" if not error else "failed",
                        "usage": {"input_tokens": 30, "output_tokens": 20},
                    },
                }
            )
        text = "".join("data: " + json.dumps(e) + "\n\n" for e in events)
        if terminal == "[DONE]":
            text += "data: [DONE]\n\n"
        return httpx.Response(200, text=text)

    await gateway.client.aclose()
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    emitted = []

    async def emit(outcome, parser, record):
        emitted.append(record)

    result = await gateway.stream(
        endpoint,
        [
            {"role": "system", "content": "system instruction"},
            {"role": "user", "content": "Explain a queue?"},
        ],
        "id",
        emit,
    )
    assert bool(result.error) == error
    if not error:
        assert result.lines == ["A useful sentence."] and result.usage["output_tokens"] == 20
        assert result.first_useful is not None
    assert "secret reasoning" not in str(emitted)
    await gateway.close()


@pytest.fixture
def signing():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test", alg="RS256", use="sig")
    return key, jwk


async def setup_auth(tmp_path, signing, invalid="", scopes=SCOPES):
    auth = ChatGPTAuth(tmp_path / "accounts", 8787)
    url = await auth.begin()
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == ["dynamic_agent_client"]
    assert query["agent_name_hint"] == ["Interview Helper"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8787/auth/callback"]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(auth.pending["verifier"].encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert query["code_challenge"] == [challenge]
    key, jwk = signing
    claims = {
        "iss": ISSUER,
        "aud": "issued-client",
        "sub": "person",
        "email": "person@example.invalid",
        "exp": int(time.time()) + 600,
        "nonce": auth.pending["nonce"],
    }
    if invalid:
        claims[invalid] = int(time.time()) - 60 if invalid == "exp" else "invalid"
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})

    async def handler(request):
        if request.url.path.endswith("oauth/token"):
            form = parse_qs(request.content.decode())
            assert form["client_id"] == ["issued-client"]
            assert form["code_verifier"] == [auth.pending_verifier]
            return httpx.Response(
                200,
                json={
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "id_token": token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": scopes,
                },
            )
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200, json={"issuer": ISSUER, "jwks_uri": ISSUER + "/.well-known/jwks.json"}
            )
        return httpx.Response(200, json={"keys": [jwk]})

    auth.pending_verifier = auth.pending["verifier"]
    await auth.client.aclose()
    auth.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return auth, query


async def test_signin_storage_reauth_and_scope(tmp_path, signing):
    auth, query = await setup_auth(tmp_path, signing)
    account = await auth.finish(
        {"state": query["state"][0], "client_id": "issued-client", "code": "one-use-code"}
    )
    path = account_path(auth.root, account)
    assert path.stat().st_mode & 0o777 == 0o600
    assert auth.root.stat().st_mode & 0o777 == 0o700
    assert auth.accounts()[0]["plan_enabled"]
    assert "secret" not in json.dumps(auth.accounts())
    host = query["ext_agent_host_id"]
    url = await auth.begin(account)
    query2 = parse_qs(urlsplit(url).query)
    assert query2["client_id"] == ["issued-client"] and query2["ext_agent_host_id"] == host
    assert query2["state"] != query["state"] and "agent_name_hint" not in query2
    assert "access-secret" not in url and "id_token_hint" not in query2
    with pytest.raises(ValueError, match="mismatch"):
        await auth.finish({"state": query2["state"][0], "client_id": "other-client", "code": "x"})
    await auth.client.aclose()


@pytest.mark.parametrize("invalid", ["iss", "aud", "exp", "nonce"])
async def test_invalid_identity_never_saved(tmp_path, signing, invalid):
    auth, query = await setup_auth(tmp_path, signing, invalid)
    with pytest.raises(ValueError, match="validation"):
        await auth.finish({"state": query["state"][0], "client_id": "issued-client", "code": "x"})
    assert auth.accounts() == []
    await auth.client.aclose()


async def test_state_denial_and_missing_permission(tmp_path, signing):
    auth, query = await setup_auth(tmp_path, signing, scopes="openid profile email")
    with pytest.raises(ValueError, match="state"):
        await auth.finish({"state": "wrong", "code": "x"})
    account = await auth.finish(
        {"state": query["state"][0], "client_id": "issued-client", "code": "x"}
    )
    assert not auth.accounts()[0]["plan_enabled"]
    with pytest.raises(RuntimeError, match="permission"):
        await access_token(account_path(auth.root, account), auth.client)
    await auth.begin(account)
    with pytest.raises(ValueError, match="declined"):
        await auth.finish({"state": auth.pending["state"], "error": "access_denied"})
    await auth.client.aclose()


async def test_refresh_rotation_serialized_and_terminal_clear(tmp_path):
    path = tmp_path / "session.json"
    record = {
        "client_id": "own-client",
        "subject": "person",
        "access_token": "old",
        "refresh_token": "refresh",
        "scopes": SCOPES.split(),
        "expires_at": 0,
    }
    atomic_json(path, record)
    calls = []

    async def handler(request):
        form = parse_qs(request.content.decode())
        calls.append(form)
        assert form["client_id"] == ["own-client"] and "scope" not in form
        await asyncio.sleep(0.02)
        return httpx.Response(
            200,
            json={
                "access_token": "new",
                "refresh_token": "rotated",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await asyncio.gather(access_token(path, client), access_token(path, client)) == [
            "new",
            "new",
        ]
    assert len(calls) == 1 and json.loads(path.read_text())["refresh_token"] == "rotated"
    record["expires_at"] = 0
    atomic_json(path, record)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"error": "invalid_grant"})
        )
    ) as client:
        with pytest.raises(RuntimeError, match="expired"):
            await access_token(path, client)
    saved = json.loads(path.read_text())
    assert saved["client_id"] == "own-client" and "access_token" not in saved


async def test_temporary_refresh_failure_retains_tokens(tmp_path):
    path = tmp_path / "session.json"
    record = {
        "client_id": "own-client",
        "access_token": "old",
        "refresh_token": "refresh",
        "scopes": SCOPES.split(),
        "expires_at": 0,
    }
    atomic_json(path, record)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as client:
        with pytest.raises(RuntimeError):
            await access_token(path, client)
    assert json.loads(path.read_text()) == record


def test_cloud_api_guards_and_callback_exception(tmp_path):
    config = Config.load(tmp_path / "config.local.toml")
    with TestClient(create_app(config), base_url="http://127.0.0.1:8787") as client:
        client.get("/")
        csrf = client.get("/api/state").json()["csrf"]
        assert client.post("/api/cloud/sign-in", json={}).status_code == 403
        headers = {"Origin": "http://127.0.0.1:8787", "X-Interview-CSRF": csrf}
        result = client.post("/api/cloud/sign-in", json={}, headers=headers)
        assert result.status_code == 200
        assert result.json()["url"].startswith(ISSUER)
        response = client.get(
            "/auth/callback?state=wrong&code=secret",
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert response.status_code == 303 and response.headers["location"] == "/"
        assert "secret" not in response.text
        assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
        assert (
            client.get("/api/cloud/accounts", headers={"Sec-Fetch-Site": "cross-site"}).status_code
            == 403
        )
        assert client.get("/api/cloud/accounts").json() == []
        assert (
            client.post(
                "/api/cloud/select", json={"provider": "chatgpt"}, headers=headers
            ).status_code
            == 409
        )


async def test_cloud_http_failure_pauses_without_retry_or_body_leak():
    endpoint = cloud()
    gateway = Gateway([endpoint])
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            429,
            headers={"x-request-id": "request-123"},
            json={
                "error": {"code": "insufficient_quota", "param": "model", "message": "PRIVATE BODY"}
            },
        )

    await gateway.client.aclose()
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def emit(*args):
        pass

    one = await gateway.stream(endpoint, [], "one", emit)
    two = await gateway.stream(endpoint, [], "two", emit)
    assert len(calls) == 1 and "paused" in two.error
    assert one.diagnostics == {
        "http_status": 429,
        "failure_type": "RuntimeError",
        "http_version": "HTTP/1.1",
        "parser_done": False,
        "accepted_records": 0,
        "request_id": "request-123",
        "body_shape": "error",
        "code": "insufficient_quota",
        "param": "model",
    }
    assert "PRIVATE BODY" not in str(one)
    await gateway.close()


async def test_returning_identity_must_match(tmp_path, signing):
    auth, query = await setup_auth(tmp_path, signing)
    auth.pending["saved"] = {"client_id": "issued-client", "subject": "someone-else"}
    with pytest.raises(ValueError, match="validation"):
        await auth.finish({"state": query["state"][0], "client_id": "issued-client", "code": "x"})
    assert auth.accounts() == []
    await auth.client.aclose()


async def test_signature_rejected(tmp_path, signing):
    auth, query = await setup_auth(tmp_path, signing)
    original = auth.client

    async def handler(request):
        response = await original.send(request)
        if request.url.path.endswith("oauth/token"):
            body = response.json()
            parts = body["id_token"].split(".")
            parts[2] = "AAAA"
            body["id_token"] = ".".join(parts)
            return httpx.Response(200, json=body)
        return response

    auth.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="validation"):
        await auth.finish({"state": query["state"][0], "client_id": "issued-client", "code": "x"})
    assert auth.accounts() == []
    await auth.client.aclose()
    await original.aclose()


async def test_failed_code_exchange_reuses_issued_registration(tmp_path):
    auth = ChatGPTAuth(tmp_path / "accounts", 8787)
    await auth.begin()
    state = auth.pending["state"]
    await auth.client.aclose()
    auth.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"error": "invalid_grant"})
        )
    )
    with pytest.raises(ValueError):
        await auth.finish(
            {"state": state, "client_id": "issued-for-this-app", "code": "expired-code"}
        )
    url = await auth.begin()
    params = parse_qs(urlsplit(url).query)
    assert params["client_id"] == ["issued-for-this-app"] and "agent_name_hint" not in params
    assert auth.accounts() == []
    await auth.client.aclose()


async def test_signout_retains_mapping_and_reports_revocation_failure(tmp_path):
    auth = ChatGPTAuth(tmp_path / "accounts", 8787)
    await auth.begin()
    account = "a" * 24
    path = account_path(auth.root, account)
    atomic_json(
        path,
        {
            "client_id": "own-client",
            "subject": "person",
            "refresh_token": "private-refresh",
            "access_token": "private-access",
            "id_token": "private-id",
        },
    )

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200, json={"revocation_endpoint": ISSUER + "/api/accounts/oauth/revoke"}
            )
        assert parse_qs(request.content.decode())["client_id"] == ["own-client"]
        return httpx.Response(503)

    await auth.client.aclose()
    auth.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await auth.sign_out(account) is False
    assert json.loads(path.read_text()) == {"client_id": "own-client", "subject": "person"}
    assert auth.pending is None
    await auth.client.aclose()
