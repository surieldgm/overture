"""Small WSGI host for the Overture wizard."""

from __future__ import annotations

from dataclasses import dataclass
from http import cookies
import html
import json
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qs

from .intake import IntakeRecord, create_intake_record

INTAKE_TEXT_MAX_CHARS = 5000
SESSION_COOKIE_NAME = "overture_session"
DEFAULT_STORE_DIR = Path(".overture")
EXAMPLES_LIBRARY_PATH = Path("examples") / "intake_examples"
RESEARCH_APPROVAL_ROUTE = "/research/approval"

StartResponse = Callable[[str, list[tuple[str, str]]], None]


@dataclass(frozen=True)
class IntakeSubmissionResult:
    record: IntakeRecord
    session: dict[str, str]


class OvertureUiApp:
    def __init__(self, store_dir: Path | str = DEFAULT_STORE_DIR) -> None:
        self.store_dir = Path(store_dir)

    def __call__(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))

        if path in {"", "/"}:
            return self._redirect(start_response, "/intake")
        if path == "/intake" and method == "GET":
            return self._render(
                start_response,
                render_intake_page(session_from_environ(environ)),
            )
        if path == "/intake" and method == "POST":
            return self._handle_intake_post(environ, start_response)
        if path == RESEARCH_APPROVAL_ROUTE and method == "GET":
            return self._render(
                start_response,
                render_research_approval_page(session_from_environ(environ)),
            )
        if path == "/examples/intake_examples/" and method == "GET":
            return self._render(start_response, render_examples_library())

        return self._render(start_response, render_not_found(), status="404 Not Found")

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
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> list[bytes]:
        headers = [("Location", location), ("Content-Length", "0")]
        if extra_headers:
            headers.extend(extra_headers)
        start_response("303 See Other", headers)
        return [b""]


def submit_intake(raw_text: str, store_dir: Path | str, session: dict[str, str] | None = None) -> IntakeSubmissionResult:
    record, _path = create_intake_record(
        raw_text,
        Path(store_dir) / "intake",
        source_type="ui",
    )
    next_session = dict(session or {})
    next_session["intake_id"] = record.id
    return IntakeSubmissionResult(record=record, session=next_session)


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
    return _page(
        "Intake",
        f"""
        <main class="shell">
          <section class="workspace">
            <h1>Intake</h1>
            <form method="post" action="/intake" novalidate>
              <label for="idea">Raw idea</label>
              <textarea id="idea" name="idea" maxlength="{INTAKE_TEXT_MAX_CHARS}" autofocus>{value}</textarea>
              <div class="form-footer">
                <span>{len(raw_text)} / {INTAKE_TEXT_MAX_CHARS:,}</span>
                <button type="submit">Start research approval</button>
              </div>
              {error_markup}
              {session_markup}
            </form>
          </section>
          <aside class="side-panel" aria-label="Curated examples">
            <h2>Examples</h2>
            <p>Review prior intakes before starting from a blank page.</p>
            <a href="/examples/intake_examples/">Open curated examples</a>
          </aside>
        </main>
        """,
    )


def render_research_approval_page(session: dict[str, str]) -> str:
    intake_id = session.get("intake_id")
    if intake_id:
        message = f"Intake ready: <code>{html.escape(intake_id)}</code>"
    else:
        message = 'No intake is stored in this session. <a href="/intake">Return to intake</a>.'
    return _page(
        "Research approval",
        f"""
        <main class="shell single">
          <section class="workspace">
            <h1>Research approval</h1>
            <p>{message}</p>
          </section>
        </main>
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
    return _page(
        "Curated examples",
        f"""
        <main class="shell single">
          <section class="workspace">
            <h1>Curated examples</h1>
            <ul>{''.join(links)}</ul>
            <p><a href="/intake">Back to intake</a></p>
          </section>
        </main>
        """,
    )


def render_not_found() -> str:
    return _page(
        "Not found",
        """
        <main class="shell single">
          <section class="workspace">
            <h1>Not found</h1>
            <p><a href="/intake">Go to intake</a></p>
          </section>
        </main>
        """,
    )


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


def _page(title: str, body: str) -> str:
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
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--panel);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    .shell {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 280px;
      gap: 24px;
      max-width: 1040px;
      min-height: 100vh;
      margin: 0 auto;
      padding: 40px 24px;
      align-items: start;
    }}
    .shell.single {{ grid-template-columns: minmax(0, 1fr); }}
    .workspace {{
      background: var(--surface);
      padding: 24px;
    }}
    .side-panel {{
      border-left: 1px solid var(--line);
      padding: 24px;
    }}
    h1, h2 {{ margin: 0 0 16px; line-height: 1.2; }}
    h1 {{ font-size: 32px; }}
    h2 {{ font-size: 18px; }}
    label {{ display: block; font-weight: 650; margin-bottom: 8px; }}
    textarea {{
      width: 100%;
      min-height: 280px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      color: var(--ink);
      font: inherit;
      background: #fff;
    }}
    textarea:focus {{
      outline: 3px solid #99f6e4;
      border-color: var(--accent);
    }}
    .form-footer {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 14px;
    }}
    button, a {{
      color: var(--accent);
      font-weight: 650;
    }}
    button {{
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      padding: 10px 14px;
      cursor: pointer;
      font: inherit;
    }}
    .validation {{ color: var(--danger); margin: 12px 0 0; font-weight: 650; }}
    .session-note {{ color: var(--muted); margin-bottom: 0; }}
    code {{ background: #edf2f7; padding: 2px 4px; border-radius: 4px; }}
    @media (max-width: 760px) {{
      .shell {{ grid-template-columns: minmax(0, 1fr); padding: 20px 12px; }}
      .form-footer {{ align-items: stretch; flex-direction: column; }}
      button {{ width: 100%; }}
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""
