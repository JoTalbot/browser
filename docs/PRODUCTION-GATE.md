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

- [x] Run the real deployment workflow against the production host.
  - Evidence 2026-09-08: deploy runs [34202356022](https://github.com/JoTalbot/browser/actions/runs/34202356022) (ec4721b), [34200380740](https://github.com/JoTalbot/browser/actions/runs/34200380740) (3575ca7), [34197562335](https://github.com/JoTalbot/browser/actions/runs/34197562335) (8c2ec3c) — all success; `/var/log/octopus-update.log` shows idempotent `APPLIED==HEAD` applies.
- [ ] Verify `/health`, `/ready` and authenticated `/metrics` after deployment. — PARTIAL, blocked: no `OCTOPUS_API_KEY` on prod.
  - Live: `/health` + `/ready` → 200 (0.4.0); protected endpoints fail closed → 503 `API authentication is not configured`. Auth 200/401 verified in sandbox (throwaway key) + CI smoke. Authenticated prod `/metrics` awaits key provisioning.
- [ ] Run real Playwright browser E2E against the deployed service. — SKIPPED per operator decision 2026-09-08 (browsers not installed: `pw-lib OK`, `~/.cache/ms-playwright` empty).
- [ ] Verify proxy health/rotation with the actual proxy provider. — PARTIAL, blocked: DECISIONS.md #1 (proxy=mock).
  - Mock-live drill on prod host 2026-09-08: `refresh_health` ok/fail paths, failed proxy in cooldown, rotation sticks to healthy, `rotations_total=3`. Live vendor awaits decision-1 revisit.
- [x] Verify encrypted session backup and restore on the production filesystem.
  - Evidence 2026-09-08 (`scripts/backup.py`): backup of real `/opt/octopus-browser/data` (3 files, 180743 bytes, 4 dirs) → `verify` ok → restore to /tmp → `diff -r` MATCHES prod → wiped. Key via env, never logged. Runbook: `docs/BACKUP.md`.
- [x] Verify rollback from the previous release artifact.
  - Evidence 2026-09-08: v0.3.2 has no binary assets → tag-as-artifact drill: `git archive v0.3.2` → throwaway venv install → import/jobs(40+2)/vault/api-version-0.3.2 all OK. Prod rollback = revert-PR through normal deploy (watchdog fights manual checkouts — never `git checkout` old commits on prod).
- [x] Verify external secret storage and rotation.
  - Evidence 2026-09-08: vault rotation drill (session blob re-encrypted A→B, loads with B, A rejected `Повреждённая или недоступная сессия`) + proxy credential rotation old→new, tmp stores, prod code. Scope: prod has no `SESSION_ENCRYPTION_KEY`/`OCTOPUS_API_KEY` yet; API-key rotation procedure documented in `docs/BACKUP.md`, execution awaits key provisioning.
- [x] Verify load/soak and failure-injection behavior.
  - Evidence 2026-09-08: 100-task agent load (90 done/5 cancelled/5 timeout); soak (full suite 2× + load 3×, all green); sandbox `kill -9` → restart: lease/job-id/events/metrics state survived; prod `systemctl restart` 08:48 UTC → active + health/ready 200.

## Release rule

A release is **production-ready only when every mandatory pre-production validation item is checked with evidence**. Documentation must never claim a capability is complete merely because a stub, interface, or unit test exists.

## Security rules

- Never commit API keys, cookies, session state, private keys, `.env` files, or deployment credentials.
- Keep production secrets in GitHub Secrets or the configured external secret manager.
- Treat browser navigation and all secondary network requests as untrusted egress.
- Do not disable SSRF checks just to make an E2E test easier. Tests must use an explicit safe fixture or controlled environment.

## Evidence

The CI workflows publish the security audit and SBOM artifacts. Deployment and E2E evidence belongs in the corresponding GitHub Actions run and release record.

Phase 7 drill transcripts (2026-09-08): PR #15 body, `docs/BACKUP.md` runbook, STATUS entry `Фаза 7 — evidence`. v1.0.0 is BLOCKED on items 2 (auth key), 3 (skipped E2E), 4 (live proxy vendor).
