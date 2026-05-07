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
