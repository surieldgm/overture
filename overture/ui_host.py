"""Local-only UI host for the Overture wizard."""

from __future__ import annotations

from dataclasses import dataclass
from http import cookies
import html
from ipaddress import ip_address
import json
from pathlib import Path
import secrets
from typing import Callable, Iterable, Mapping
from urllib.parse import parse_qs
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from .intake import IntakeRecord, create_intake_record, load_intake_record
from .research import ResearchResult
from .research_llm import LLMSuggestedSourceAdapter, fake_llm_client, write_research_result

INTAKE_TEXT_MAX_CHARS = 5000
DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 8765
SESSION_COOKIE_NAME = "overture_session"
DEFAULT_STORE_DIR = Path(".overture")
EXAMPLES_LIBRARY_PATH = Path("examples") / "intake_examples"
RESEARCH_APPROVAL_ROUTE = "/research/approval"

StartResponse = Callable[[str, list[tuple[str, str]]], None]


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
        placeholder="Capture the designer idea before research starts.",
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


@dataclass(frozen=True)
class IntakeSubmissionResult:
    record: IntakeRecord
    session: dict[str, str]


@dataclass(frozen=True)
class ResearchApprovalResult:
    result: ResearchResult
    session: dict[str, str]
    path: Path


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


class LoopbackOnlyWSGIServer(WSGIServer):
    """WSGI server that accepts only loopback clients."""

    def verify_request(self, request: object, client_address: tuple[str, int]) -> bool:
        try:
            return ip_address(client_address[0]).is_loopback
        except ValueError:
            return False


class QuietRequestHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class OvertureUiApp:
    def __init__(
        self,
        store_dir: Path | str = DEFAULT_STORE_DIR,
        *,
        llm_client: Callable[[str], str] = fake_llm_client,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.session_store = SessionStore()
        self.llm_client = llm_client

    def __call__(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        if path in {"", "/"}:
            return self._redirect(start_response, "/intake", status="302 Found")
        if path == "/intake" and method == "GET":
            session_id, server_session, is_new = self._server_session(environ)
            body = render_intake_page(
                session_from_environ(environ),
                session_id=session_id,
                visit_count=_record_visit(server_session),
            )
            return self._render(
                start_response,
                body,
                extra_headers=[("Set-Cookie", _opaque_session_cookie(session_id))] if is_new else None,
            )
        if path == "/intake" and method == "POST":
            return self._handle_intake_post(environ, start_response)
        if path == RESEARCH_APPROVAL_ROUTE and method == "GET":
            return self._render(
                start_response,
                render_research_approval_page(session_from_environ(environ)),
            )
        if path == RESEARCH_APPROVAL_ROUTE and method == "POST":
            return self._handle_research_approval_post(environ, start_response)
        if path == "/examples/intake_examples" and method == "GET":
            return self._render(start_response, render_examples_library())
        if path in ROUTES_BY_PATH and method == "GET":
            session_id, server_session, is_new = self._server_session(environ)
            body = render_placeholder_page(
                ROUTES_BY_PATH[path],
                session_id=session_id,
                visit_count=_record_visit(server_session),
            )
            return self._render(
                start_response,
                body,
                extra_headers=[("Set-Cookie", _opaque_session_cookie(session_id))] if is_new else None,
            )

        return self._render(start_response, render_not_found(path), status="404 Not Found")

    def _handle_intake_post(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        fields = _form_fields(environ)
        raw_text = fields.get("idea", [""])[0]
        session = session_from_environ(environ)
        error = validate_intake_text(raw_text)
        if error:
            return self._render(
                start_response,
                render_intake_page(session, raw_text=raw_text, error=error),
                status="400 Bad Request",
            )

        result = submit_intake(raw_text, self.store_dir, session)
        return self._redirect(
            start_response,
            RESEARCH_APPROVAL_ROUTE,
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _handle_research_approval_post(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> Iterable[bytes]:
        session = session_from_environ(environ)
        intake_id = session.get("intake_id")
        if not intake_id:
            return self._render(
                start_response,
                render_research_approval_page(session, error="Submit an intake before approving research."),
                status="400 Bad Request",
            )

        try:
            result = approve_research(intake_id, self.store_dir, session, llm_client=self.llm_client)
        except FileNotFoundError:
            return self._render(
                start_response,
                render_research_approval_page(session, error="The intake record for this session was not found."),
                status="404 Not Found",
            )

        if not result.result.ok:
            return self._render(
                start_response,
                render_research_approval_page(session, error="Research approval did not produce usable sources."),
                status="500 Internal Server Error",
            )

        return self._redirect(
            start_response,
            "/synthesis",
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _render(
        self,
        start_response: StartResponse,
        body: str,
        *,
        status: str = "200 OK",
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> list[bytes]:
        payload = body.encode("utf-8")
        headers = [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(payload))),
            ("Cache-Control", "no-store"),
        ]
        if extra_headers:
            headers.extend(extra_headers)
        start_response(status, headers)
        return [payload]

    def _redirect(
        self,
        start_response: StartResponse,
        location: str,
        *,
        status: str = "303 See Other",
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> list[bytes]:
        headers = [("Location", location), ("Content-Length", "0")]
        if extra_headers:
            headers.extend(extra_headers)
        start_response(status, headers)
        return [b""]

    def _server_session(self, environ: dict[str, object]) -> tuple[str, dict[str, object], bool]:
        return self.session_store.get_or_create(_opaque_session_id_from_environ(environ))


def build_ui_server(
    host: str = DEFAULT_UI_HOST,
    port: int = DEFAULT_UI_PORT,
    *,
    store_dir: Path | str = DEFAULT_STORE_DIR,
    llm_client: Callable[[str], str] = fake_llm_client,
) -> LoopbackOnlyWSGIServer:
    _ensure_loopback_bind_host(host)
    app = OvertureUiApp(store_dir=store_dir, llm_client=llm_client)
    return make_server(
        host,
        port,
        app,
        server_class=LoopbackOnlyWSGIServer,
        handler_class=QuietRequestHandler,
    )


def serve_ui_host(host: str = DEFAULT_UI_HOST, port: int = DEFAULT_UI_PORT, store_dir: Path | str = DEFAULT_STORE_DIR) -> None:
    server = build_ui_server(host=host, port=port, store_dir=store_dir)
    bound_host, bound_port = server.server_address[:2]
    print(f"Overture UI host listening on http://localhost:{bound_port}/intake")
    print(f"Bound to loopback address {bound_host}; press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def submit_intake(raw_text: str, store_dir: Path | str, session: dict[str, str] | None = None) -> IntakeSubmissionResult:
    record, _path = create_intake_record(
        raw_text,
        Path(store_dir) / "intake",
        source_type="ui",
    )
    next_session = dict(session or {})
    next_session["intake_id"] = record.id
    return IntakeSubmissionResult(record=record, session=next_session)


def approve_research(
    intake_id: str,
    store_dir: Path | str,
    session: dict[str, str] | None = None,
    *,
    llm_client: Callable[[str], str] = fake_llm_client,
) -> ResearchApprovalResult:
    base_dir = Path(store_dir)
    intake_path = base_dir / "intake" / f"{intake_id}.json"
    intake = load_intake_record(intake_path)
    adapter = LLMSuggestedSourceAdapter(llm_client=llm_client, approver=lambda source: True)
    research = adapter.research(intake)
    research_path = write_research_result(base_dir / "research" / f"{intake.id}.json", research)

    next_session = dict(session or {})
    next_session["intake_id"] = intake.id
    next_session["research_id"] = intake.id
    next_session["next_route"] = "/synthesis"
    return ResearchApprovalResult(result=research, session=next_session, path=research_path)


def validate_intake_text(raw_text: str) -> str | None:
    if not raw_text.strip():
        return "Enter an idea before continuing."
    if len(raw_text) > INTAKE_TEXT_MAX_CHARS:
        return f"Idea text must be {INTAKE_TEXT_MAX_CHARS:,} characters or fewer."
    return None


def session_from_environ(environ: dict[str, object]) -> dict[str, str]:
    header = str(environ.get("HTTP_COOKIE", ""))
    if not header:
        return {}
    jar = cookies.SimpleCookie()
    jar.load(header)
    morsel = jar.get(SESSION_COOKIE_NAME)
    if morsel is None:
        return {}
    try:
        payload = json.loads(morsel.value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def render_intake_page(
    session: dict[str, str],
    *,
    raw_text: str = "",
    error: str | None = None,
    session_id: str | None = None,
    visit_count: int | None = None,
) -> str:
    value = html.escape(raw_text)
    escaped_error = html.escape(error) if error else ""
    error_markup = f'<p class="validation" role="alert">{escaped_error}</p>' if error else ""
    intake_id = session.get("intake_id")
    session_markup = (
        f'<p class="session-note">Current intake: <code>{html.escape(intake_id)}</code></p>'
        if intake_id
        else ""
    )
    server_session_markup = _server_session_markup(session_id, visit_count)
    return render_layout(
        title="Intake",
        active_path="/intake",
        content=f"""
        <section class="workspace">
          <h2>Intake</h2>
          <p>{html.escape(ROUTES_BY_PATH["/intake"].placeholder)}</p>
          <form method="post" action="/intake" novalidate>
            <label for="idea">Raw idea</label>
            <textarea id="idea" name="idea" maxlength="{INTAKE_TEXT_MAX_CHARS}" autofocus>{value}</textarea>
            <div class="form-footer">
              <span>{len(raw_text)} / {INTAKE_TEXT_MAX_CHARS:,}</span>
              <button type="submit">Start research approval</button>
            </div>
            {error_markup}
            {session_markup}
            {server_session_markup}
          </form>
        </section>
        <aside class="side-panel" aria-label="Curated examples">
          <h3>Examples</h3>
          <p>Review prior intakes before starting from a blank page.</p>
          <a href="/examples/intake_examples/">Open curated examples</a>
        </aside>
        """,
        shell_class="shell",
    )


def render_research_approval_page(session: dict[str, str], *, error: str | None = None) -> str:
    intake_id = session.get("intake_id")
    if intake_id:
        message = f"Intake ready: <code>{html.escape(intake_id)}</code>"
    else:
        message = 'No intake is stored in this session. <a href="/intake">Return to intake</a>.'
    error_markup = f'<p class="validation" role="alert">{html.escape(error)}</p>' if error else ""
    disabled = "" if intake_id else " disabled"
    return render_layout(
        title="Research approval",
        active_path="/research",
        content=f"""
        <section class="workspace">
          <h2>Research approval</h2>
          <p>{message}</p>
          <form method="post" action="{RESEARCH_APPROVAL_ROUTE}">
            <button type="submit"{disabled}>Approve research and continue</button>
          </form>
          {error_markup}
        </section>
        """,
    )


def render_placeholder_page(route: WizardRoute, *, session_id: str, visit_count: int) -> str:
    return render_layout(
        title=route.title,
        active_path=route.path,
        content=f"""
        <section class="workspace">
          <h2>{html.escape(route.title)}</h2>
          <p>{html.escape(route.placeholder)}</p>
          {_server_session_markup(session_id, visit_count)}
        </section>
        """,
    )


def render_examples_library() -> str:
    links = []
    if EXAMPLES_LIBRARY_PATH.exists():
        for path in sorted(EXAMPLES_LIBRARY_PATH.glob("*.md")):
            title = path.stem.replace("-", " ").title()
            links.append(f"<li>{html.escape(title)}</li>")
    if not links:
        links.append("<li>No curated examples are available.</li>")
    return render_layout(
        title="Curated examples",
        active_path="/intake",
        content=f"""
        <section class="workspace">
          <h2>Curated examples</h2>
          <ul>{''.join(links)}</ul>
          <p><a href="/intake">Back to intake</a></p>
        </section>
        """,
    )


def render_not_found(path: str) -> str:
    return render_layout(
        title="Not found",
        active_path=None,
        content=f"""
        <section class="workspace">
          <h2>Not found</h2>
          <p>No wizard route exists for {html.escape(path)}.</p>
          <p><a href="/intake">Go to intake</a></p>
        </section>
        """,
    )


def render_layout(*, title: str, active_path: str | None, content: str, shell_class: str = "shell single") -> str:
    nav = "\n".join(
        f'<a href="{html.escape(route.path)}"{_aria_current(route.path, active_path)}>{html.escape(route.label)}</a>'
        for route in WIZARD_ROUTES
    )
    breadcrumbs = " / ".join(
        f"<span>{html.escape(route.label)}</span>"
        if route.path == active_path
        else f'<a href="{html.escape(route.path)}">{html.escape(route.label)}</a>'
        for route in WIZARD_ROUTES
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} - Overture</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1f2933;
      --muted: #52606d;
      --line: #d9e2ec;
      --surface: #ffffff;
      --panel: #f5f7fa;
      --accent: #0f766e;
      --danger: #b42318;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--panel); color: var(--ink); line-height: 1.5; }}
    header {{ background: #173f4f; color: white; padding: 18px 32px; }}
    header h1 {{ font-size: 22px; margin: 0 0 12px; letter-spacing: 0; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    nav a {{ color: white; border: 1px solid rgba(255,255,255,.38); border-radius: 6px; padding: 7px 10px; text-decoration: none; }}
    nav a[aria-current="page"] {{ background: white; color: #173f4f; }}
    .breadcrumbs {{ color: var(--muted); font-size: 14px; margin: 24px auto 0; max-width: 1040px; padding: 0 24px; }}
    .breadcrumbs a {{ color: #2b6577; }}
    .shell {{ display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 24px; max-width: 1040px; margin: 0 auto; padding: 24px; align-items: start; }}
    .shell.single {{ grid-template-columns: minmax(0, 1fr); }}
    .workspace {{ background: var(--surface); padding: 24px; }}
    .side-panel {{ border-left: 1px solid var(--line); padding: 24px; }}
    h2, h3 {{ margin: 0 0 16px; line-height: 1.2; letter-spacing: 0; }}
    h2 {{ font-size: 28px; }}
    h3 {{ font-size: 18px; }}
    label {{ display: block; font-weight: 650; margin-bottom: 8px; }}
    textarea {{ width: 100%; min-height: 280px; resize: vertical; border: 1px solid var(--line); border-radius: 6px; padding: 12px; color: var(--ink); font: inherit; background: #fff; }}
    textarea:focus {{ outline: 3px solid #99f6e4; border-color: var(--accent); }}
    .form-footer {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-top: 12px; color: var(--muted); font-size: 14px; }}
    button, a {{ color: var(--accent); font-weight: 650; }}
    button {{ border: 0; border-radius: 6px; background: var(--accent); color: white; padding: 10px 14px; cursor: pointer; font: inherit; }}
    .validation {{ color: var(--danger); margin: 12px 0 0; font-weight: 650; }}
    .session, .session-note {{ color: var(--muted); margin-bottom: 0; }}
    code {{ background: #edf2f7; padding: 2px 4px; border-radius: 4px; }}
    @media (max-width: 760px) {{
      .shell {{ grid-template-columns: minmax(0, 1fr); padding: 20px 12px; }}
      .breadcrumbs {{ padding: 0 12px; }}
      .form-footer {{ align-items: stretch; flex-direction: column; }}
      button {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Overture Wizard</h1>
    <nav aria-label="Wizard steps">
      {nav}
    </nav>
  </header>
  <div class="breadcrumbs" aria-label="Breadcrumbs">{breadcrumbs}</div>
  <main class="{html.escape(shell_class)}">
    <section>
    {content}
    </section>
  </main>
</body>
</html>
"""


def _form_fields(environ: dict[str, object]) -> dict[str, list[str]]:
    try:
        length = int(str(environ.get("CONTENT_LENGTH") or "0"))
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(length).decode("utf-8") if length else ""
    return parse_qs(body, keep_blank_values=True)


def _session_cookie(session: dict[str, str]) -> str:
    jar = cookies.SimpleCookie()
    jar[SESSION_COOKIE_NAME] = json.dumps(session, sort_keys=True, separators=(",", ":"))
    jar[SESSION_COOKIE_NAME]["path"] = "/"
    jar[SESSION_COOKIE_NAME]["httponly"] = True
    jar[SESSION_COOKIE_NAME]["samesite"] = "Lax"
    return jar.output(header="").strip()


def _opaque_session_cookie(session_id: str) -> str:
    return f"{SESSION_COOKIE_NAME}={session_id}; Path=/; HttpOnly; SameSite=Lax"


def _opaque_session_id_from_environ(environ: dict[str, object]) -> str | None:
    header = str(environ.get("HTTP_COOKIE", ""))
    if not header:
        return None
    jar = cookies.SimpleCookie()
    jar.load(header)
    morsel = jar.get(SESSION_COOKIE_NAME)
    if morsel is None:
        return None
    value = morsel.value
    if value.startswith("{"):
        return None
    return value


def _record_visit(session: dict[str, object]) -> int:
    visit_count = int(session.get("visits", 0)) + 1
    session["visits"] = visit_count
    return visit_count


def _server_session_markup(session_id: str | None, visit_count: int | None) -> str:
    if session_id is None or visit_count is None:
        return ""
    return (
        f'<p class="session">Session <code>{html.escape(session_id)}</code> '
        f"has rendered {visit_count} page view(s).</p>"
    )


def _aria_current(candidate_path: str, active_path: str | None) -> str:
    return ' aria-current="page"' if candidate_path == active_path else ""


def _ensure_loopback_bind_host(host: str) -> None:
    if host == "localhost":
        return
    try:
        if ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError(f"UI host must bind to localhost or a loopback address, got {host!r}")
