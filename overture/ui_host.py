"""Local-only HTTP host for the Overture wizard scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import html
from ipaddress import ip_address
import secrets
from typing import Mapping
from urllib.parse import urlparse


DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 8765
SESSION_COOKIE_NAME = "overture_session"


@dataclass(frozen=True)
class WizardRoute:
    path: str
    label: str
    title: str
    placeholder: str


WIZARD_ROUTES: tuple[WizardRoute, ...] = (
    WizardRoute(
        path="/intake",
        label="Intake",
        title="Intake",
        placeholder="Placeholder for the designer intake step.",
    ),
    WizardRoute(
        path="/research",
        label="Research",
        title="Research",
        placeholder="Placeholder for curated research review.",
    ),
    WizardRoute(
        path="/synthesis",
        label="Synthesis",
        title="Synthesis",
        placeholder="Placeholder for synthesis brief review.",
    ),
    WizardRoute(
        path="/ticket",
        label="Ticket",
        title="Ticket",
        placeholder="Placeholder for Symphony ticket drafting.",
    ),
    WizardRoute(
        path="/export",
        label="Export",
        title="Export",
        placeholder="Placeholder for local export confirmation.",
    ),
)
ROUTES_BY_PATH: Mapping[str, WizardRoute] = {route.path: route for route in WIZARD_ROUTES}


class SessionStore:
    """In-memory server-side session state keyed by an opaque cookie id."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, object]] = {}

    def get_or_create(self, session_id: str | None) -> tuple[str, dict[str, object], bool]:
        if session_id and session_id in self._sessions:
            return session_id, self._sessions[session_id], False

        new_session_id = secrets.token_urlsafe(24)
        session = {"visits": 0}
        self._sessions[new_session_id] = session
        return new_session_id, session, True


class LoopbackOnlyHTTPServer(HTTPServer):
    """HTTP server that accepts only loopback clients."""

    def verify_request(self, request: object, client_address: tuple[str, int]) -> bool:
        try:
            return ip_address(client_address[0]).is_loopback
        except ValueError:
            return False


class OvertureUIRequestHandler(BaseHTTPRequestHandler):
    server_version = "OvertureUI/0.1"

    def do_GET(self) -> None:
        requested_path = urlparse(self.path).path
        if requested_path == "/":
            self._redirect("/intake")
            return

        path = requested_path.rstrip("/")
        route = ROUTES_BY_PATH.get(path)
        if route is None:
            self._send_html(HTTPStatus.NOT_FOUND, render_not_found(path))
            return

        session_id, session, is_new = self.server.session_store.get_or_create(  # type: ignore[attr-defined]
            self._session_cookie()
        )
        session["visits"] = int(session["visits"]) + 1
        body = render_page(route, session_id=session_id, visit_count=int(session["visits"]))
        self._send_html(
            HTTPStatus.OK,
            body,
            headers={"Set-Cookie": _session_cookie_header(session_id)} if is_new else None,
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def _send_html(
        self,
        status: HTTPStatus,
        body: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _session_cookie(self) -> str | None:
        cookie_header = self.headers.get("Cookie", "")
        for segment in cookie_header.split(";"):
            name, _, value = segment.strip().partition("=")
            if name == SESSION_COOKIE_NAME and value:
                return value
        return None


def build_ui_server(host: str = DEFAULT_UI_HOST, port: int = DEFAULT_UI_PORT) -> LoopbackOnlyHTTPServer:
    _ensure_loopback_bind_host(host)
    server = LoopbackOnlyHTTPServer((host, port), OvertureUIRequestHandler)
    server.session_store = SessionStore()  # type: ignore[attr-defined]
    return server


def serve_ui_host(host: str = DEFAULT_UI_HOST, port: int = DEFAULT_UI_PORT) -> None:
    server = build_ui_server(host, port)
    bound_host, bound_port = server.server_address[:2]
    print(f"Overture UI host listening on http://localhost:{bound_port}/intake")
    print(f"Bound to loopback address {bound_host}; press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def render_page(route: WizardRoute, *, session_id: str, visit_count: int) -> str:
    breadcrumbs = " / ".join(
        f'<a href="{html.escape(candidate.path)}">{html.escape(candidate.label)}</a>'
        if candidate.path != route.path
        else f"<span>{html.escape(candidate.label)}</span>"
        for candidate in WIZARD_ROUTES
    )
    nav = "\n".join(
        f'<a href="{html.escape(candidate.path)}"{_aria_current(candidate, route)}>'
        f"{html.escape(candidate.label)}</a>"
        for candidate in WIZARD_ROUTES
    )
    content = (
        f"<h2>{html.escape(route.title)}</h2>"
        f"<p>{html.escape(route.placeholder)}</p>"
        f'<p class="session">Session <code>{html.escape(session_id)}</code> '
        f"has rendered {visit_count} page view(s).</p>"
    )
    return render_layout(title=route.title, breadcrumbs=breadcrumbs, nav=nav, content=content)


def render_not_found(path: str) -> str:
    return render_layout(
        title="Not Found",
        breadcrumbs="<span>Not Found</span>",
        nav="\n".join(f'<a href="{html.escape(route.path)}">{html.escape(route.label)}</a>' for route in WIZARD_ROUTES),
        content=f"<h2>Not Found</h2><p>No wizard route exists for {html.escape(path)}.</p>",
    )


def render_layout(*, title: str, breadcrumbs: str, nav: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Overture - {html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f7f7f4; color: #1d2528; }}
    header {{ background: #173f4f; color: white; padding: 18px 32px; }}
    header h1 {{ font-size: 22px; margin: 0 0 12px; letter-spacing: 0; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    nav a {{ color: white; border: 1px solid rgba(255,255,255,.38); border-radius: 6px; padding: 7px 10px; text-decoration: none; }}
    nav a[aria-current="page"] {{ background: white; color: #173f4f; }}
    main {{ max-width: 900px; padding: 28px 32px 48px; }}
    .breadcrumbs {{ color: #526064; font-size: 14px; margin-bottom: 22px; }}
    .breadcrumbs a {{ color: #2b6577; }}
    h2 {{ font-size: 28px; margin: 0 0 12px; letter-spacing: 0; }}
    p {{ line-height: 1.55; max-width: 70ch; }}
    code {{ background: #ece8df; border-radius: 4px; padding: 2px 5px; }}
  </style>
</head>
<body>
  <header>
    <h1>Overture Wizard</h1>
    <nav aria-label="Wizard steps">
      {nav}
    </nav>
  </header>
  <main>
    <div class="breadcrumbs" aria-label="Breadcrumbs">{breadcrumbs}</div>
    <section>
      {content}
    </section>
  </main>
</body>
</html>
"""


def _aria_current(candidate: WizardRoute, route: WizardRoute) -> str:
    return ' aria-current="page"' if candidate.path == route.path else ""


def _session_cookie_header(session_id: str) -> str:
    return f"{SESSION_COOKIE_NAME}={session_id}; Path=/; HttpOnly; SameSite=Lax"


def _ensure_loopback_bind_host(host: str) -> None:
    if host == "localhost":
        return
    try:
        if ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError(f"UI host must bind to localhost or a loopback address, got {host!r}")
