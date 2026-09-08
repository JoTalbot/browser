# Changelog

All notable changes to Octopus Browser are documented here.

## [Unreleased]

### Added
- Import AIOS CDP adapter into the monorepo (`integrations/browser-aios-adapter/`); it previously lived only in unmanaged `/opt/octopus-browser-aios-adapter`.
- CI job `adapter` (ruff + pytest for the adapter package); quality job installs both packages.
- Deploy installs the adapter systemd unit from Git and restarts the service on update.
- New `skills/deploy-verify` skill: post-deploy `/health` + `/ready` verification.
- Proxy provider abstraction: `StaticListProvider` (seeds from `PROXY_LIST`) and scripted `MockProxyProvider` (no network; live vendors deferred per DECISIONS.md).
- Vault-backed proxy credentials (`secret_ref` + encrypted store) and health-aware rotation (scoring, exponential cooldown, persisted pool).
- Proxy control-plane API: `GET/POST/DELETE /proxies`, `GET /proxies/health`, `POST /proxies/rotate`, `POST /proxies/credentials`, plus `proxies_*` metrics.
- External vision via adapter: `AdapterVisionProvider` (+`OpenAICompat`/`Mock`), prompt registry, frame fusion (screenshot+DOM+a11y), grounding, TTL cache, hourly budgets; no local models (DECISIONS.md #7).
- Adapter `POST /vision/analyze` endpoint backed by VisionRouter (gemini/groq/balancer + failover).
- Vision control-plane API: `POST /vision/analyze`, `GET /vision/status`, `vision_*` metrics.
- Adapter vision: failover-леги логируются (`vision leg ... failed`, без секретов) для диагностики.
- Adapter vision: HTTP-ошибки провайдеров включают усечённый ответ гейтвея (первые 200 символов) для диагностики 4xx.
- Agent hardening: bounded retries + recoveries, cooperative cancellation, deadlines, pre/postconditions, goal verification (verify_fn + done-confidence gate), AgentPlanner abstraction, structured ActionValidationError.
- Agent jobs API: cooperative cancel of running jobs, per-task deadline_seconds, retries/recoveries/verified in results, agent_* metrics.
- BrowserController.reload() for stale-page recovery; load scenario: 100 scripted tasks with mixed outcomes.

### Fixed
- Deploy restarts were silently skipped: `systemctl list-unit-files | grep -q` under `set -o pipefail` dies from SIGPIPE (exit 141), so the service never restarted and production ran Sep-3 code. Restart detection now uses `systemctl cat`, apply state is tracked in `.applied_commit`, concurrent runs are serialized with `flock`.
- Deploy/release quality gates install the adapter package so root `pytest -q` collects its tests.

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
