# Changelog

All notable changes to Octopus Browser are documented here.

## [0.3.1] - 2026-09-05

### Security
- Enforce a bounded API request body size.
- Add authenticated AES-GCM encryption for persisted browser sessions.
- Require `SESSION_ENCRYPTION_KEY` before creating or importing sessions.
- Add session TTL, revocation and expiry purge support.
- Store session files with owner-only permissions where supported.
- Add a secret-redacting append-only JSONL audit sink.

### Operations
- Make GitHub release publishing idempotent when a release already exists.
- Expose request body limits in health/metrics responses.
- Modernize package license metadata to SPDX form.

### Verification
- Add regression coverage for body limits, session encryption/tamper detection, revocation and audit redaction.
