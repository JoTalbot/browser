# 🚀 Production Release Runbook

## Release gate

1. Worktree is clean and no runtime data, credentials, cookies or database files are tracked.
2. `ruff check .` passes.
3. `pytest -q` passes.
4. Build/install succeeds on the supported Python matrix.
5. Playwright browsers are installed and the E2E suite passes in the deployment image/runner.
6. Security regression suite passes.
7. Deployment preflight confirms `OCTOPUS_API_KEY`, filesystem permissions, writable data directories and expected browser binaries.
8. `/health` and `/ready` return successful responses after startup.

## Deployment

- Build an immutable artifact from the tagged commit.
- Deploy to a staging instance first.
- Run smoke navigation against an explicitly allowed external host.
- Promote only after health/readiness checks succeed.
- Keep the previous artifact available for rollback.

## Rollback

- Stop the new instance.
- Restore the previous immutable artifact and compatible configuration.
- Verify `/health`, `/ready`, API authentication and a smoke navigation.
- Do not restore secrets or runtime state from source control.

## Security requirements

- Never expose `OCTOPUS_API_KEY` in logs or CI output.
- Keep `ALLOWED_HOSTS` restrictive in production.
- Do not enable downloads/uploads unless the deployment policy explicitly requires them.
- Store persistent session secrets in an external secret manager until the encrypted vault is enabled.

## Versioning

Use semantic versions. Update `pyproject.toml`, release notes and the Git tag in the same release change. Do not publish a release from a failing CI commit.
