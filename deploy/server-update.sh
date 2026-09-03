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
CURRENT="$(git rev-parse HEAD 2>/dev/null || echo none)"
git fetch --all
git checkout main
git pull --ff-only origin main
NEW="$(git rev-parse HEAD)"

# 📚 Синхронизация инструкций на сервер — ВСЕГДА, независимо от того, менялся ли
# код: этот скрипт может быть вызван уже ПОСЛЕ внешнего git pull (например, из
# GitHub Actions), и тогда CURRENT==NEW, но инструкции всё равно должны быть
# актуальны на сервере (идемпотентно, безопасно перезаписывать).
# 🔐 /root/agents/ может принадлежать root — используем sudo (ubuntu в NOPASSWD),
# с fallback на обычный cp, если sudo недоступен.
if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  sudo mkdir -p "${AGENTS_DIR}"
  sudo cp -r docs/agent-instructions/* "${AGENTS_DIR}/"
  sudo chmod -R a+rwX "${AGENTS_DIR}"
else
  mkdir -p "${AGENTS_DIR}"
  cp -r docs/agent-instructions/* "${AGENTS_DIR}/"
  chmod -R u+rwX "${AGENTS_DIR}"
fi
log "📚 Инструкции синхронизированы в ${AGENTS_DIR}"

if [ "${CURRENT}" = "${NEW}" ]; then
  log "✅ Код не менялся (${NEW})"
  exit 0
fi

log "⬆️ Код обновлён ${CURRENT} -> ${NEW}"

# 🛠️ Зависимости (раскомментируйте, когда появится код)
# npm ci

# 🚀 Рестарт сервиса
if systemctl list-unit-files | grep -q '^octopus-browser'; then
  sudo systemctl restart octopus-browser
  log "🚀 Сервис octopus-browser перезапущен"
fi

log "✅ Обновление применено: ${NEW}"
