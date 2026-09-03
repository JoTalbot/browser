#!/usr/bin/env bash
# 🚀 Первичная установка Octopus Browser на сервер (запускать от ubuntu, один раз).
# Установка идёт через GitHub: сервер клонирует репозиторий и далее обновляется сам
# через deploy/server-update.sh (CI push в main + cron watchdog каждые 2 мин).
set -euo pipefail

APP_DIR="${DEPLOY_PATH:-/opt/octopus-browser}"
AGENTS_DIR="/root/agents"
LOG="/var/log/octopus-update.log"
REPO_URL="${REPO_URL:-https://github.com/JoTalbot/browser.git}"

echo "🛠️ Bootstrap Octopus Browser в ${APP_DIR}"
sudo mkdir -p "${APP_DIR}"
sudo chown "$(id -u):$(id -g)" "${APP_DIR}"
mkdir -p "${AGENTS_DIR}" 2>/dev/null || sudo mkdir -p "${AGENTS_DIR}"

# 1) 📥 Клонируем репозиторий (если ещё не клонирован)
if [ ! -d "${APP_DIR}/.git" ]; then
  echo "📥 Клонирование $(basename "${REPO_URL}")..."
  git clone "${REPO_URL}" "${APP_DIR}"
else
  echo "✅ Репозиторий уже есть, обновляем..."
  git -C "${APP_DIR}" fetch --all
  git -C "${APP_DIR}" checkout main
  git -C "${APP_DIR}" pull --ff-only origin main
fi

cd "${APP_DIR}"

# 2) 🐍 Python-окружение и зависимости (проект — FastAPI/Playwright, см. pyproject.toml)
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
echo "🐍 Виртуальное окружение готово (.venv)"

# 3) ⚙️ .env — выбрать свободный порт, если APP_PORT занят
if [ ! -f ".env" ]; then
  cp .env.example .env
fi
PORT="$(grep -E '^APP_PORT=' .env | cut -d= -f2)"
PORT="${PORT:-8090}"
while ss -ltn 2>/dev/null | grep -q ":${PORT} "; do
  echo "⚠️ Порт ${PORT} занят, пробуем следующий..."
  PORT=$((PORT + 1))
done
sed -i "s/^APP_PORT=.*/APP_PORT=${PORT}/" .env
echo "⚙️ APP_PORT=${PORT}"

# 4) 📚 Синхронизация инструкций в /root/agents/ (см. deploy/server-update.sh
#    для деталей идемпотентной логики — тут делаем то же самое разово).
if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  SUDO="sudo"
else
  SUDO=""
fi
for f in docs/agent-instructions/*; do
  name="$(basename "${f}")"
  ${SUDO} cp -r "${f}" "${AGENTS_DIR}/${name}"
  ${SUDO} chmod a+rwX "${AGENTS_DIR}/${name}" 2>/dev/null || true
done
echo "📚 Инструкции синхронизированы в ${AGENTS_DIR}"

# 5) 🧲 Watchdog: резервное авто-обновление каждые 2 минуты
CRON_LINE="*/2 * * * * DEPLOY_PATH=${APP_DIR} ${APP_DIR}/deploy/server-update.sh >> ${LOG} 2>&1"
( crontab -l 2>/dev/null | grep -v "$(basename "${APP_DIR}")/deploy/server-update.sh" ; echo "${CRON_LINE}" ) | crontab -
echo "🧲 Watchdog добавлен в cron (каждые 2 мин)"

# 6) 🚀 systemd-сервис
if [ ! -f /etc/systemd/system/octopus-browser.service ]; then
  sudo tee /etc/systemd/system/octopus-browser.service >/dev/null <<EOF
[Unit]
Description=Octopus Browser
After=network.target

[Service]
User=$(whoami)
WorkingDirectory=${APP_DIR}
EnvironmentFile=-${APP_DIR}/.env
Environment=PYTHONPATH=${APP_DIR}/src
ExecStart=${APP_DIR}/.venv/bin/python -m octopus_browser.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now octopus-browser
  echo "🚀 systemd-сервис octopus-browser создан и запущен"
else
  sudo systemctl restart octopus-browser
  echo "🚀 systemd-сервис octopus-browser перезапущен"
fi

echo "✅ Bootstrap завершён. Проверьте: curl http://127.0.0.1:${PORT}/health"
