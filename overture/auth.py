"""Authenticated user extraction for local Overture UI requests.

The M3 UI treats the auth cookie as the handoff from the magic-link flow and
binds wizard state to the authenticated designer identity found there. If a
shared browser reuses a wizard session while the authenticated user changes, the
UI discards the stale wizard state and starts a user-scoped session instead. A
token may include the issuing IP address or user agent; when present, either
value changing requires re-authentication.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import cookies
import json
from typing import Mapping

AUTH_COOKIE_NAME = "overture_auth"
LOGIN_ROUTE = "/login"


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str


def issue_session_token(
    user_id: str,
    *,
    email: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> str:
    payload: dict[str, str] = {"user_id": _require_text(user_id, "user_id")}
    payload["email"] = email.strip() if email and email.strip() else payload["user_id"]
    if ip_address:
        payload["ip_address"] = ip_address
    if user_agent:
        payload["user_agent"] = user_agent
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def authenticated_user_from_environ(environ: Mapping[str, object]) -> AuthenticatedUser | None:
    header = str(environ.get("HTTP_COOKIE", ""))
    if not header:
        return None
    jar = cookies.SimpleCookie()
    try:
        jar.load(header)
    except cookies.CookieError:
        return None
    morsel = jar.get(AUTH_COOKIE_NAME)
    if morsel is None:
        return None
    try:
        payload = json.loads(morsel.value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    expected_ip = payload.get("ip_address")
    if expected_ip and str(environ.get("REMOTE_ADDR", "")) != str(expected_ip):
        return None
    expected_user_agent = payload.get("user_agent")
    if expected_user_agent and str(environ.get("HTTP_USER_AGENT", "")) != str(expected_user_agent):
        return None

    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        return None
    email = str(payload.get("email") or user_id).strip() or user_id
    return AuthenticatedUser(user_id=user_id, email=email)


def auth_cookie(user_id: str, *, email: str | None = None) -> str:
    jar = cookies.SimpleCookie()
    jar[AUTH_COOKIE_NAME] = issue_session_token(user_id, email=email)
    jar[AUTH_COOKIE_NAME]["path"] = "/"
    jar[AUTH_COOKIE_NAME]["httponly"] = True
    jar[AUTH_COOKIE_NAME]["samesite"] = "Lax"
    return jar.output(header="").strip()


def _require_text(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()
