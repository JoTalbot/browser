# 🐙 Octopus Browser — план развития

## 🎯 Цель

Построить production-grade browser runtime для экосистемы Octopus/AIOS: изолированные профили, безопасный web execution, vision/LLM agent, управляемые sessions, observability и надёжный deployment.

## Phase 0 — Foundation / Audit

- [x] Репозиторий и package layout.
- [x] FastAPI control plane.
- [x] Playwright launcher.
- [x] Profiles/sessions/cookies foundation.
- [x] CI/CD deploy foundation.
- [x] Initial security hardening.
- [ ] Lock dependencies + reproducible build.
- [ ] Remove all tracked runtime artifacts.

## Phase 1 — P0 Security

- [x] API key authentication.
- [ ] OIDC authentication.
- [x] Endpoint-level protection for sensitive API routes.
- [ ] Secrets/session encryption at rest.
- [x] SSRF syntax + DNS address preflight.
- [ ] DNS rebinding protection at network/browser layer.
- [x] Profile/session filesystem path sandboxing.
- [x] Browser concurrency limit.
- [ ] Request size/rate limiting.
- [ ] Audit log without leaking cookies/tokens.

**Exit:** no unauthenticated sensitive operation; security regression suite green.

## Phase 2 — Browser Runtime

- [x] Configurable Playwright action/navigation timeout.
- [ ] Robust browser lifecycle manager.
- [ ] Context/page/tab registry.
- [ ] Navigation cancellation/deadlines.
- [ ] Download/upload policy.
- [ ] Popup/dialog/permission handling.
- [ ] Network interception and allow/deny rules.
- [ ] Proxy profiles and health-aware rotation.
- [ ] Browser crash recovery.
- [ ] Per-profile process locking.

**Exit:** 24h soak test without leaked processes or profiles.

## Phase 3 — Agent Runtime

- [ ] Typed action schema.
- [ ] Explicit state machine: observe → plan → validate → act → verify.
- [ ] Action preconditions/postconditions.
- [x] Bounded step budget with explicit `limit` state.
- [ ] Retry policy with bounded budgets.
- [ ] Cancellation/deadlines.
- [ ] Goal completion verification.
- [ ] Recovery from stale selectors/pages.
- [ ] Provider abstraction for vision/LLM.
- [ ] Structured model outputs.

**Exit:** benchmark suite with deterministic pass/fail criteria.

## Phase 4 — Vision & Web Intelligence

- [ ] DOM + accessibility tree + screenshot fusion.
- [ ] Element grounding and stable selectors.
- [ ] OCR fallback.
- [ ] Page understanding cache.
- [ ] Vision confidence scoring.
- [ ] Model/provider failover.
- [ ] Prompt/version registry.
- [ ] Cost and latency budgets.

## Phase 5 — Data Plane

- [ ] Session import/export schema versioning.
- [ ] Encrypted cookie/storage-state vault.
- [ ] Session TTL and revocation.
- [ ] Profile lifecycle policies.
- [ ] Backup/restore.
- [ ] Data retention and secure deletion.

## Phase 6 — Octopus / AIOS Integration

- [ ] Stable adapter contract.
- [ ] Capability discovery.
- [ ] Job submission/status API.
- [ ] Webhook/event integration.
- [ ] Shared run IDs/correlation IDs.
- [ ] Multi-agent concurrency coordination.
- [ ] Backpressure and queueing.

## Phase 7 — Observability & Operations

- [ ] Structured JSON logs.
- [ ] Metrics and traces.
- [ ] Browser/agent/provider dashboards.
- [ ] Error taxonomy.
- [ ] Alert thresholds.
- [x] Health endpoint.
- [ ] Readiness endpoint.
- [ ] Run/event persistence.

## Phase 8 — QA / Security / Performance

- [x] Unit/smoke suite.
- [ ] API integration suite.
- [ ] Real Playwright E2E suite.
- [x] Security regression coverage for auth/path/SSRF baseline.
- [ ] Dependency/SBOM scanning.
- [ ] Load and soak tests.
- [ ] Failure-injection tests.
- [ ] Compatibility matrix for Python/Playwright/browser versions.

## Phase 9 — Release Engineering

- [ ] Semantic versioning.
- [ ] Changelog/release notes.
- [ ] Reproducible artifact build.
- [ ] Deployment preflight.
- [ ] Health-gated rollout.
- [ ] Automatic rollback.
- [ ] Migration/version compatibility checks.
- [ ] Production runbook.

## Phase 10 — Advanced Platform

- [ ] Multi-browser support where justified.
- [ ] Distributed browser workers.
- [ ] Queue scheduler.
- [ ] Policy engine.
- [ ] Human approval checkpoints for risky actions.
- [ ] Long-running workflows.
- [ ] Benchmark-driven model routing.
- [ ] Plugin/skill system.

## Правило разработки

- Любое новое улучшение классифицируется как security/product/quality/performance.
- Production blockers закрываются в текущей фазе, даже если старый план этого не содержал.
- Изменения публичного контракта фиксируются отдельным roadmap item.
- После каждой фазы: тесты → security review → integration check → статус → следующий этап.
