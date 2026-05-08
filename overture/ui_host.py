"""Local-only UI host for the Overture wizard."""

from __future__ import annotations

from dataclasses import dataclass
from http import cookies
import html
from ipaddress import ip_address
import json
import os
from pathlib import Path
import secrets
from socketserver import ThreadingMixIn
from typing import Callable, Iterable, Mapping
from urllib.parse import parse_qs
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from .auth import AuthenticatedUser, DesignerSession, MagicLinkAuth, auth_cookie, authenticated_user_from_session, sender_from_env
from .export import parse_ticket_markdown
from .graph import GraphRecord, research_result_to_graph_records
from .graph_store import EDGE_KINDS, NODE_KINDS, SqliteGraphStore
from .intake import IntakeRecord, create_intake_record, load_intake_record
from .export import parse_ticket_file
from .export_runner import ExportRunResult, run_ticket_export
from .linear_client import LinearClient
from .observation_log import ObservationEvent, ObservationLog, founder_emails_from_env
from .peer_onboarding import (
    PEER_ONBOARDING_ROUTE,
    PeerOnboardingArtifact,
    initialize_peer_onboarding_template,
    load_latest_peer_onboarding_artifact,
    load_peer_onboarding_artifacts,
    ordered_peer_onboarding_sections,
    validate_peer_onboarding_artifact,
)
from .research import CuratedSource, ResearchClaim, ResearchError, ResearchItem, ResearchResult, SourceReference, _normalize_source
from .research_llm import (
    LLMSuggestedSourceAdapter,
    fake_llm_client,
    research_result_to_jsonable,
    write_research_result,
)
from .synthesis import GraphContext, SynthesisBrief, synthesize_graph_context
from .ticket_writer import generate_linear_issue_draft, validation_error_hints

INTAKE_TEXT_MAX_CHARS = 5000
DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 8765
SESSION_COOKIE_NAME = "overture_session"
DEFAULT_STORE_DIR = Path(".overture")
EXAMPLES_LIBRARY_PATH = Path("examples") / "intake_examples"
RESEARCH_APPROVAL_ROUTE = "/research/approval"
RESEARCH_COMPLETE_ROUTE = "/research/complete"
SYNTHESIS_ROUTE = "/synthesis"
TICKET_REVIEW_ROUTE = "/ticket"
SESSION_CANDIDATES_KEY = "research_candidates"
SESSION_APPROVALS_KEY = "research_approvals"
SESSION_SYNTHESIS_BRIEF_KEY = "synthesis_brief"
SESSION_TICKET_MARKDOWN_KEY = "ticket_markdown"
SESSION_TICKET_PATH_KEY = "ticket_path"
SESSION_TICKET_TITLE_KEY = "ticket_title"
SESSION_TICKET_BODY_KEY = "ticket_body"
SESSION_AUTHOR_ID_KEY = "author_id"
SESSION_AUTHOR_EMAIL_KEY = "author_email"
SESSION_PEER_ONBOARDING_TEMPLATE_KEY = "peer_onboarding_template"
AUTH_LOGIN_ROUTE = "/auth/login"
AUTH_MAGIC_LINK_ROUTE = "/auth/magic-link"
AUTH_CONSUME_ROUTE = "/auth/consume"
OBSERVATION_LOG_ROUTE_PREFIX = "/sessions/"

StartResponse = Callable[[str, list[tuple[str, str]]], None]


@dataclass(frozen=True)
class WizardRoute:
    path: str
    label: str
    title: str
    placeholder: str


@dataclass(frozen=True)
class EmptyStateGuidance:
    title: str
    action_label: str
    action_href: str


