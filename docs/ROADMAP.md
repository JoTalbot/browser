# 🐙 Octopus Browser — Production Roadmap

Построить production-grade browser runtime для экосистемы Octopus/AIOS: изолированные профили, безопасный web execution, vision/LLM agent, управляемые sessions, observability и надёжный deployment.

## Phase 0 — Foundation / Audit
- [x] Repository/package layout, FastAPI control plane, Playwright launcher.
- [x] Profiles/sessions/cookies foundation and initial security hardening.
- [x] CI quality gate.
- [x] Runtime artifact hygiene baseline.
- [ ] Lock dependencies + reproducible build.

## Phase 1 — P0 Security
- [x] API key authentication and endpoint protection.
- [x] SSRF syntax + DNS address preflight.
- [x] Profile/session filesystem path sandboxing.
- [x] Browser concurrency limit.
- [x] Request rate limiting.
- [ ] OIDC authentication.
- [ ] DNS-rebinding enforcement at browser network layer.
- [ ] Request body size limit.
- [ ] Secret-safe audit log sink.
- [ ] Encrypted session/cookie storage.

## Phase 2 — Browser Runtime
- [x] Configurable Playwright action/navigation timeout.
- [x] Proxy URL validation and health-check foundation.
- [ ] Lifecycle manager with deterministic startup/shutdown.
- [ ] Context/page/tab registry.
- [ ] Navigation cancellation/deadlines.
- [ ] Download/upload policy.
- [ ] Popup/dialog/permission policy.
- [ ] Network interception and allow/deny rules.
- [ ] Health-aware proxy rotation.
- [ ] Crash recovery and per-profile locking.

## Phase 3 — Agent Runtime
- [x] Typed action model and validation foundation.
- [x] Explicit observe → plan → validate → act → verify state machine.
- [x] Bounded step budget with explicit `limit` state.
- [ ] Preconditions/postconditions.
- [ ] Bounded retries, cancellation and deadlines.
- [ ] Goal completion verification.
- [ ] Stale page/selector recovery.
- [ ] Provider abstraction and structured model outputs.

## Phase 4 — Vision & Web Intelligence
- [x] Structured vision decision parsing and confidence field.
- [x] Provider timeout/latency instrumentation foundation.
- [ ] DOM + accessibility tree + screenshot fusion.
- [ ] Stable element grounding/selectors.
- [ ] OCR fallback.
- [ ] Page understanding cache.
- [ ] Confidence calibration and model/provider failover.
- [ ] Prompt/version registry.
- [ ] Cost/latency budgets.

## Phase 5 — Data Plane
- [ ] Versioned session import/export schema.
- [ ] Authenticated encryption for cookie/storage-state vault.
- [ ] Session TTL, revocation and profile lifecycle policies.
- [ ] Backup/restore.
- [ ] Retention and secure deletion.

## Phase 6 — Octopus / AIOS Integration
- [x] Stable API foundation and capability discovery endpoint.
- [x] Shared request/correlation ID foundation.
- [ ] Job submission/status/cancellation API.
- [ ] Webhook/event integration.
- [ ] Multi-agent concurrency coordination.
- [ ] Backpressure and durable queueing.

## Phase 7 — Observability & Operations
- [x] Structured JSON logging foundation.
- [x] Metrics endpoint and readiness endpoint.
- [ ] Metrics/traces with persistent backend integration.
- [ ] Browser/agent/provider dashboards.
- [ ] Error taxonomy and alert thresholds.
- [ ] Persistent run/event store.

## Phase 8 — QA / Security / Performance
- [x] Unit/smoke suite and security regression baseline.
- [x] CI lint + test gate.
- [ ] API integration suite and real Playwright E2E.
- [ ] Dependency/SBOM/security scanning.
- [ ] Load, soak and failure-injection tests.
- [ ] Python/Playwright/browser compatibility matrix.
- [ ] Performance budgets enforced in CI.

## Phase 9 — Release Engineering
- [x] Semantic-version foundation.
- [ ] Changelog/release notes.
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

**Current release gate:** PR CI must remain green before merge. Advanced phases remain explicitly open until their production behavior is implemented and tested.

**Final target:** secure, observable, recoverable, policy-controlled autonomous browser runtime integrated into Octopus/AIOS, with deterministic CI and rollback-capable deployment.
