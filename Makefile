.PHONY: install run test lint docker

install:            ## 📦 Установить зависимости
	pip install -e ".[dev]"
	playwright install chromium

run:                ## 🚀 Запустить API-сервер
	octopus-browser

test:               ## 🧪 Запустить тесты
	pytest -q

lint:               ## ✨ Линтер
	ruff check src tests

docker:             ## 🐳 Собрать образ
	docker build -t octopus-browser:0.1.0 .
