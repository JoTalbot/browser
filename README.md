# 🐙 Octopus Browser

> 🤖 Безопасный браузер с ИИ-управлением и адаптер экосистемы Octopus/AIOS.

---

## 🎯 Возможности

- 🛡️ API-key authentication и консервативная SSRF/egress policy.
- 🌐 Playwright runtime с configurable timeouts и browser network guard.
- 👥 Изолированные профили и безопасные session paths.
- 🍪 Версионированный session storage foundation.
- 👁️ Vision + bounded agent state machine.
- 🚦 Ограничение одновременных browser jobs и API rate limiting.
- 📊 Readiness, metrics и correlation IDs.
- 🧪 Ruff + Pytest quality gate.

## 🚀 Быстрый старт

```bash
make install
make test
make run
```

### 🔐 Production environment

```bash
export OCTOPUS_API_KEY='change-me'
export APP_HOST='127.0.0.1'
export APP_PORT='8090'
export NAVIGATION_TIMEOUT_MS='30000'
export MAX_BROWSER_CONCURRENCY='4'
export RATE_LIMIT_PER_MINUTE='120'
export ALLOWED_HOSTS='example.com,example.org'
```

`OCTOPUS_API_KEY` обязателен для чувствительных API endpoints. Не храните ключ в репозитории.

## 🧪 Quality gate

1. `ruff check .`
2. `pytest -q`
3. Security regression tests
4. E2E в deployment environment
5. Только после зелёного CI допускается merge/deploy.

## 📂 Документация

- [`AGENTS.md`](AGENTS.md) — автоинструкции для агентов.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — архитектура.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — production roadmap.
- [`docs/RELEASE.md`](docs/RELEASE.md) — release/deployment/rollback runbook.

## 🟢 Production readiness

Текущий branch закрывает security/runtime/agent/observability foundations и проходит CI. Полный production release всё ещё требует E2E, dependency/SBOM scanning, encrypted secret storage и deployment validation. Эти пункты намеренно не отмечаются выполненными без работающей реализации и проверки.

> ⚠️ **Безопасность:** токены, ключи, cookies и storage state не должны попадать в чат, коммиты или логи. Используйте secrets manager/GitHub Secrets.