WIZARD_ROUTES: tuple[WizardRoute, ...] = (
    WizardRoute(
        path="/intake",
        label="Intake",
        title="Intake",
        placeholder="Describe your idea before starting research.",
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
    WizardRoute(
        path=PEER_ONBOARDING_ROUTE,
        label="Peer transfer",
        title="Peer onboarding",
        placeholder="Read the designer-to-designer transfer artifact while running the wizard.",
    ),
)
ROUTES_BY_PATH: Mapping[str, WizardRoute] = {route.path: route for route in WIZARD_ROUTES}
AUTHENTICATED_WIZARD_PATHS = {
    "/intake",
    RESEARCH_APPROVAL_ROUTE,
    RESEARCH_COMPLETE_ROUTE,
    SYNTHESIS_ROUTE,
    TICKET_REVIEW_ROUTE,
    "/export",
    PEER_ONBOARDING_ROUTE,
}


def _prerequisite_guidance(path: str) -> EmptyStateGuidance:
    route_paths = [route.path for route in WIZARD_ROUTES]
    index = route_paths.index(path)
    previous = WIZARD_ROUTES[index - 1]
    title_label = previous.title.lower()
    action_label = title_label
    href = previous.path
    if previous.path == "/research":
        title_label = "research approval"
        action_label = title_label
        href = RESEARCH_APPROVAL_ROUTE
    elif previous.path == SYNTHESIS_ROUTE:
        title_label = "synthesis review"
    return EmptyStateGuidance(
        title=f"Complete {title_label} first",
        action_label=f"Go to {action_label}",
        action_href=href,
    )


@dataclass(frozen=True)
class IntakeSubmissionResult:
    record: IntakeRecord
    session: dict[str, str]


@dataclass(frozen=True)
class ResearchReviewResult:
    session: dict[str, str]
    candidates: tuple[CuratedSource, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class TicketReviewResult:
    session: dict[str, str]
    markdown: str = ""
    error: str | None = None
    validation_hints: tuple[str, ...] = ()
    empty_state: EmptyStateGuidance | None = None


@dataclass(frozen=True)
class SynthesisReviewResult:
    session: dict[str, str]
    brief: Mapping[str, object] | None = None
    error: str | None = None
    cached: bool = False
    empty_state: EmptyStateGuidance | None = None


@dataclass(frozen=True)
class ExportReviewResult:
    session: dict[str, str]
    ticket_path: Path | None = None
    title: str = ""
    body_preview: str = ""
    message: str | None = None
    result: ExportRunResult | None = None


class SessionStore:
    """In-memory server-side session state keyed by authenticated user and cookie id."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], dict[str, object]] = {}

    def get_or_create(self, session_id: str | None, *, user_id: str) -> tuple[str, dict[str, object], bool]:
        if session_id:
            key = (user_id, session_id)
            if key in self._sessions:
                return session_id, self._sessions[key], False

        new_session_id = secrets.token_urlsafe(24)
        session = {"visits": 0, "user_id": user_id}
        self._sessions[(user_id, new_session_id)] = session
        return new_session_id, session, True


class LoopbackOnlyWSGIServer(ThreadingMixIn, WSGIServer):
    """WSGI server that accepts only loopback clients."""

    daemon_threads = True

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
        synthesizer: Callable[..., SynthesisBrief] = synthesize_graph_context,
        linear_client_factory: Callable[[], object] | None = None,
        graph_backend: object | None = None,
        auth_manager: MagicLinkAuth | None = None,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.session_store = SessionStore()
        self.llm_client = llm_client
        self.synthesizer = synthesizer
        self.linear_client_factory = linear_client_factory or _linear_client_from_env
        self.graph_backend = graph_backend
        self.auth_manager = auth_manager or MagicLinkAuth(sender=sender_from_env(self.store_dir))
        self.observation_log = ObservationLog(self.store_dir)
        self._active_auth_session: DesignerSession | None = None

    def __call__(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        if path in {"", "/"}:
            return self._redirect(start_response, "/intake", status="302 Found")
        if path == AUTH_LOGIN_ROUTE and method == "GET":
            return self._render(start_response, render_login_page())
        if path == AUTH_MAGIC_LINK_ROUTE and method == "POST":
            return self._handle_magic_link_post(environ, start_response)
        if path == AUTH_CONSUME_ROUTE and method == "GET":
            return self._handle_auth_consume(environ, start_response)

        auth_session = self.auth_manager.authenticate(environ)
        if auth_session is None:
            if path in AUTHENTICATED_WIZARD_PATHS or _is_observation_log_route(path):
                return self._redirect(start_response, f"{AUTH_LOGIN_ROUTE}?next={path}", status="302 Found")
            return self._unauthorized(start_response)

        self._active_auth_session = auth_session
        user = authenticated_user_from_session(auth_session)
        environ["overture.authenticated_user"] = user
        try:
            return self._route_authenticated(method, path, environ, start_response, user)
        finally:
            self._active_auth_session = None

    def _route_authenticated(
        self,
        method: str,
        path: str,
        environ: dict[str, object],
        start_response: StartResponse,
        user: AuthenticatedUser,
    ) -> Iterable[bytes]:
        if path == "/intake" and method == "GET":
            assert user is not None
            session_id, server_session, is_new = self._server_session(environ, user)
            body = render_intake_page(
                session_from_environ(environ, user=user),
                session_id=session_id,
                visit_count=_record_visit(server_session),
                designer_email=self._active_auth_session.email if self._active_auth_session else None,
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
            assert user is not None
            session = session_from_environ(environ, user=user)
            self._record_observation(
                session,
                event_type="page_transition",
                route=RESEARCH_COMPLETE_ROUTE,
                action="view",
                user=user,
                request={"method": "GET"},
                response={"status": 200},
            )
            return self._render(start_response, render_research_complete_page(session))
        if path == SYNTHESIS_ROUTE and method == "GET":
            return self._handle_synthesis_get(environ, start_response)
        if path == SYNTHESIS_ROUTE and method == "POST":
            return self._handle_synthesis_post(environ, start_response)
        if path == TICKET_REVIEW_ROUTE and method == "GET":
            return self._handle_ticket_get(environ, start_response)
        if path == TICKET_REVIEW_ROUTE and method == "POST":
            return self._handle_ticket_post(environ, start_response)
        if path == "/export" and method == "GET":
            return self._handle_export_get(environ, start_response)
        if path == "/export" and method == "POST":
            return self._handle_export_post(environ, start_response)
        if path == PEER_ONBOARDING_ROUTE and method == "GET":
            store = SqliteGraphStore(Path(self.store_dir) / "graph.sqlite")
            artifacts = load_peer_onboarding_artifacts(store)
            artifact = load_latest_peer_onboarding_artifact(store)
            errors = validate_peer_onboarding_artifact(artifact)
            status = "500 Internal Server Error" if errors else "200 OK"
            return self._render(
                start_response,
                render_peer_onboarding_artifact_page(artifact, artifacts=artifacts, errors=errors),
                status=status,
            )
        observation_session_id = _observation_session_id_from_path(path)
        if observation_session_id and method == "GET":
            return self._handle_observation_log_get(observation_session_id, start_response, user)
        if path == "/examples/intake_examples" and method == "GET":
            return self._render(start_response, render_examples_library())
        if path in ROUTES_BY_PATH and method == "GET":
            assert user is not None
            session_id, server_session, is_new = self._server_session(environ, user)
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

    def _handle_observation_log_get(
        self,
        session_id: str,
        start_response: StartResponse,
        user: AuthenticatedUser,
    ) -> Iterable[bytes]:
        log = ObservationLog(Path(self.store_dir) / "observation.sqlite")
        try:
            events = log.iter_session_events(session_id, user=user, founder_emails=founder_emails_from_env())
        except PermissionError:
            return self._render(start_response, render_observation_forbidden_page(session_id), status="403 Forbidden")
        if not events:
            return self._render(start_response, render_observation_log_page(session_id, events=()), status="404 Not Found")
        return self._render(start_response, render_observation_log_page(session_id, events=events))

    def _handle_magic_link_post(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        fields = _form_fields(environ)
        email = fields.get("email", [""])[0]
        try:
            delivery = self.auth_manager.request_link(email)
        except (RuntimeError, ValueError) as exc:
            return self._render(start_response, render_login_page(email=email, error=str(exc)), status="400 Bad Request")
        return self._render(start_response, render_magic_link_sent_page(delivery.email, delivery.link, delivery.outbox_path))

    def _handle_auth_consume(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        query = parse_qs(str(environ.get("QUERY_STRING", "")), keep_blank_values=True)
        token = query.get("token", [""])[0]
        session_token = self.auth_manager.consume_link(token)
        if session_token is None:
            return self._render(
                start_response,
                render_login_page(error="This magic link is invalid or expired. Request a new link."),
                status="401 Unauthorized",
            )
        return self._render(
            start_response,
            render_magic_link_consumed_page(),
            extra_headers=[("Set-Cookie", auth_cookie(session_token))],
        )

    def _unauthorized(self, start_response: StartResponse) -> list[bytes]:
        return self._render(
            start_response,
            render_unauthorized_page(),
            status="401 Unauthorized",
            extra_headers=[("WWW-Authenticate", 'Bearer realm="overture"')],
        )

    def _handle_intake_post(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        fields = _form_fields(environ)
        raw_text = fields.get("idea", [""])[0]
        user = _require_user(environ)
        session = session_from_environ(environ, user=user)
        error = validate_intake_text(raw_text)
        if error:
            self._record_observation(
                session,
                event_type="validation_error",
                route="/intake",
                action="submit",
                user=user,
                request={"fields": _flatten_form_fields(fields)},
                response={"status": 400, "message": error},
                error=error,
            )
            return self._render(
                start_response,
                render_intake_page(session, raw_text=raw_text, error=error),
                status="400 Bad Request",
            )

        result = submit_intake(raw_text, self.store_dir, session, user=user)
        self._record_observation(
            result.session,
            event_type="form_submission",
            route="/intake",
            action="submit",
            user=user,
            request={"fields": _flatten_form_fields(fields)},
            response={"status": 303, "location": RESEARCH_APPROVAL_ROUTE, "intake_id": result.record.id},
        )
        self._record_observation(
            result.session,
            event_type="page_transition",
            route=RESEARCH_APPROVAL_ROUTE,
            action="advance",
            user=user,
            request={"from": "/intake", "method": "POST"},
            response={"status": 303, "location": RESEARCH_APPROVAL_ROUTE},
        )
        return self._redirect(
            start_response,
            RESEARCH_APPROVAL_ROUTE,
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _handle_research_get(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        user = _require_user(environ)
        result = prepare_research_review(session_from_environ(environ, user=user), self.store_dir, self.llm_client)
        self._record_observation(
            result.session,
            event_type="page_transition",
            route=RESEARCH_APPROVAL_ROUTE,
            action="view",
            user=user,
            request={"method": "GET"},
            response={
                "status": 400 if result.error and not result.candidates else 200,
                "candidate_count": len(result.candidates),
            },
            error=result.error,
        )
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
            session=session_from_environ(environ, user=_require_user(environ)),
            store_dir=self.store_dir,
            approved_keys=approved_keys,
            user=_require_user(environ),
        )
        if result.error:
            self._record_observation(
                result.session,
                event_type="validation_error",
                route=RESEARCH_APPROVAL_ROUTE,
                action="submit",
                user=_require_user(environ),
                request={"fields": _flatten_form_fields(fields), "approved_keys": approved_keys},
                response={"status": 400, "message": result.error},
                error=result.error,
            )
            return self._render(
                start_response,
                render_research_approval_page(result.session, candidates=result.candidates, error=result.error),
                status="400 Bad Request",
                extra_headers=[("Set-Cookie", _session_cookie(result.session))],
            )
        self._record_observation(
            result.session,
            event_type="form_submission",
            route=RESEARCH_APPROVAL_ROUTE,
            action="submit",
            user=_require_user(environ),
            request={"fields": _flatten_form_fields(fields), "approved_keys": approved_keys},
            response={
                "status": 303,
                "location": RESEARCH_COMPLETE_ROUTE,
                "research_id": result.session.get("research_id"),
            },
        )
        self._record_observation(
            result.session,
            event_type="page_transition",
            route=RESEARCH_COMPLETE_ROUTE,
            action="advance",
            user=_require_user(environ),
            request={"from": RESEARCH_APPROVAL_ROUTE, "method": "POST"},
            response={"status": 303, "location": RESEARCH_COMPLETE_ROUTE},
        )
        return self._redirect(
            start_response,
            RESEARCH_COMPLETE_ROUTE,
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _handle_synthesis_get(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        user = _require_user(environ)
        result = prepare_synthesis_review(
            session_from_environ(environ, user=user),
            self.store_dir,
            synthesizer=self.synthesizer,
            graph_backend=self.graph_backend,
            user=user,
        )
        self._record_observation(
            result.session,
            event_type="page_transition",
            route=SYNTHESIS_ROUTE,
            action="view",
            user=user,
            request={"method": "GET"},
            response={"status": 200, "cached": result.cached, "has_brief": result.brief is not None},
            error=result.error,
        )
        return self._render(
            start_response,
            render_synthesis_review_page(
                result.session,
                brief=result.brief,
                error=result.error,
                cached=result.cached,
                empty_state=result.empty_state,
            ),
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _handle_synthesis_post(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        user = _require_user(environ)
        session = session_from_environ(environ, user=user)
        result = advance_synthesis_review(session, self.store_dir, user=user)
        if result.error:
            self._record_observation(
                result.session,
                event_type="validation_error",
                route=SYNTHESIS_ROUTE,
                action="advance",
                user=user,
                request={"fields": {}},
                response={"status": 400, "message": result.error},
                error=result.error,
            )
            return self._render(
                start_response,
                render_synthesis_review_page(
                    result.session,
                    brief=result.brief,
                    error=result.error,
                    cached=result.cached,
                    empty_state=result.empty_state,
                ),
                status="400 Bad Request",
                extra_headers=[("Set-Cookie", _session_cookie(result.session))],
            )
        self._record_observation(
            result.session,
            event_type="form_submission",
            route=SYNTHESIS_ROUTE,
            action="advance",
            user=user,
            request={"fields": {}},
            response={"status": 303, "location": TICKET_REVIEW_ROUTE, "synthesis_id": result.session.get("synthesis_id")},
        )
        self._record_observation(
            result.session,
            event_type="page_transition",
            route=TICKET_REVIEW_ROUTE,
            action="advance",
            user=user,
            request={"from": SYNTHESIS_ROUTE, "method": "POST"},
            response={"status": 303, "location": TICKET_REVIEW_ROUTE},
        )
        return self._redirect(
            start_response,
            TICKET_REVIEW_ROUTE,
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _handle_ticket_get(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        user = _require_user(environ)
        result = prepare_ticket_review(session_from_environ(environ, user=user), user=user)
        self._record_observation(
            result.session,
            event_type="page_transition",
            route=TICKET_REVIEW_ROUTE,
            action="view",
            user=user,
            request={"method": "GET"},
            response={"status": 200, "has_markdown": bool(result.markdown)},
            error=result.error,
        )
        if result.empty_state is not None:
            return self._redirect(
                start_response,
                SYNTHESIS_ROUTE,
                extra_headers=[("Set-Cookie", _session_cookie(result.session))],
            )
        return self._render(
            start_response,
            render_ticket_review_page(
                result.session,
                markdown=result.markdown,
                error=result.error,
                validation_hints=result.validation_hints,
                empty_state=result.empty_state,
            ),
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _handle_ticket_post(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        fields = _form_fields(environ)
        markdown = fields.get("ticket_markdown", [""])[0]
        user = _require_user(environ)
        result = submit_ticket_review(session_from_environ(environ, user=user), markdown, user=user)
        if result.error:
            self._record_observation(
                result.session,
                event_type="validation_error",
                route=TICKET_REVIEW_ROUTE,
                action="submit",
                user=user,
                request={"fields": _flatten_form_fields(fields)},
                response={"status": 400, "message": result.error},
                error=result.error,
            )
            return self._render(
                start_response,
                render_ticket_review_page(
                    result.session,
                    markdown=result.markdown,
                    error=result.error,
                    validation_hints=result.validation_hints,
                ),
                status="400 Bad Request",
                extra_headers=[("Set-Cookie", _session_cookie(result.session))],
            )
        self._record_observation(
            result.session,
            event_type="form_submission",
            route=TICKET_REVIEW_ROUTE,
            action="submit",
            user=user,
            request={"fields": _flatten_form_fields(fields)},
            response={"status": 303, "location": "/export", "ticket_title": result.session.get("ticket_title")},
        )
        self._record_observation(
            result.session,
            event_type="page_transition",
            route="/export",
            action="advance",
            user=user,
            request={"from": TICKET_REVIEW_ROUTE, "method": "POST"},
            response={"status": 303, "location": "/export"},
        )
        return self._redirect(
            start_response,
            "/export",
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _handle_export_get(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        user = _require_user(environ)
        result = prepare_export_review(session_from_environ(environ, user=user), self.store_dir, user=user)
        self._record_observation(
            result.session,
            event_type="page_transition",
            route="/export",
            action="view",
            user=user,
            request={"method": "GET"},
            response={"status": 200, "has_ticket": result.ticket_path is not None},
            error=result.message if result.ticket_path is None else None,
        )
        return self._render(
            start_response,
            render_export_page(result),
            status="200 OK",
            extra_headers=[("Set-Cookie", _session_cookie(result.session))],
        )

    def _handle_export_post(self, environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
        fields = _form_fields(environ)
        action = fields.get("action", [""])[0]
        user = _require_user(environ)
        session = session_from_environ(environ, user=user)
        if action == "back":
            self._record_observation(
                session,
                event_type="form_submission",
                route="/export",
                action="retreat",
                user=user,
                request={"fields": _flatten_form_fields(fields)},
                response={"status": 303, "location": TICKET_REVIEW_ROUTE},
            )
            self._record_observation(
                session,
                event_type="page_transition",
                route=TICKET_REVIEW_ROUTE,
                action="retreat",
                user=user,
                request={"from": "/export", "method": "POST"},
                response={"status": 303, "location": TICKET_REVIEW_ROUTE},
            )
            return self._redirect(start_response, TICKET_REVIEW_ROUTE, extra_headers=[("Set-Cookie", _session_cookie(session))])

        dry_run = action == "dry-run"
        if action not in {"dry-run", "export"}:
            review = prepare_export_review(session, self.store_dir, message="Choose Dry-run or Export before continuing.", user=user)
            self._record_observation(
                review.session,
                event_type="validation_error",
                route="/export",
                action="submit",
                user=user,
                request={"fields": _flatten_form_fields(fields)},
                response={"status": 400, "message": review.message},
                error=review.message,
            )
            return self._render(
                start_response,
                render_export_page(review),
                status="400 Bad Request",
                extra_headers=[("Set-Cookie", _session_cookie(review.session))],
            )

        review = prepare_export_review(session, self.store_dir, user=user)
        if review.ticket_path is None:
            self._record_observation(
                review.session,
                event_type="validation_error",
                route="/export",
                action=action,
                user=user,
                request={"fields": _flatten_form_fields(fields)},
                response={"status": 400, "message": review.message},
                error=review.message,
            )
            return self._render(
                start_response,
                render_export_page(review),
                status="400 Bad Request",
                extra_headers=[("Set-Cookie", _session_cookie(review.session))],
            )
        if not dry_run and "LINEAR_API_KEY" not in os.environ:
            review = ExportReviewResult(
                session=review.session,
                ticket_path=review.ticket_path,
                title=review.title,
                body_preview=review.body_preview,
                message="LINEAR_API_KEY is required before exporting to Linear. Dry-run remains available.",
            )
            self._record_observation(
                review.session,
                event_type="validation_error",
                route="/export",
                action=action,
                user=user,
                request={"fields": _flatten_form_fields(fields)},
                response={"status": 400, "message": review.message},
                error=review.message,
            )
            return self._render(
                start_response,
                render_export_page(review),
                status="400 Bad Request",
                extra_headers=[("Set-Cookie", _session_cookie(review.session))],
            )

        export_result = run_ticket_export(
            review.ticket_path,
            team_id=os.environ.get("LINEAR_TEAM_ID"),
            project_id=os.environ.get("LINEAR_PROJECT_ID"),
            dry_run=dry_run,
            ledger_db=self.store_dir / "exports.sqlite",
            linear_client_factory=self.linear_client_factory,
        )
        status = "200 OK" if export_result.status in {"dry_run", "exported", "already_exported"} else "400 Bad Request"
        review = ExportReviewResult(
            session=review.session,
            ticket_path=review.ticket_path,
            title=review.title,
            body_preview=review.body_preview,
            result=export_result,
        )
        self._record_observation(
            review.session,
            event_type="form_submission",
            route="/export",
            action=action,
            user=user,
            request={"fields": _flatten_form_fields(fields)},
            response={"status": int(status.split()[0]), "export_status": export_result.status, "url": export_result.url},
            error=export_result.message if status.startswith("400") else None,
        )
        return self._render(
            start_response,
            render_export_page(review),
            status=status,
            extra_headers=[("Set-Cookie", _session_cookie(review.session))],
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
        headers.extend(self._auth_refresh_headers())
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
        headers.extend(self._auth_refresh_headers())
        if extra_headers:
            headers.extend(extra_headers)
        start_response(status, headers)
        return [b""]

    def _auth_refresh_headers(self) -> list[tuple[str, str]]:
        if self._active_auth_session is None:
            return []
        token = self.auth_manager.refresh_session(self._active_auth_session)
        return [("Set-Cookie", auth_cookie(token))]

    def _record_observation(
        self,
        session: Mapping[str, str],
        *,
        event_type: str,
        route: str,
        action: str,
        user: AuthenticatedUser,
        request: Mapping[str, object] | None = None,
        response: Mapping[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        session_id = _observation_session_id(session)
        if not session_id:
            return
        ObservationLog(Path(self.store_dir) / "observation.sqlite").append(
            session_id=session_id,
            event_type=event_type,
            route=route,
            action=action,
            actor=user,
            author_id=session.get(SESSION_AUTHOR_ID_KEY) or session.get("user_id"),
            author_email=session.get(SESSION_AUTHOR_EMAIL_KEY) or session.get("user_email"),
            request=request,
            response=response,
            error=error,
        )

    def _server_session(self, environ: dict[str, object], user: AuthenticatedUser) -> tuple[str, dict[str, object], bool]:
        return self.session_store.get_or_create(_opaque_session_id_from_environ(environ), user_id=user.user_id)


def build_ui_server(
    host: str = DEFAULT_UI_HOST,
    port: int = DEFAULT_UI_PORT,
    *,
    store_dir: Path | str = DEFAULT_STORE_DIR,
    llm_client: Callable[[str], str] = fake_llm_client,
    synthesizer: Callable[..., SynthesisBrief] = synthesize_graph_context,
    linear_client_factory: Callable[[], object] | None = None,
    graph_backend: object | None = None,
    auth_manager: MagicLinkAuth | None = None,
) -> LoopbackOnlyWSGIServer:
    _ensure_loopback_bind_host(host)
    auth = auth_manager or MagicLinkAuth(sender=sender_from_env(store_dir), base_url=f"http://localhost:{port}")
    app = OvertureUiApp(
        store_dir=store_dir,
        llm_client=llm_client,
        synthesizer=synthesizer,
        linear_client_factory=linear_client_factory,
        graph_backend=graph_backend,
        auth_manager=auth,
    )
    server = make_server(
        host,
        port,
        app,
        server_class=LoopbackOnlyWSGIServer,
        handler_class=QuietRequestHandler,
    )
    if auth_manager is None:
        _bound_host, bound_port = server.server_address[:2]
        auth.base_url = f"http://localhost:{bound_port}"
    return server


def serve_ui_host(
    host: str = DEFAULT_UI_HOST,
    port: int = DEFAULT_UI_PORT,
    store_dir: Path | str = DEFAULT_STORE_DIR,
    *,
    llm_client: Callable[[str], str] = fake_llm_client,
    synthesizer: Callable[..., SynthesisBrief] = synthesize_graph_context,
    linear_client_factory: Callable[[], object] | None = None,
    graph_backend: object | None = None,
    auth_manager: MagicLinkAuth | None = None,
) -> None:
    server = build_ui_server(
        host=host,
        port=port,
        store_dir=store_dir,
        llm_client=llm_client,
        synthesizer=synthesizer,
        linear_client_factory=linear_client_factory,
        graph_backend=graph_backend,
        auth_manager=auth_manager,
    )
    bound_host, bound_port = server.server_address[:2]
    print(f"Overture UI host listening on http://localhost:{bound_port}/intake")
    print(f"Bound to loopback address {bound_host}; press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def submit_intake(
    raw_text: str,
    store_dir: Path | str,
    session: dict[str, str] | None = None,
    *,
    user: AuthenticatedUser,
) -> IntakeSubmissionResult:
    record, _path = create_intake_record(
        raw_text,
        Path(store_dir) / "intake",
        source_type="ui",
        author_id=session.get(SESSION_AUTHOR_ID_KEY) if session else None,
        author_email=session.get(SESSION_AUTHOR_EMAIL_KEY) if session else None,
    )
    _tag_json_file(_path, user)
    next_session = _session_for_user(session or {}, user)
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
    next_session.pop(SESSION_CANDIDATES_KEY, None)
    candidates = _session_candidates(next_session, intake_id)
    if not candidates:
        candidates = _research_candidate_cache(store_dir, intake_id)
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
        _cache_research_candidates(store_dir, intake_id, candidates)
        if result.errors and not candidates:
            return ResearchReviewResult(next_session, candidates, result.errors[0].message)

    return ResearchReviewResult(next_session, candidates)


def submit_research_approvals(
    *,
    session: dict[str, str],
    store_dir: Path | str,
    approved_keys: Iterable[str],
    user: AuthenticatedUser,
) -> ResearchReviewResult:
    intake_id = session.get("intake_id", "")
    candidates = _session_candidates(session, intake_id) if intake_id else ()
    if not candidates and intake_id:
        candidates = _research_candidate_cache(store_dir, intake_id)
    selected = {str(key) for key in approved_keys}
    next_session = _store_session_approvals(dict(session), intake_id, selected) if intake_id else dict(session)

    if not intake_id:
        _clear_research_candidate_cache(store_dir, intake_id)
        return ResearchReviewResult(next_session, candidates, "No intake is stored in this session.")
    if not candidates:
        _clear_research_candidate_cache(store_dir, intake_id)
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

    research_path = Path(store_dir) / "research" / f"{intake.id}.json"
    write_research_result(research_path, result)
    _tag_json_file(research_path, user)
    next_session["research_result"] = json.dumps(research_result_to_jsonable(result), sort_keys=True, separators=(",", ":"))
    next_session["research_id"] = intake.id
    next_session["next_route"] = "/synthesis"
    return ResearchReviewResult(next_session, candidates)


def prepare_synthesis_review(
    session: dict[str, str],
    store_dir: Path | str,
    *,
    synthesizer: Callable[..., SynthesisBrief] = synthesize_graph_context,
    graph_backend: object | None = None,
    user: AuthenticatedUser | None = None,
) -> SynthesisReviewResult:
    intake_id = session.get("intake_id", "")
    if not intake_id:
        return SynthesisReviewResult(
            session=dict(session),
            empty_state=_prerequisite_guidance(SYNTHESIS_ROUTE),
        )

    cache_path = _synthesis_cache_path(store_dir, intake_id)
    if cache_path.exists():
        brief = _read_json(cache_path)
        next_session = dict(session)
        next_session[SESSION_SYNTHESIS_BRIEF_KEY] = json.dumps(brief, sort_keys=True, separators=(",", ":"))
        return SynthesisReviewResult(next_session, brief, cached=True)

    try:
        intake = load_intake_record(Path(store_dir) / "intake" / f"{intake_id}.json")
    except FileNotFoundError:
        return SynthesisReviewResult(dict(session), empty_state=_prerequisite_guidance(SYNTHESIS_ROUTE))

    research = _research_result_from_session(session)
    if research is None:
        research_path = Path(store_dir) / "research" / f"{intake_id}.json"
        if not research_path.exists():
            return SynthesisReviewResult(dict(session), empty_state=_prerequisite_guidance(SYNTHESIS_ROUTE))
        research = _research_result_from_json(_read_json(research_path))
    if not research.items:
        return SynthesisReviewResult(dict(session), error="No approved research result is available for synthesis.")

    current_context = _synthesis_context_from_intake_research(intake, research, user=user)
    graph_store = SqliteGraphStore(Path(store_dir) / "graph.sqlite")
    writable_graph = graph_backend if graph_backend is not None else graph_store
    prior_context = writable_graph.load_context()
    brief = synthesizer(current_context, prior_context=prior_context).to_dict()
    if user is not None:
        brief["author_id"] = user.user_id
        brief["author_email"] = user.email
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(brief, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if user is not None:
        writable_graph.upsert_records(_graph_records_from_context(current_context, user))

    next_session = dict(session)
    next_session["synthesis_id"] = intake_id
    next_session["next_route"] = TICKET_REVIEW_ROUTE
    next_session[SESSION_SYNTHESIS_BRIEF_KEY] = json.dumps(brief, sort_keys=True, separators=(",", ":"))
    return SynthesisReviewResult(next_session, brief, cached=False)


def advance_synthesis_review(
    session: dict[str, str],
    store_dir: Path | str,
    *,
    user: AuthenticatedUser | None = None,
) -> SynthesisReviewResult:
    result = prepare_synthesis_review(session, store_dir, user=user)
    if result.error or result.empty_state:
        return result
    next_session = dict(result.session)
    next_session["synthesis_id"] = next_session.get("intake_id", "")
    next_session["next_route"] = TICKET_REVIEW_ROUTE
    return SynthesisReviewResult(next_session, result.brief, cached=result.cached)


def prepare_ticket_review(session: dict[str, str], *, user: AuthenticatedUser | None = None) -> TicketReviewResult:
    next_session = dict(session)
    if user is not None:
        next_session = _session_for_user(next_session, user)
    existing = next_session.get(SESSION_TICKET_MARKDOWN_KEY)
    if existing:
        try:
            parse_ticket_markdown(existing)
        except ValueError as exc:
            message = str(exc)
            return TicketReviewResult(
                session=next_session,
                markdown=existing,
                error=message,
                validation_hints=validation_error_hints(message),
            )
        return TicketReviewResult(session=next_session, markdown=existing)

    brief_json = next_session.get(SESSION_SYNTHESIS_BRIEF_KEY) or next_session.get("synthesis")
    if not brief_json:
        return TicketReviewResult(
            session=next_session,
            empty_state=_prerequisite_guidance(TICKET_REVIEW_ROUTE),
        )
    try:
        brief = json.loads(brief_json)
        draft = generate_linear_issue_draft(brief)
    except (TypeError, ValueError, IndexError, json.JSONDecodeError) as exc:
        return TicketReviewResult(session=next_session, error=f"Could not generate ticket draft: {exc}")

    markdown = _ticket_markdown_with_author(draft.description, next_session)
    next_session[SESSION_TICKET_MARKDOWN_KEY] = markdown
    return TicketReviewResult(session=next_session, markdown=markdown)


def submit_ticket_review(
    session: dict[str, str],
    markdown: str,
    *,
    user: AuthenticatedUser | None = None,
) -> TicketReviewResult:
    next_session = dict(session)
    if user is not None:
        next_session = _session_for_user(next_session, user)
    next_session[SESSION_TICKET_MARKDOWN_KEY] = markdown
    try:
        parsed = parse_ticket_markdown(markdown)
    except ValueError as exc:
        return TicketReviewResult(
            session=next_session,
            markdown=markdown,
            error=str(exc),
            validation_hints=validation_error_hints(str(exc)),
        )

    next_session["ticket_title"] = parsed.title
    next_session["next_route"] = "/export"
    return TicketReviewResult(session=next_session, markdown=markdown)


def prepare_export_review(
    session: dict[str, str],
    store_dir: Path | str,
    *,
    message: str | None = None,
    user: AuthenticatedUser | None = None,
) -> ExportReviewResult:
    next_session = dict(session)
    if user is not None:
        next_session = _session_for_user(next_session, user)
    session_ticket_path = _session_ticket_path(session, store_dir)
    if session_ticket_path is not None:
        return _export_review_from_path(next_session, session_ticket_path, message=message)

    ticket_markdown = _session_ticket_markdown(session)
    if not ticket_markdown:
        return ExportReviewResult(
            session=next_session,
            message=message or "No validated ticket is stored in this session. Return to ticket review before exporting.",
        )

    session_key = next_session.get("intake_id") or next_session.get("research_id") or "session"
    ticket_path = Path(store_dir) / "ticket" / f"{_safe_session_key(session_key)}-export.md"
    ticket_path.parent.mkdir(parents=True, exist_ok=True)
    ticket_path.write_text(ticket_markdown, encoding="utf-8")
    if user is not None:
        _write_author_sidecar(ticket_path, user)
    return _export_review_from_path(next_session, ticket_path, message=message)


def validate_intake_text(raw_text: str) -> str | None:
    if not raw_text.strip():
        return "Enter an idea before continuing."
    if len(raw_text) > INTAKE_TEXT_MAX_CHARS:
        return f"Idea text must be {INTAKE_TEXT_MAX_CHARS:,} characters or fewer."
    return None


def session_from_environ(environ: dict[str, object], *, user: AuthenticatedUser | None = None) -> dict[str, str]:
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
    session = {str(key): str(value) for key, value in payload.items()}
    if user is None:
        return session
    return _session_for_user(session, user)


def _export_review_from_path(
    session: dict[str, str],
    ticket_path: Path,
    *,
    message: str | None = None,
) -> ExportReviewResult:
    try:
        parsed = parse_ticket_file(ticket_path)
    except ValueError as exc:
        return ExportReviewResult(session=session, ticket_path=ticket_path, message=str(exc))

    preview = parsed.description[:200]
    if len(parsed.description) > 200:
        preview += "..."
    render_message = message
    if render_message is None and "LINEAR_API_KEY" not in os.environ:
        render_message = "LINEAR_API_KEY is not set. Dry-run is available, but Export requires setup before it can create an issue."
    return ExportReviewResult(
        session=session,
        ticket_path=ticket_path,
        title=parsed.title,
        body_preview=preview,
        message=render_message,
    )


def _session_ticket_markdown(session: Mapping[str, str]) -> str:
    markdown = str(session.get(SESSION_TICKET_MARKDOWN_KEY, "")).strip()
    if markdown:
        return markdown + ("\n" if not markdown.endswith("\n") else "")

    title = str(session.get(SESSION_TICKET_TITLE_KEY, "")).strip()
    body = str(session.get(SESSION_TICKET_BODY_KEY, "")).strip()
    if not title or not body:
        return ""
    if body.startswith("## "):
        description = body
    else:
        description = f"## Context\n\n{body}"
    return f"# {title}\n\n{description}\n"


def _session_ticket_path(session: Mapping[str, str], store_dir: Path | str) -> Path | None:
    raw_path = str(session.get(SESSION_TICKET_PATH_KEY, "")).strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(store_dir) / path
    return path if path.exists() else None


def _peer_onboarding_template_from_session(session: Mapping[str, str]) -> dict[str, object] | None:
    raw_template = session.get(SESSION_PEER_ONBOARDING_TEMPLATE_KEY)
    if not raw_template:
        return None
    try:
        payload = json.loads(raw_template)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _safe_session_key(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in value)
    return safe.strip("-") or "session"


def _linear_client_from_env() -> LinearClient:
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise RuntimeError("LINEAR_API_KEY is required for real Linear export")
    return LinearClient(api_key=api_key)


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


def _research_candidate_cache(store_dir: Path | str, intake_id: str) -> tuple[CuratedSource, ...]:
    path = _research_candidate_cache_path(store_dir, intake_id)
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ()
    if not isinstance(payload, list):
        return ()
    sources = []
    for item in payload:
        if isinstance(item, Mapping):
            source = _normalize_source(item)
            if source is not None:
                sources.append(source)
    return tuple(sources)


def _cache_research_candidates(store_dir: Path | str, intake_id: str, candidates: Iterable[CuratedSource]) -> None:
    path = _research_candidate_cache_path(store_dir, intake_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = [_source_to_jsonable(source) for source in candidates]
    path.write_text(json.dumps(serialized, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")


def _research_candidate_cache_path(store_dir: Path | str, intake_id: str) -> Path:
    return Path(store_dir) / "session" / f"{intake_id}-candidates.json"


def _clear_research_candidate_cache(store_dir: Path | str, intake_id: str) -> None:
    path = _research_candidate_cache_path(store_dir, intake_id)
    path.unlink(missing_ok=True)


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


def _peer_onboarding_section_markup(section: Mapping[str, object]) -> str:
    fields = section.get("fields", [])
    field_markup = ""
    if isinstance(fields, list):
        field_markup = "\n".join(_peer_onboarding_field_markup(field) for field in fields if isinstance(field, Mapping))
    if not field_markup:
        field_markup = '<p class="empty-state">No notes have been added yet.</p>'
    description = str(section.get("description", ""))
    description_markup = f"<p>{html.escape(description)}</p>" if description else ""
    return f"""
    <section class="brief-section peer-section">
      <h3>{html.escape(str(section.get("title", "Untitled section")))}</h3>
      {description_markup}
      <dl class="peer-fields">
        {field_markup}
      </dl>
    </section>
    """


def _peer_onboarding_field_markup(field: Mapping[str, object]) -> str:
    label = html.escape(str(field.get("label", field.get("id", "Field"))))
    value = field.get("value")
    return f"""
      <dt>{label}</dt>
      <dd>{_peer_onboarding_value_markup(value)}</dd>
    """


def _peer_onboarding_value_markup(value: object) -> str:
    if isinstance(value, str):
        return html.escape(value) if value.strip() else '<span class="empty-state">Not filled yet.</span>'
    if isinstance(value, list):
        if not value:
            return '<span class="empty-state">Not filled yet.</span>'
        if all(isinstance(item, Mapping) and "step" in item for item in value):
            rows = []
            for item in value:
                step = html.escape(str(item.get("step", "")))
                note = str(item.get("note", ""))
                note_markup = html.escape(note) if note.strip() else '<span class="empty-state">No note yet.</span>'
                rows.append(f"<li><strong>{step}</strong><p>{note_markup}</p></li>")
            return f'<ol class="wizard-watchouts">{"".join(rows)}</ol>'
        items = [f"<li>{html.escape(str(item))}</li>" for item in value if str(item).strip()]
        return f"<ul>{''.join(items)}</ul>" if items else '<span class="empty-state">Not filled yet.</span>'
    if isinstance(value, Mapping):
        items = "".join(
            f"<li><strong>{html.escape(str(key))}</strong>: {html.escape(str(item))}</li>"
            for key, item in value.items()
        )
        return f"<ul>{items}</ul>" if items else '<span class="empty-state">Not filled yet.</span>'
    return html.escape(str(value)) if value is not None else '<span class="empty-state">Not filled yet.</span>'


def render_login_page(*, email: str = "", error: str | None = None) -> str:
    escaped_email = html.escape(email)
    error_markup = f'<p class="validation" role="alert">{html.escape(error)}</p>' if error else ""
    return render_layout(
        title="Sign in to Overture",
        active_path="/intake",
        content=f"""
        <section class="workspace auth-panel">
          <h2>Sign in to Overture</h2>
          <p>Enter the email address you use for Overture. We will send a short-lived sign-in link.</p>
          <form method="post" action="{AUTH_MAGIC_LINK_ROUTE}" novalidate>
            <label for="email">Email</label>
            <input id="email" name="email" type="email" value="{escaped_email}" autocomplete="email" autofocus required>
            <div class="form-footer">
              <span>No password or SSO is required.</span>
              <button type="submit">Send magic link</button>
            </div>
            {error_markup}
          </form>
        </section>
        """,
    )


def render_magic_link_sent_page(email: str, link: str, outbox_path: Path | None) -> str:
    escaped_path = html.escape(str(outbox_path)) if outbox_path else ""
    outbox_markup = (
        f"""
          <details class="session-note dev-details">
            <summary>Local development details</summary>
            <p>Development outbox: <code>{escaped_path}</code></p>
          </details>
        """
        if outbox_path
        else ""
    )
    return render_layout(
        title="Magic link sent",
        active_path="/intake",
        content=f"""
        <section class="workspace auth-panel">
          <h2>Magic link sent</h2>
          <p>A sign-in link was sent to <code>{html.escape(email)}</code>. It expires in 15 minutes.</p>
          <p class="session-note"><a href="{html.escape(link)}">Open the magic link locally</a></p>
          {outbox_markup}
        </section>
        """,
    )


def render_magic_link_consumed_page() -> str:
    return render_layout(
        title="Sign in confirmed",
        active_path="/intake",
        content="""
        <section class="workspace auth-panel">
          <h2>Sign in confirmed</h2>
          <p>Your designer session is ready.</p>
          <div class="form-footer">
            <span>Continue the wizard from the first step.</span>
            <a class="primary-action" href="/intake">Continue to intake</a>
          </div>
        </section>
        """,
    )


def render_unauthorized_page() -> str:
    return render_layout(
        title="Authentication required",
        active_path=None,
        content=f"""
        <section class="workspace auth-panel">
          <h2>Authentication required</h2>
          <p>This backend route requires a current Overture session.</p>
          <p><a href="{AUTH_LOGIN_ROUTE}">Request a magic link</a></p>
        </section>
        """,
    )


def render_intake_page(
    session: dict[str, str],
    *,
    raw_text: str = "",
    error: str | None = None,
    session_id: str | None = None,
    visit_count: int | None = None,
    designer_email: str | None = None,
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
    designer_markup = (
        f'<p class="session-note">Signed in as <code>{html.escape(designer_email)}</code></p>'
        if designer_email
        else ""
    )
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
            {designer_markup}
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
          <div class="form-footer">
            <span>Approved evidence is ready for the next step.</span>
            <a class="primary-action" href="{SYNTHESIS_ROUTE}">Continue to synthesis</a>
          </div>
        </section>
        """,
    )


def render_synthesis_review_page(
    session: dict[str, str],
    *,
    brief: Mapping[str, object] | None = None,
    error: str | None = None,
    cached: bool = False,
    empty_state: EmptyStateGuidance | None = None,
) -> str:
    intake_id = session.get("intake_id", "")
    error_markup = f'<p class="validation" role="alert">{html.escape(error)}</p>' if error else ""
    if empty_state is not None:
        content = _empty_state_content("Synthesis", empty_state, active_id=intake_id)
    elif brief is None:
        content = f"""
        <section class="workspace">
          <h2>Synthesis</h2>
          <p>{html.escape(ROUTES_BY_PATH[SYNTHESIS_ROUTE].placeholder)}</p>
          <p>Current intake: <code>{html.escape(intake_id)}</code></p>
          {error_markup}
        </section>
        """
    else:
        ticket_items = _ticket_items(brief.get("candidate_ticket_breakdown"))
        cache_note = "Cached brief" if cached else "New brief"
        content = f"""
        <section class="workspace synthesis-brief">
          <h2>Synthesis</h2>
          <p class="session-note">{html.escape(cache_note)} for <code>{html.escape(intake_id)}</code>.</p>
          {error_markup}
          <article aria-label="Synthesis brief">
            {_brief_text_section("Problem", brief.get("problem"))}
            {_brief_text_section("User need", brief.get("user_need"))}
            {_evidence_section(brief.get("relevant_evidence"))}
            {_connected_concepts_section(brief.get("connected_concepts"))}
            {_brief_text_section("Proposed capability", brief.get("proposed_capability"))}
            <section class="brief-section">
              <h3>Candidate ticket</h3>
              {ticket_items}
            </section>
          </article>
          <form method="post" action="{SYNTHESIS_ROUTE}">
            <div class="form-footer">
              <span>Brief is read-only until ticket review.</span>
              <button type="submit">Continue to ticket review</button>
            </div>
          </form>
        </section>
        """
    return render_layout(title="Synthesis", active_path=SYNTHESIS_ROUTE, content=content)


def render_ticket_review_page(
    session: dict[str, str],
    *,
    markdown: str = "",
    error: str | None = None,
    validation_hints: tuple[str, ...] = (),
    empty_state: EmptyStateGuidance | None = None,
) -> str:
    if empty_state is not None:
        return render_layout(
            title="Ticket",
            active_path=TICKET_REVIEW_ROUTE,
            content=_empty_state_content("Ticket", empty_state),
        )
    escaped_markdown = html.escape(markdown)
    if validation_hints:
        hint_items = "".join(f"<li>{html.escape(item)}</li>" for item in validation_hints)
        error_markup = f'<div class="validation" role="alert"><ul>{hint_items}</ul></div>'
    else:
        error_markup = f'<p class="validation" role="alert">{html.escape(error)}</p>' if error else ""
    disabled_attr = 'disabled="disabled"' if validation_hints or error else ""
    session_note = (
        '<p class="session-note">Draft is stored in this browser session until export.</p>'
        if session.get(SESSION_TICKET_MARKDOWN_KEY)
        else ""
    )
    return render_layout(
        title="Ticket",
        active_path=TICKET_REVIEW_ROUTE,
        content=f"""
        <section class="workspace">
          <h2>Ticket</h2>
          <p>{html.escape(ROUTES_BY_PATH[TICKET_REVIEW_ROUTE].placeholder)}</p>
          <form method="post" action="{TICKET_REVIEW_ROUTE}" novalidate>
            <label for="ticket_markdown">Ticket draft</label>
            <textarea id="ticket_markdown" name="ticket_markdown" autofocus>{escaped_markdown}</textarea>
            <div class="form-footer">
              <span>{len(markdown)} characters</span>
              <button type="submit" name="action" value="advance" {disabled_attr}>Advance to export</button>
            </div>
            {error_markup}
            {session_note}
          </form>
        </section>
        """,
    )


def _empty_state_content(title: str, guidance: EmptyStateGuidance, *, active_id: str = "") -> str:
    active_markup = f'<p>Current intake: <code>{html.escape(active_id)}</code></p>' if active_id else ""
    return f"""
        <section class="workspace">
          <h2>{html.escape(title)}</h2>
          <p class="empty-state">{html.escape(guidance.title)}</p>
          {active_markup}
          <div class="form-footer">
            <a class="button" href="{html.escape(guidance.action_href)}">{html.escape(guidance.action_label)}</a>
          </div>
        </section>
        """


def render_export_page(review: ExportReviewResult) -> str:
    error_markup = f'<p class="validation" role="alert">{html.escape(review.message)}</p>' if review.message else ""
    result_markup = ""
    if review.result is not None:
        result_class = "export-result" if review.result.status in {"dry_run", "exported", "already_exported"} else "validation"
        escaped = html.escape(review.result.message)
        if review.result.url and review.result.status in {"exported", "already_exported"}:
            escaped_url = html.escape(review.result.url)
            result_markup = (
                f'<div class="{result_class}" role="status">'
                f"<p>{html.escape(review.result.status.replace('_', ' '))}</p>"
                f'<p><a href="{escaped_url}">{escaped_url}</a></p>'
                f"</div>"
            )
        else:
            result_markup = f'<pre class="{result_class}" role="status">{escaped}</pre>'

    if review.ticket_path is None or not review.title:
        summary_markup = '<p class="empty-state">No export-ready ticket is available.</p>'
        actions = f'<div class="form-footer"><a href="{TICKET_REVIEW_ROUTE}">Back to ticket review</a></div>'
    else:
        summary_markup = f"""
          <dl class="export-summary">
            <dt>Title</dt>
            <dd>{html.escape(review.title)}</dd>
            <dt>Body preview</dt>
            <dd>{html.escape(review.body_preview)}</dd>
          </dl>
        """
        actions = """
          <div class="form-footer">
            <button type="submit" name="action" value="back" class="secondary">Back</button>
            <span>Dry-run previews the Linear payload without creating an issue.</span>
            <button type="submit" name="action" value="dry-run">Dry-run</button>
            <button type="submit" name="action" value="export">Export</button>
          </div>
        """

    return render_layout(
        title="Export",
        active_path="/export",
        content=f"""
        <section class="workspace">
          <h2>Export</h2>
          {error_markup}
          {summary_markup}
          <form method="post" action="/export" novalidate>
            {actions}
          </form>
          {result_markup}
        </section>
        """,
    )


def render_observation_forbidden_page(session_id: str) -> str:
    return render_layout(
        title="Observation log unavailable",
        active_path=None,
        content=f"""
        <section class="workspace">
          <h2>Observation log unavailable</h2>
          <p>Session <code>{html.escape(session_id)}</code> is only readable by the session author or founder.</p>
        </section>
        """,
    )


def render_observation_log_page(session_id: str, *, events: Iterable[ObservationEvent]) -> str:
    event_rows = []
    for event in events:
        request = html.escape(json.dumps(dict(event.request), sort_keys=True))
        response = html.escape(json.dumps(dict(event.response), sort_keys=True))
        error = html.escape(event.error or "")
        event_rows.append(
            f"""
            <tr>
              <td>{event.id}</td>
              <td><time>{html.escape(event.occurred_at)}</time></td>
              <td>{html.escape(event.event_type)}</td>
              <td>{html.escape(event.route)}</td>
              <td>{html.escape(event.action)}</td>
              <td><code>{request}</code></td>
              <td><code>{response}</code></td>
              <td>{error}</td>
            </tr>
            """
        )
    rows = "".join(event_rows) or '<tr><td colspan="8" class="empty-state">No observation events were captured for this session.</td></tr>'
    return render_layout(
        title="Observation log",
        active_path=None,
        content=f"""
        <section class="workspace observation-log">
          <h2>Observation log</h2>
          <p>Session <code>{html.escape(session_id)}</code></p>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Timestamp</th>
                <th>Event</th>
                <th>Route</th>
                <th>Action</th>
                <th>Input</th>
                <th>Output</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        """,
    )


def render_peer_onboarding_page(session: Mapping[str, str], *, template: Mapping[str, object]) -> str:
    author = template.get("author", {})
    author_email = ""
    if isinstance(author, Mapping):
        author_email = str(author.get("email", ""))
    if not author_email:
        author_email = str(session.get("user_email", ""))
    schema_version = str(template.get("schema_version", "unknown"))
    section_markup = "\n".join(_peer_onboarding_section_markup(section) for section in ordered_peer_onboarding_sections(template))
    if not section_markup:
        section_markup = '<p class="empty-state">No peer onboarding sections are available.</p>'

    return render_layout(
        title="Peer onboarding",
        active_path=PEER_ONBOARDING_ROUTE,
        content=f"""
        <section class="workspace peer-onboarding">
          <h2>Peer onboarding</h2>
          <p>{html.escape(ROUTES_BY_PATH[PEER_ONBOARDING_ROUTE].placeholder)}</p>
          <p>Designer-to-designer transfer artifact for the active wizard workflow.</p>
          <p class="session-note">Schema <code>{html.escape(schema_version)}</code> authored by <code>{html.escape(author_email)}</code>.</p>
          <article aria-label="Peer onboarding template">
            {section_markup}
          </article>
        </section>
        <aside class="side-panel" aria-label="Wizard context">
          <h3>Wizard context</h3>
          <ol class="wizard-context">
            <li><a href="/intake">Intake</a></li>
            <li><a href="{RESEARCH_APPROVAL_ROUTE}">Research approval</a></li>
            <li><a href="{SYNTHESIS_ROUTE}">Synthesis</a></li>
            <li><a href="{TICKET_REVIEW_ROUTE}">Ticket</a></li>
            <li><a href="/export">Export</a></li>
          </ol>
        </aside>
        """,
        shell_class="shell",
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


def render_peer_onboarding_artifact_page(
    artifact: PeerOnboardingArtifact,
    *,
    artifacts: Iterable[PeerOnboardingArtifact] = (),
    errors: Iterable[str] = (),
) -> str:
    error_items = "".join(f"<li>{html.escape(error)}</li>" for error in errors)
    error_markup = f'<div class="validation" role="alert"><ul>{error_items}</ul></div>' if error_items else ""
    artifact_list = tuple(sorted(artifacts or (artifact,), key=lambda item: item.generation, reverse=True))
    generation_items = "".join(
        f"<li><strong>Generation {item.generation}</strong>: {html.escape(item.title)} "
        f"<span>for <code>{html.escape(item.audience_id)}</code></span></li>"
        for item in artifact_list
    )
    generation_markup = f"""
          <section class="brief-section">
            <h3>Available generations</h3>
            <ol class="source-list">{generation_items}</ol>
          </section>
    """
    section_markup = "\n".join(_peer_onboarding_section_markup(section) for section in artifact.sections)
    example_markup = '<ol class="source-list">' + "".join(
        _peer_example_markup(example) for example in artifact.intake_examples
    ) + "</ol>"
    source_nodes = ", ".join(f"<code>{html.escape(node)}</code>" for node in artifact.source_nodes)
    return render_layout(
        title=artifact.title,
        active_path=PEER_ONBOARDING_ROUTE,
        content=f"""
        <section class="workspace peer-onboarding">
          <h2>{html.escape(artifact.title)}</h2>
          <p>{html.escape(ROUTES_BY_PATH[PEER_ONBOARDING_ROUTE].placeholder)}</p>
          <p>Showing generation {artifact.generation} for <code>{html.escape(artifact.audience_id)}</code>.</p>
          <p>Author: <code>{html.escape(artifact.author_id)}</code> &lt;{html.escape(artifact.author_email)}&gt;</p>
          <p>Template: <code>{html.escape(artifact.template_id)}</code></p>
          {error_markup}
          {generation_markup}
          <article aria-label="Peer onboarding template">
            {section_markup}
          </article>
          <section class="brief-section">
            <h3>Original intake examples</h3>
            {example_markup}
          </section>
          <section class="brief-section">
            <h3>Graph sources</h3>
            <p>{source_nodes}</p>
          </section>
        </section>
        <aside class="side-panel" aria-label="Wizard context">
          <h3>Wizard context</h3>
          <ol class="wizard-context">
            <li><a href="/intake">Intake</a></li>
            <li><a href="{RESEARCH_APPROVAL_ROUTE}">Research approval</a></li>
            <li><a href="{SYNTHESIS_ROUTE}">Synthesis</a></li>
            <li><a href="{TICKET_REVIEW_ROUTE}">Ticket</a></li>
            <li><a href="/export">Export</a></li>
          </ol>
        </aside>
        """,
        shell_class="shell",
    )


def _peer_example_markup(example: object) -> str:
    payload = example if isinstance(example, Mapping) else {}
    href = str(payload.get("href") or "")
    title = str(payload.get("title") or href)
    raw_intake = str(payload.get("raw_intake") or "")
    why = str(payload.get("why_it_helped") or "")
    return f"""
    <li class="source-option">
      <div>
        <h3><a href="/{html.escape(href)}">{html.escape(title)}</a></h3>
        <p><strong>Original intake:</strong> {html.escape(raw_intake)}</p>
        <p>{html.escape(why)}</p>
      </div>
    </li>
    """


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
    input, textarea {{ width: 100%; border: 1px solid var(--line); border-radius: 6px; padding: 12px; color: var(--ink); font: inherit; background: #fff; }}
    textarea {{ min-height: 280px; resize: vertical; }}
    input:focus, textarea:focus {{ outline: 3px solid #99f6e4; border-color: var(--accent); }}
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
    .brief-section {{ border-top: 1px solid var(--line); padding-top: 18px; margin-top: 18px; }}
    .brief-section p {{ margin: 0 0 10px; }}
    .brief-list {{ margin: 0; padding-left: 20px; }}
    .peer-fields {{ display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 12px 18px; margin: 16px 0 0; }}
    .peer-fields dt {{ color: var(--muted); font-weight: 650; }}
    .peer-fields dd {{ margin: 0; overflow-wrap: anywhere; }}
    .wizard-context, .wizard-watchouts {{ margin: 0; padding-left: 20px; }}
    .wizard-watchouts li {{ margin-bottom: 10px; }}
    .wizard-watchouts p {{ margin: 4px 0 0; }}
    .concept-list, .ticket-list {{ display: grid; gap: 12px; list-style: none; margin: 0; padding: 0; }}
    .concept-card, .ticket-card {{ border: 1px solid var(--line); border-radius: 6px; padding: 14px; }}
    .concept-card.prior {{ border-color: #b7791f; background: #fffbeb; }}
    .concept-meta {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; }}
    .concept-badge {{ border-radius: 999px; padding: 2px 8px; background: #e6fffa; color: #0f766e; font-size: 12px; font-weight: 700; }}
    .concept-badge.prior {{ background: #fef3c7; color: #92400e; }}
    details.brief-section summary {{ cursor: pointer; font-size: 18px; font-weight: 700; margin-bottom: 16px; }}
    .export-summary {{ display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 12px 18px; margin: 22px 0; }}
    .export-summary dt {{ color: var(--muted); font-weight: 650; }}
    .export-summary dd {{ margin: 0; overflow-wrap: anywhere; }}
    .export-result {{ background: #ecfdf5; border: 1px solid #99f6e4; border-radius: 6px; margin-top: 18px; padding: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-top: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
    td code {{ display: block; max-width: 260px; overflow-wrap: anywhere; white-space: normal; }}
    button, a {{ color: var(--accent); font-weight: 650; }}
    button, a.button {{ border: 0; border-radius: 6px; background: var(--accent); color: white; padding: 10px 14px; cursor: pointer; font: inherit; text-decoration: none; }}
    button:disabled {{ opacity: 0.5; background: #c4cdd6; cursor: not-allowed; color: #4a5568; }}
    button.secondary {{ background: #edf2f7; color: var(--ink); }}
    .primary-action {{ display: inline-block; border-radius: 6px; background: var(--accent); color: white; padding: 10px 14px; text-decoration: none; }}
    .validation {{ color: var(--danger); margin: 12px 0 0; font-weight: 650; }}
    .session, .session-note {{ color: var(--muted); margin-bottom: 0; }}
    .dev-details {{ margin-top: 16px; }}
    .dev-details summary {{ cursor: pointer; font-weight: 650; }}
    .dev-details p {{ margin: 8px 0 0; }}
    code {{ background: #edf2f7; padding: 2px 4px; border-radius: 4px; }}
    @media (max-width: 760px) {{
      .shell {{ grid-template-columns: minmax(0, 1fr); padding: 20px 12px; }}
      .breadcrumbs {{ padding: 0 12px; }}
      .form-footer {{ align-items: stretch; flex-direction: column; }}
      .source-option {{ grid-template-columns: minmax(0, 1fr); }}
      .peer-fields {{ grid-template-columns: minmax(0, 1fr); }}
      button, a.button, .primary-action {{ width: 100%; text-align: center; }}
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


def _flatten_form_fields(fields: Mapping[str, list[str]]) -> dict[str, object]:
    flattened: dict[str, object] = {}
    for key, values in fields.items():
        flattened[str(key)] = values[0] if len(values) == 1 else list(values)
    return flattened


def _observation_session_id(session: Mapping[str, str]) -> str:
    return str(session.get("intake_id") or session.get("research_id") or "").strip()


def _is_observation_log_route(path: str) -> bool:
    return _observation_session_id_from_path(path) is not None


def _observation_session_id_from_path(path: str) -> str | None:
    if not path.startswith(OBSERVATION_LOG_ROUTE_PREFIX) or not path.endswith("/observation"):
        return None
    session_id = path[len(OBSERVATION_LOG_ROUTE_PREFIX) : -len("/observation")].strip("/")
    return session_id or None


def _session_cookie(session: dict[str, str]) -> str:
    jar = cookies.SimpleCookie()
    jar[SESSION_COOKIE_NAME] = json.dumps(session, sort_keys=True, separators=(",", ":"))
    jar[SESSION_COOKIE_NAME]["path"] = "/"
    jar[SESSION_COOKIE_NAME]["httponly"] = True
    jar[SESSION_COOKIE_NAME]["samesite"] = "Lax"
    return jar.output(header="").strip()


def _require_user(environ: Mapping[str, object]) -> AuthenticatedUser:
    user = environ.get("overture.authenticated_user")
    if isinstance(user, AuthenticatedUser):
        return user
    raise RuntimeError("authenticated user required after auth gate")


def _session_for_user(session: Mapping[str, str], user: AuthenticatedUser) -> dict[str, str]:
    if session.get("user_id") and session.get("user_id") != user.user_id:
        return {"user_id": user.user_id, "user_email": user.email}
    next_session = {str(key): str(value) for key, value in session.items()}
    next_session["user_id"] = user.user_id
    next_session["user_email"] = user.email
    next_session["designer_email"] = user.email
    return next_session


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


def _synthesis_cache_path(store_dir: Path | str, intake_id: str) -> Path:
    return Path(store_dir) / "synthesis" / f"{intake_id}.json"


def _read_json(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _tag_json_file(path: Path, user: AuthenticatedUser) -> None:
    payload = dict(_read_json(path))
    payload["author_id"] = user.user_id
    payload["author_email"] = user.email
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_author_sidecar(path: Path, user: AuthenticatedUser) -> None:
    payload = {
        "author_id": user.user_id,
        "author_email": user.email,
        "artifact_path": str(path),
    }
    path.with_suffix(path.suffix + ".author.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _research_result_from_session(session: Mapping[str, str]) -> ResearchResult | None:
    payload = _session_json_map(session.get("research_result"))
    return _research_result_from_json(payload) if payload else None


def _research_result_from_json(payload: Mapping[str, object]) -> ResearchResult:
    items = []
    for item in payload.get("items", ()):
        if not isinstance(item, Mapping):
            continue
        source_payload = item.get("source", {})
        source = source_payload if isinstance(source_payload, Mapping) else {}
        claims = []
        for claim in item.get("claims", ()):
            if isinstance(claim, Mapping):
                claims.append(
                    ResearchClaim(
                        text=str(claim.get("text") or ""),
                        kind="inference" if claim.get("kind") == "inference" else "evidence",
                        confidence=float(claim.get("confidence") or 0),
                    )
                )
        items.append(
            ResearchItem(
                source=SourceReference(
                    title=str(source.get("title") or ""),
                    url=_optional_text(source.get("url")),
                    citation=_optional_text(source.get("citation")),
                ),
                summary=str(item.get("summary") or ""),
                claims=tuple(claim for claim in claims if claim.text),
                relevance_score=float(item.get("relevance_score") or 0),
                confidence=float(item.get("confidence") or 0),
            )
        )
    errors = []
    for error in payload.get("errors", ()):
        if isinstance(error, Mapping):
            errors.append(
                ResearchError(
                    code=str(error.get("code") or "adapter_failure"),  # type: ignore[arg-type]
                    message=str(error.get("message") or ""),
                    source=_optional_text(error.get("source")),
                )
            )
    return ResearchResult(intake_id=_optional_text(payload.get("intake_id")), items=tuple(items), errors=tuple(errors))


def _author_identity(session: Mapping[str, str]) -> dict[str, str]:
    author_id = str(session.get("author_id") or session.get("user_id") or "").strip()
    author_email = str(session.get("author_email") or session.get("user_email") or "").strip()
    identity: dict[str, str] = {}
    if author_id:
        identity["author_id"] = author_id
    if author_email:
        identity["author_email"] = author_email
    return identity


def _with_author_identity(payload: Mapping[str, object], session: Mapping[str, str]) -> dict[str, object]:
    next_payload = dict(payload)
    identity = _author_identity(session)
    if identity:
        next_payload.update(identity)
    return next_payload


def _ticket_markdown_with_author(markdown: str, session: Mapping[str, str]) -> str:
    identity = _author_identity(session)
    if not identity:
        return markdown
    author_lines = "\n".join(f"<!-- {key}: {value} -->" for key, value in sorted(identity.items()))
    if "\n## " in markdown:
        return markdown.replace("\n## ", f"\n{author_lines}\n\n## ", 1)
    return f"{markdown.rstrip()}\n\n{author_lines}\n"


def _synthesis_context_from_intake_research(
    intake: IntakeRecord,
    research: ResearchResult,
    *,
    user: AuthenticatedUser | None = None,
) -> GraphContext:
    author = _author_properties(user)
    records = research_result_to_graph_records(research)
    nodes = [
        {
            "id": f"userinput_{intake.id}",
            "type": "UserInput",
            "label": "Designer intake",
            "summary": intake.normalized_summary,
            "raw_text": intake.raw_text,
            "provenance": {"origin": "user_input", "source_refs": [intake.id], "confidence": "high"},
            **author,
        },
        {
            "id": f"need_{intake.id}",
            "type": "Need",
            "label": "Pre-ticket synthesis review",
            "summary": _first_inference(research)
            or "Designers need a read-only synthesis brief before committing to a generated ticket draft.",
            "provenance": {"origin": "research", "source_node_ids": [f"userinput_{intake.id}"], "confidence": "medium"},
            **author,
        },
        {
            "id": f"capability_{intake.id}_synthesis_review",
            "type": "Capability",
            "label": "Synthesis brief review",
            "summary": "Render approved research as a structured product and engineering brief before ticket review.",
            "provenance": {"origin": "synthesis", "source_node_ids": [f"need_{intake.id}"], "confidence": "high"},
            **author,
        },
        {
            "id": f"ticketcandidate_{intake.id}_ticket_review",
            "type": "TicketCandidate",
            "label": "Generate ticket from synthesis brief",
            "title": f"Draft ticket for {intake.normalized_summary[:72]}",
            "scope": "Convert the reviewed synthesis brief into a Symphony-ready ticket draft.",
            "validation_plan": ["Confirm the ticket review route receives the approved synthesis session."],
            "readiness": "draft",
            "provenance": {
                "origin": "synthesis",
                "source_node_ids": [f"capability_{intake.id}_synthesis_review"],
                "confidence": "medium",
            },
            **author,
        },
    ]
    edges = [
        {
            "id": f"need_{intake.id}__derived_from__userinput_{intake.id}",
            "type": "derived_from",
            "from": f"need_{intake.id}",
            "to": f"userinput_{intake.id}",
            **author,
        },
        {
            "id": f"capability_{intake.id}_synthesis_review__addresses__need_{intake.id}",
            "type": "addresses",
            "from": f"capability_{intake.id}_synthesis_review",
            "to": f"need_{intake.id}",
            **author,
        },
        {
            "id": f"capability_{intake.id}_synthesis_review__suggests__ticketcandidate_{intake.id}_ticket_review",
            "type": "suggests",
            "from": f"capability_{intake.id}_synthesis_review",
            "to": f"ticketcandidate_{intake.id}_ticket_review",
            **author,
        },
    ]
    for record in records:
        if record.kind in {"Source", "ResearchItem", "Claim"}:
            properties = dict(record.properties)
            if record.kind == "Claim" and "text" in properties:
                properties["statement"] = properties["text"]
            nodes.append({"id": record.key, "type": record.kind, "kind": record.kind, **properties, **author})
        else:
            edge = {"id": record.key, "type": record.kind, "kind": record.kind, **record.properties, **author}
            edges.append(edge)
    for index, item in enumerate(research.items):
        evidence_id = f"evidence_{intake.id}_{index}"
        nodes.append(
            {
                "id": evidence_id,
                "type": "Evidence",
                "label": item.source.title,
                "summary": item.summary,
                "provenance": {"origin": "research", "source_refs": [item.source.reference], "confidence": item.confidence},
                **author,
            }
        )
        edges.append(
            {
                "id": f"{evidence_id}__supports__capability_{intake.id}_synthesis_review",
                "type": "supports",
                "from": evidence_id,
                "to": f"capability_{intake.id}_synthesis_review",
                **author,
            }
        )
    return GraphContext(nodes=tuple(nodes), edges=tuple(edges))


def _author_properties(user: AuthenticatedUser | None) -> dict[str, str]:
    if user is None:
        return {}
    return {"author_id": user.user_id, "author_email": user.email}


def _graph_records_from_context(context: GraphContext, user: AuthenticatedUser) -> tuple[GraphRecord, ...]:
    records: list[GraphRecord] = []
    for node in context.nodes:
        if not isinstance(node, Mapping):
            continue
        node_id = str(node.get("id") or "").strip()
        kind = str(node.get("kind") or node.get("type") or "").strip()
        if not node_id or kind not in NODE_KINDS:
            continue
        properties = {
            str(key): value
            for key, value in node.items()
            if str(key) not in {"id", "kind", "type"}
        }
        properties.update(_author_properties(user))
        records.append(GraphRecord(kind=kind, key=node_id, properties=properties))  # type: ignore[arg-type]
    for edge in context.edges:
        if not isinstance(edge, Mapping):
            continue
        from_id = str(edge.get("from") or "").strip()
        to_id = str(edge.get("to") or "").strip()
        kind = str(edge.get("kind") or edge.get("type") or "").strip()
        if not from_id or not to_id or not kind:
            continue
        if kind not in EDGE_KINDS:
            continue
        properties = {
            str(key): value
            for key, value in edge.items()
            if str(key) not in {"id", "kind", "type"}
        }
        properties.update(_author_properties(user))
        records.append(GraphRecord(kind=kind, key=str(edge.get("id") or f"{from_id}:{kind}:{to_id}"), properties=properties))  # type: ignore[arg-type]
    return tuple(records)


def _first_inference(research: ResearchResult) -> str:
    for item in research.items:
        for claim in item.claims:
            if claim.kind == "inference" and claim.text:
                return claim.text
    return ""


def _brief_text_section(title: str, value: object) -> str:
    return f"""
    <section class="brief-section">
      <h3>{html.escape(title)}</h3>
      <p>{html.escape(str(value or "Not provided."))}</p>
    </section>
    """


def _evidence_section(value: object) -> str:
    payload = value if isinstance(value, Mapping) else {}
    evidence = _list_items(payload.get("evidence"), lambda item: _summary_line(item, "summary"))
    claims = _list_items(payload.get("evidence_backed_claims"), lambda item: _summary_line(item, "statement"))
    assumptions = _list_items(payload.get("assumptions"), lambda item: _summary_line(item, "statement"))
    return f"""
    <section class="brief-section">
      <h3>Evidence</h3>
      <h4>References</h4>
      {evidence}
      <h4>Claims</h4>
      {claims}
      <h4>Assumptions</h4>
      {assumptions}
    </section>
    """


def _connected_concepts_section(value: object) -> str:
    concepts = value if _is_sequence(value) else []
    items = []
    for concept in concepts:
        if not isinstance(concept, Mapping):
            continue
        from_prior = bool(concept.get("from_prior"))
        badge = "Prior run" if from_prior else "Current run"
        prior_class = " prior" if from_prior else ""
        items.append(
            f"""
            <li class="concept-card{prior_class}">
              <div class="concept-meta">
                <span class="concept-badge{prior_class}">{html.escape(badge)}</span>
                <strong>{html.escape(str(concept.get("label") or concept.get("id") or "Untitled concept"))}</strong>
                <span>{html.escape(str(concept.get("type") or "Concept"))}</span>
              </div>
              <p>{html.escape(str(concept.get("summary") or "No summary provided."))}</p>
            </li>
            """
        )
    if not items:
        items.append('<li class="empty-state">No connected concepts were produced.</li>')
    return f"""
    <details class="brief-section" open>
      <summary>Connected concepts</summary>
      <ul class="concept-list">{''.join(items)}</ul>
    </details>
    """


def _ticket_items(value: object) -> str:
    tickets = value if _is_sequence(value) else []
    items = []
    for ticket in tickets:
        if not isinstance(ticket, Mapping):
            continue
        validation = _list_items(ticket.get("validation_plan"), lambda item: str(item))
        items.append(
            f"""
            <li class="ticket-card">
              <h4>{html.escape(str(ticket.get("title") or "Untitled ticket"))}</h4>
              <p>{html.escape(str(ticket.get("scope") or "No scope provided."))}</p>
              <h4>Validation plan</h4>
              {validation}
            </li>
            """
        )
    if not items:
        items.append('<li class="empty-state">No candidate ticket was produced.</li>')
    return f'<ul class="ticket-list">{"".join(items)}</ul>'


def _list_items(value: object, formatter: Callable[[object], str]) -> str:
    values = value if _is_sequence(value) else []
    items = [f"<li>{html.escape(formatter(item))}</li>" for item in values if formatter(item)]
    if not items:
        items = ['<li class="empty-state">None.</li>']
    return f'<ul class="brief-list">{"".join(items)}</ul>'


def _summary_line(item: object, key: str) -> str:
    if isinstance(item, Mapping):
        text = str(item.get(key) or item.get("id") or "").strip()
        refs = item.get("source_refs")
        if _is_sequence(refs) and refs:
            return f"{text} ({', '.join(str(ref) for ref in refs)})"
        return text
    return str(item)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_sequence(value: object) -> bool:
    return isinstance(value, (list, tuple))
