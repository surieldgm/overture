"""Stub-friendly magic-link authentication for local wizard tests."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from uuid import NAMESPACE_URL, uuid5


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str


class MagicLinkAuth:
    """In-memory magic-link auth backend for local and test flows.

    The backend deliberately does not send email. Callers can issue a token and
    then verify that token through the UI route, which lets tests exercise the
    same session boundary without external network access.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, AuthenticatedUser] = {}

    def issue_token(self, email: str) -> str:
        normalized = email.strip().lower()
        if not normalized or "@" not in normalized:
            raise ValueError("email must be a non-empty address")
        token = secrets.token_urlsafe(24)
        self._tokens[token] = AuthenticatedUser(user_id=_stable_user_id(normalized), email=normalized)
        return token

    def verify_token(self, token: str) -> AuthenticatedUser | None:
        return self._tokens.pop(token.strip(), None)


def _stable_user_id(email: str) -> str:
    return f"user_{uuid5(NAMESPACE_URL, f'overture-auth:{email}').hex}"
