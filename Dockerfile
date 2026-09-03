# 🐙 Octopus Browser — контейнер API-сервера
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

WORKDIR /app

# 🌐 Конфигурация
ENV APP_HOST=0.0.0.0 APP_PORT=8090 DATA_DIR=/data

# 📦 Зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 🧩 Код
COPY src ./src
COPY README.md .

# 🖥️ Данные (профили, сессии) — volume
VOLUME ["/data"]

EXPOSE 8090

CMD ["python", "-m", "octopus_browser.main"]
