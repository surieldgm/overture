# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Overture, please report it privately by emailing **suriel.garcia@eria.ai**. Do not open a public GitHub issue or pull request describing the vulnerability — public disclosure before a fix is shipped puts users at risk.

When reporting, include:

- A description of the vulnerability and its potential impact
- Steps to reproduce, ideally with a minimal example
- Any known mitigations, workarounds, or related context

We aim to:

- Acknowledge receipt within 2 business days
- Triage and respond with a path forward within 7 business days
- Coordinate public disclosure with you once a fix has shipped

## In Scope

- Code under `overture/`, `tests/`, and `examples/`
- Published GitHub Actions workflows under `.github/workflows/`
- Documentation under `docs/` that affects security posture (auth flows, secrets handling, deployment guidance)

## Out of Scope

- Vulnerabilities in third-party dependencies — please report upstream first; we track them via Dependabot
- Issues that require physical or local-machine access to a developer's workstation
- Denial of service through deliberately malformed inputs to local-only commands (those run on operator machines, not shared hosts)
- Social engineering of maintainers or contributors

## Automated Protections

This repository has the following GitHub security features enabled:

- **Secret scanning** detects credentials accidentally committed to history
- **Push protection** blocks commits that contain detected secret patterns at the push boundary
- **Dependabot alerts** flag known-vulnerable dependencies
- **Dependabot security updates** open patch PRs automatically

If you accidentally push a secret, the push is blocked. If a secret reaches the repository through any other path, GitHub notifies the maintainers automatically and we will revoke and rotate the credential as soon as we are aware.

## Coordinated Disclosure

We prefer coordinated disclosure with reporters. If you need to publish your finding on a fixed timeline (for example, a conference talk), please tell us at first contact so we can plan accordingly.
