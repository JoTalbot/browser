# 🐙 Octopus Browser — план развития

## 🎯 Цель

Построить production-grade browser runtime для экосистемы Octopus/AIOS: изолированные профили, безопасный web execution, vision/LLM agent, управляемые sessions, observability и надёжный deployment.

## Phase 0 — Foundation / Audit
- [x] Repository/package layout, FastAPI control plane, Playwright launcher.
- [x] Profiles/sessions/cookies foundation and initial security hardening.
- [x] CI/CD deploy foundation.
- [ ] Lock dependencies + reproducible build.
- [ ] Remove tracked runtime artifacts and add repository hygiene gate.

## Phase 1 — P0 Security
- [x] API key authentication and endpoint protection.
- [ ] OIDC authentication.
- [x] SSRF syntax + DNS address preflight.
- [ ] DNS-rebinding enforcement at network/browser layer.
- [x] Profile/session filesystem sandboxing.
- [x] Browser concurrency limit.
- [ ] Request size/rate limiting.
- [ ] Secret-safe audit logging.
- [ ] Encrypted session/cookie storage.

## Phase 2 — Browser Runtime
- [x] Configurable Playwright action/navigation timeout.
- [ ] Lifecycle manager with deterministic startup/shutdown.
- [ ] Context/page/tab registry.
- [ ] Navigation cancellation/deadlines.
- [ ] Download/upload policy.
- [ ] Popup/dialog/permission policy.
- [ ] Network interception and allow/deny rules.
- [x] Proxy validation and health checks.
- [ ] Health-aware proxy rotation.
- [ ] Crash recovery and per-profile locking.

## Phase 3 — Agent Runtime
- [ ] Typed action schema and validation.
- [ ] Explicit observe → plan → validate → act → verify state machine.
- [ ] Preconditions/postconditions.
- [x] Bounded step budget with explicit `limit` state.
- [ ] Bounded retries, cancellation and deadlines.
- [ ] Goal completion verification.
- [ ] Stale page/selector recovery.
- [ ] Provider abstraction and structured model outputs.

## Phase 4 — Vision & Web Intelligence
- [ ] DOM + accessibility tree + screenshot fusion.
- [ ] Stable element grounding/selectors.
- [ ] OCR fallback.
- [ ] Page understanding cache.
- [ ] Confidence scoring and model/provider failover.
- [ ] Prompt/version registry.
- [ ] Cost/latency budgets.

## Phase 5 — Data Plane
- [ ] Versioned session import/export schema.
- [ ] Authenticated encryption for cookie/storage-state vault.
- [ ] Session TTL, revocation and profile lifecycle policies.
- [ ] Backup/restore.
- [ ] Retention and secure deletion.

## Phase 6 — Octopus / AIOS Integration
- [ ] Stable adapter contract and capability discovery.
- [ ] Job submission/status/cancellation API.
- [ ] Webhook/event integration.
- [ ] Shared run/correlation IDs.
- [ ] Multi-agent coordination, backpressure and queueing.

## Phase 7 — Observability & Operations
- [ ] Structured JSON logs with secret redaction.
- [ ] Metrics/traces and error taxonomy.
- [ ] Browser/agent/provider dashboards.
- [ ] Alert thresholds.
- [x] Health endpoint.
- [ ] Readiness endpoint.
- [ ] Persistent run/event store.

## Phase 8 — QA / Security / Performance
- [x] Unit/smoke suite and baseline security regression tests.
- [ ] API integration suite and real Playwright E2E.
- [ ] Dependency/SBOM/security scanning.
- [ ] Load, soak and failure-injection tests.
- [ ] Python/Playwright/browser compatibility matrix.
- [ ] Performance budgets enforced in CI.

## Phase 9 — Release Engineering
- [ ] Semantic versioning and changelog.
- [ ] Reproducible release artifacts.
- [ ] Deployment preflight and health-gated rollout.
- [ ] Automatic rollback.
- [ ] Migration/version compatibility checks.
- [ ] Production runbook and release checklist.

## Phase 10 — Advanced Platform
- [ ] Multi-browser support where justified.
- [ ] Distributed browser workers and queue scheduler.
- [ ] Policy engine and risk classification.
- [ ] Human approval checkpoints for risky actions.
- [ ] Long-running workflows.
- [ ] Benchmark-driven model routing.
- [ ] Plugin/skill system with capability isolation.

## 🧭 All-phase execution rule

The implementation target is the complete platform, not a collection of disconnected stubs. Every phase must ship with tests, security review, integration checks and documented operational behavior. Production blockers discovered during implementation are promoted into the current batch instead of being hidden in a backlog.

**Final target:** secure, observable, recoverable, policy-controlled autonomous browser runtime integrated into Octopus/AIOS, with deterministic CI and rollback-capable deployment.
