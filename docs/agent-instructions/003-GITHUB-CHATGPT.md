# 🤖 003 — Инструкция для ChatGPT с плагином GitHub

> 🎯 Сценарий: ChatGPT (с подключённым GitHub-плагином/действием) читает
> инструкции из репозитория, вносит правки в GitHub — они автоматически
> применяются на сервере. Работает так же для Arena, Claude, Gemini, Codex.

---

## 1. 🏗️ Как устроен поток (схема)

```text
🧑 Пользователь
   │
   ▼
🤖 ChatGPT (GitHub plugin)
   │  читает: AGENTS.md → docs/agent-instructions/*
   │  правит: репозиторий JoTalbot/browser (ветка → PR)
   ▼
📦 GitHub main
   │  push/merge
   ▼
⚙️ GitHub Actions (deploy.yml — из шаблона deploy/github-actions/)
   │  SSH-подключение по секрету DEPLOY_SSH_KEY
   ▼
🖥️ Сервер (OCI, ubuntu@DEPLOY_HOST)
   │  git pull --ff-only → deploy/server-update.sh → restart
   ▼
🔄 /root/agents/ + приложение обновлены ✅
```

---

## 2. 📖 Что ChatGPT должен делать в начале сессии

- ✅ Прочитать `AGENTS.md`.
- ✅ Прочитать `docs/agent-instructions/000-README.md`.
- ✅ Открыть профильный файл: `001-GENERAL.md`, `002-REPOSITORY.md`, `003-GITHUB-CHATGPT.md`.
- ✅ Спросить пользователя: что за задача (изменение кода / инструкции / деплой).
- ✅ Проверить последние коммиты и статус GitHub Actions.

---

## 3. 📦 Как ChatGPT вносит правки

- ✅ Ветка: `arena/chatgpt-<дата>` или `feat/<краткое-название>`, затем Pull Request.
- ✅ Уметь в Pull Request: заголовок `feat: ...`, описание из шаблона ниже.
- ✅ Статус-чек `✅` — только после того, как workflow `deploy.yml` завершился успешно.
- ✅ Для «горячих» правил: с разрешения пользователя — прямой push в `main`.
- ❌ Не трогать чужие открытые PR без предупреждения.
- ❌ Не переписывать историю (`rebase --force`) в общих ветках.

---

## 4. 📋 Шаблон описания Pull Request

```markdown
- 🤖 **Автор:** ChatGPT + GitHub plugin
- 🎯 **Что:** {суть изменений}
- ✅ **Правки:**
  - {файл} — {что изменено}
- 🧪 **Проверки:** {линт/тесты/ручная проверка}
- 🚀 **Деплой:** GitHub Actions → сервер (авто)
- 📌 **Заметки:** {что нужно проверить человеку}
```

---

## 5. 🚀 Что происходит после merge (автоматика)

1. ⚙️ `.github/workflows/deploy.yml` запускается на push в `main`.
2. 🔐 Берёт `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` из Secrets.
3. 🖥️ SSH: `cd /opt/octopus-browser && git pull --ff-only`.
4. 🛠️ Запуск `deploy/server-update.sh` (копирует инструкции в `/root/agents/`, рестарт сервиса).
5. 📊 Результат виден в Actions → пользователь получает ссылку на запуск.
6. 🧲 Резервный канал: на сервере cron/watchdog каждые 2 мин сам `git pull`, если CI недоступен.

---

## 6. ⚠️ Ограничения агента

- ✅ Может: править файлы, создавать PR, комментировать, читать Actions.
- ✅ Может: запускать workflow (если есть разрешение `workflow_dispatch`).
- ❌ Не может/не должен: трогать секреты руками, удалять `main`, менять `deploy/` без проверки.
- ❌ Не может: выполнять команды на сервере вне деплой-скриптов.
- 📌 При ошибке деплоя — сообщить пользователю, предложить путь к логу, **не** править сервер напрямую.

---

## 7. 🔧 Настройка ChatGPT-плагина

- ✅ В ChatGPT подключить GitHub (Actions/plugin) с доступом к `JoTalbot/browser`.
- ✅ Включить разрешения: read repo, read/write pull requests, checks, workflows.
- ✅ Указать в системной инструкции: «Читай `AGENTS.md` в корне репозитория».
- ✅ Запросы к серверу — через push в `main`, не напрямую.
