#!/usr/bin/env bash
# 🔄 Авто-обновление Octopus Browser на сервере.
# Вызывается из GitHub Actions (push в main) и из cron (watchdog).
set -euo pipefail

APP_DIR="${DEPLOY_PATH:-/opt/octopus-browser}"
AGENTS_DIR="/root/agents"
LOG="/var/log/octopus-update.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "${LOG}"; }

log "🔄 Начало обновления"

cd "${APP_DIR}"
git fetch --all
CURRENT="$(git rev-parse HEAD)"
git checkout main
git pull --ff-only origin main
NEW="$(git rev-parse HEAD)"

if [ "${CURRENT}" = "${NEW}" ]; then
  log "✅ Изменений нет (${NEW})"
  exit 0
fi

log "⬆️ Обновление ${CURRENT} -> ${NEW}"

# 📚 Синхронизация инструкций на сервер
mkdir -p "${AGENTS_DIR}"
cp -r docs/agent-instructions/* "${AGENTS_DIR}/"
chmod -R u+rwX "${AGENTS_DIR}"
log "📚 Инструкции обновлены в ${AGENTS_DIR}"

# 🛠️ Зависимости (раскомментируйте, когда появится код)
# npm ci

# 🚀 Рестарт сервиса
if systemctl list-unit-files | grep -q '^octopus-browser'; then
  sudo systemctl restart octopus-browser
  log "🚀 Сервис octopus-browser перезапущен"
fi

log "✅ Обновление применено: ${NEW}"
