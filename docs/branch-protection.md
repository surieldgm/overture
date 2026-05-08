# Main Branch Protection

Last verified on 2026-05-07.

This document is the source of truth for the GitHub branch protection rule on
`main`. The rule makes CI mandatory for human merges and Symphony auto-merge.

## Canonical CI Check

Require this exact status check:

```text
Python 3.11 unittest
```

Source: `.github/workflows/pr-tests.yml`, workflow `PR tests`, job
`unittest`, job display name `Python 3.11 unittest`.

## GitHub Navigation

Open the repository on GitHub, then use this path:

```text
Settings > Code and automation > Branches > Branch protection rules > Add rule
```

If a rule for `main` already exists, use this path instead:

```text
Settings > Code and automation > Branches > Branch protection rules > Edit
```

## Required Settings

Set `Branch name pattern` to:

```text
main
```

Under `Protect matching branches`, configure these settings:

| GitHub UI path | Required value |
| --- | --- |
| `Branch name pattern` | `main` |
| `Protect matching branches > Require a pull request before merging` | Enabled |
| `Protect matching branches > Require a pull request before merging > Require approvals` | Disabled |
| `Protect matching branches > Require status checks to pass before merging` | Enabled |
| `Protect matching branches > Require status checks to pass before merging > Require branches to be up to date before merging` | Enabled |
| `Protect matching branches > Require status checks to pass before merging > Status checks that are required` | `Python 3.11 unittest` |
| `Protect matching branches > Do not allow bypassing the above settings` | Enabled |
| `Rules applied to everyone including administrators > Allow force pushes` | Disabled |
| `Rules applied to everyone including administrators > Allow deletions` | Disabled |

## Review Policy

Human approval is not required by branch protection. A green CI result for the
required `Python 3.11 unittest` check is sufficient for Symphony auto-merge.

Reviewers may still request changes in GitHub or Linear, but branch protection
does not require an approving review before merge.

## Live Repository Verification

Before ERI-82 closes, verify the live repository rule from:

```text
Settings > Code and automation > Branches > Branch protection rules > Edit
```

Confirm that:

- The `main` rule exists.
- `Python 3.11 unittest` is the only required CI status check for this workflow.
- PRs with failing required checks cannot be merged.
- Force-pushes to `main` are rejected by GitHub.

## End-to-End CI Smoke Test

Run this smoke test whenever the workflow, validator, branch protection rule, or
Linear-GitHub integration is re-applied. The smoke PR must be closed without
merging after validation.

1. Start from a clean `main` branch updated to `origin/main`.
2. Create a disposable branch whose name includes the Linear issue identifier,
   for example:

   ```text
   <user>/ERI-83-ci-smoke
   ```

3. Commit one passing change, such as a temporary note under `docs/`, and one
   deliberately failing unittest. The failing test should be obvious and
   isolated, for example:

   ```python
   self.assertTrue(False, "deliberate CI smoke failure")
   ```

4. Push the branch and open a pull request against `main`. Include the Linear
   issue identifier in the PR title or body so the native Linear-GitHub
   integration links the PR to the issue.
5. Within 5 minutes, verify the PR shows the required `Python 3.11 unittest`
   check as failed. Record the failed check URL or screenshot in the ticket
   workpad.
6. Verify GitHub blocks the merge while CI is red. In the GitHub PR UI, the
   merge control must be disabled or replaced by the branch-protection failure
   message for the required check.
7. Open the linked Linear issue and verify the PR card or GitHub activity shows
   the failed status for the same PR. If the issue does not show a native
   GitHub-linked PR status, treat the integration as failed even if the PR URL
   was manually attached.
8. Fix the deliberately failing test on the same branch and push the fix commit.
9. Verify the same PR transitions to a successful `Python 3.11 unittest` check.
10. Verify GitHub now reports the PR as mergeable. In the GitHub PR UI, the merge
    control should become enabled once the required check is green and the
    branch is up to date.
11. Re-open the linked Linear issue and verify the PR card or GitHub activity
    reflects the successful status transition.
12. Close the smoke-test PR without merging. Delete the disposable remote branch
    and record the closure in the ticket workpad.

The rollback step is mandatory: never merge the smoke-test PR, even after it
turns green. The PR exists only to prove that red CI blocks merge and that the
GitHub-to-Linear status chain reports both red and green states.
