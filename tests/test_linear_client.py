import json
import unittest
from urllib.error import HTTPError

from overture.linear_client import CreatedIssue, LinearAPIError, LinearClient, LinearRateLimitError


class StubResponse:
    def __init__(self, payload: dict[str, object], *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass


class LinearClientTests(unittest.TestCase):
    def test_create_issue_posts_expected_mutation_request(self) -> None:
        requests = []

        def opener(request):
            requests.append(request)
            return StubResponse(
                {
                    "data": {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "issue-id", "identifier": "ERI-1", "url": "https://linear.app/issue/ERI-1"},
                        }
                    }
                }
            )

        LinearClient(api_key="x", base_url="https://linear.test/graphql", opener=opener).create_issue(
            team_id="t",
            title="T",
            description="d",
        )

        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.full_url, "https://linear.test/graphql")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "x")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload,
            {
                "query": (
                    "mutation IssueCreate($input: IssueCreateInput!) { "
                    "issueCreate(input: $input) { success issue { id identifier url } } "
                    "}"
                ),
                "variables": {"input": {"teamId": "t", "title": "T", "description": "d"}},
            },
        )

    def test_create_issue_includes_project_id_when_provided(self) -> None:
        captured_payloads = []

        def opener(request):
            captured_payloads.append(json.loads(request.data.decode("utf-8")))
            return StubResponse(
                {
                    "data": {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "issue-id", "identifier": "ERI-1", "url": "https://linear.app/issue/ERI-1"},
                        }
                    }
                }
            )

        LinearClient(api_key="x", opener=opener).create_issue(
            team_id="team-id",
            title="Title",
            description="Description",
            project_id="project-id",
        )

        self.assertEqual(captured_payloads[0]["variables"]["input"]["projectId"], "project-id")

    def test_create_issue_resolves_and_posts_metadata_ids(self) -> None:
        captured_payloads = []

        def opener(request):
            payload = json.loads(request.data.decode("utf-8"))
            captured_payloads.append(payload)
            query = payload["query"]
            if "IssueLabels" in query:
                return StubResponse({"data": {"issueLabels": {"nodes": [{"id": "label-id", "name": "m2-s1"}]}}})
            if "ProjectMilestones" in query:
                return StubResponse({"data": {"projectMilestones": {"nodes": [{"id": "milestone-id", "name": "M2"}]}}})
            return StubResponse(
                {
                    "data": {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "issue-id", "identifier": "ERI-1", "url": "https://linear.app/issue/ERI-1"},
                        }
                    }
                }
            )

        LinearClient(api_key="x", opener=opener).create_issue(
            team_id="team-id",
            title="Title",
            description="Description",
            project_id="project-id",
            priority=2,
            sprint_label="m2-s1",
            milestone="M2",
        )

        issue_input = captured_payloads[-1]["variables"]["input"]
        self.assertEqual(issue_input["priority"], 2)
        self.assertEqual(issue_input["labelIds"], ["label-id"])
        self.assertEqual(issue_input["projectMilestoneId"], "milestone-id")

    def test_create_issue_returns_created_issue_on_success(self) -> None:
        def opener(_request):
            return StubResponse(
                {
                    "data": {
                        "issueCreate": {
                            "success": True,
                            "issue": {
                                "id": "issue-id",
                                "identifier": "ERI-20",
                                "url": "https://linear.app/eria/issue/ERI-20/title",
                            },
                        }
                    }
                }
            )

        issue = LinearClient(api_key="x", opener=opener).create_issue(team_id="t", title="T", description="d")

        self.assertEqual(
            issue,
            CreatedIssue(id="issue-id", identifier="ERI-20", url="https://linear.app/eria/issue/ERI-20/title"),
        )

    def test_create_issue_raises_api_error_for_401_response(self) -> None:
        def opener(_request):
            return StubResponse({"errors": [{"message": "Unauthorized"}]}, status=401)

        with self.assertRaises(LinearAPIError) as error:
            LinearClient(api_key="bad-key", opener=opener).create_issue(team_id="t", title="T", description="d")

        self.assertEqual(error.exception.status_code, 401)
        self.assertIn("HTTP 401", str(error.exception))

    def test_create_issue_raises_api_error_for_http_error_exception(self) -> None:
        def opener(_request):
            raise HTTPError(
                url="https://linear.test/graphql",
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=StubResponse({"errors": [{"message": "Unauthorized"}]}, status=401),
            )

        with self.assertRaises(LinearAPIError) as error:
            LinearClient(api_key="bad-key", opener=opener).create_issue(team_id="t", title="T", description="d")

        self.assertEqual(error.exception.status_code, 401)
        self.assertIn("HTTP 401", str(error.exception))

    def test_create_issue_raises_api_error_for_graphql_errors(self) -> None:
        def opener(_request):
            return StubResponse({"errors": [{"message": "Team not found"}, {"message": "Second error"}]})

        with self.assertRaises(LinearAPIError) as error:
            LinearClient(api_key="x", opener=opener).create_issue(team_id="missing", title="T", description="d")

        self.assertEqual(error.exception.errors, ("Team not found", "Second error"))
        self.assertIn("Team not found", str(error.exception))

    def test_create_issue_raises_rate_limit_error_with_retry_after(self) -> None:
        def opener(_request):
            return StubResponse(
                {"errors": [{"message": "Rate limit exceeded"}]},
                status=429,
                headers={"Retry-After": "30"},
            )

        with self.assertRaises(LinearRateLimitError) as error:
            LinearClient(api_key="x", opener=opener).create_issue(team_id="t", title="T", description="d")

        self.assertEqual(error.exception.status_code, 429)
        self.assertEqual(error.exception.retry_after, "30")
        self.assertIn("HTTP 429", str(error.exception))

    def test_create_issue_raises_api_error_when_issue_payload_missing(self) -> None:
        def opener(_request):
            return StubResponse({"data": {"issueCreate": {"success": True}}})

        with self.assertRaises(LinearAPIError) as error:
            LinearClient(api_key="x", opener=opener).create_issue(team_id="t", title="T", description="d")

        self.assertIn("missing data.issueCreate.issue", str(error.exception))


if __name__ == "__main__":
    unittest.main()
