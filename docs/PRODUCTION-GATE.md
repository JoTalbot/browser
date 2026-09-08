# 🟢 Octopus Browser — Production Gate

This document is the release gate for `octopus-browser`. A green unit-test run alone is not a production approval.

## Required gates

- [x] Repository structure and agent operating rules.
- [x] API-key authentication for protected endpoints.
- [x] SSRF/egress preflight and browser network interception foundation.
- [x] Profile/session path isolation and encrypted session storage.
- [x] Bounded browser concurrency and API rate limiting.
- [x] Request body size limit and correlation IDs.
- [x] Release/version consistency audit in CI.
- [x] Dependency vulnerability audit in CI.
- [x] CycloneDX SBOM generation and artifact publication in CI.
- [x] Node 24-compatible GitHub Actions baseline.
- [x] Automated deploy workflow and release workflow.

## Mandatory pre-production validation

- [ ] Run the real deployment workflow against the production host.
- [ ] Verify `/health`, `/ready` and authenticated `/metrics` after deployment.
- [ ] Run real Playwright browser E2E against the deployed service.
- [ ] Verify proxy health/rotation with the actual proxy provider.
- [ ] Verify encrypted session backup and restore on the production filesystem.
- [ ] Verify rollback from the previous release artifact.
- [ ] Verify external secret storage and rotation.
- [ ] Verify load/soak and failure-injection behavior.

## Release rule

A release is **production-ready only when every mandatory pre-production validation item is checked with evidence**. Documentation must never claim a capability is complete merely because a stub, interface, or unit test exists.

## Security rules

- Never commit API keys, cookies, session state, private keys, `.env` files, or deployment credentials.
- Keep production secrets in GitHub Secrets or the configured external secret manager.
- Treat browser navigation and all secondary network requests as untrusted egress.
- Do not disable SSRF checks just to make an E2E test easier. Tests must use an explicit safe fixture or controlled environment.

## Evidence

The CI workflows publish the security audit and SBOM artifacts. Deployment and E2E evidence belongs in the corresponding GitHub Actions run and release record.
