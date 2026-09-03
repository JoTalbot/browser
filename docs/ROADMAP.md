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

- [ ] API key/OIDC authentication.
- [ ] Endpoint-level authorization.
- [ ] Secrets/session encryption at rest.
- [ ] SSRF protection and explicit egress policy.
- [ ] DNS rebinding protection.
- [ ] Per-profile filesystem sandbox.
- [ ] Request size/rate/concurrency limits.
- [ ] Audit log without leaking cookies/tokens.

**Exit:** no unauthenticated sensitive operation; security regression suite green.

## Phase 2 — Browser Runtime

- [ ] Robust browser lifecycle manager.
- [ ] Context/page/tab registry.
- [ ] Navigation timeout and cancellation.
- [ ] Download/upload policy.
- [ ] Popup/dialog/permission handling.
- [ ] Network interception and allow/deny rules.
- [ ] Proxy profiles and health-aware rotation.
- [ ] Browser crash recovery.

**Exit:** 24h soak test without leaked processes or profiles.

## Phase 3 — Agent Runtime

- [ ] Typed action schema.
- [ ] Explicit state machine: observe → plan → validate → act → verify.
- [ ] Action preconditions/postconditions.
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

**Exit:** reliable task completion benchmark across representative sites.

## Phase 5 — Data Plane

- [ ] Session import/export schema versioning.
- [ ] Encrypted cookie/storage-state vault.
- [ ] Session TTL and revocation.
- [ ] Profile lifecycle policies.
- [ ] Backup/restore.
- [ ] Data retention and secure deletion.

**Exit:** documented recovery and secret-handling guarantees.

## Phase 6 — Octopus / AIOS Integration

- [ ] Stable adapter contract.
- [ ] Capability discovery.
- [ ] Job submission/status API.
- [ ] Webhook/event integration.
- [ ] Shared run IDs/correlation IDs.
- [ ] Multi-agent concurrency coordination.
- [ ] Backpressure and queueing.

**Exit:** AIOS can submit, monitor, cancel and recover browser jobs through the public contract.

## Phase 7 — Observability & Operations

- [ ] Structured JSON logs.
- [ ] Metrics and traces.
- [ ] Browser/agent/provider dashboards.
- [ ] Error taxonomy.
- [ ] Alert thresholds.
- [ ] Health/readiness/liveness endpoints.
- [ ] Run/event persistence.

**Exit:** every production run is diagnosable without reproducing it manually.

## Phase 8 — QA / Security / Performance

- [ ] Unit suite.
- [ ] API integration suite.
- [ ] Real Playwright E2E suite.
- [ ] Security regression suite.
- [ ] Dependency/SBOM scanning.
- [ ] Load and soak tests.
- [ ] Failure-injection tests.
- [ ] Compatibility matrix for Python/Playwright/browser versions.

**Exit:** release gates green and performance budgets documented.

## Phase 9 — Release Engineering

- [ ] Semantic versioning.
- [ ] Changelog/release notes.
- [ ] Reproducible artifact build.
- [ ] Deployment preflight.
- [ ] Health-gated rollout.
- [ ] Automatic rollback.
- [ ] Migration/version compatibility checks.
- [ ] Production runbook.

**Exit:** release can be deployed and rolled back predictably.

## Phase 10 — Advanced Platform

- [ ] Multi-browser support where justified.
- [ ] Distributed browser workers.
- [ ] Queue scheduler.
- [ ] Policy engine.
- [ ] Human approval checkpoints for risky actions.
- [ ] Long-running workflows.
- [ ] Benchmark-driven model routing.
- [ ] Plugin/skill system.

**Final target:** secure, observable, recoverable autonomous browser runtime integrated into Octopus/AIOS.

## Правило разработки

- Любое новое улучшение, обнаруженное во время реализации, сначала классифицируется как security/product/quality/performance.
- Если улучшение снижает риск или закрывает production blocker, оно добавляется в текущую фазу, а не откладывается ради формального следования старому плану.
- Если изменение меняет продуктовый контракт, оно фиксируется отдельным roadmap item до реализации.
- После каждой фазы выполняются: тесты → security review → integration check → обновление статуса → следующий этап.
