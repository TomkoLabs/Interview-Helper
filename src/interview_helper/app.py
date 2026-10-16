"""Local HTTP surface. Same-origin cookie auth; no secrets sent to JavaScript."""

from contextlib import asynccontextmanager
import secrets
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from .session import Session
from .cloud_auth import ChatGPTAuth, account_path
from .connections import cloud_endpoint, select
from .gateway import Gateway
from .storage import SESSION_ID, SessionStore

STATIC = Path(__file__).parent / "static"


def create_app(config, session=None):
    session = session or Session(config)
    auth = ChatGPTAuth(config.root / ".local" / "chatgpt", config.port)
    secret = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    hosts = {f"127.0.0.1:{config.port}", f"localhost:{config.port}"}
    origins = {"http://" + h for h in hosts}

    @asynccontextmanager
    async def lifespan(app):
        yield
        await session.shutdown()
        await auth.client.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.session = session

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        if host not in hosts or (origin and origin not in origins):
            return JSONResponse({"detail": "Local origin required"}, status_code=403)
        navigation = request.method == "GET" and request.url.path in {"/auth/callback", "/"}
        if request.headers.get("sec-fetch-site") == "cross-site" and not navigation:
            return JSONResponse({"detail": "Cross-site request denied"}, status_code=403)
        if request.url.path.startswith("/api/"):
            if not secrets.compare_digest(request.cookies.get("interview_session", ""), secret):
                return JSONResponse({"detail": "Open the local application first"}, status_code=401)
            if request.method != "GET" and (
                origin not in origins
                or not secrets.compare_digest(request.headers.get("x-interview-csrf", ""), csrf)
            ):
                return JSONResponse({"detail": "Invalid request origin/token"}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    async def index():
        response = FileResponse(STATIC / "index.html")
        response.set_cookie("interview_session", secret, httponly=True, samesite="strict")
        return response

    @app.get("/static/{name}")
    async def static(name: str):
        if name not in {"app.js", "app.css", "theme.js"}:
            raise HTTPException(404)
        return FileResponse(STATIC / name)

    @app.get("/api/state")
    async def state():
        return {**session.view(), "csrf": csrf}

    @app.get("/api/updates")
    async def updates(after: int = -1):
        changed = session.hint_changed
        if after == session.hint_revision:
            try:
                await asyncio.wait_for(changed.wait(), timeout=25)
            except TimeoutError:
                pass
        return {"hint_revision": session.hint_revision}

    @app.post("/api/hint-visible")
    async def visible(request: Request):
        body = await request.json()
        rid = body.get("request_id")
        if not isinstance(rid, str) or len(rid) > 128:
            raise HTTPException(400, "Invalid request ID")
        try:
            session.acknowledge_visible(rid)
        except OSError:
            raise HTTPException(507, "UI timing save failed") from None
        return {"received": True}

    @app.post("/api/start")
    async def start():
        try:
            return {"id": session.start()}
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/end")
    async def end():
        session.end()
        return {"state": session.state}

    @app.post("/api/retry-save")
    async def retry_save():
        try:
            session.retry_save()
            return {"saved": True}
        except OSError as exc:
            raise HTTPException(507, "Disk still unavailable") from exc

    @app.post("/api/review-now")
    async def review_now():
        if session.state != "recording" or not session.controller:
            raise HTTPException(409, "No recording session")
        if not session.controller.review_now():
            raise HTTPException(409, "No reviewable transcript; check context status")
        return {"queued": True}

    @app.post("/api/reset-context")
    async def reset_context():
        if not session.controller:
            raise HTTPException(409, "No session")
        session.controller.reset()
        session.notice("Question context reset explicitly; saved transcript retained")
        return {"reset": True}

    def require_idle():
        if session.state not in {"idle", "ended", "failed"} or session.unsaved:
            raise HTTPException(
                409, "End the session and finish saving before changing connections"
            )

    def save_connection(selection):
        try:
            select(config, selection)
        except OSError:
            raise HTTPException(
                507, "Could not save connection preference; selection unchanged"
            ) from None

    async def choices(endpoint):
        gateway = Gateway([endpoint])
        try:
            return await gateway.model_choices(endpoint)
        finally:
            await gateway.close()

    @app.get("/api/cloud/accounts")
    async def accounts():
        return auth.accounts()

    @app.post("/api/cloud/sign-in")
    async def sign_in(request: Request):
        require_idle()
        try:
            body = await request.json()
            return {"url": await auth.begin(body.get("account", ""))}
        except (OSError, ValueError):
            raise HTTPException(400, "Unable to begin sign-in for this account") from None

    @app.get("/auth/callback")
    async def callback(request: Request):
        # Callback and its return-to-home navigation permit cross-site GETs only.
        # OAuth state/PKCE/nonce are
        # checked independently of the SameSite cookie, which is absent on return.
        try:
            await auth.finish(dict(request.query_params))
            session.notice(
                "ChatGPT sign-in validated. Load account models and explicitly select cloud to use it."
            )
        except Exception:
            session.notice(
                "ChatGPT sign-in was declined, expired or could not be validated. No connection was changed; start sign-in again."
            )
        return RedirectResponse("/", status_code=303)

    @app.post("/api/cloud/sign-out")
    async def sign_out(request: Request):
        require_idle()
        try:
            account = (await request.json())["account"]
            confirmed = await auth.sign_out(account)
        except (KeyError, ValueError, OSError):
            raise HTTPException(400, "Unknown account") from None
        selected = str(account_path(auth.root, account))
        if any(e.oauth_file == selected for e in config.endpoints):
            save_connection({"provider": "local"})
        return {
            "message": "Signed out"
            if confirmed
            else "Signed out locally; remote revocation unconfirmed. Disconnect the app in ChatGPT settings."
        }

    @app.post("/api/cloud/models")
    async def cloud_models(request: Request):
        try:
            body = await request.json()
            endpoint = cloud_endpoint(config, body["provider"], body.get("account", ""), "catalog")
            return await choices(endpoint)
        except (ValueError, KeyError, OSError, RuntimeError):
            raise HTTPException(
                409,
                "Connect this account or configure OPENAI_API_KEY on the backend first; account access is not yet verified",
            ) from None
        except Exception:
            raise HTTPException(
                502, "Account model catalog unavailable; check authentication or policy"
            ) from None

    @app.post("/api/cloud/select")
    async def select_cloud(request: Request):
        require_idle()
        try:
            body = await request.json()
            if body.get("send_transcript_to_openai") is not True:
                raise ValueError("Cloud disclosure must be accepted")
            endpoint = cloud_endpoint(
                config,
                body["provider"],
                body.get("account", ""),
                body["model"],
                body["reasoning"],
                body.get("tier", "default"),
                body.get("transport", "http"),
            )
            if endpoint.model not in [m["id"] for m in await choices(endpoint)]:
                raise ValueError("Model absent from this account's current catalog")
        except (KeyError, ValueError, OSError, RuntimeError):
            raise HTTPException(
                409,
                "Select an available account model and supported settings; cloud authentication is required",
            ) from None
        except Exception:
            raise HTTPException(502, "Could not verify account model access") from None
        save_connection(
            {
                k: body[k]
                for k in ("provider", "account", "model", "reasoning", "tier", "transport")
                if k in body
            }
        )
        session.hosts.clear()
        return {
            "message": "Cloud selected. Transcript context will be sent to OpenAI; model reasoning support is validated on inference. Selection is saved for future sessions and restarts."
        }

    @app.post("/api/cloud/local")
    async def select_local():
        require_idle()
        save_connection({"provider": "local"})
        session.hosts.clear()
        return {"message": "Configured local models selected and saved for restarts"}

    @app.get("/api/sessions")
    async def sessions():
        rows = []
        if config.data_dir.exists():
            import json

            for path in sorted(config.data_dir.iterdir(), reverse=True):
                if not SESSION_ID.fullmatch(path.name) or path.is_symlink():
                    continue
                try:
                    metadata = json.loads((path / "metadata.json").read_text())
                    metadata["active"] = bool(
                        session.store
                        and session.store.id == path.name
                        and session.state not in {"ended", "failed"}
                    )
                    rows.append(metadata)
                except (OSError, ValueError):
                    rows.append({"id": path.name, "status": "unreadable metadata"})
        return rows

    @app.get("/api/sessions/{session_id}")
    async def inspect(session_id: str):
        try:
            return SessionStore.inspect(config.data_dir, session_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(404, "Session unavailable or corrupt") from exc

    @app.get("/api/sessions/{session_id}/transcript")
    async def export(session_id: str):
        try:
            data = SessionStore.inspect(config.data_dir, session_id)
            return PlainTextResponse(
                data["readable"]
                + (
                    "\n[RECOVERY] Incomplete final journal record excluded.\n"
                    if data["partial_tail"]
                    else ""
                ),
                headers={
                    "Content-Disposition": f'attachment; filename="{session_id}-playback.txt"'
                },
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(
                507,
                "Readable transcript unavailable; journal retained. Check storage and use recover --write-view.",
            ) from exc

    return app
