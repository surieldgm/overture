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
from .research import CuratedSource, _normalize_source
from .research_llm import (
    LLMSuggestedSourceAdapter,
    fake_llm_client,
    research_result_to_jsonable,
    write_research_result,
)

INTAKE_TEXT_MAX_CHARS = 5000
DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 8765
SESSION_COOKIE_NAME = "overture_session"
DEFAULT_STORE_DIR = Path(".overture")
EXAMPLES_LIBRARY_PATH = Path("examples") / "intake_examples"
RESEARCH_APPROVAL_ROUTE = "/research/approval"
RESEARCH_COMPLETE_ROUTE = "/research/complete"
SESSION_CANDIDATES_KEY = "research_candidates"
SESSION_APPROVALS_KEY = "research_approvals"

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
class ResearchReviewResult:
    session: dict[str, str]
    candidates: tuple[CuratedSource, ...] = ()
    error: str | None = None


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
            return self._handle_research_get(environ, start_response)
        if path == RESEARCH_APPROVAL_ROUTE and method == "POST":
            return self._handle_research_post(environ, start_response)
        if path == RESEARCH_COMPLETE_ROUTE and method == "GET":
            return self._render(start_response, render_research_complete_page(session_from_environ(environ)))
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

    def _handle_research_get(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        result = prepare_research_review(session_from_environ(environ), self.store_dir, self.llm_client)
        return self._render(
            start_response,
            render_research_approval_page(result.session, candidates=result.candidates, error=result.error),
            status="400 Bad Request" if result.error and not result.candidates else "200 OK",
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _handle_research_post(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        fields = _form_fields(environ)
        approved_keys = [
            value[len("approve:") :]
            for values in fields.values()
            for value in values
            if value.startswith("approve:")
        ]
        result = submit_research_approvals(
            session=session_from_environ(environ),
            store_dir=self.store_dir,
            approved_keys=approved_keys,
        )
        if result.error:
            return self._render(
                start_response,
                render_research_approval_page(result.session, candidates=result.candidates, error=result.error),
                status="400 Bad Request",
                extra_headers=[("Set-Cookie", _session_cookie(result.session))],
            )
        return self._redirect(
            start_response,
            RESEARCH_COMPLETE_ROUTE,
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


def serve_ui_host(
    host: str = DEFAULT_UI_HOST,
    port: int = DEFAULT_UI_PORT,
    store_dir: Path | str = DEFAULT_STORE_DIR,
    *,
    llm_client: Callable[[str], str] = fake_llm_client,
) -> None:
    server = build_ui_server(host=host, port=port, store_dir=store_dir, llm_client=llm_client)
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


def prepare_research_review(
    session: dict[str, str],
    store_dir: Path | str,
    llm_client: Callable[[str], str] = fake_llm_client,
) -> ResearchReviewResult:
    intake_id = session.get("intake_id", "")
    if not intake_id:
        return ResearchReviewResult(
            session=dict(session),
            error="No intake is stored in this session. Return to intake before approving research sources.",
        )

    next_session = dict(session)
    candidates = _session_candidates(next_session, intake_id)
    if not candidates:
        try:
            intake = load_intake_record(Path(store_dir) / "intake" / f"{intake_id}.json")
        except FileNotFoundError:
            return ResearchReviewResult(next_session, error=f"Intake record not found for {intake_id}.")
        probe = LLMSuggestedSourceAdapter(llm_client=llm_client, approver=lambda _source: True)
        result = probe.research(intake)
        candidates = tuple(
            CuratedSource(
                title=item.source.title,
                url=item.source.url,
                citation=item.source.citation,
                summary=item.summary,
                evidence_claims=tuple(claim.text for claim in item.claims if claim.kind == "evidence"),
                inference_claims=tuple(claim.text for claim in item.claims if claim.kind == "inference"),
            )
            for item in result.items
        )
        next_session = _store_session_candidates(next_session, intake_id, candidates)
        next_session = _store_session_approvals(next_session, intake_id, {_source_key(source) for source in candidates})
        if result.errors and not candidates:
            return ResearchReviewResult(next_session, candidates, result.errors[0].message)

    return ResearchReviewResult(next_session, candidates)


def submit_research_approvals(
    *,
    session: dict[str, str],
    store_dir: Path | str,
    approved_keys: Iterable[str],
) -> ResearchReviewResult:
    intake_id = session.get("intake_id", "")
    candidates = _session_candidates(session, intake_id) if intake_id else ()
    selected = {str(key) for key in approved_keys}
    next_session = _store_session_approvals(dict(session), intake_id, selected) if intake_id else dict(session)

    if not intake_id:
        return ResearchReviewResult(next_session, candidates, "No intake is stored in this session.")
    if not candidates:
        return ResearchReviewResult(next_session, candidates, "No suggested sources are available for this intake.")
    if not selected:
        return ResearchReviewResult(next_session, candidates, "Approve at least one source before continuing.")

    try:
        intake = load_intake_record(Path(store_dir) / "intake" / f"{intake_id}.json")
    except FileNotFoundError:
        return ResearchReviewResult(next_session, candidates, f"Intake record not found for {intake_id}.")

    candidate_payload = json.dumps([_source_to_jsonable(source) for source in candidates])
    adapter = LLMSuggestedSourceAdapter(
        llm_client=lambda _prompt: candidate_payload,
        approver=lambda source: _source_key(source) in selected,
    )
    result = adapter.research(intake)
    if not result.items:
        message = result.errors[0].message if result.errors else "Approve at least one source before continuing."
        return ResearchReviewResult(next_session, candidates, message)

    write_research_result(Path(store_dir) / "research" / f"{intake.id}.json", result)
    next_session["research_result"] = json.dumps(research_result_to_jsonable(result), sort_keys=True, separators=(",", ":"))
    next_session["research_id"] = intake.id
    next_session["next_route"] = "/synthesis"
    return ResearchReviewResult(next_session, candidates)


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


def _session_candidates(session: Mapping[str, str], intake_id: str) -> tuple[CuratedSource, ...]:
    snapshots = _session_json_map(session.get(SESSION_CANDIDATES_KEY))
    payload = snapshots.get(intake_id)
    if not isinstance(payload, list):
        return ()
    sources = []
    for item in payload:
        if isinstance(item, Mapping):
            source = _normalize_source(item)
            if source is not None:
                sources.append(source)
    return tuple(sources)


def _session_approval_keys(session: Mapping[str, str], intake_id: str) -> set[str]:
    approvals = _session_json_map(session.get(SESSION_APPROVALS_KEY))
    payload = approvals.get(intake_id)
    if not isinstance(payload, list):
        return set()
    return {str(item) for item in payload}


def _store_session_candidates(
    session: dict[str, str],
    intake_id: str,
    candidates: Iterable[CuratedSource],
) -> dict[str, str]:
    snapshots = _session_json_map(session.get(SESSION_CANDIDATES_KEY))
    snapshots[intake_id] = [_source_to_jsonable(source) for source in candidates]
    session[SESSION_CANDIDATES_KEY] = json.dumps(snapshots, sort_keys=True, separators=(",", ":"))
    return session


def _store_session_approvals(session: dict[str, str], intake_id: str, approved_keys: Iterable[str]) -> dict[str, str]:
    approvals = _session_json_map(session.get(SESSION_APPROVALS_KEY))
    approvals[intake_id] = sorted({str(key) for key in approved_keys})
    session[SESSION_APPROVALS_KEY] = json.dumps(approvals, sort_keys=True, separators=(",", ":"))
    return session


def _session_json_map(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): item for key, item in payload.items()}


def _source_to_jsonable(source: CuratedSource) -> dict[str, object]:
    return {
        "title": source.title,
        "url": source.url,
        "citation": source.citation,
        "summary": source.summary,
        "evidence_claims": list(source.evidence_claims),
        "inference_claims": list(source.inference_claims),
    }


def _source_key(source: CuratedSource) -> str:
    return source.url or source.citation or source.title


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


def render_research_approval_page(
    session: dict[str, str],
    *,
    candidates: Iterable[CuratedSource] = (),
    error: str | None = None,
) -> str:
    intake_id = session.get("intake_id")
    source_items = []
    approved = _session_approval_keys(session, intake_id or "")
    for index, source in enumerate(candidates):
        key = _source_key(source)
        approved_checked = " checked" if key in approved else ""
        rejected_checked = "" if key in approved else " checked"
        reference = source.url or source.citation or "No reference provided"
        source_items.append(
            f"""
            <li class="source-option">
              <div>
                <h3>{html.escape(source.title)}</h3>
                <p>{html.escape(source.summary)}</p>
                <p class="source-ref">{html.escape(reference)}</p>
              </div>
              <fieldset>
                <legend>Decision</legend>
                <label><input type="radio" name="decision-{index}" value="approve:{html.escape(key)}"{approved_checked}> Approve</label>
                <label><input type="radio" name="decision-{index}" value="reject:{html.escape(key)}"{rejected_checked}> Reject</label>
              </fieldset>
            </li>
            """
        )
    if source_items:
        source_markup = f"<ul class=\"source-list\">{''.join(source_items)}</ul>"
        footer = '<div class="form-footer"><span>Rejected sources stay out of the research result.</span><button type="submit">Save approved sources</button></div>'
    else:
        source_markup = '<p class="empty-state">No suggested sources are available yet.</p>'
        footer = ""
    error_markup = f'<p class="validation" role="alert">{html.escape(error)}</p>' if error else ""
    if intake_id:
        message = f"Current intake: <code>{html.escape(intake_id)}</code>"
    else:
        message = 'No intake is stored in this session. <a href="/intake">Return to intake</a>.'
    return render_layout(
        title="Research approval",
        active_path="/research",
        content=f"""
        <section class="workspace">
          <h2>Research approval</h2>
          <p>{message}</p>
          {error_markup}
          <form method="post" action="{RESEARCH_APPROVAL_ROUTE}" novalidate>
            {source_markup}
            {footer}
          </form>
        </section>
        """,
    )


def render_research_complete_page(session: dict[str, str]) -> str:
    intake_id = session.get("intake_id", "")
    result = _session_json_map(session.get("research_result"))
    item_count = len(result.get("items", [])) if isinstance(result.get("items"), list) else 0
    return render_layout(
        title="Research saved",
        active_path="/research",
        content=f"""
        <section class="workspace">
          <h2>Research saved</h2>
          <p>Saved {item_count} approved source{"s" if item_count != 1 else ""} for <code>{html.escape(intake_id)}</code>.</p>
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
    .source-list {{ display: grid; gap: 16px; list-style: none; margin: 24px 0 0; padding: 0; }}
    .source-option {{ display: grid; grid-template-columns: minmax(0, 1fr) 180px; gap: 20px; border: 1px solid var(--line); border-radius: 6px; padding: 16px; }}
    .source-option h3 {{ margin-bottom: 8px; }}
    .source-option p {{ margin: 0 0 10px; }}
    .source-ref {{ color: var(--muted); overflow-wrap: anywhere; font-size: 14px; }}
    fieldset {{ border: 0; margin: 0; padding: 0; }}
    legend {{ color: var(--muted); font-size: 13px; font-weight: 650; margin-bottom: 8px; }}
    fieldset label {{ display: flex; gap: 8px; align-items: center; font-weight: 500; }}
    .empty-state {{ color: var(--muted); }}
    button, a {{ color: var(--accent); font-weight: 650; }}
    button {{ border: 0; border-radius: 6px; background: var(--accent); color: white; padding: 10px 14px; cursor: pointer; font: inherit; }}
    .validation {{ color: var(--danger); margin: 12px 0 0; font-weight: 650; }}
    .session, .session-note {{ color: var(--muted); margin-bottom: 0; }}
    code {{ background: #edf2f7; padding: 2px 4px; border-radius: 4px; }}
    @media (max-width: 760px) {{
      .shell {{ grid-template-columns: minmax(0, 1fr); padding: 20px 12px; }}
      .breadcrumbs {{ padding: 0 12px; }}
      .form-footer {{ align-items: stretch; flex-direction: column; }}
      .source-option {{ grid-template-columns: minmax(0, 1fr); }}
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
