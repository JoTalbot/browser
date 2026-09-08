#!/usr/bin/env bash
# 🔄 Авто-обновление Octopus Browser на сервере.
# Вызывается из GitHub Actions (push в main) и из cron (watchdog).
set -euo pipefail

APP_DIR="${DEPLOY_PATH:-/opt/octopus-browser}"
AGENTS_DIR="/root/agents"
LOG="/var/log/octopus-update.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "${LOG}"; }

log "🔄 Начало обновления"

# 🔒 Защита от параллельных запусков (cron + Actions)
exec 9>"${APP_DIR}/.update.lock"
if ! flock -n 9; then
  log "⏭️ Обновление уже выполняется, пропуск"
  exit 0
fi

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
# ⚠️ /root/agents/ — ОБЩАЯ директория экосистемы Октопус (другие проекты тоже
# пишут туда свои файлы/логи). chmod применяем ТОЛЬКО к своим скопированным
# файлам, а не рекурсивно по всей директории — иначе можно задеть чужие права
# и упасть на файлах с расширенными атрибутами (см. lsattr).
if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  SUDO="sudo"
else
  SUDO=""
fi
${SUDO} mkdir -p "${AGENTS_DIR}"
for f in docs/agent-instructions/*; do
  name="$(basename "${f}")"
  ${SUDO} cp -r "${f}" "${AGENTS_DIR}/${name}"
  ${SUDO} chmod a+rwX "${AGENTS_DIR}/${name}" 2>/dev/null || true
done
log "📚 Инструкции синхронизированы в ${AGENTS_DIR}"

APPLIED_FILE="${APP_DIR}/.applied_commit"
APPLIED="$(cat "${APPLIED_FILE}" 2>/dev/null || echo none)"
if [ "${APPLIED}" = "${NEW}" ]; then
  log "✅ Код уже применён (${NEW})"
  exit 0
fi

log "⬆️ Применение ${APPLIED} -> ${NEW} (pull: ${CURRENT} -> ${NEW})"

# 🛠️ Зависимости (Python venv, если уже создано bootstrap-скриптом)
if [ -d ".venv" ]; then
  .venv/bin/pip install -q -r requirements.txt
  log "🐍 Зависимости обновлены (.venv)"
fi

# 🚀 Рестарт сервиса
# Детерминированный предикат через `systemctl cat`: прежний вариант
# `list-unit-files | grep -q` под `pipefail` умирал по SIGPIPE (exit 141),
# поэтому рестарт не выполнялся никогда и прод висел на старом коде.
if systemctl cat octopus-browser.service > /dev/null 2>&1; then
  sudo systemctl restart octopus-browser
  if [ "$(systemctl is-active octopus-browser.service 2>/dev/null || echo inactive)" = "active" ]; then
    log "🚀 Сервис octopus-browser перезапущен"
  else
    log "⚠️ Рестарт octopus-browser: сервис не active после restart"
  fi
fi

# 🧩 AIOS-адаптер из монорепо (unit-файл — источник истины в Git)
ADAPTER_SRC="integrations/browser-aios-adapter/systemd/octopus-browser-aios-adapter.service"
if [ -f "${ADAPTER_SRC}" ]; then
  ${SUDO} cp "${ADAPTER_SRC}" /etc/systemd/system/octopus-browser-aios-adapter.service
  ${SUDO} systemctl daemon-reload
  if ${SUDO} systemctl restart octopus-browser-aios-adapter; then
    log "🧩 Адаптер AIOS обновлён из монорепо"
  else
    log "⚠️ Рестарт адаптера AIOS не удался"
  fi
fi

echo "${NEW}" > "${APPLIED_FILE}"
log "✅ Обновление применено: ${NEW}"
