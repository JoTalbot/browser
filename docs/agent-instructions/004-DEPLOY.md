# 🚀 004 — Установка и авто-деплой на сервер

> 🖥️ Цель: любая правка в GitHub автоматически применяется на сервере.
> Установка сервера — тоже через GitHub.

---

## 1. 🏷️ Требуемые GitHub Secrets

| Секрет | Что содержит | Пример |
|---|---|---|
| `DEPLOY_HOST` | IP/домен сервера | `129.213.177.56` |
| `DEPLOY_USER` | SSH-пользователь | `ubuntu` |
| `DEPLOY_SSH_KEY` | Приватный ключ (fine-grained, без пароля) | `-----BEGIN OPENSSH ...` |
| `DEPLOY_PATH` | Каталог приложения на сервере | `/opt/octopus-browser` |

- 🔐 Добавляются: **Settings → Secrets and variables → Actions**.
- ⚠️ Ключ создавать отдельный (deploy key), дать только на этот репозиторий.
- 🚫 Никогда не вставлять ключи в чат/коммит/инструкции.

---

## 2. ⚙️ GitHub Actions (`.github/workflows/deploy.yml`)

- ✅ **Триггеры:** `push` в `main`, `workflow_dispatch` (ручной запуск).
- ✅ Шаги: checkout → подключение deploy key → SSH → `git pull` → `server-update.sh` → статус.
- ✅ Результат: зелёный/красный статус виден в Actions.
- ✅ Логи шагов — там же; полные секреты **не** выводятся.

---

## 3. 🖥️ Первичная установка на сервер (один раз)

1. 🧰 Создать каталог: `sudo mkdir -p /opt/octopus-browser && sudo chown ubuntu:ubuntu /opt/octopus-browser`.
2. 🧑‍💻 Deploy-ключ: `ssh-keygen -t ed25519 -C "octopus-deploy"` (без пароля).
3. 📌 Добавить **публичную** часть в GitHub repo → Settings → Deploy keys (read).
4. 📥 На сервере: `cd /opt/octopus-browser && git clone git@github.com:JoTalbot/browser.git .` (или с deploy key).
5. 🛠️ Запустить `deploy/server-bootstrap.sh` (ставит зависимости, настраивает watchdog).
6. 🔐 Добавить Secrets (`DEPLOY_*`) в репозиторий.
7. 🚀 Обновить шаблон `deploy/github-actions/deploy.yml.example` при необходимости; для активации изменений в `.github/workflows/` нужен PAT с разрешением **Workflows**.

---

## 4. 🔄 Авто-обновление после правок

- ✅ Каждый push/merge в `main` → Actions → SSH → `git pull --ff-only` → apply.
- ✅ `deploy/server-update.sh` выполняет:
  - копирует `docs/agent-instructions/` → `/root/agents/`,
  - `npm install` / сборка (если есть `package.json`),
  - рестарт сервиса (`systemctl restart octopus-browser` или supervisor),
  - лог в `/var/log/octopus-update.log`.
- 🧲 Резервный watchdog (если CI недоступен):
  - cron каждые 2 мин: `cd /opt/octopus-browser && git fetch && git pull --ff-only && deploy/server-update.sh`.

---

## 5. 🐙 Связь с Октопусом (AIOS)

- 🧩 Этот репозиторий — **адаптер/интеграция** Octopus Browser в экосистему Октопус.
- 🔗 Подключение к `JoTalbot/AIOS` / `JoTalbot/octopus`: через модуль `integration/` или webhook.
- 📚 Инструкции Октопуса зеркалируются в `/root/agents/` — единый источник для агентов.
- 🗣️ При изменении интерфейса интеграции — обновлять `AGENTS.md` и `004-DEPLOY.md`.

---

## 6. ✅ Чек-лист «деплой работает»

- [ ] 🔑 `DEPLOY_*` Secrets заполнены
- [ ] 📥 Сервер клонирует репозиторий через deploy key
- [ ] ⚙️ Actions запускается по push в `main`
- [ ] 🖥️ `server-update.sh` отрабатывает без ошибок
- [ ] 📚 `/root/agents/` обновился (сравнить содержимое с репозиторием)
- [ ] 🧲 Watchdog в cron активен (резервный канал)
- [ ] 📊 Пользователь видит статус/лог деплоя
