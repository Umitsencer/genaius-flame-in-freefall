"""FastAPI application for the loopback GeNAIus prototype (not a production deployment).

Routing is FastAPI's; request validation stays in `AppService` (Pydantic models in
`genaius.schemas`), so FastAPI never emits its own 422 contract. Security controls that
the framework does not provide on its own are explicit here:

* Host allowlist (127.0.0.1/localhost on the *bound* port) for every request;
* Origin allowlist for POST;
* `Content-Type: application/json`, 1–32768 byte bodies, chunked bodies rejected, and the
  streamed byte count enforced independently of the declared Content-Length;
* CSP / nosniff / no-store headers on every response;
* allowlisted static files only; FastAPI docs/OpenAPI endpoints disabled;
* fixed 400/403/404/500/501/503 envelopes that never echo internal paths or input.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..app_service import AppService, envelope
from ..catalog import CatalogValidationError
from ..cfi import CfiValidationError
from ..data.query import QueryValidationError
from ..flex_predictor import FlexPredictionValidationError
from ..retrieval.bm25 import RetrievalValidationError
from ..saffire import SaffireValidationError
from ..saffire_case import SaffireCaseValidationError
from ..service import EvidenceServiceError
from .static import resolve_ai_use_doc, resolve_frontend_asset

MAX_BODY_BYTES = 32768
BODY_READ_TIMEOUT_S = 10.0
REJECT_BODY_TIMEOUT_S = 0.5
CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"Cache-Control", b"no-store"),
    (b"X-Content-Type-Options", b"nosniff"),
    (b"Content-Security-Policy", CSP_HEADER.encode("ascii")),
)
_SECURITY_HEADER_NAMES = frozenset(name.lower() for name, _ in SECURITY_HEADERS)


def _canonical_header_name(name: bytes) -> bytes:
    # Header names are case-insensitive, but the previous server emitted canonical casing and
    # simple clients (dict(getheaders())) rely on it; keep the observable contract identical.
    return b"-".join(part[:1].upper() + part[1:] for part in name.lower().split(b"-"))


INVALID_INPUT_MESSAGE = "Invalid request. Check the documented fields, identifiers, units and numeric bounds."
VALIDATION_ERRORS: tuple[type[BaseException], ...] = (
    ValueError, TypeError, QueryValidationError, RetrievalValidationError, EvidenceServiceError,
    CatalogValidationError, CfiValidationError, SaffireValidationError, SaffireCaseValidationError,
    FlexPredictionValidationError,
)
UNAVAILABLE_STATUSES = frozenset({
    "CATALOG_UNAVAILABLE", "CFI_UNAVAILABLE", "SAFFIRE_UNAVAILABLE", "SAFFIRE_CASE_UNAVAILABLE",
    "FLEX_PREDICTOR_UNAVAILABLE", "FLEX_RECONCILIATION_UNAVAILABLE",
})


class _BadRequest(Exception):
    """Transport-level request rejection mapped to the fixed INVALID_INPUT envelope."""


def json_response(status: int, content: Any) -> Response:
    body = json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return Response(body, status_code=status, media_type="application/json; charset=utf-8")


def _forbidden() -> Response:
    resp = json_response(403, envelope(None, "FORBIDDEN"))
    resp.headers["connection"] = "close"
    return resp


def _http_status(result: Any) -> int:
    return 503 if isinstance(result, dict) and result.get("status") in UNAVAILABLE_STATUSES else 200


def _allowed_hosts(scope: Scope) -> set[str]:
    port = (scope.get("server") or ("", 0))[1]
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


async def _discard_small_rejected_body(headers: dict[str, str], receive: Receive) -> None:
    """Drain only bounded, already-announced bodies before closing a rejected request.

    Closing a socket with unread incoming bytes can reset it on Windows, losing the
    403 response. Never parse or dispatch rejected input, invite 100-continue uploads,
    or wait indefinitely for a malicious/truncated body.
    """
    if headers.get("transfer-encoding") or headers.get("expect"):
        return
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        return
    if not 0 < length <= MAX_BODY_BYTES:
        return

    async def discard() -> None:
        consumed = 0
        while consumed < length:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            consumed += len(message.get("body", b""))
            if consumed > MAX_BODY_BYTES or not message.get("more_body", False):
                return

    try:
        await asyncio.wait_for(discard(), timeout=REJECT_BODY_TIMEOUT_S)
    except asyncio.TimeoutError:
        pass  # Still deny; a slow/unbounded request must never reach the service.


class LoopbackGuard:
    """Raw ASGI wrapper: Host/Origin allowlists and security headers on every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (_canonical_header_name(k), v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in _SECURITY_HEADER_NAMES
                ]
                message["headers"] = headers + list(SECURITY_HEADERS)
            await send(message)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        allowed = _allowed_hosts(scope)
        method = scope.get("method", "GET")
        origin = headers.get("origin")
        if headers.get("host") not in allowed or (
            method == "POST" and origin and origin not in {f"http://{h}" for h in allowed}
        ):
            await _discard_small_rejected_body(headers, receive)
            await _forbidden()(scope, receive, send_with_headers)
            return
        await self.app(scope, receive, send_with_headers)


