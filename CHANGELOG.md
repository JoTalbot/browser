# Changelog

All notable changes to Octopus Browser are documented here.

## [0.3.2] - 2026-09-05

### Release engineering
- Align package and API runtime version to 0.3.2.
- Move GitHub Actions to Node 24-compatible pinned action commits.
- Use `webfactory/ssh-agent` v0.10.0 for deployment SSH setup.
- Keep the release workflow idempotent and artifact-producing.

### Runtime / API
- Keep bounded asynchronous agent jobs with queue capacity limits.
- Preserve explicit queued/running/done/error/cancelled lifecycle states.

### Verification
- Retain regression coverage for request limits, encrypted sessions, revocation, audit redaction and job lifecycle.
- Require Ruff, Pytest, dependency audit and package build in CI before release.

## [0.3.1] - 2026-09-05

### Security
- Enforce a bounded API request body size.
- Add authenticated AES-GCM encryption for persisted browser sessions.
- Require `SESSION_ENCRYPTION_KEY` before creating or importing sessions.
- Add session TTL, revocation and expiry purge support.
- Store session files with owner-only permissions where supported.
- Add a secret-redacting append-only JSONL audit sink.
- Pin CI action references to immutable commit SHAs.
- Add CI dependency vulnerability auditing with `pip-audit`.

### Runtime / API
- Add bounded asynchronous agent jobs with queue capacity limits.
- Add authenticated job submission, status, listing and cancellation endpoints.
- Expose job counts in metrics.
- Track job creation, start and finish timestamps.
- Preserve explicit `cancelled` state rather than reporting a cancelled job as completed.

### Operations
- Make GitHub release publishing idempotent when a release already exists.
- Expose request body limits in health/metrics responses.
- Modernize package license metadata to SPDX form.
- Remove tracked Python `__pycache__` runtime artifacts.

### Verification
- Add regression coverage for body limits, session encryption/tamper detection, revocation and audit redaction.
- Add job lifecycle and cancellation tests.
- CI remains green across Python 3.10–3.13 before release.
