"""FastAPI/Uvicorn katmanına özgü güvenlik sözleşmeleri (Görev 056).

Framework varsayılanlarının (422, /docs, /openapi.json, 405, Server header) sözleşmeye
sızmadığını ve gövde sınırının yalnız Content-Length'e güvenmediğini gerçek soketle doğrular.
"""
import asyncio
import json
import socket
import threading
import time
import unittest
from pathlib import Path

import genaius.api.app as api_app
from genaius.app_service import AppService
from genaius.prototype.server import make_server

ROOT = Path(__file__).resolve().parents[1]


def _raw(port: int, data: bytes, *, pause_after: float = 0.0, tail: bytes = b"") -> tuple[int, dict, bytes]:
    with socket.create_connection(("127.0.0.1", port), timeout=15) as sock:
        sock.sendall(data)
        if pause_after:
            time.sleep(pause_after)
        if tail:
            sock.sendall(tail)
        chunks = []
        while True:
            try:
                buf = sock.recv(65536)
            except socket.timeout:
                break
            if not buf:
                break
            chunks.append(buf)
            if b"\r\n\r\n" in b"".join(chunks):
                head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
                lengths = [ln for ln in head.split(b"\r\n") if ln.lower().startswith(b"content-length:")]
                if lengths and len(body) >= int(lengths[0].split(b":")[1]):
                    break
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(b":")
        headers[k.decode().strip()] = v.decode().strip()
    return status, headers, body


class ApiSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(AppService(ROOT), 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port
        cls.host = f"127.0.0.1:{cls.port}".encode()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _req(self, method: bytes, path: bytes, body: bytes = b"", extra: bytes = b"") -> tuple[int, dict, bytes]:
        head = method + b" " + path + b" HTTP/1.1\r\nHost: " + self.host + b"\r\nConnection: close\r\n" + extra
        if body or method == b"POST":
            head += b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        return _raw(self.port, head + b"\r\n" + body)

    def test_framework_docs_and_openapi_are_not_exposed(self):
        for path in (b"/openapi.json", b"/docs", b"/redoc", b"/docs/oauth2-redirect"):
            status, _, body = self._req(b"GET", path)
            self.assertEqual(status, 404, path)
            self.assertEqual(json.loads(body)["status"], "NOT_FOUND")

    def test_wrong_method_is_404_envelope_not_405(self):
        status, _, body = self._req(b"POST", b"/api/schema", b"{}", b"Content-Type: application/json\r\n")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["status"], "NOT_FOUND")
        status, _, body = self._req(b"PUT", b"/api/search")
        self.assertEqual(status, 501)
        self.assertEqual(json.loads(body)["status"], "NOT_IMPLEMENTED")

    def test_validation_never_returns_framework_422(self):
        ctype = b"Content-Type: application/json\r\n"
        for path, body in (
            (b"/api/search", b'{"limit": "5"}'),
            (b"/api/search", b'{"limit": 5.0}'),
            (b"/api/flex/predict", b'{"fuel": "Heptane"}'),
            (b"/api/documents", b'{"query": 12}'),
        ):
            status, _, raw = self._req(b"POST", path, body, ctype)
            self.assertEqual(status, 400, (path, body))
            payload = json.loads(raw)
            self.assertEqual(payload["status"], "INVALID_INPUT")
            self.assertNotIn("detail", payload)  # no Pydantic/FastAPI error echo

    def test_chunked_and_oversized_bodies_are_rejected(self):
        status, _, _ = _raw(
            self.port,
            b"POST /api/search HTTP/1.1\r\nHost: " + self.host + b"\r\nConnection: close\r\n"
            b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n",
        )
        self.assertEqual(status, 400)
        status, _, _ = self._req(b"POST", b"/api/documents", b'{"query":"' + b"x" * 33000 + b'"}',
                                 b"Content-Type: application/json\r\n")
        self.assertEqual(status, 400)

    def test_truncated_body_times_out_instead_of_hanging(self):
        original = api_app.BODY_READ_TIMEOUT_S
        api_app.BODY_READ_TIMEOUT_S = 0.5
        try:
            started = time.monotonic()
            status, _, body = _raw(
                self.port,
                b"POST /api/search HTTP/1.1\r\nHost: " + self.host + b"\r\nConnection: close\r\n"
                b"Content-Type: application/json\r\nContent-Length: 200\r\n\r\n{\"limit\":",
            )
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["status"], "INVALID_INPUT")
            self.assertLess(time.monotonic() - started, 8)
        finally:
            api_app.BODY_READ_TIMEOUT_S = original

    def test_host_origin_and_headers(self):
        status, headers, _ = _raw(self.port, b"GET /api/schema HTTP/1.1\r\nHost: 127.0.0.1:1\r\nConnection: close\r\n\r\n")
        self.assertEqual(status, 403)
        self.assertIn("Content-Security-Policy", headers)
        ok_origin = b"Origin: http://localhost:" + str(self.port).encode() + b"\r\nContent-Type: application/json\r\n"
        status, headers, _ = self._req(b"POST", b"/api/search", b"{}", ok_origin)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertNotIn("Server", headers)
        bad_origin = b"Origin: http://localhost:1\r\nContent-Type: application/json\r\n"
        self.assertEqual(self._req(b"POST", b"/api/search", b"{}", bad_origin)[0], 403)

    def test_rejected_post_body_arriving_after_headers_still_returns_403(self):
        status, headers, body = _raw(
            self.port,
            b"POST /api/search HTTP/1.1\r\nHost: " + self.host
            + b"\r\nOrigin: https://untrusted.invalid\r\nContent-Type: application/json"
            b"\r\nContent-Length: 2\r\nConnection: close\r\n\r\n",
            pause_after=0.05,
            tail=b"{}",
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["status"], "FORBIDDEN")
        self.assertIn("Content-Security-Policy", headers)


class RejectedBodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_body_is_discarded_but_never_dispatched(self):
        events = iter([
            {"type": "http.request", "body": b"{", "more_body": True},
            {"type": "http.request", "body": b"}", "more_body": False},
        ])
        async def receive():
            return next(events)
        await api_app._discard_small_rejected_body({"content-length": "2"}, receive)
        self.assertEqual(list(events), [])

    async def test_unbounded_and_expect_continue_bodies_are_not_read(self):
        async def receive():
            self.fail("Rejected unbounded/Expect body must not trigger a read")
        for headers in (
            {}, {"content-length": "invalid"}, {"content-length": "33000"},
            {"content-length": "2", "expect": "100-continue"},
            {"transfer-encoding": "chunked"},
        ):
            await api_app._discard_small_rejected_body(headers, receive)

    async def test_stalled_rejected_body_is_time_bounded(self):
        async def receive():
            await asyncio.Event().wait()
        original = api_app.REJECT_BODY_TIMEOUT_S
        api_app.REJECT_BODY_TIMEOUT_S = 0.02
        try:
            await asyncio.wait_for(
                api_app._discard_small_rejected_body({"content-length": "2"}, receive),
                timeout=1.0,
            )
        finally:
            api_app.REJECT_BODY_TIMEOUT_S = original


if __name__ == "__main__":
    unittest.main()
