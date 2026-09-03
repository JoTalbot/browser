#!/usr/bin/env bash
# 🚀 Первичная установка Octopus Browser на сервер (запускать от ubuntu, один раз)
# Установка идёт через GitHub: сервер клонирует репозиторий и далее обновляется сам.
set -euo pipefail

APP_DIR="${DEPLOY_PATH:-/opt/octopus-browser}"
AGENTS_DIR="/root/agents"
LOG="/var/log/octopus-update.log"

echo "🛠️ Bootstrap Octopus Browser в ${APP_DIR}"
mkdir -p "${APP_DIR}" "${AGENTS_DIR}"

# 1) Клонируем репозиторий (если ещё не клонирован)
if [ ! -d "${APP_DIR}/.git" ]; then
  echo "📥 Клонирование JoTalbot/browser..."
  git clone git@github.com:JoTalbot/browser.git "${APP_DIR}"
else
  echo "✅ Репозиторий уже есть, обновляем..."
  git -C "${APP_DIR}" fetch --all
  git -C "${APP_DIR}" checkout main
  git -C "${APP_DIR}" pull --ff-only origin main
fi

# 2) Зеркалируем инструкции в /root/agents/
cp -r "${APP_DIR}/docs/agent-instructions/"* "${AGENTS_DIR}/"
chmod -R u+rwX "${AGENTS_DIR}"
echo "📚 Инструкции синхронизированы в ${AGENTS_DIR}"

# 3) Зависимости (пример: Node-проект; раскомментируйте по мере надобности)
# cd "${APP_DIR}" && npm ci || npm install

# 4) Watchdog: резервное авто-обновление каждые 2 минуты
CRON_LINE="*/2 * * * * ${APP_DIR}/deploy/server-update.sh >> ${LOG} 2>&1"
( crontab -l 2>/dev/null | grep -v 'octopus-browser/deploy/server-update.sh' ; echo "${CRON_LINE}" ) | crontab -
echo "🧲 Watchdog добавлен в cron (каждые 2 мин)"

# 5) Сервис (пример systemd; отредактируйте под своё приложение)
if [ ! -f /etc/systemd/system/octopus-browser.service ]; then
  sudo tee /etc/systemd/system/octopus-browser.service >/dev/null <<'EOF'
[Unit]
Description=Octopus Browser
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/octopus-browser
ExecStart=/usr/bin/env bash -lc 'cd /opt/octopus-browser && npm start'
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now octopus-browser
  echo "🚀 systemd-сервис octopus-browser создан и запущен"
fi

echo "✅ Bootstrap завершён. Проверьте: ls -la ${AGENTS_DIR}"
