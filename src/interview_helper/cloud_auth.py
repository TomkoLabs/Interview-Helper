"""App-owned SIWC registrations. No browser storage or borrowed application credentials."""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode
import uuid

from filelock import FileLock, Timeout
import httpx
import jwt

from .storage import atomic_json

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
TERMINAL = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


@asynccontextmanager
async def locked(path):
    # A process-shared lock prevents refresh rotation races across CLI and server.
    private_dir(path.parent)
    lock = FileLock(str(path) + ".lock", mode=0o600)
    deadline = time.monotonic() + 35
    while True:
        try:
            lock.acquire(timeout=0)
            break
        except Timeout:
            if time.monotonic() > deadline:
                raise RuntimeError("Account is busy; retry later") from None
            await asyncio.sleep(0.05)
    try:
        yield
    finally:
        lock.release()


def account_path(root, account):
    if len(account) != 24 or any(c not in "0123456789abcdef" for c in account):
        raise ValueError("Unknown account registration")
    return root / (account + ".json")


async def exchange(client, form):
    response = await client.post(TOKEN, data=form, timeout=20)
    if response.status_code != 200:
        try:
            code = response.json().get("error")
        except ValueError:
            code = None
        # Never surface provider descriptions, tokens or arbitrary response text.
        if code in TERMINAL:
            raise ValueError("Sign in again")
        raise RuntimeError(f"Token endpoint HTTP {response.status_code}; retry or sign in again")
    return response.json()


def tokens(old, new):
    required = ["access_token", "refresh_token", "expires_in", "token_type"]
    if any(not new.get(k) for k in required) or new["token_type"].lower() != "bearer":
        raise RuntimeError("Incomplete token response")
    return {
        **old,
        **{k: new[k] for k in required},
        "id_token": new.get("id_token", old.get("id_token", "")),
        "scopes": new.get("scope", " ".join(old.get("scopes", []))).split(),
        "expires_at": time.time() + float(new["expires_in"]),
        "earliest_refresh_at": new.get("earliest_refresh_at"),
    }


async def access_token(path, client):
    path = Path(path)
    async with locked(path):
        if not path.exists():
            raise RuntimeError("Continue with ChatGPT to connect this app")
        record = json.loads(path.read_text())
        if not record.get("access_token"):
            raise RuntimeError("Sign in again with this ChatGPT account")
        if "chatgpt.tokens.use.direct" not in record.get("scopes", []):
            raise RuntimeError("ChatGPT plan usage permission is disabled; sign in to enable it")
        if record["expires_at"] < time.time() + 60:
            try:
                new = await exchange(
                    client,
                    {
                        "grant_type": "refresh_token",
                        "client_id": record["client_id"],
                        "refresh_token": record["refresh_token"],
                        "resource": RESOURCE,
                    },
                )
            except ValueError:
                clear_tokens(record)
                atomic_json(path, record)
                raise RuntimeError("ChatGPT session expired; sign in again") from None
            record = tokens(record, new)
            atomic_json(path, record)
        if "chatgpt.tokens.use.direct" not in record["scopes"]:
            raise RuntimeError("ChatGPT plan usage permission is disabled")
        return record["access_token"]


def clear_tokens(record):
    for key in ("access_token", "refresh_token", "id_token", "expires_at", "scopes"):
        record.pop(key, None)


