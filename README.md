# 🐙 Octopus Browser

> 🤖 Супербезопасный браузер с ИИ-управлением — адаптер экосистемы
> **Октопус** (`JoTalbot/AIOS`, `JoTalbot/octopus`).

---

## 🎯 О проекте

- 🛡️ **Безопасность** — изоляция, sandbox, policy-контроль и безопасное выполнение.
- 🌐 **Прокси и VPN** — каналы, ротация и гео-профили.
- 👥 **Мульти-профили** — независимые профили, сессии и cookies.
- 🍪 **Менеджеры сессий и кук** — импорт/экспорт и lifecycle management.
- 👁️ **ИИ-управление** — vision + агентский action loop.
- 🤖 **Агентский контур** — GitHub → CI → сервер.

---

## 📂 Структура

| Путь | Описание |
|---|---|
| [`AGENTS.md`](AGENTS.md) | 🤖 Автоинструкции для агентов |
| [`docs/agent-instructions/`](docs/agent-instructions/000-README.md) | 📚 Полный набор инструкций |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 🏗️ Архитектура проекта |
| [`docs/AUDIT-2026-09-03.md`](docs/AUDIT-2026-09-03.md) | 🔎 Полный production-аудит |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 🗺️ План развития до production platform |
| [`deploy/`](deploy/) | 🚀 Скрипты установки/обновления сервера |
| [`src/octopus_browser/`](src/octopus_browser/) | 🧩 Python + Playwright + FastAPI |

---

## 🚀 Workflow правок

1. ✍️ Агент правит код/документацию.
2. 📦 Изменения проходят PR/merge в `main`.
3. 🧪 CI выполняет Ruff + Pytest.
4. ⚙️ Production deploy запускается только после quality gate.
5. 🔄 Сервер применяет `deploy/server-update.sh`.
6. 📊 Статус доступен в GitHub Actions.

---

## 🧪 Быстрый старт

```bash
make install   # зависимости + браузер
make test      # smoke/unit-тесты
make run       # API на :8090
```

---

## 🛠️ Текущий статус

- 🟢 Repository/package foundation
- 🟢 FastAPI control plane
- 🟢 Playwright browser controller
- 🟢 Profiles / sessions / cookies foundation
- 🟢 Initial agent + vision loop
- 🟢 CI quality gate
- 🟢 Deploy quality gate + server update path
- 🟢 Initial security hardening
- 🟡 Production security: AuthN/AuthZ, SSRF/egress policy, encryption-at-rest
- 🟡 Agent runtime: state machine, cancellation, retries, typed actions
- 🟡 Observability: metrics, traces, persistent runs
- 🔴 Production release: not ready yet

---

## 📚 Development plan

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

> ⚠️ **Безопасность:** никогда не вставляйте токены, ключи, пароли
> в чат, коммиты или инструкции. Секреты — только в GitHub Secrets.
