"""Minimal Linear GraphQL API client.

This module assumes Linear's `issueCreate` GraphQL shape documented at
https://developers.linear.app/docs/graphql/working-with-the-graphql-api.
It intentionally uses only Python's standard library for runtime code.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ISSUE_CREATE_MUTATION = (
    "mutation IssueCreate($input: IssueCreateInput!) { "
    "issueCreate(input: $input) { success issue { id identifier url } } "
    "}"
)

ISSUE_LABELS_QUERY = (
    "query IssueLabels($teamId: String!, $name: String!) { "
    "issueLabels(filter: { team: { id: { eq: $teamId } }, name: { eqIgnoreCase: $name } }, first: 2) { "
    "nodes { id name } "
    "} "
    "}"
)

PROJECT_MILESTONES_QUERY = (
    "query ProjectMilestones($projectId: String!, $name: String!) { "
    "projectMilestones(filter: { project: { id: { eq: $projectId } }, name: { eqIgnoreCase: $name } }, first: 2) { "
    "nodes { id name } "
    "} "
    "}"
)


@dataclass(frozen=True)
class CreatedIssue:
    id: str
    identifier: str
    url: str


class LinearAPIError(RuntimeError):
    """Raised when Linear rejects a request or returns an invalid response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        errors: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors = errors


class LinearRateLimitError(LinearAPIError):
    """Raised for HTTP 429 responses from Linear."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = 429,
        errors: tuple[str, ...] = (),
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, errors=errors)
        self.retry_after = retry_after


class LinearClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.linear.app/graphql",
        opener: Callable[[Request], Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self._opener = opener or urlopen

    def create_issue(
        self,
        *,
        team_id: str,
        title: str,
        description: str,
        project_id: str | None = None,
        priority: int | None = None,
        sprint_label: str | None = None,
        milestone: str | None = None,
    ) -> CreatedIssue:
        issue_input = {
            "teamId": team_id,
            "title": title,
            "description": description,
        }
        if project_id is not None:
            issue_input["projectId"] = project_id
        if priority is not None:
            issue_input["priority"] = priority
        if sprint_label is not None:
            issue_input["labelIds"] = [self._resolve_issue_label_id(team_id, sprint_label)]
        if milestone is not None:
            if project_id is None:
                raise LinearAPIError("project id is required when frontmatter includes milestone")
            issue_input["projectMilestoneId"] = self._resolve_project_milestone_id(project_id, milestone)

        response_payload = self._post_graphql(
            {
                "query": ISSUE_CREATE_MUTATION,
                "variables": {"input": issue_input},
            }
        )
        errors = _graphql_errors(response_payload)
        if errors:
            raise LinearAPIError(errors[0], errors=errors)

        issue_create = response_payload.get("data", {}).get("issueCreate")
        if not isinstance(issue_create, dict):
            raise LinearAPIError("Linear response missing data.issueCreate")
        if issue_create.get("success") is not True:
            raise LinearAPIError("Linear issueCreate returned success=false")

        issue = issue_create.get("issue")
        if not isinstance(issue, dict):
            raise LinearAPIError("Linear response missing data.issueCreate.issue")

        try:
            return CreatedIssue(
                id=issue["id"],
                identifier=issue["identifier"],
                url=issue["url"],
            )
        except KeyError as exc:
            raise LinearAPIError(f"Linear issue response missing field: {exc.args[0]}") from exc

    def _resolve_issue_label_id(self, team_id: str, name: str) -> str:
        payload = self._post_graphql(
            {
                "query": ISSUE_LABELS_QUERY,
                "variables": {"teamId": team_id, "name": name},
            }
        )
        errors = _graphql_errors(payload)
        if errors:
            raise LinearAPIError(errors[0], errors=errors)
        return _single_node_id(payload, ("data", "issueLabels", "nodes"), "issue label", name)

    def _resolve_project_milestone_id(self, project_id: str, name: str) -> str:
        payload = self._post_graphql(
            {
                "query": PROJECT_MILESTONES_QUERY,
                "variables": {"projectId": project_id, "name": name},
            }
        )
        errors = _graphql_errors(payload)
        if errors:
            raise LinearAPIError(errors[0], errors=errors)
        return _single_node_id(payload, ("data", "projectMilestones", "nodes"), "project milestone", name)

    def _post_graphql(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url,
            data=body,
            headers={
                "Authorization": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            response = self._opener(request)
        except HTTPError as exc:
            response_body = exc.read()
            self._raise_http_error(exc.code, response_body, exc.headers)

        status_code = _response_status(response)
        response_body = response.read()
        if status_code is not None and not 200 <= status_code < 300:
            self._raise_http_error(status_code, response_body, getattr(response, "headers", None))

        return _parse_json_response(response_body, status_code=status_code)

    def _raise_http_error(self, status_code: int, body: bytes, headers: Any) -> None:
        errors = _graphql_errors(_parse_json_response(body, status_code=status_code, allow_empty=True))
        detail = f": {errors[0]}" if errors else ""
        message = f"Linear API request failed with HTTP {status_code}{detail}"
        if status_code == 429:
            raise LinearRateLimitError(
                message,
                status_code=status_code,
                errors=errors,
                retry_after=_retry_after(headers),
            )
        raise LinearAPIError(message, status_code=status_code, errors=errors)


def _response_status(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if status is None:
        status = getattr(response, "code", None)
    return status


def _parse_json_response(
    body: bytes,
    *,
    status_code: int | None,
    allow_empty: bool = False,
) -> dict[str, Any]:
    if allow_empty and not body:
        return {}
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        label = f"HTTP {status_code}" if status_code is not None else "response"
        raise LinearAPIError(f"Linear API returned invalid JSON for {label}", status_code=status_code) from exc
    if not isinstance(payload, dict):
        raise LinearAPIError("Linear API returned a non-object JSON response", status_code=status_code)
    return payload


def _graphql_errors(payload: dict[str, Any]) -> tuple[str, ...]:
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return ()

    messages: list[str] = []
    for error in errors:
        if isinstance(error, dict):
            message = error.get("message")
            messages.append(message if isinstance(message, str) else json.dumps(error, sort_keys=True))
        else:
            messages.append(str(error))
    return tuple(messages)


def _single_node_id(payload: dict[str, Any], path: tuple[str, ...], kind: str, name: str) -> str:
    value: Any = payload
    for segment in path:
        if not isinstance(value, dict):
            raise LinearAPIError(f"Linear response missing {kind} lookup nodes")
        value = value.get(segment)
    if not isinstance(value, list):
        raise LinearAPIError(f"Linear response missing {kind} lookup nodes")
    if len(value) == 0:
        raise LinearAPIError(f"Linear {kind} not found: {name}")
    if len(value) > 1:
        raise LinearAPIError(f"Linear {kind} is ambiguous: {name}")
    node = value[0]
    if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
        raise LinearAPIError(f"Linear {kind} lookup returned an invalid node")
    return node["id"]


def _retry_after(headers: Any) -> str | None:
    if headers is None:
        return None
    get = getattr(headers, "get", None)
    if callable(get):
        return get("Retry-After")
    return None