class ChatGPTAuth:
    def __init__(self, root, port):
        self.root, self.port = root, port
        self.pending = None
        self.retry_client = None
        self.client = httpx.AsyncClient(trust_env=False)

    def accounts(self):
        result = []
        for path in sorted(self.root.glob("*.json")):
            if path.name == "host.json":
                continue
            record = json.loads(path.read_text())
            result.append(
                {
                    "id": path.stem,
                    "label": record.get("email", "ChatGPT account") + " · " + path.stem[:6],
                    "connected": bool(record.get("access_token")),
                    "plan_enabled": "chatgpt.tokens.use.direct" in record.get("scopes", []),
                }
            )
        return result

    async def begin(self, account=""):
        host_path = self.root / "host.json"
        async with locked(host_path):
            if not host_path.exists():
                atomic_json(host_path, {"id": "urn:uuid:" + str(uuid.uuid4())})
            host = json.loads(host_path.read_text())["id"]
        saved = json.loads(account_path(self.root, account).read_text()) if account else {}
        expected_client = saved.get("client_id", self.retry_client or "dynamic_agent_client")
        verifier = secrets.token_urlsafe(48)
        nonce, state = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        redirect = f"http://127.0.0.1:{self.port}/auth/callback"
        self.pending = {
            "verifier": verifier,
            "nonce": nonce,
            "state": state,
            "redirect": redirect,
            "saved": saved,
            "client_id": expected_client,
            "host": host,
            "deadline": time.monotonic() + 600,
        }
        import base64

        params = {
            "client_id": expected_client,
            "ext_agent_host_id": host,
            "response_type": "code",
            "redirect_uri": redirect,
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("="),
        }
        if expected_client == "dynamic_agent_client":
            params["agent_name_hint"] = "Interview Helper"
        elif saved and "chatgpt.tokens.use.direct" not in saved.get("scopes", []):
            params["prompt"] = "consent"
        # Optional ID/login hints are omitted: no tokens cross the local UI boundary.
        return AUTHORIZE + "?" + urlencode(params)

    async def finish(self, query):
        pending = self.pending
        if (
            not pending
            or time.monotonic() > pending["deadline"]
            or not secrets.compare_digest(query.get("state", ""), pending["state"])
        ):
            raise ValueError("Invalid or expired sign-in state; start again")
        self.pending = None
        if query.get("error"):
            raise ValueError("Sign-in declined or unavailable; local backend remains available")
        saved = pending["saved"]
        expected_client = pending["client_id"]
        client_id = query.get("client_id") or (
            expected_client if expected_client != "dynamic_agent_client" else None
        )
        if (
            not client_id
            or client_id == "dynamic_agent_client"
            or (expected_client != "dynamic_agent_client" and client_id != expected_client)
        ):
            raise ValueError("Registration client mismatch or missing issued client ID")
        if not query.get("code"):
            raise ValueError("Missing authorization code")
        if not saved:
            self.retry_client = client_id
        new = await exchange(
            self.client,
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": query["code"],
                "code_verifier": pending["verifier"],
                "redirect_uri": pending["redirect"],
                "resource": RESOURCE,
            },
        )
        try:
            discovery = await self.client.get(
                ISSUER + "/.well-known/openid-configuration", timeout=15
            )
            discovery.raise_for_status()
            metadata = discovery.json()
            if (
                metadata["issuer"] != ISSUER
                or metadata["jwks_uri"] != ISSUER + "/.well-known/jwks.json"
            ):
                raise ValueError("Unexpected OpenAI identity metadata")
            response = await self.client.get(metadata["jwks_uri"], timeout=15)
            response.raise_for_status()
            header = jwt.get_unverified_header(new["id_token"])
            key = next(k for k in response.json()["keys"] if k["kid"] == header["kid"])
            identity = jwt.decode(
                new["id_token"],
                jwt.PyJWK.from_dict(key).key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=ISSUER,
                options={"require": ["exp", "iss", "aud", "sub", "nonce"]},
            )
            if not secrets.compare_digest(identity["nonce"], pending["nonce"]):
                raise ValueError("Nonce mismatch")
            if identity.get("azp", client_id) != client_id:
                raise ValueError("Authorized party mismatch")
            if saved and identity["sub"] != saved["subject"]:
                raise ValueError("Account mismatch")
        except Exception:
            raise ValueError(
                "OpenAI identity validation failed; no account was activated"
            ) from None
        record = tokens(
            {
                "client_id": client_id,
                "subject": identity["sub"],
                "email": identity.get("email", "ChatGPT account"),
                "issuer": ISSUER,
                "ext_agent_host_id": pending["host"],
            },
            new,
        )
        account = hashlib.sha256(client_id.encode()).hexdigest()[:24]
        path = account_path(self.root, account)
        async with locked(path):
            atomic_json(path, record)
        self.retry_client = None
        return account

    async def sign_out(self, account):
        self.pending = None
        path = account_path(self.root, account)
        confirmed = False
        async with locked(path):
            record = json.loads(path.read_text())
            if record.get("refresh_token"):
                try:
                    response = await self.client.get(
                        ISSUER + "/.well-known/openid-configuration", timeout=15
                    )
                    endpoint = response.json()["revocation_endpoint"]
                    if endpoint != ISSUER + "/api/accounts/oauth/revoke":
                        raise ValueError("Unexpected revocation endpoint")
                    for delay in (0, 0.5, 1):
                        if delay:
                            await asyncio.sleep(delay)
                        try:
                            response = await self.client.post(
                                endpoint,
                                data={
                                    "token": record["refresh_token"],
                                    "token_type_hint": "refresh_token",
                                    "client_id": record["client_id"],
                                },
                                timeout=10,
                            )
                            confirmed = response.status_code == 200
                            if confirmed or response.status_code < 500:
                                break
                        except httpx.HTTPError:
                            continue
                except (httpx.HTTPError, ValueError, KeyError):
                    pass
            else:
                confirmed = True
            clear_tokens(record)
            atomic_json(path, record)
        return confirmed
