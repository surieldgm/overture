import http.client
import subprocess
import sys
import threading
import unittest
from urllib.parse import urlparse

import overture.cli as cli
from overture.ui_host import (
    WIZARD_ROUTES,
    SessionStore,
    build_ui_server,
)


class UIHostTests(unittest.TestCase):
    def test_all_wizard_routes_render_base_layout(self) -> None:
        with _running_server() as base_url:
            for route in WIZARD_ROUTES:
                with self.subTest(route=route.path):
                    response = _get(base_url, route.path)

                self.assertEqual(response.status, 200)
                self.assertIn("<header>", response.body)
                self.assertIn('aria-label="Breadcrumbs"', response.body)
                self.assertIn("<section>", response.body)
                self.assertIn(route.title, response.body)
                if route.path == "/export":
                    self.assertIn("No export-ready ticket is available.", response.body)
                else:
                    self.assertIn(route.placeholder, response.body)

    def test_session_cookie_reuses_server_side_session_on_refresh(self) -> None:
        with _running_server() as base_url:
            first = _get(base_url, "/intake")
            cookie = first.headers["Set-Cookie"].split(";", 1)[0]
            second = _get(base_url, "/intake", headers={"Cookie": cookie})

        session_id = cookie.split("=", 1)[1]
        self.assertIn(f"Session <code>{session_id}</code>", first.body)
        self.assertIn(f"Session <code>{session_id}</code>", second.body)
        self.assertIn("has rendered 2 page view(s)", second.body)
        self.assertNotIn("Set-Cookie", second.headers)

    def test_root_redirects_to_intake(self) -> None:
        with _running_server() as base_url:
            response = _get(base_url, "/")

        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/intake")

    def test_non_loopback_bind_address_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            build_ui_server("0.0.0.0", 0)

    def test_non_loopback_client_address_is_rejected(self) -> None:
        server = build_ui_server(port=0)
        try:
            self.assertFalse(server.verify_request(object(), ("192.0.2.10", 4040)))
            self.assertTrue(server.verify_request(object(), ("127.0.0.1", 4040)))
        finally:
            server.server_close()

    def test_ui_command_is_registered(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["ui", "--port", "9000"])

        self.assertEqual(args.command, "ui")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 9000)

    def test_pipeline_imports_do_not_load_ui_host(self) -> None:
        script = (
            "import sys\n"
            "import overture.fixture\n"
            "import overture.intake\n"
            "import overture.synthesis\n"
            "print('overture.ui_host' in sys.modules)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "False")


class SessionStoreTests(unittest.TestCase):
    def test_session_store_reuses_known_session(self) -> None:
        store = SessionStore()
        session_id, session, is_new = store.get_or_create(None)
        same_id, same_session, same_is_new = store.get_or_create(session_id)

        self.assertTrue(is_new)
        self.assertFalse(same_is_new)
        self.assertEqual(same_id, session_id)
        self.assertIs(same_session, session)


def _running_server() -> "_ServerContext":
    return _ServerContext()


class _ServerContext:
    def __enter__(self) -> str:
        self.server = build_ui_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


def _get(base_url: str, path: str, *, headers: dict[str, str] | None = None) -> "_Response":
    parsed = urlparse(base_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        return _Response(
            status=response.status,
            headers={key: value for key, value in response.getheaders()},
            body=body,
        )
    finally:
        connection.close()


class _Response:
    def __init__(self, *, status: int, headers: dict[str, str], body: str) -> None:
        self.status = status
        self.headers = headers
        self.body = body


if __name__ == "__main__":
    unittest.main()
