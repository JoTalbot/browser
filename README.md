# 🐙 Octopus Browser

> 🤖 Безопасный браузер с ИИ-управлением и адаптер экосистемы Octopus/AIOS.

---

## 🎯 Возможности

- 🛡️ API-key authentication и консервативная SSRF/egress policy.
- 🌐 Playwright runtime с configurable timeouts.
- 👥 Изолированные профили и безопасные session paths.
- 🍪 Session/cookie foundation.
- 👁️ Vision + агентский action loop.
- 🚦 Ограничение одновременных browser jobs.
- 🧪 Ruff + Pytest quality gate.

---

## 📂 Структура

| Путь | Описание |
|---|---|
| [`AGENTS.md`](AGENTS.md) | 🤖 Автоинструкции для агентов |
| [`docs/agent-instructions/`](docs/agent-instructions/000-README.md) | 📚 Инструкции |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 🏗️ Архитектура |
| [`docs/AUDIT_2026-09-03.md`](docs/AUDIT_2026-09-03.md) | 🔎 Production/security audit |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 🗺️ План развития |
| [`deploy/`](deploy/) | 🚀 Deployment scripts |
| [`src/octopus_browser/`](src/octopus_browser/) | 🧩 Python + Playwright + FastAPI |

---

## 🚀 Быстрый старт

```bash
make install   # зависимости + браузер
make test      # smoke/unit-тесты
make run       # API на :8090
```

### 🔐 Production environment

```bash
export OCTOPUS_API_KEY='change-me'
export APP_HOST='127.0.0.1'
export APP_PORT='8090'
export NAVIGATION_TIMEOUT_MS='30000'
export MAX_BROWSER_CONCURRENCY='4'
export ALLOWED_HOSTS='example.com,example.org'
```

`OCTOPUS_API_KEY` обязателен для чувствительных API endpoints. Не храните ключ в репозитории.

---

## 🧪 Quality gate

1. `ruff check .`
2. `pytest -q`
3. Security regression tests
4. Только после зелёного CI допускается merge/deploy.

---

## 🛠️ Текущий статус

- 🟢 Repository/package foundation
- 🟢 FastAPI control plane
- 🟢 Playwright browser controller
- 🟢 Profiles / sessions / cookies foundation
- 🟢 Initial agent + vision loop
- 🟢 CI quality gate
- 🟢 Initial authentication + SSRF baseline
- 🟢 Filesystem/session path hardening
- 🟢 Runtime timeout + concurrency controls
- 🟡 DNS-rebinding network enforcement
- 🟡 Encryption-at-rest / secret management
- 🟡 Agent state machine / cancellation / retries
- 🟡 Observability / metrics / traces
- 🔴 Production release: not ready yet

---

## 📚 План развития

- **Phase 1:** P0 Security
- **Phase 2:** Browser Runtime
- **Phase 3:** Agent Runtime
- **Phase 4:** Vision & Web Intelligence
- **Phase 5:** Data Plane
- **Phase 6:** Octopus / AIOS Integration
- **Phase 7:** Observability & Operations
- **Phase 8:** QA / Security / Performance
- **Phase 9:** Release Engineering
- **Phase 10:** Advanced Platform

Подробные exit criteria находятся в [`docs/ROADMAP.md`](docs/ROADMAP.md).

---

> ⚠️ **Безопасность:** токены, ключи, cookies и storage state не должны попадать в чат, коммиты или логи. Используйте secrets manager/GitHub Secrets.
