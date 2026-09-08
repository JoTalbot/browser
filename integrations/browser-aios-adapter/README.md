# Octopus Browser → AIOS adapter

Безопасный адаптер для проекта `JoTalbot/octopus`:

- подключается к уже запущенным Chrome-профилям через CDP (`primary`/`secondary`);
- не копирует `user-data-dir`, `Cookies`, `Local State`, storage state или пароли;
- анализирует скриншоты через внешний vision API только при явном включении;
- защищает `navigate`, `click` и `fill` consent-gate `approved=true`;
- отдаёт локальный HTTP-интерфейс, который может вызывать AIOS.

## Установка

```bash
cd integrations/browser-aios-adapter
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
playwright install chromium
```

Секреты загружаются только из окружения или защищённого `EnvironmentFile`; в Git и логах их быть не должно.

```bash
export OCTOPUS_BROWSER_PRIMARY_CDP_URL=http://127.0.0.1:9222
export OCTOPUS_BROWSER_SECONDARY_CDP_URL=http://127.0.0.1:9224
export GEMINI_API_KEY='...'
export GROQ_API_KEY='...'
export OCTOPUS_BROWSER_VISION_PROVIDER=gemini
# Опционально: OpenAI-compatible LLM balancer (например, Arena Gateway):
# export OCTOPUS_BROWSER_VISION_PROVIDER=balancer
# export OCTOPUS_BROWSER_LLM_BALANCER_URL=http://127.0.0.1:13014/v1
# export OCTOPUS_BROWSER_LLM_BALANCER_MODEL=auto
# export OCTOPUS_BROWSER_LLM_BALANCER_API_KEY='...'
# Только после отдельной проверки политики передачи скриншотов:
export OCTOPUS_BROWSER_ALLOW_EXTERNAL_VISION=1
python -m octopus_browser_adapter.main
```

Локальный API по умолчанию: `127.0.0.1:9615`.

- `GET /health` — статические capabilities, без подключения к Chrome.
- `GET /status` — доступность CDP и количество вкладок; URL показываются только как host.
- `GET /aios/status` — проверка локального AIOS bridge `127.0.0.1:9600`.
- `POST /observe` — screenshot + vision; требует `OCTOPUS_BROWSER_ALLOW_EXTERNAL_VISION=1`.
- `POST /action` — `navigate`, `click`, `fill`; требует `approved: true`.

## Vision-маршрутизация

- Рабочий baseline на сервере: `gemini-2.5-flash` для base64 screenshot.
- Fallback: `qwen/qwen3.8-27b` через Groq при наличии `GROQ_API_KEY`.
- Опциональный `balancer` отправляет OpenAI-compatible image request в локальный или удалённый LLM gateway, например Arena Gateway; gateway сам выбирает модель и fallback.
- Синтетический benchmark не отправляет данные Google-профилей; реальные скриншоты нельзя отправлять наружу без отдельной политики данных.
- Модель и порядок провайдеров настраиваются через `OCTOPUS_BROWSER_VISION_PROVIDER`, `OCTOPUS_BROWSER_GEMINI_MODEL`, `OCTOPUS_BROWSER_GROQ_MODEL`, `OCTOPUS_BROWSER_LLM_BALANCER_URL` и `OCTOPUS_BROWSER_LLM_BALANCER_MODEL`.

## Пример запроса

```json
{
  "profile": "secondary",
  "action": "navigate",
  "url": "https://example.com",
  "approved": true
}
```

Подключение по CDP не завершает пользовательский Chrome при отключении адаптера. Запуск/восстановление контейнеров выполняется отдельно, через утверждённый deployment-канал.

## Запуск GitHub Actions через существующий browser-профиль

Для workflow dispatch можно использовать `tools/start_github_workflow_via_cdp.py`.
Скрипт подключается к уже запущенному Chrome по CDP, проверяет пользователя
`JoTalbot` и выполняет только GitHub UI-действие; raw-профиль и cookies не читаются.
Флаг `--approved` обязателен:

```bash
python tools/start_github_workflow_via_cdp.py \\
  --workflow octopus-eternal-recovery.yml \\
  --branch main \\
  --input verify_only=true \\
  --approved
```

Скрипт не вводит пароль, не обходит 2FA/CAPTCHA и не выполняет действия вне
`github.com`. Для deployment-воркфлоу перед запуском нужно убедиться, что
workflow уже опубликован в `.github/workflows/` и его secrets настроены.

## Тесты

```bash
pytest -q
```

Тесты используют mocks и не читают реальные cookies, профили или внешние API.