async def _read_json_body(request: Request) -> Any:
    ctype = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if ctype != "application/json":
        raise _BadRequest("Content-Type must be application/json.")
    if request.headers.get("transfer-encoding"):
        raise _BadRequest("Chunked request bodies are unsupported.")
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise _BadRequest("Invalid Content-Length.") from None
    if not 0 < declared <= MAX_BODY_BYTES:
        raise _BadRequest(f"Request body must be 1–{MAX_BODY_BYTES} bytes.")

    async def _collect() -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_BODY_BYTES:  # never trust the declared length alone
                raise _BadRequest("Request body exceeds the byte limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    try:
        raw = await asyncio.wait_for(_collect(), timeout=BODY_READ_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise _BadRequest("Request body read timed out.") from None

    def _reject_constant(_token: str) -> Any:
        raise ValueError("Non-finite JSON number.")

    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError):
        raise _BadRequest("Malformed JSON body.") from None


def create_app(service: AppService) -> ASGIApp:
    """Build the guarded ASGI app over one shared `AppService` (the only business-logic layer)."""
    root = Path(service.root)
    frontend_dir: Path | None = root / "frontend"
    if not (frontend_dir / "index.html").is_file():
        frontend_dir = None

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 405:  # a GET-only path hit with POST (or vice versa) is simply unknown
            return json_response(404, envelope(None, "NOT_FOUND"))
        return json_response(exc.status_code, envelope(None, "NOT_FOUND" if exc.status_code == 404 else "ERROR"))

    @app.exception_handler(Exception)
    async def _internal_error(_request: Request, _exc: Exception) -> Response:
        return json_response(500, envelope(None, "INTERNAL_ERROR", "Request failed; no result was generated."))

    get_routes: dict[str, Callable[[], dict]] = {
        "/api/schema": service.schema,
        "/api/catalog/filters": service.catalog_filters,
        "/api/cfi/schema": service.cfi_schema,
        "/api/saffire/schema": service.saffire_schema,
        "/api/saffire/case/schema": service.saffire_case_schema,
        "/api/flex/predict/schema": service.flex_prediction_schema,
        "/api/flex/reconciliation": service.flex_reconciliation,
        "/api/prevention/summary": service.prevention_summary,
    }
    post_routes: dict[str, Callable[[Any], dict]] = {
        "/api/search": service.search,
        "/api/detail": service.detail,
        "/api/compare": service.compare,
        "/api/documents": service.documents,
        "/api/evidence": service.evidence,
        "/api/answer": service.answer,
        "/api/catalog/search": service.catalog_search,
        "/api/analytics": service.analytics,
        "/api/export": service.export,
        "/api/analytics/flex": service.analytics_flex,
        "/api/analytics/materials": service.analytics_materials,
        "/api/cfi/analysis": service.cfi_analysis,
        "/api/saffire/reference": service.saffire_reference,
        "/api/saffire/case": service.saffire_case_reference,
        "/api/saffire/case/export": service.saffire_case_export,
        "/api/scenario/check": service.scenario_check,
        "/api/scenario/grid": service.scenario_grid,
        "/api/scenario/report": service.scenario_report,
        "/api/flex/predict": service.flex_prediction,
        "/api/flex/predict/map": service.flex_prediction_map,
        "/api/flex/predict/export": service.flex_prediction_export,
    }

    def _get_endpoint(handler: Callable[[], dict]) -> Callable[[], Awaitable[Response]]:
        async def endpoint() -> Response:
            result = await run_in_threadpool(handler)
            return json_response(_http_status(result), result)
        return endpoint

    def _post_endpoint(handler: Callable[[Any], dict]) -> Callable[[Request], Awaitable[Response]]:
        async def endpoint(request: Request) -> Response:
            try:
                payload = await _read_json_body(request)
                result = await run_in_threadpool(handler, payload)
            except (_BadRequest, *VALIDATION_ERRORS):
                return json_response(400, envelope(None, "INVALID_INPUT", INVALID_INPUT_MESSAGE))
            return json_response(_http_status(result), result)
        return endpoint

    for path, handler in get_routes.items():
        app.add_api_route(path, _get_endpoint(handler), methods=["GET"], include_in_schema=False)
    for path, handler in post_routes.items():
        app.add_api_route(path, _post_endpoint(handler), methods=["POST"], include_in_schema=False)

    @app.get("/docs/AI_USE.md", include_in_schema=False)
    async def ai_use_doc() -> Response:
        doc = resolve_ai_use_doc(root)
        if doc is None:
            return json_response(404, envelope(None, "NOT_FOUND"))
        return Response(doc.read_bytes(), media_type="text/plain; charset=utf-8")

    @app.get("/{asset_path:path}", include_in_schema=False)
    async def static_asset(request: Request) -> Response:
        asset = resolve_frontend_asset(frontend_dir, request.url.path)
        if asset is None:
            return json_response(404, envelope(None, "NOT_FOUND"))
        file_path, mime = asset
        media = f"{mime}; charset=utf-8" if mime.startswith("text/") else mime
        return Response(file_path.read_bytes(), media_type=media)

    @app.api_route("/{any_path:path}", methods=["PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
                   include_in_schema=False)
    async def unsupported_method() -> Response:
        return json_response(501, envelope(None, "NOT_IMPLEMENTED", "Only GET and POST are supported."))

    return LoopbackGuard(app)
