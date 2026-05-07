"""Magic-link authentication for designer identities.

The default sender writes links to a local JSONL outbox so the local-only wizard
can be exercised without a new runtime dependency. For production deployment,
configure a transactional email bridge with ``OVERTURE_MAGIC_LINK_WEBHOOK_URL``;
when delivery fails, a founder can generate an emergency token from a Python
shell by instantiating ``MagicLinkAuth`` and calling ``issue_session(email)``.

Magic links expire after 15 minutes and are single-use. Auth session tokens
expire after 8 hours and are refreshed on every authenticated wizard response
while the session is active.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import cookies
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from typing import Callable, Mapping
from urllib import request

MAGIC_LINK_TTL_SECONDS = 15 * 60
SESSION_TOKEN_TTL_SECONDS = 8 * 60 * 60
AUTH_COOKIE_NAME = "overture_auth"


@dataclass(frozen=True)
class DesignerSession:
    email: str
    expires_at: int


@dataclass(frozen=True)
class MagicLinkDelivery:
    email: str
    link: str
    outbox_path: Path | None = None


class MagicLinkSender:
    def send(self, email: str, link: str) -> MagicLinkDelivery:
        raise NotImplementedError


class FileMagicLinkSender(MagicLinkSender):
    """Append generated magic links to a local JSONL outbox."""

    def __init__(self, outbox_path: Path | str) -> None:
        self.outbox_path = Path(outbox_path)

    def send(self, email: str, link: str) -> MagicLinkDelivery:
        self.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"email": email, "link": link, "created_at": int(time.time())}
        with self.outbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        return MagicLinkDelivery(email=email, link=link, outbox_path=self.outbox_path)


class WebhookMagicLinkSender(MagicLinkSender):
    """Send generated magic links through a configured transactional email bridge."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, email: str, link: str) -> MagicLinkDelivery:
        body = json.dumps({"email": email, "magic_link": link}).encode("utf-8")
        req = request.Request(
            self.webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=10) as response:  # nosec B310 - operator configured endpoint
            if response.status >= 400:
                raise RuntimeError(f"magic-link delivery failed with HTTP {response.status}")
        return MagicLinkDelivery(email=email, link=link)


class MagicLinkAuth:
    def __init__(
        self,
        *,
        secret: str | bytes | None = None,
        sender: MagicLinkSender | None = None,
        base_url: str = "http://localhost:8765",
        now: Callable[[], float] | None = None,
    ) -> None:
        self.secret = _secret_bytes(secret)
        self.sender = sender or FileMagicLinkSender(Path(".overture") / "magic-links.jsonl")
        self.base_url = base_url.rstrip("/")
        self.now = now or time.time
        self._pending_links: dict[str, tuple[str, int]] = {}

    def request_link(self, email: str) -> MagicLinkDelivery:
        normalized = _normalize_email(email)
        token = secrets.token_urlsafe(32)
        expires_at = int(self.now()) + MAGIC_LINK_TTL_SECONDS
        self._pending_links[token] = (normalized, expires_at)
        return self.sender.send(normalized, f"{self.base_url}/auth/consume?token={token}")

    def consume_link(self, token: str) -> str | None:
        record = self._pending_links.pop(token, None)
        if record is None:
            return None
        email, expires_at = record
        if expires_at <= int(self.now()):
            return None
        return self.issue_session(email)

    def issue_session(self, email: str, *, ttl_seconds: int = SESSION_TOKEN_TTL_SECONDS) -> str:
        expires_at = int(self.now()) + ttl_seconds
        payload = {
            "email": _normalize_email(email),
            "exp": expires_at,
            "nonce": secrets.token_urlsafe(12),
        }
        body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = _sign(body, self.secret)
        return f"{body}.{signature}"

    def authenticate(self, environ: Mapping[str, object]) -> DesignerSession | None:
        token = _bearer_token(environ) or _cookie_token(environ)
        if not token:
            return None
        return self.validate_session(token)

    def validate_session(self, token: str) -> DesignerSession | None:
        try:
            body, signature = token.split(".", 1)
        except ValueError:
            return None
        if not hmac.compare_digest(_sign(body, self.secret), signature):
            return None
        try:
            payload = json.loads(_unb64(body).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        expires_at = int(payload.get("exp") or 0)
        if expires_at <= int(self.now()):
            return None
        email = str(payload.get("email") or "").strip().lower()
        if "@" not in email:
            return None
        return DesignerSession(email=email, expires_at=expires_at)

    def refresh_session(self, session: DesignerSession) -> str:
        return self.issue_session(session.email)


def sender_from_env(store_dir: Path | str) -> MagicLinkSender:
    webhook_url = os.environ.get("OVERTURE_MAGIC_LINK_WEBHOOK_URL")
    if webhook_url:
        return WebhookMagicLinkSender(webhook_url)
    outbox = os.environ.get("OVERTURE_MAGIC_LINK_OUTBOX")
    return FileMagicLinkSender(Path(outbox) if outbox else Path(store_dir) / "magic-links.jsonl")


def auth_cookie(token: str) -> str:
    jar = cookies.SimpleCookie()
    jar[AUTH_COOKIE_NAME] = token
    jar[AUTH_COOKIE_NAME]["path"] = "/"
    jar[AUTH_COOKIE_NAME]["httponly"] = True
    jar[AUTH_COOKIE_NAME]["samesite"] = "Lax"
    jar[AUTH_COOKIE_NAME]["max-age"] = str(SESSION_TOKEN_TTL_SECONDS)
    return jar.output(header="").strip()


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("Enter a valid email address.")
    return normalized


def _secret_bytes(secret: str | bytes | None) -> bytes:
    if isinstance(secret, bytes):
        return secret
    if isinstance(secret, str) and secret:
        return secret.encode("utf-8")
    env_secret = os.environ.get("OVERTURE_AUTH_SECRET")
    if env_secret:
        return env_secret.encode("utf-8")
    return secrets.token_bytes(32)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(body: str, secret: bytes) -> str:
    digest = hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()
    return _b64(digest)


def _bearer_token(environ: Mapping[str, object]) -> str | None:
    header = str(environ.get("HTTP_AUTHORIZATION", "")).strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _cookie_token(environ: Mapping[str, object]) -> str | None:
    header = str(environ.get("HTTP_COOKIE", ""))
    if not header:
        return None
    jar = cookies.SimpleCookie()
    jar.load(header)
    morsel = jar.get(AUTH_COOKIE_NAME)
    return morsel.value if morsel else None
